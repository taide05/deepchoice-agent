import asyncio
from collections.abc import Mapping

from ..retrievers import RETRIEVER_REGISTRY
from ..retrievers.base import error_text
from ..retrievers.contracts import RetrievalRequest, RetrievalResult
from ..retrievers.learned_docs import extract_terms, harvest
from ..retrievers.official import TECH_DOCS
from ..observability import ExternalCallKind, TraceStatus, current_trace_recorder
from ..runtime.context import classify_cancelled_trace_status, get_run_context
from ..budget_errors import BudgetError
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
    request: RetrievalRequest | None = None,
) -> tuple[object, bool]:
    try:
        retriever = cls()
    except BudgetError:
        raise
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
        request = request or RetrievalRequest(
            query=query,
            sub_questions=sub_questions,
            max_results=7,
            adapted_queries=adapted_queries,
        )
    except BudgetError:
        raise
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
    except BudgetError:
        raise
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
    except BudgetError:
        raise
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


async def _invoke_retriever_miss(
    name: str,
    cls: type,
    *,
    query: str,
    sub_questions: list[str],
    adapted_queries: list[str],
    request: RetrievalRequest | None = None,
) -> tuple[object, bool]:
    """Record one independent retrieval call without retaining its query."""

    from ..budget import BudgetAmount, BudgetResource, reserve_call, settle_call

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
        reservations = await reserve_call(
            (BudgetAmount(resource=BudgetResource.RETRIEVAL_CALLS, amount=1),),
            call_id=trace_call.call_id if trace_call is not None else None,
            summary={"operation": "retrieval", "provider": name},
        )
    except BudgetError as budget_exc:
        if trace is not None:
            await trace.finish_external_call(
                trace_call,
                status=TraceStatus.FAILED,
                result_summary={
                    "failure_category": (
                        "budget_exceeded"
                        if getattr(budget_exc, "code", "") == "RUN_BUDGET_EXCEEDED"
                        else "budget_gate_failed"
                    )
                },
            )
        raise
    try:
        invocation = await _invoke_retriever_untraced(
            name,
            cls,
            query=query,
            sub_questions=sub_questions,
            adapted_queries=adapted_queries,
            request=request,
        )
    except asyncio.CancelledError:
        await settle_call(
            reservations, {BudgetResource.RETRIEVAL_CALLS: 1}
        )
        if trace is not None:
            await trace.finish_external_call(
                trace_call, status=classify_cancelled_trace_status()
            )
        raise
    except Exception as exc:
        await settle_call(
            reservations, {BudgetResource.RETRIEVAL_CALLS: 1}
        )
        if trace is not None:
            await trace.finish_external_call(
                trace_call,
                status=TraceStatus.FAILED,
                result_summary={"error_type": type(exc).__name__},
            )
        raise

    await settle_call(reservations, {BudgetResource.RETRIEVAL_CALLS: 1})

    raw_result, is_stable = invocation
    try:
        result = RetrievalResult.model_validate(raw_result)
    except Exception:
        trace_status = TraceStatus.FAILED
        summary = {"retrieval_status": "invalid_contract"}
    else:
        if is_stable and result.source != name:
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


def _validated_cache_result(
    raw_result: object,
    *,
    source: str,
    is_stable: bool,
) -> RetrievalResult | None:
    try:
        result = RetrievalResult.model_validate(raw_result)
    except Exception:
        return None
    if result.status != "success":
        return None
    if is_stable and result.source != source:
        return None
    return result


async def _complete_cache_flight(cache, run_id: str, cache_key: str, claim) -> None:
    """Wake followers even when the inline leader is being cancelled."""

    completion = asyncio.create_task(cache.complete(run_id, cache_key, claim))
    cancelled_during_cleanup = False
    while not completion.done():
        try:
            await asyncio.shield(completion)
        except asyncio.CancelledError:
            cancelled_during_cleanup = True
            continue
        except Exception:
            break
    if not completion.cancelled():
        try:
            completion.result()
        except Exception:
            pass
    if cancelled_during_cleanup:
        raise asyncio.CancelledError


def _publish_cache_flight(
    cache,
    claim,
    *,
    invocation: tuple[object, bool] | None = None,
    error: Exception | None = None,
    retry: bool = False,
) -> None:
    try:
        cache.publish(claim, invocation=invocation, error=error, retry=retry)
    except Exception:
        pass


