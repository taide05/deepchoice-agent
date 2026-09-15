import asyncio
import json
import os

import httpx
import numpy as np

from .. import outbound as _outbound
from ..budget_errors import BudgetError
from ..retrievers.tavily_keypool import post_with_failover
from ..utils.embedding import get_embedding_model
from ..utils.llm import MAX_OUTPUT_TOKENS, call_model, summarize_usage
from ..utils.views import print_agent_output

# ---------------------------------------------------------------------------
# Concurrency limits. Two flash tiers: deepseek-flash (500/min) + qwen-flash.
# Env-tunable — set LLM_DS_CONCURRENCY / LLM_QW_CONCURRENCY to the provider RPM.
# QW_SEM is the separate re-arbitration-path gate (qwen-flash tier).
# ---------------------------------------------------------------------------
FLASH_SEM = asyncio.Semaphore(int(os.environ.get("LLM_DS_CONCURRENCY", "80")))
QW_SEM = asyncio.Semaphore(int(os.environ.get("LLM_QW_CONCURRENCY", "10")))

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ARBITRATION_SYSTEM = """You are an impartial technical arbitrator. Two sources make claims about the same topic but may disagree.

Rules:
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right (different contexts)
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference

Return ONLY a JSON object — no prose or analysis paragraphs outside the JSON; keep "reasoning" and "key_factor" to a short phrase (<=12 words each):
{"resolution": "A_correct|B_correct|both_partial|insufficient_data", "confidence": "high|medium|low", "reasoning": "Short phrase citing score/evidence difference", "key_factor": "Short decisive factor"}"""


CONTRADICTION_SCAN_SYSTEM = """You are checking if two technical sources present meaningfully different perspectives about a technology comparison.

Consider ANY of these as a "difference worth flagging":
1. Different winner recommendations (Source A says pick X, Source B says pick Y)
2. Vendor bias (one source is from a vendor comparing itself to competitors)
3. Contradictory trade-off assessments (one says X is faster, another says Y is faster)
4. Different weight given to the same evidence (one prioritizes simplicity, another scalability)
5. Source A and B draw opposite conclusions from similar facts

A "difference" does NOT require factual contradiction. Different recommendations based on different priorities or use cases also count."""


# Deterministic arbitration short-circuit: ARBITRATION rule 1 — a score gap
# >= SCORE_GAP_DECIDE makes the higher-scored source correct without an LLM
# call. Only close-score pairs need semantic arbitration (evidence-type nuance).
SCORE_GAP_DECIDE = 2.5
SCORE_GAP_HIGH_CONF = 5.0


def _deterministic_arbitration(a: dict, b: dict) -> dict | None:
    """Apply arbitration rule 1 without an LLM call. Returns the resolved
    verdict when the score gap is decisive, or None when the gap is too small
    to decide by score alone (semantic arbitration is then required)."""
    score_a = float(a.get("total_score", 0))
    score_b = float(b.get("total_score", 0))
    diff = abs(score_a - score_b)
    if diff < SCORE_GAP_DECIDE:
        return None
    winner = "A" if score_a > score_b else "B"
    confidence = "high" if diff >= SCORE_GAP_HIGH_CONF else "medium"
    return {
        "resolution": f"{winner}_correct",
        "confidence": confidence,
        "reasoning": (f"Score gap {diff:.1f} >= {SCORE_GAP_DECIDE} favors source "
                      f"{winner} ({max(score_a, score_b):.1f} vs {min(score_a, score_b):.1f})"),
        "key_factor": "score_difference",
    }


# ---------------------------------------------------------------------------
# Inline multi-turn evidence gathering — 3 search tools (web / scholarly / kb)
# ---------------------------------------------------------------------------

SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for latest tech comparisons, benchmarks, community discussions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_scholarly",
            "description": "Search academic papers on arXiv for research findings and benchmarks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Academic search query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Search local knowledge base for previously researched tech comparison data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Knowledge base query"},
                    "max_results": {"type": "integer", "description": "Max results (1-5)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
]
EVIDENCE_GATHER_SYSTEM = (
    "You gather evidence to resolve technical disagreements. "
    "Search broadly across sources, then summarize the key finding "
    "in 2-3 sentences that would help an arbitrator decide which claim is more credible."
)
EVIDENCE_GATHER_USER_TEMPLATE = (
    "Topic: {topic}\n"
    "Claim A: {claim_a}\n"
    "Claim B: {claim_b}\n\n"
    "Search for evidence using at least 1 different tool."
)
EVIDENCE_GATHER_MAX_ITERATIONS = 2
EVIDENCE_GATHER_CLIENT_TIMEOUT_S = 60.0
EVIDENCE_GATHER_CALL_TIMEOUT_S = 30.0
EVIDENCE_GATHER_TOOL_TIMEOUT_S = 20.0


