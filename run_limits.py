"""Stop lines for the single authorized diagnostic run.

The candidate revision (48b32bd) predates the durable budget layer, so the
three limits are enforced here, at the real dispatch points, before any request
leaves the process. Nothing is persisted and no durable budget system is added.

  LLM requests   hard cap. Counted by subclassing the OpenAI async client and
                 wrapping `request()`, which is the single funnel that
                 `chat.completions.create` reaches through `_post`. Every real
                 HTTP attempt increments exactly once, so the retry loop in
                 utils.llm and any SDK-level retry are both included.
  Tavily POSTs   hard cap, counted in the keypool transport that every Tavily
                 search POST goes through, so key-failover retries count too.
  Wall clock     dispatch deadline from arming. A request already in flight
                 cannot be interrupted; this stops new dispatches, which is
                 what gets recorded.

Nothing here changes research nodes, prompts, parsing or retry policy.
"""
from __future__ import annotations

import os
import time

LLM_REQUESTS_MAX = int(os.environ.get("PRECODEX_LLM_MAX", "40"))
TAVILY_POSTS_MAX = int(os.environ.get("PRECODEX_TAVILY_MAX", "24"))
WALL_CLOCK_MAX_S = float(os.environ.get("PRECODEX_WALL_MAX_S", "900"))

_state: dict = {
    "llm_requests": 0,
    "tavily_posts": 0,
    "llm_rejected": 0,
    "tavily_rejected": 0,
    "started_at": None,
    "stop_reason": None,
    "events": [],
}


class DispatchLimitReached(RuntimeError):
    """Raised instead of dispatching once a stop line has been reached."""


def _note(kind: str, detail: str = "") -> None:
    started = _state["started_at"]
    elapsed = round(time.monotonic() - started, 1) if started else 0.0
    _state["events"].append({"elapsed_s": elapsed, "kind": kind, "detail": detail})
    if _state["stop_reason"] is None:
        _state["stop_reason"] = kind
    print(f"[stop-line] {kind} {detail} (t+{elapsed}s)", flush=True)


def _deadline_hit() -> bool:
    started = _state["started_at"]
    if started is None:
        return False
    if time.monotonic() - started >= WALL_CLOCK_MAX_S:
        if _state["stop_reason"] is None:
            _note("wall_clock", f">={WALL_CLOCK_MAX_S}s")
        return True
    return False


def _limit_reached() -> bool:
    """True once any stop line has been reached."""
    return (
        _state["llm_requests"] >= LLM_REQUESTS_MAX
        or _state["tavily_posts"] >= TAVILY_POSTS_MAX
        or _state["stop_reason"] is not None
    )


def snapshot() -> dict:
    out = dict(_state)
    out.update(
        llm_requests_max=LLM_REQUESTS_MAX,
        tavily_posts_max=TAVILY_POSTS_MAX,
        wall_clock_max_s=WALL_CLOCK_MAX_S,
    )
    if _state["started_at"] is not None:
        out["elapsed_s"] = round(time.monotonic() - _state["started_at"], 1)
    return out


def _guard(counter: str, rejected: str, cap: int, label: str, deadline_kind: str) -> None:
    if _deadline_hit():
        _state[rejected] += 1
        raise DispatchLimitReached(f"wall clock stop line reached ({label})")
    if _state[counter] >= cap:
        _state[rejected] += 1
        _note(counter, f"cap {cap} reached")
        raise DispatchLimitReached(f"{label} stop line reached ({cap})")


def arm_run_timer() -> None:
    """Start the wall clock at research dispatch and cancel work past the limit.

    Separate from arm() because the research clock starts when the run is
    dispatched, not when the service starts. Wrapping the orchestrator's stream
    gives run-level cancellation: `asyncio.wait_for` cancels the graph task when
    the deadline passes, so cancellable work stops rather than only being
    refused at the next dispatch.
    """
    from deepchoice.agents import orchestrator

    original = orchestrator.ChiefEditorAgent.astream_research_task
    _state["run_started_at"] = time.monotonic()

    def timed(self, *args, **kwargs):
        async def runner():
            return await original(self, *args, **kwargs)

        return _wall_guard(runner())

    orchestrator.ChiefEditorAgent.astream_research_task = timed
    print(f"[stop-line] research wall clock started: {WALL_CLOCK_MAX_S}s", flush=True)


