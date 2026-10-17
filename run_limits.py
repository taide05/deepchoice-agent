"""Stop lines for the single authorized diagnostic run.

The candidate revision (48b32bd) predates the durable budget layer, so the three
limits are enforced here, at real dispatch points, before any request leaves the
process. Nothing is persisted and no durable budget system is added, and no
research node, prompt, parsing or retry rule is changed.

  LLM requests   Counted in `_prepare_request`, which the installed SDK calls
                 inside its retry loop immediately before each real send, so
                 every attempt is counted whether it comes from utils.llm's own
                 retry loop or from SDK-internal retries.
  Tavily POSTs   Counted for api.tavily.com inside httpx.AsyncClient.post, so the
                 search transport, key probing and key failover are all covered.
  Wall clock     Measured from the moment research actually starts, not from
                 service start, and enforced outside the async-for consumption so
                 the async generator interface is preserved. The deadline cancels
                 the research instead of only refusing later dispatches.

A stop reached in one category stops the whole run: both guards consult one
shared stop state, so no further send of either kind happens afterwards.

A run also leaves its own minimal record: identity and limits at research start,
counters on every change, and final state when it ends. That record is written
from the research process itself, so a run that is killed by the launcher's
process guard still leaves what was confirmed, rather than waiting for a clean
finish that never happens. It reuses the existing counters; it adds no new
observation system and stores no credentials or request content.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time

LLM_REQUESTS_MAX = int(os.environ.get("PRECODEX_LLM_MAX", "40"))
TAVILY_POSTS_MAX = int(os.environ.get("PRECODEX_TAVILY_MAX", "24"))
WALL_CLOCK_MAX_S = float(os.environ.get("PRECODEX_WALL_MAX_S", "900"))

_state: dict = {
    "llm_requests": 0,
    "tavily_posts": 0,
    "llm_rejected": 0,
    "tavily_rejected": 0,
    "started_at": None,          # arming time
    "run_started_at": None,      # research start: what the wall clock uses
    "stop_reason": None,
    "stop_at": None,
    "events": [],
}

# Verification-only: shifts the research clock so a deadline can be exercised
# without waiting. Left at zero in a real run.
_run_clock_offset_s = 0.0

# The running research's output directory and identity. Set at research start;
# counters are written here as they change, so an abnormal exit still leaves its
# confirmed counts on disk.
_run_dir: pathlib.Path | None = None
_task_id: str | None = None


class DispatchLimitReached(RuntimeError):
    """Raised once any stop line has been reached; aborts the run."""


class RunRecordError(RuntimeError):
    """The run record could not be established, so research must not start.

    The guard's deadline and any later reconstruction both depend on this record;
    starting the graph without it would be an untracked run.
    """


def normalize_single_tavily_key() -> int:
    """Reduce the Tavily configuration to exactly one key.

    Run before anything imports the key pool. Both environment names are set to
    the same single key so that re-reading them later cannot rebuild a multi-key
    pool, and a pool-wide re-probe is never enabled.
    """
    os.environ.pop("TAVILY_REPROBE", None)
    raw = os.environ.get("TAVILY_API_KEYS", "") or os.environ.get("TAVILY_API_KEY", "")
    first = next((part.strip() for part in raw.split(",") if part.strip()), "")
    if not first:
        return 0
    os.environ["TAVILY_API_KEYS"] = first
    os.environ["TAVILY_API_KEY"] = first
    return 1


# ---------------------------------------------------------------- stop state
def _note(kind: str, detail: str = "") -> None:
    started = _state["started_at"]
    elapsed = round(time.monotonic() - started, 1) if started else 0.0
    if _state["stop_at"] is None:
        _state["stop_at"] = time.monotonic()
    _state["events"].append({"elapsed_s": elapsed, "kind": kind, "detail": detail})
    if _state["stop_reason"] is None:
        _state["stop_reason"] = kind
    print(f"[stop-line] {kind} {detail} (t+{elapsed}s)", flush=True)
    _persist_active()


def stopped() -> bool:
    """One global stop state, consulted by every dispatch path."""
    return _state["stop_reason"] is not None


# ------------------------------------------------------------ run record
def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


def _run_state(mutate: dict | None = None) -> dict:
    """Current run-state record, optionally updated with `mutate`."""
    record = {
        "task_id": _task_id,
        "state": "running",
        "pid": os.getpid(),
        # The launcher's per-service token: how its guard knows this run belongs
        # to the child it started, without depending on process ids.
        "service_token": os.environ.get("DEEPCHOICE_SERVICE_TOKEN"),
        "started_at_epoch": _state.get("run_started_at_epoch"),
        "started_at_iso": _iso(_state.get("run_started_at_epoch")),
        "ended_at_epoch": None,
        "ended_at_iso": None,
        "wall_clock_max_s": WALL_CLOCK_MAX_S,
        "llm_requests_max": LLM_REQUESTS_MAX,
        "tavily_posts_max": TAVILY_POSTS_MAX,
        "stop_reason": _state.get("stop_reason"),
        "counts_at_start": _state.get("counts_at_start"),
        "counts": {
            "llm_requests": _state["llm_requests"],
            "tavily_posts": _state["tavily_posts"],
        },
    }
    if mutate:
        record.update(mutate)
    return record


def _write_run_state(record: dict, strict: bool = False) -> str | None:
    """Write the run record. Strict writes raise: the record gates dispatch."""
    if _run_dir is None:
        if strict:
            raise RunRecordError("no run output directory was set")
        return None
    try:
        _run_dir.mkdir(parents=True, exist_ok=True)
        path = _run_dir / "run_state.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception as exc:
        if strict:
            raise
        print(f"[stop-line] could not write run state: {exc}", flush=True)
        return None


def _persist_active() -> bool:
    """Write the counters as they change while a run is active."""
    if _run_dir is None:
        return False
    persist_counts(str(_run_dir))
    return (_run_dir / "run_limits_counts.json").is_file()


def begin_run(task_id: str, directory: str) -> None:
    """Record the run's identity at the moment research actually starts.

    This is a precondition for dispatch, not a courtesy log line: if the identity,
    start time and limits cannot be written, the caller must not enter the graph
    or make a research outbound call, and raises RunRecordError.
    """
    global _run_dir, _task_id
    _run_dir = pathlib.Path(directory)
    _task_id = task_id
    # Each run gets its own clock. Reusing an earlier run's start would make the
    # guard treat a fresh run as already near its deadline.
    _state["run_started_at_epoch"] = time.time()
    if _state.get("run_started_at") is None or _state.get("run_ended"):
        _state["run_started_at"] = time.monotonic()
        _state["run_ended"] = False
    _state["counts_at_start"] = {
        "llm_requests": _state["llm_requests"],
        "tavily_posts": _state["tavily_posts"],
    }
    record = _run_state({"state": "running"})
    try:
        state_path = _write_run_state(record, strict=True)
        counts_written = _persist_active()
    except Exception as exc:
        raise RunRecordError(
            f"run record could not be established: {type(exc).__name__}: {exc}"
        ) from exc
    if not state_path or not pathlib.Path(state_path).is_file() or not counts_written:
        raise RunRecordError(
            "run record could not be established: identity or counters were not written"
        )
    print(f"[stop-line] run record started for {task_id}", flush=True)


def end_run(state: str, detail: str = "") -> None:
    """Record how the run ended, from the research process itself.

    `state` is one of complete / failed / cancelled — a forced termination is
    never written here as complete; the launcher's guard records that separately.
    """
    record = _run_state({
        "state": state,
        "detail": detail,
        "stop_reason": _state.get("stop_reason"),
        "ended_at_epoch": time.time(),
        "ended_at_iso": _iso(time.time()),
    })
    _write_run_state(record)
    _persist_active()
    _state["run_ended"] = True
    print(f"[stop-line] run record ended: {state}"
          f"{(' — ' + detail) if detail else ''}", flush=True)


def _run_elapsed() -> float | None:
    started = _state["run_started_at"]
    if started is None:
        return None
    return time.monotonic() - started + _run_clock_offset_s


def set_run_clock_offset(seconds: float) -> None:
    """Verification-only clock shift; no effect when left at zero."""
    global _run_clock_offset_s
    _run_clock_offset_s = float(seconds)


def set_wall_clock_max(seconds: float) -> None:
    """Verification-only: shorten the real deadline. Not used in a real run."""
    global WALL_CLOCK_MAX_S
    WALL_CLOCK_MAX_S = float(seconds)


def _check(kind: str) -> None:
    """Raise if this run may no longer dispatch.

    Order matters: the shared stop flag is consulted first, so once any category
    has tripped, every later dispatch of either category is refused.
    """
    if stopped():
        raise DispatchLimitReached(
            f"run already stopped by {_state['stop_reason']}; refusing new dispatch"
        )
    elapsed = _run_elapsed()
    if elapsed is not None and elapsed >= WALL_CLOCK_MAX_S:
        _note("wall_clock", f"research exceeded {WALL_CLOCK_MAX_S}s")
        raise DispatchLimitReached(
            f"research wall clock reached ({WALL_CLOCK_MAX_S}s)"
        )
    if kind == "llm" and _state["llm_requests"] >= LLM_REQUESTS_MAX:
        _note("llm_requests", f"cap {LLM_REQUESTS_MAX} reached")
        raise DispatchLimitReached(f"LLM request stop line reached ({LLM_REQUESTS_MAX})")
    if kind == "tavily" and _state["tavily_posts"] >= TAVILY_POSTS_MAX:
        _note("tavily_posts", f"cap {TAVILY_POSTS_MAX} reached")
        raise DispatchLimitReached(f"Tavily POST stop line reached ({TAVILY_POSTS_MAX})")


def snapshot() -> dict:
    out = dict(_state)
    out.update(
        task_id=_task_id,
        llm_requests_max=LLM_REQUESTS_MAX,
        tavily_posts_max=TAVILY_POSTS_MAX,
        wall_clock_max_s=WALL_CLOCK_MAX_S,
    )
    if _state["started_at"] is not None:
        out["elapsed_s"] = round(time.monotonic() - _state["started_at"], 1)
    elapsed = _run_elapsed()
    if elapsed is not None:
        out["run_elapsed_s"] = round(elapsed, 1)
    return out


# ---------------------------------------------------------------- run timing
def persist_counts(directory: str | None = None) -> str | None:
    """Write the counters beside the run's own outputs.

    The counters live in this process, so without this an aborted run leaves no
    record of how many requests it actually made. This writes the existing
    counters as they are; it adds no budget or observability system.
    """
    import json
    import pathlib

    target = pathlib.Path(directory) if directory else pathlib.Path.cwd() / "outputs"
    try:
        target.mkdir(parents=True, exist_ok=True)
        path = target / "run_limits_counts.json"
        path.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"[stop-line] counts written to {path}", flush=True)
        return str(path)
    except Exception as exc:
        print(f"[stop-line] could not write counts: {exc}", flush=True)
        return None


def start_run_clock() -> None:
    """Start the research wall clock. Called when a run actually begins.

    Idempotent: `begin_run` already starts it from the research task, and the
    stream timer also arms it. The first start wins, so the guard, the timer and
    the in-process checks all measure from the same moment.
    """
    if _state["run_started_at"] is not None:
        return
    _state["run_started_at"] = time.monotonic()
    if _state.get("run_started_at_epoch") is None:
        _state["run_started_at_epoch"] = time.time()
    print(f"[stop-line] research clock started ({WALL_CLOCK_MAX_S}s)", flush=True)


# ---------------------------------------------------------------- arming
def arm() -> None:
    """Patch the real dispatch points. Call after credentials are configured."""
    import httpx
    from deepchoice.utils import llm as llm_module

    _state["started_at"] = time.monotonic()
    base_client = llm_module.AsyncOpenAI

    class CountingAsyncOpenAI(base_client):
        """Counts every real send attempt by hooking the pre-send step.

        The installed SDK calls `_prepare_request(request)` inside its retry
        loop, directly before the network send, so this counts one per actual
        attempt regardless of where the retry came from.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            inner = self._prepare_request

            async def counted_prepare(request, *a, **kw):
                _check("llm")
                _state["llm_requests"] += 1
                if stopped():
                    _state["llm_rejected"] += 1
                # Persist as it changes: a killed run must leave the confirmed
                # count rather than wait for a clean finish.
                _persist_active()
                return await inner(request, *a, **kw)

            self._prepare_request = counted_prepare

    llm_module.AsyncOpenAI = CountingAsyncOpenAI

    original_client_post = httpx.AsyncClient.post

    async def counted_client_post(self, url, *args, **kwargs):
        target = url if isinstance(url, str) else str(url)
        if "api.tavily.com" in target:
            try:
                _check("tavily")
            except DispatchLimitReached:
                _state["tavily_rejected"] += 1
                raise
            _state["tavily_posts"] += 1
            _persist_active()
        return await original_client_post(self, url, *args, **kwargs)

    httpx.AsyncClient.post = counted_client_post

    print(
        f"[stop-line] armed: LLM<= {LLM_REQUESTS_MAX} requests (_prepare_request), "
        f"Tavily<= {TAVILY_POSTS_MAX} POSTs (api.tavily.com), "
        f"wall<= {WALL_CLOCK_MAX_S}s from research start",
        flush=True,
    )