async def _execute_search(tool_name: str, arguments: dict) -> str:
    """Execute a single search tool and return JSON-serialized results."""
    query = arguments.get("query", "")
    max_results = min(arguments.get("max_results", 3), 5)

    if tool_name == "search_web":
        async with httpx.AsyncClient(timeout=15.0) as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            try:
                resp, _ = await post_with_failover(post, {
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                })
                if resp is None:
                    return json.dumps({"error": "no Tavily API key available"})
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])[:max_results]
                return json.dumps([{"title": r.get("title", ""),
                                    "content": r.get("content", "")[:300],
                                    "url": r.get("url", "")} for r in results],
                                  ensure_ascii=False)
            except BudgetError:
                raise
            except Exception as exc:
                return json.dumps({"error": type(exc).__name__})

    elif tool_name == "search_scholarly":
        import urllib.parse
        try:
            async with await _outbound.make_client("arxiv") as client:
                q = urllib.parse.quote(f"all:{query}", safe="")
                url = f"https://export.arxiv.org/api/query?search_query={q}&max_results={max_results}"
                resp = await client.get(url)
                resp.raise_for_status()
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                results = []
                for entry in root.findall("atom:entry", ns):
                    title = entry.find("atom:title", ns)
                    summary = entry.find("atom:summary", ns)
                    link = entry.find("atom:id", ns)
                    results.append({
                        "title": title.text.strip() if title is not None else "",
                        "summary": summary.text.strip()[:300] if summary is not None else "",
                        "url": link.text.strip() if link is not None else "",
                    })
                return json.dumps(results[:max_results], ensure_ascii=False)
        except BudgetError:
            raise
        except Exception as exc:
            return json.dumps({"error": type(exc).__name__})

    elif tool_name == "search_kb":
        chroma_path = os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db")
        try:
            import chromadb
            from chromadb.errors import NotFoundError
            client = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            try:
                collection = client.get_collection("knowledge_base")
            except NotFoundError:
                return json.dumps({"error": "KB collection not found", "results": []})
            results = collection.query(query_texts=[query], n_results=max_results)
            docs = []
            for i, doc in enumerate(results.get("documents", [[]])[0]):
                meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                docs.append({"content": doc[:300] if doc else "", "metadata": meta})
            return json.dumps(docs, ensure_ascii=False)
        except ImportError:
            return json.dumps({"error": "chromadb not installed in this process"})
        except BudgetError:
            raise
        except Exception as exc:
            return json.dumps({"error": type(exc).__name__})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def _tool_failure_category(result: str) -> str | None:
    """Map a structured tool error to a public-safe trace category."""

    try:
        payload = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "error" not in payload:
        return None
    error = str(payload.get("error", "")).lower()
    if "unknown tool" in error:
        return "unsupported_tool"
    if "kb collection" in error:
        return "knowledge_base_unavailable"
    if "api key" in error or "provider" in error or "available" in error:
        return "provider_unavailable"
    return "provider_error"