async def _invoke_retriever(
    name: str,
    cls: type,
    *,
    query: str,
    sub_questions: list[str],
    adapted_queries: list[str],
) -> tuple[object, bool, str]:
    """Use a validated cache before the budgeted and traced dispatch path."""

    context = get_run_context()
    cache = context.retrieval_cache if context is not None else None
    if cache is None or not getattr(cache, "enabled", False):
        result, is_stable = await _invoke_retriever_miss(
            name,
            cls,
            query=query,
            sub_questions=sub_questions,
            adapted_queries=adapted_queries,
        )
        return result, is_stable, "bypass"

    try:
        request = RetrievalRequest(
            query=query,
            sub_questions=sub_questions,
            max_results=7,
            adapted_queries=adapted_queries,
        )
        cache_key = cache.make_key(
            source=name,
            request=request,
            manifest_id=context.manifest_id,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        result, is_stable = await _invoke_retriever_miss(
            name,
            cls,
            query=query,
            sub_questions=sub_questions,
            adapted_queries=adapted_queries,
        )
        return result, is_stable, "bypass"

    is_stable = callable(getattr(cls, "retrieve", None))
    waited = False
    while True:
        try:
            cached = _validated_cache_result(
                await cache.get(cache_key),
                source=name,
                is_stable=is_stable,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            cached = None
        if cached is not None:
            return cached, is_stable, "coalesced" if waited else "hit"

        try:
            claim = await cache.claim(context.run_id, cache_key)
        except asyncio.CancelledError:
            raise
        except Exception:
            result, actual_is_stable = await _invoke_retriever_miss(
                name,
                cls,
                query=query,
                sub_questions=sub_questions,
                adapted_queries=adapted_queries,
                request=request,
            )
            return result, actual_is_stable, "miss"

        if not claim.is_leader:
            try:
                await cache.wait(claim)
            except asyncio.CancelledError:
                raise
            except Exception:
                result, actual_is_stable = await _invoke_retriever_miss(
                    name,
                    cls,
                    query=query,
                    sub_questions=sub_questions,
                    adapted_queries=adapted_queries,
                    request=request,
                )
                return result, actual_is_stable, "miss"
            waited = True
            if claim.retry:
                await asyncio.shield(claim.released.wait())
                continue
            shared_error = claim.error
            if isinstance(shared_error, Exception):
                raise shared_error
            shared_invocation = claim.invocation
            if shared_invocation is not None:
                result, actual_is_stable = shared_invocation
                return result, actual_is_stable, "coalesced"
            continue

        try:
            try:
                cached = _validated_cache_result(
                    await cache.get(cache_key),
                    source=name,
                    is_stable=is_stable,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                cached = None
            if cached is not None:
                _publish_cache_flight(
                    cache,
                    claim,
                    invocation=(cached, is_stable),
                )
                return cached, is_stable, "coalesced" if waited else "hit"

            try:
                result, actual_is_stable = await _invoke_retriever_miss(
                    name,
                    cls,
                    query=query,
                    sub_questions=sub_questions,
                    adapted_queries=adapted_queries,
                    request=request,
                )
            except asyncio.CancelledError:
                _publish_cache_flight(cache, claim, retry=True)
                raise
            except Exception as exc:
                _publish_cache_flight(cache, claim, error=exc)
                raise
            _publish_cache_flight(
                cache,
                claim,
                invocation=(result, actual_is_stable),
            )
            cacheable = _validated_cache_result(
                result,
                source=name,
                is_stable=actual_is_stable,
            )
            if cacheable is not None:
                try:
                    await cache.put(cache_key, cacheable, source=name)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            return result, actual_is_stable, "miss"
        finally:
            await _complete_cache_flight(cache, context.run_id, cache_key, claim)

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

        # Budget correctness failures must not be downgraded to ordinary
        # per-source partial failures by the retriever's resilient fan-out.
        for invocation in raw_results:
            if isinstance(invocation, BudgetError):
                raise invocation

        search_results = []
        partial_failures = []
        cache_hits = 0
        cache_coalesced = 0
        cache_misses = 0
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
                result, is_stable, cache_disposition = invocation
                if cache_disposition == "hit":
                    cache_hits += 1
                elif cache_disposition == "coalesced":
                    cache_coalesced += 1
                elif cache_disposition == "miss":
                    cache_misses += 1
                try:
                    validated = RetrievalResult.model_validate(result)
                    if is_stable and validated.source != name:
                        raise ValueError(
                            f"source mismatch: expected {name!r}, got {validated.source!r}"
                        )
                except Exception:
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
                "cache_hits": cache_hits,
                "cache_coalesced": cache_coalesced,
                "cache_misses": cache_misses,
            }],
        }