def arm_run_timer() -> None:
    """Bound the whole consumption by elapsed research time, as an async generator.

    The wrapper stays an async generator so callers keep using `async for`.

    Each wait for the next event runs inside its own `asyncio.timeout` armed with
    the time REMAINING against one deadline taken at research start. So the total
    consumption cannot exceed the limit, waiting for an event never renews the
    full budget, and an upstream that stalls without ever producing an event
    still expires. The scope is disarmed while the wrapper is suspended at a
    yield, so our deadline can never cancel work that belongs to the consumer.

    Our own expiry is told apart from an upstream TimeoutError by asking the
    scope whether it expired; an upstream TimeoutError raised inside the scope
    leaves it unexpired and is re-raised as upstream behaviour.
    """
    from deepchoice.agents import orchestrator

    original = orchestrator.ChiefEditorAgent.astream_research_task

    async def timed_stream(self, *args, **kwargs):
        start_run_clock()
        deadline = time.monotonic() + WALL_CLOCK_MAX_S
        source = original(self, *args, **kwargs)

        async def close_source() -> None:
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass  # cleanup must not replace the stop reason

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _note("wall_clock", f"research exceeded {WALL_CLOCK_MAX_S}s")
                    await close_source()
                    raise DispatchLimitReached(
                        f"research wall clock reached ({WALL_CLOCK_MAX_S}s); cancelled"
                    )
                scope = asyncio.timeout(remaining)
                try:
                    async with scope:
                        event = await source.__anext__()
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    if scope.expired():
                        _note("wall_clock", f"research exceeded {WALL_CLOCK_MAX_S}s")
                        await close_source()
                        raise DispatchLimitReached(
                            f"research wall clock reached ({WALL_CLOCK_MAX_S}s); "
                            "cancelled"
                        ) from None
                    await close_source()
                    raise
                if stopped():
                    await close_source()
                    raise DispatchLimitReached(
                        f"run stopped by {_state['stop_reason']}; research cancelled"
                    )
                yield event
        except asyncio.CancelledError:
            # External cancellation is not ours to swallow.
            await close_source()
            raise
        except DispatchLimitReached:
            await close_source()
            raise

    orchestrator.ChiefEditorAgent.astream_research_task = timed_stream
    print("[stop-line] research stream timer installed (async generator)", flush=True)