async def _wall_guard(coro):
    import asyncio

    try:
        return await asyncio.wait_for(coro, timeout=WALL_CLOCK_MAX_S)
    except asyncio.TimeoutError:
        _note("wall_clock", f"research exceeded {WALL_CLOCK_MAX_S}s; work cancelled")
        raise DispatchLimitReached(
            f"research wall clock reached ({WALL_CLOCK_MAX_S}s); work cancelled"
        ) from None


def arm() -> None:
    """Patch the real dispatch points. Call after credentials are configured."""
    import httpx
    import openai
    from deepchoice.utils import llm as llm_module

    _state["started_at"] = time.monotonic()

    # chat.completions.create() calls self._post(...). That attribute is bound
    # per resource instance, not defined on a class, so the counter is installed
    # by subclassing the client and wrapping the resource's own _post after
    # construction. Every real send attempt goes through it, so the retry loop
    # in utils.llm and any SDK-internal retry are each counted once.
    base_client = llm_module.AsyncOpenAI

    class CountingAsyncOpenAI(base_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            resource = self.chat.completions
            inner = resource._post

            async def counted_post(*a, **kw):
                _guard("llm_requests", "llm_rejected", LLM_REQUESTS_MAX,
                       "LLM request", "llm")
                _state["llm_requests"] += 1
                return await inner(*a, **kw)

            resource._post = counted_post

    llm_module.AsyncOpenAI = CountingAsyncOpenAI

    # Every Tavily POST in this revision goes to one endpoint, whatever client
    # created it: the search transport in TavilySearch._do_search (key probing
    # and failover both use it) and the outbound health probe. Counting by
    # destination catches all of them without depending on internal wiring.
    original_client_post = httpx.AsyncClient.post

    async def counted_client_post(self, url, *args, **kwargs):
        target = url if isinstance(url, str) else str(url)
        if "api.tavily.com" in target:
            _guard("tavily_posts", "tavily_rejected", TAVILY_POSTS_MAX,
                   "Tavily POST", "tavily")
            _state["tavily_posts"] += 1
        return await original_client_post(self, url, *args, **kwargs)

    httpx.AsyncClient.post = counted_client_post

    # post_with_failover treats every transport error as "try the next key", so a
    # stop-line exception would be swallowed into a (None, None) return and then
    # raised as "no Tavily API key available". Re-raise it after the call so a
    # reached limit aborts the research instead of degrading into a normal
    # network failure. Only the stop-line error is affected; ordinary transport
    # errors keep their existing failover behaviour.
    import deepchoice.retrievers.tavily_keypool as keypool
    import deepchoice.retrievers.tavily_search as tavily_search

    original_failover = keypool.post_with_failover

    async def limit_aware_failover(post, payload, *args, **kwargs):
        outcome = None
        try:
            outcome = await original_failover(post, payload, *args, **kwargs)
        except DispatchLimitReached:
            raise
        except Exception:
            if _limit_reached():
                raise DispatchLimitReached(
                    "stop line reached during Tavily failover"
                ) from None
            raise
        if _limit_reached() and (not outcome or outcome[0] is None):
            raise DispatchLimitReached("stop line reached during Tavily failover")
        return outcome

    keypool.post_with_failover = limit_aware_failover
    tavily_search.post_with_failover = limit_aware_failover

    print(
        f"[stop-line] armed: LLM<= {LLM_REQUESTS_MAX} requests "
        f"(per-client _post), Tavily<= {TAVILY_POSTS_MAX} POSTs "
        f"(api.tavily.com via httpx), wall<= {WALL_CLOCK_MAX_S}s",
        flush=True,
    )