async def _gather_evidence(topic: str, claim_a: str, claim_b: str,
                           max_iterations: int = EVIDENCE_GATHER_MAX_ITERATIONS,
                           per_call_timeout: float = EVIDENCE_GATHER_CALL_TIMEOUT_S,
                           usage: list | None = None) -> str:
    """Inline multi-turn evidence gathering via OpenAI-compatible tool calling.

    Returns a plain-text summary of collected evidence suitable for
    enriching claim descriptions in the arbitration prompt.
    """
    from ..utils.llm import TIERS, _get_client
    from ..observability import ExternalCallKind, TraceStatus, current_trace_recorder
    from ..runtime.context import classify_cancelled_trace_status
    from ..budget import (
        BudgetAmount,
        BudgetError,
        BudgetExceededError,
        BudgetResource,
        reserve_call,
        settle_call,
        unknown_call,
    )

    client = _get_client(timeout=EVIDENCE_GATHER_CLIENT_TIMEOUT_S, tier="deepseek-flash")

    messages = [
        {"role": "system", "content": EVIDENCE_GATHER_SYSTEM},
        {
            "role": "user",
            "content": EVIDENCE_GATHER_USER_TEMPLATE.format(
                topic=topic,
                claim_a=claim_a,
                claim_b=claim_b,
            ),
        },
    ]

    summaries = []

    for iteration in range(max_iterations):
        trace, node_attempt_id = current_trace_recorder()
        trace_call = None
        if trace is not None:
            trace_call = await trace.start_external_call(
                node_attempt_id=node_attempt_id,
                kind=ExternalCallKind.LLM,
                provider="deepseek-flash",
                operation="evidence_gather.chat",
                request_summary={"iteration_no": iteration + 1},
            )
        llm_reservations = ()
        try:
            message_bytes = len(
                json.dumps(
                    messages,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            llm_reservations = await reserve_call(
                (
                    BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                    BudgetAmount(
                        resource=BudgetResource.TOTAL_TOKENS,
                        amount=message_bytes + MAX_OUTPUT_TOKENS,
                    ),
                ),
                call_id=trace_call.call_id if trace_call is not None else None,
                summary={"operation": "evidence_gather_llm", "iteration_no": iteration + 1},
            )
        except BudgetError as budget_exc:
            if trace is not None:
                await trace.finish_external_call(
                    trace_call,
                    status=TraceStatus.FAILED,
                    result_summary={
                        "failure_category": (
                            "budget_exceeded"
                            if isinstance(budget_exc, BudgetExceededError)
                            else "budget_gate_failed"
                        )
                    },
                )
            raise
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=TIERS["deepseek-flash"]["model"],
                    messages=messages,
                    tools=SEARCH_TOOLS,
                    temperature=0,
                    max_tokens=MAX_OUTPUT_TOKENS,
                ),
                timeout=per_call_timeout,
            )
        except asyncio.CancelledError:
            await unknown_call(
                llm_reservations,
                known_actuals={BudgetResource.LLM_CALLS: 1},
            )
            if trace is not None:
                await trace.finish_external_call(
                    trace_call, status=classify_cancelled_trace_status()
                )
            raise
        except TimeoutError:
            await unknown_call(
                llm_reservations,
                known_actuals={BudgetResource.LLM_CALLS: 1},
            )
            if trace is not None:
                await trace.finish_external_call(
                    trace_call, status=TraceStatus.TIMED_OUT
                )
            print_agent_output("Evidence gathering LLM call timed out", agent="CONFLICT_DETECTOR")
            break
        except BudgetError:
            await unknown_call(
                llm_reservations,
                known_actuals={BudgetResource.LLM_CALLS: 1},
            )
            raise
        except Exception as exc:
            await unknown_call(
                llm_reservations,
                known_actuals={BudgetResource.LLM_CALLS: 1},
            )
            if trace is not None:
                await trace.finish_external_call(
                    trace_call,
                    status=TraceStatus.FAILED,
                    result_summary={"error_type": type(exc).__name__},
                )
            print_agent_output("Evidence gathering LLM error", agent="CONFLICT_DETECTOR")
            break

        trace_usage = {}
        if getattr(response, "usage", None) is not None:
            trace_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        await settle_call(
            llm_reservations,
            {
                BudgetResource.LLM_CALLS: 1,
                BudgetResource.TOTAL_TOKENS: (
                    response.usage.total_tokens
                    if getattr(response, "usage", None) is not None
                    else None
                ),
            },
        )
        if trace is not None:
            await trace.finish_external_call(
                trace_call,
                status=TraceStatus.SUCCEEDED,
                usage_summary=trace_usage,
            )

        # Capture token usage (same 4-field shape as call_model) so the
        # panel does not undercount direct-AsyncOpenAI evidence-gathering calls.
        if usage is not None and getattr(response, "usage", None) is not None:
            usage.append({
                "model": getattr(response, "model", None) or TIERS["deepseek-flash"]["model"],
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            })

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            if msg.content:
                summaries.append(msg.content)
            break

        tool_calls = [tc for tc in msg.tool_calls if tc.type == "function"]

        async def _run_tool(tc):
            tool_trace = None
            if trace is not None:
                tool_trace = await trace.start_external_call(
                    node_attempt_id=node_attempt_id,
                    kind=ExternalCallKind.RETRIEVAL,
                    provider=tc.function.name,
                    operation="evidence_gather.tool",
                    request_summary={"iteration_no": iteration + 1},
                )
            try:
                tool_reservations = await reserve_call(
                    (
                        BudgetAmount(
                            resource=BudgetResource.RETRIEVAL_CALLS,
                            amount=1,
                        ),
                    ),
                    call_id=tool_trace.call_id if tool_trace is not None else None,
                    summary={"operation": "evidence_gather_tool"},
                )
            except BudgetError as budget_exc:
                if trace is not None:
                    await trace.finish_external_call(
                        tool_trace,
                        status=TraceStatus.FAILED,
                        result_summary={
                            "failure_category": (
                                "budget_exceeded"
                                if isinstance(budget_exc, BudgetExceededError)
                                else "budget_gate_failed"
                            )
                        },
                    )
                raise
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            try:
                result = await asyncio.wait_for(
                    _execute_search(tc.function.name, arguments),
                    timeout=EVIDENCE_GATHER_TOOL_TIMEOUT_S,
                )
            except asyncio.CancelledError:
                await settle_call(
                    tool_reservations,
                    {BudgetResource.RETRIEVAL_CALLS: 1},
                )
                if trace is not None:
                    await trace.finish_external_call(
                        tool_trace, status=classify_cancelled_trace_status()
                    )
                raise
            except TimeoutError:
                await settle_call(
                    tool_reservations,
                    {BudgetResource.RETRIEVAL_CALLS: 1},
                )
                result = json.dumps({"error": f"{tc.function.name} timed out"})
                if trace is not None:
                    await trace.finish_external_call(
                        tool_trace, status=TraceStatus.TIMED_OUT
                    )
            except BudgetError:
                await settle_call(
                    tool_reservations,
                    {BudgetResource.RETRIEVAL_CALLS: 1},
                )
                raise
            except Exception as exc:
                await settle_call(
                    tool_reservations,
                    {BudgetResource.RETRIEVAL_CALLS: 1},
                )
                result = json.dumps({"error": type(exc).__name__})
                if trace is not None:
                    await trace.finish_external_call(
                        tool_trace,
                        status=TraceStatus.FAILED,
                        result_summary={"error_type": type(exc).__name__},
                    )
            else:
                await settle_call(
                    tool_reservations,
                    {BudgetResource.RETRIEVAL_CALLS: 1},
                )
                failure_category = _tool_failure_category(result)
                if trace is not None:
                    await trace.finish_external_call(
                        tool_trace,
                        status=(
                            TraceStatus.FAILED
                            if failure_category is not None
                            else TraceStatus.SUCCEEDED
                        ),
                        result_summary=(
                            {"failure_category": failure_category}
                            if failure_category is not None
                            else {"result_chars": len(result)}
                        ),
                    )
            return tc.id, result

        tool_results = await asyncio.gather(*[_run_tool(tc) for tc in tool_calls])
        for tool_call_id, result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            })

    return "\n".join(summaries) if summaries else ""


