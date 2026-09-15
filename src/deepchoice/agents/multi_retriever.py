import asyncio
from collections.abc import Mapping

from ..retrievers import RETRIEVER_REGISTRY
from ..retrievers.base import error_text
from ..retrievers.contracts import RetrievalRequest, RetrievalResult
from ..retrievers.learned_docs import extract_terms, harvest
from ..retrievers.official import TECH_DOCS
from ..observability import ExternalCallKind, TraceStatus, current_trace_recorder
from ..runtime.context import classify_cancelled_trace_status
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
    return [f"{query} — detailed technical comparison"] + sub_questions[:19]


async def _contract_failure(source: str, _exc: Exception) -> RetrievalResult:
    return RetrievalResult(
        source=source,
        status="failed",
        results=[],
        error="RetrievalContractError: invalid retrieval contract",
        latency_ms=0,
    )


async def _invoke_retriever_untraced(
    name: str,
    cls: type,
    *,
    query: str,
    sub_questions: list[str],
    adapted_queries: list[str],
) -> tuple[object, bool]:
    try:
        retriever = cls()
    except Exception as exc:
        return (
            RetrievalResult(
                source=name,
                status="failed",
                results=[],
                error=error_text(exc),
                latency_ms=0,
            ),
            True,
        )

    try:
        request = RetrievalRequest(
            query=query,
            sub_questions=sub_questions,
            max_results=7,
            adapted_queries=adapted_queries,
        )
    except Exception as exc:
        return await _contract_failure(name, exc), True

    is_stable = callable(getattr(retriever, "retrieve", None))
    try:
        pending = (
            retriever.retrieve(request)
            if is_stable
            else retriever.search(
                query,
                sub_questions,
                adapted_queries=adapted_queries,
            )
        )
    except Exception as exc:
        return (
            RetrievalResult(
                source=name,
                status="failed",
                results=[],
                error=error_text(exc),
                latency_ms=0,
            ),
            is_stable,
        )

    if not hasattr(pending, "__await__"):
        return await _contract_failure(
            name, TypeError("retriever result is not awaitable")
        ), is_stable
    try:
        return await pending, is_stable
    except Exception as exc:
        return (
            RetrievalResult(
                source=name,
                status="failed",
                results=[],
                error=error_text(exc),
                latency_ms=0,
            ),
            is_stable,
        )


async def _invoke_retriever(
    name: str,
    cls: type,
    *,
    query: str,
    sub_questions: list[str],
    adapted_queries: list[str],
) -> tuple[object, bool]:
    """Record one independent retrieval call without retaining its query."""

    trace, node_attempt_id = current_trace_recorder()
    trace_call = None
    if trace is not None:
        trace_call = await trace.start_external_call(
            node_attempt_id=node_attempt_id,
            kind=ExternalCallKind.RETRIEVAL,
            provider=name,
            operation="retrieve",
            request_summary={
                "max_results": 7,
                "sub_question_count": len(sub_questions),
                "adapted_query_count": len(adapted_queries),
            },
        )
    try:
        invocation = await _invoke_retriever_untraced(
            name,
            cls,
            query=query,
            sub_questions=sub_questions,
            adapted_queries=adapted_queries,
        )
    except asyncio.CancelledError:
        if trace is not None:
            await trace.finish_external_call(
                trace_call, status=classify_cancelled_trace_status()
            )
        raise
    except Exception as exc:
        if trace is not None:
            await trace.finish_external_call(
                trace_call,
                status=TraceStatus.FAILED,
                result_summary={"error_type": type(exc).__name__},
            )
        raise

    raw_result, is_stable = invocation
    try:
        result = RetrievalResult.model_validate(raw_result)
    except Exception:
        trace_status = TraceStatus.FAILED
        summary = {"retrieval_status": "invalid_contract"}
    else:
        trace_status = (
            TraceStatus.FAILED
            if result.status == "failed"
            else TraceStatus.SUCCEEDED
        )
        summary = {
            "retrieval_status": result.status,
            "result_count": len(result.results),
            "latency_ms": result.latency_ms,
        }
    if trace is not None:
        await trace.finish_external_call(
            trace_call, status=trace_status, result_summary=summary
        )
    return invocation

class MultiRetrieverAgent:
    def __init__(
        self,
        websocket=None,
        stream_output=None,
        headers=None,
        retriever_registry: Mapping[str, type] | None = None,
    ):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers
        self.retriever_registry = (
            RETRIEVER_REGISTRY if retriever_registry is None else retriever_registry
        )

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

        print_agent_output(
            f"Searching 6 sources ({len(query)} query chars)", agent="MULTI_RETRIEVER"
        )

        # Fallback: if LLM-decomposed sub_questions are too generic,
        # inject the original query as a concrete search dimension.
        if _is_too_generic(sub_questions):
            print_agent_output(
                "Sub-questions too generic (avg_len < 20), supplementing with original query",
                agent="MULTI_RETRIEVER",
            )
            sub_questions = _supplement_sub_questions(sub_questions, query)

        registry_entries = tuple(self.retriever_registry.items())
        tasks = []
        for name, cls in registry_entries:
            adapted = adapted_queries.get(name, []) if adapted_queries else []
            tasks.append(
                _invoke_retriever(
                    name,
                    cls,
                    query=query,
                    sub_questions=sub_questions,
                    adapted_queries=adapted,
                )
            )

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        search_results = []
        partial_failures = []
        for (name, _cls), invocation in zip(registry_entries, raw_results):
            if isinstance(invocation, Exception):
                validated = RetrievalResult(
                    source=name,
                    status="failed",
                    results=[],
                    error=error_text(invocation),
                    latency_ms=0,
                )
                search_results.append(validated.model_dump(exclude={"schema_version"}))
                partial_failures.append(name)
            else:
                result, is_stable = invocation
                try:
                    validated = RetrievalResult.model_validate(result)
                    if is_stable and validated.source != name:
                        raise ValueError(
                            f"source mismatch: expected {name!r}, got {validated.source!r}"
                        )
                except Exception as exc:
                    validated = RetrievalResult(
                        source=name,
                        status="failed",
                        results=[],
                        error="RetrievalContractError: invalid retrieval contract",
                        latency_ms=0,
                    )
                    partial_failures.append(name)
                else:
                    if validated.status == "failed":
                        partial_failures.append(validated.source)
                search_results.append(validated.model_dump(exclude={"schema_version"}))

        # Self-updating official docs: learn term -> URL pairs from search evidence
        # (curated seed terms are never re-learned)
        official_terms = extract_terms(
            " ".join(adapted_queries.get("official", [])) if adapted_queries else query
        )
        learned_new = harvest(official_terms, search_results, existing=set(TECH_DOCS))
        if learned_new:
            print_agent_output(
                f"Learned {len(learned_new)} official docs",
                agent="MULTI_RETRIEVER",
            )

        return {
            "search_results": search_results,
            "partial_failures": partial_failures,
            "quality_signals": [{
                "agent": "multi_retriever",
                "retrievers_used": len(registry_entries),
                "retrievers_failed": len(partial_failures),
                "total_results": sum(len(r.get("results", [])) for r in search_results),
                "had_adapted_queries": bool(adapted_queries),
            }],
        }
