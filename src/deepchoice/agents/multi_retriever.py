import asyncio

from ..retrievers import RETRIEVER_REGISTRY
from ..retrievers.base import error_text
from ..retrievers.learned_docs import extract_terms, harvest
from ..retrievers.official import TECH_DOCS
from ..utils.views import print_agent_output


def _is_too_generic(sub_questions: list[str]) -> bool:
    """Check if sub_questions are too generic to provide useful search dimensions."""
    if not sub_questions:
        return True
    # Heuristic: average length < 20 chars suggests overly generic questions
    avg_len = sum(len(q) for q in sub_questions) / len(sub_questions)
    return avg_len < 20


def _supplement_sub_questions(sub_questions: list[str], query: str) -> list[str]:
    """Inject the original query as a search dimension when sub_questions are generic."""
    return [f"{query} — detailed technical comparison"] + sub_questions


class MultiRetrieverAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        query = research_state["task"]["query"]
        sub_questions = research_state.get("sub_questions", [])
        adapted_queries = research_state.get("adapted_queries", {})

        # On retry, knowledge_gaps are the new search targets
        knowledge_gaps = research_state.get("knowledge_gaps", [])
        if knowledge_gaps and research_state.get("retry_count", 0) > 0:
            sub_questions = knowledge_gaps
            print_agent_output(
                f"Retry search targeting {len(knowledge_gaps)} knowledge gaps",
                agent="MULTI_RETRIEVER",
            )

        print_agent_output(f"Searching 6 sources for: {query}", agent="MULTI_RETRIEVER")

        # Fallback: if LLM-decomposed sub_questions are too generic,
        # inject the original query as a concrete search dimension.
        if _is_too_generic(sub_questions):
            print_agent_output(
                "Sub-questions too generic (avg_len < 20), supplementing with original query",
                agent="MULTI_RETRIEVER",
            )
            sub_questions = _supplement_sub_questions(sub_questions, query)

        tasks = []
        ordinary_names = []
        official_class = None
        candidate_techs = list(research_state.get("task", {}).get("candidate_techs") or [])
        constraints = list(research_state.get("task", {}).get("constraints") or [])
        for name, cls in RETRIEVER_REGISTRY.items():
            if name == "official":
                official_class = cls
                continue
            retriever = cls()
            adapted = adapted_queries.get(name, []) if adapted_queries else []
            # Candidates travel with the retrieval so the official source can
            # select by declared identity instead of by ordinary query words.
            ordinary_names.append(name)
            tasks.append(retriever.search(query, sub_questions, adapted_queries=adapted,
                                          candidate_techs=candidate_techs))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results_by_name = dict(zip(ordinary_names, raw_results))

        # The official source runs after the ordinary sources so it can reuse
        # their already-paid result rows for discovery instead of issuing a
        # second search. A safe fetch still verifies every page identity.
        if official_class is not None:
            prior_results = [
                result for name, result in results_by_name.items()
                if not isinstance(result, Exception)
            ]
            try:
                results_by_name["official"] = await official_class().search(
                    query, sub_questions,
                    adapted_queries=(adapted_queries.get("official", [])
                                     if adapted_queries else []),
                    candidate_techs=candidate_techs,
                    constraints=constraints,
                    prior_results=prior_results,
                )
            except Exception as exc:
                results_by_name["official"] = exc

        search_results = []
        partial_failures = []
        empty_sources = []
        for name, _cls in RETRIEVER_REGISTRY.items():
            result = results_by_name.get(name)
            if result is None:
                result = RuntimeError("source result missing")
            if isinstance(result, Exception):
                search_results.append({
                    "source": name, "status": "failed",
                    "results": [], "error": error_text(result), "latency_ms": 0,
                })
                partial_failures.append(name)
            else:
                search_results.append(result)
                if result["status"] == "failed":
                    partial_failures.append(name)
                elif result["status"] == "empty":
                    # No research material in this source. Distinct from a
                    # failure: nothing was attempted and nothing broke, so it is
                    # reported as empty rather than counted as unavailable.
                    empty_sources.append({
                        "source": name,
                        "reason": result.get("empty_reason", ""),
                    })

        # Self-updating official docs: learn term -> URL pairs from search evidence
        # (curated seed terms are never re-learned)
        official_terms = extract_terms(
            " ".join(adapted_queries.get("official", [])) if adapted_queries else query
        )
        learned_new = harvest(official_terms, search_results, existing=set(TECH_DOCS))
        if learned_new:
            print_agent_output(
                f"Learned {len(learned_new)} official docs: "
                f"{', '.join(e['term'] for e in learned_new)}",
                agent="MULTI_RETRIEVER",
            )

        # Retriever-internal LLM calls (currently the official URL fallback) must
        # use the same token ledger as the graph agents. Source result rows and
        # actual HTTP requests remain separate counters in `fetch_stats`.
        retriever_token_usage = []
        for result in search_results:
            retriever_token_usage.extend(result.get("token_usage") or [])
        token_usage = list(research_state.get("token_usage") or [])
        token_usage.extend(retriever_token_usage)

        official_stats = next(
            (r.get("fetch_stats") for r in search_results
             if r.get("source") == "official" and isinstance(r.get("fetch_stats"), dict)),
            None)
        source_rows = sum(len(r.get("results", [])) for r in search_results)
        quality_signal = {
            "agent": "multi_retriever",
            "retrievers_used": len(RETRIEVER_REGISTRY),
            "retrievers_failed": len(partial_failures),
            "retrievers_empty": len(empty_sources),
            "total_results": source_rows,
            "had_adapted_queries": bool(adapted_queries),
            # A source row is a result, never an HTTP dispatch. The official
            # fetch counters stay separate and absent when unknown.
            "source_result_rows": source_rows,
            "official_page_attempts": (official_stats or {}).get("page_attempts"),
            "official_http_requests": (official_stats or {}).get("http_requests"),
        }
        return {
            "search_results": search_results,
            "partial_failures": partial_failures,
            "empty_sources": empty_sources,
            "token_usage": token_usage,
            "quality_signals": [quality_signal],
        }