# ---------------------------------------------------------------------------
# Candidate scanning (LLM replaces negation-word matching)
# ---------------------------------------------------------------------------


async def _scan_pair_contradiction(src_a: dict, src_b: dict, query: str,
                                   usage: list | None = None) -> dict | None:
    """Ask flash model whether two sources present meaningfully different perspectives.

    Returns a dict with contradiction info if detected, None otherwise.
    """
    snippet_a = src_a.get("snippet", "")[:400]
    snippet_b = src_b.get("snippet", "")[:400]
    prompt = [
        {"role": "system", "content": CONTRADICTION_SCAN_SYSTEM},
        {"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Source A: {src_a.get('title', '')}\nDescription: {snippet_a if snippet_a else '(no description)'}\n\n"
            f"Source B: {src_b.get('title', '')}\nDescription: {snippet_b if snippet_b else '(no description)'}\n\n"
            f"Do these two sources present meaningfully different perspectives? Return JSON."
            """

Return ONLY a JSON object — no prose or analysis paragraphs outside the JSON; keep "explanation" to a short phrase (<=12 words):
{{
  "has_difference": true/false,
  "type": "winner_disagreement|tradeoff_disagreement|vendor_bias|none",
  "explanation": "Short phrase stating the difference (or 'none')"
}}"""
        )},
    ]
    try:
        async with FLASH_SEM:
            result = await call_model(
                prompt,
                model="deepseek-flash", tag="conflict_scan",
                response_format="json",
                usage=usage,
            )
        if isinstance(result, dict) and result.get("has_difference"):
            return result
        return None
    except BudgetError:
        raise
    except Exception:
        print_agent_output("Conflict scan failed", agent="CONFLICT_DETECTOR")
        return None


async def find_contradictions(source_scores: list[dict], query_topic: str = "",
                               threshold: float = 0.65,
                               usage: list | None = None) -> list[dict]:
    """Find contradictory source pairs using LLM semantic scan.

    Pipeline: BGE similarity pre-filter → LLM contradiction scan
    (replaces old negation-word matching).
    """
    model = get_embedding_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    if len(high_score_sources) < 2:
        return []

    titles = [s.get("title", "") for s in high_score_sources]
    embeddings = await asyncio.to_thread(model.encode, titles)
    norms = np.linalg.norm(embeddings, axis=1)

    # Build candidate pairs (BGE similarity — LLM handles semantic filtering)
    candidates: list[tuple[int, int, float]] = []
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            if not titles[i] or not titles[j]:
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]) / (norms[i] * norms[j]))
            if sim < threshold:
                continue
            candidates.append((i, j, sim))

    if not candidates:
        return []

    # Cap at top-15 by similarity to prevent O(n²) explosion with many sources
    candidates.sort(key=lambda x: x[2], reverse=True)
    candidates = candidates[:15]

    # LLM scan in parallel
    async def _scan(cand):
        i, j, sim = cand
        info = await _scan_pair_contradiction(
            high_score_sources[i], high_score_sources[j], query_topic,
            usage=usage,
        )
        return (i, j, sim, info) if info else None

    print_agent_output(
        f"LLM scanning {len(candidates)} candidate pairs for contradictions",
        agent="CONFLICT_DETECTOR",
    )
    scan_results = await asyncio.gather(*[_scan(c) for c in candidates])

    pairs = []
    for r in scan_results:
        if r is not None:
            i, j, sim, info = r
            pairs.append({
                "source_a": high_score_sources[i],
                "source_b": high_score_sources[j],
                "similarity": round(sim, 3),
                "difference_type": info.get("type", "unknown"),
                "difference_explanation": info.get("explanation", ""),
            })

    return pairs


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ConflictDetectorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None,
                 gather_evidence: bool = True):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers
        self.gather_evidence = gather_evidence

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        query = research_state["task"]["query"]
        print_agent_output(
            f"Detecting conflicts among {len(source_scores)} sources",
            agent="CONFLICT_DETECTOR",
        )

        local_usage: list = []
        pairs = await find_contradictions(source_scores, query_topic=query, usage=local_usage)
        if not pairs:
            print_agent_output("No contradictory pairs found after LLM scan", agent="CONFLICT_DETECTOR")
            return {
                "conflicts": [],
                "quality_signals": [{"agent": "conflict_detector", "conflicts_found": 0, "resolved_count": 0}],
                "token_usage": research_state.get("token_usage", [])
                + [summarize_usage("conflict_detector", local_usage)],
            }

        print_agent_output(
            f"LLM scan confirmed {len(pairs)} contradictory pairs, running flash arbitration",
            agent="CONFLICT_DETECTOR",
        )

        def _make_prompt(a: dict, b: dict) -> list[dict]:
            return [
                {"role": "system", "content": ARBITRATION_SYSTEM},
                {"role": "user", "content": (
                    f"## Topic\n{query}\n\n"
                    f"## Source A (score: {a['total_score']}/10, authority: {a['scores']['authority']}, evidence: {a.get('evidence_type', 'citation')})\nClaim: {a.get('title', '')}\n\n"
                    f"## Source B (score: {b['total_score']}/10, authority: {b['scores']['authority']}, evidence: {b.get('evidence_type', 'citation')})\nClaim: {b.get('title', '')}"
                )},
            ]

        def _build_conflict(pair: dict, result: dict, model: str = "flash") -> dict:
            return {
                "claim_a": pair["source_a"].get("title", ""),
                "claim_b": pair["source_b"].get("title", ""),
                "source_a": {"url": pair["source_a"]["url"], "score": pair["source_a"]["total_score"]},
                "source_b": {"url": pair["source_b"]["url"], "score": pair["source_b"]["total_score"]},
                "similarity": pair["similarity"],
                "resolution": result.get("resolution", "insufficient_data"),
                "confidence": result.get("confidence", "low"),
                "reasoning": result.get("reasoning", ""),
                "key_factor": result.get("key_factor", ""),
                "arbiter_model": model,
                "evidence_collected": result.get("evidence_collected", ""),
                "difference_type": pair.get("difference_type", "unknown"),
                "difference_explanation": pair.get("difference_explanation", ""),
            }

        # --- Stage 1: Flash arbitration (parallel) ---
        async def _arbitrate_one(pair: dict) -> dict:
            det = _deterministic_arbitration(pair["source_a"], pair["source_b"])
            if det is not None:
                return _build_conflict(pair, det, model="deepseek-flash(rule)")
            async with FLASH_SEM:
                result = await call_model(
                    _make_prompt(pair["source_a"], pair["source_b"]),
                    model="deepseek-flash", tag="conflict_arbitration",
                    response_format="json",
                    usage=local_usage,
                )
            return _build_conflict(pair, result, model="deepseek-flash")

        raw_conflicts = await asyncio.gather(
            *[_arbitrate_one(p) for p in pairs], return_exceptions=True,
        )

        conflicts = []
        low_confidence_pairs = []
        for pair, result in zip(pairs, raw_conflicts):
            if isinstance(result, BudgetError):
                raise result
            if isinstance(result, Exception):
                print_agent_output("Flash arbitration failed", agent="CONFLICT_DETECTOR")
                continue
            conflicts.append(result)
            if result["confidence"] == "low":
                low_confidence_pairs.append(pair)

        # Cap evidence gathering at top-1 most ambiguous pair (sorted by confidence gap)
        low_confidence_pairs = low_confidence_pairs[:1]

        # --- Stage 2: Evidence gathering + pro re-arbitration (parallel) ---
        if low_confidence_pairs and self.gather_evidence:
            print_agent_output(
                f"Evidence-gathering re-arbitration: {len(low_confidence_pairs)} pair(s)",
                agent="CONFLICT_DETECTOR",
            )
            sem = asyncio.Semaphore(3)  # Evidence gathering is heavy (multi-API per pair)

            async def _re_arbitrate(idx: int, pair: dict) -> int | None:
                async with sem:
                    a = pair["source_a"]
                    b = pair["source_b"]
                    evidence = ""
                    try:
                        evidence = await _gather_evidence(
                            topic=query,
                            claim_a=a.get("title", ""),
                            claim_b=b.get("title", ""),
                            usage=local_usage,
                        )
                    except BudgetError:
                        raise
                    except Exception:
                        print_agent_output("Evidence gathering failed", agent="CONFLICT_DETECTOR")

                    enriched_claim_a = a.get("title", "")
                    enriched_claim_b = b.get("title", "")
                    if evidence:
                        enriched_claim_a = (
                            f"{a.get('title', '')}\n\n"
                            f"[Evidence from additional search: {evidence}]"
                        )
                        enriched_claim_b = (
                            f"{b.get('title', '')}\n\n"
                            f"[Evidence from additional search: {evidence}]"
                        )

                    enriched_a = dict(a, title=enriched_claim_a)
                    enriched_b = dict(b, title=enriched_claim_b)

                    try:
                        async with QW_SEM:
                            qw_result = await call_model(
                                _make_prompt(enriched_a, enriched_b),
                                model="qwen-flash", tag="conflict_rearbitration",
                                response_format="json",
                                timeout=300.0,
                                usage=local_usage,
                            )
                    except BudgetError:
                        raise
                    except Exception:
                        print_agent_output("Pro re-arbitration failed", agent="CONFLICT_DETECTOR")
                        return None

                    qw_conflict = _build_conflict(pair, qw_result, model="qwen-flash+evidence")
                    qw_conflict["evidence_collected"] = evidence[:500] if evidence else ""
                    return idx, qw_conflict

            re_results = await asyncio.gather(
                *[_re_arbitrate(i, p) for i, p in enumerate(low_confidence_pairs)],
                return_exceptions=True,
            )
            for r in re_results:
                if isinstance(r, BudgetError):
                    raise r
                if isinstance(r, Exception):
                    continue
                if r is not None:
                    idx, qw_conflict = r
                    if idx < len(conflicts):
                        conflicts[idx] = qw_conflict
        elif low_confidence_pairs:
            print_agent_output(
                f"Skipping evidence gathering (disabled): {len(low_confidence_pairs)} pair(s)",
                agent="CONFLICT_DETECTOR",
            )

        resolved_count = sum(
            1 for c in conflicts
            if c.get("resolution") not in ("insufficient_data", None)
        )
        return {
            "conflicts": conflicts,
            "quality_signals": [{
                "agent": "conflict_detector",
                "conflicts_found": len(conflicts),
                "resolved_count": resolved_count,
                "unresolved_count": len(conflicts) - resolved_count,
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conflict_detector", local_usage)],
        }
