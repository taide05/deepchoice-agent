"""Targeted check of the whole-consumption deadline. No network, no clock edits.

Scenarios:
  A  upstream stalls for longer than a short deadline without producing any
     event: the wrapper must expire on its own and the source's cleanup must run
  B  normal stream: every event is produced and the deadline is not consumed by
     waiting for events (a second wait does not renew the 900s budget)
  C  an upstream TimeoutError raised inside the deadline is NOT reported as the
     run deadline
  D  external cancellation propagates and is not swallowed
"""
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(r"D:\deepchoice-precodex")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

os.environ["PRECODEX_WALL_MAX_S"] = "1"   # short deadline for A/C

import run_limits  # noqa: E402

from deepchoice.agents import orchestrator  # noqa: E402

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


cleanup = {"ran": 0}


async def stalling_source(self, *args, **kwargs):
    """Never yields; stalls. Cleanup must still run on expiry."""
    try:
        await asyncio.sleep(120)
        yield {"node": "never"}
    finally:
        cleanup["ran"] += 1


async def normal_source(self, *args, **kwargs):
    for index in range(3):
        await asyncio.sleep(0)
        yield {"node": f"n{index}"}


async def upstream_timeout_source(self, *args, **kwargs):
    raise TimeoutError("upstream own timeout")
    yield {"node": "never"}


async def cancellable_source(self, *args, **kwargs):
    try:
        while True:
            await asyncio.sleep(0.01)
            yield {"node": "tick"}
    finally:
        cleanup["ran"] += 1


async def install(source_fn):
    orchestrator.ChiefEditorAgent.astream_research_task = source_fn
    run_limits.arm_run_timer()
    return orchestrator.ChiefEditorAgent.astream_research_task


async def scenario_a():
    print("--- A: no events at all, short deadline, cleanup must run ---")
    cleanup["ran"] = 0
    wrapped = await install(stalling_source)
    agent = orchestrator.ChiefEditorAgent.__new__(orchestrator.ChiefEditorAgent)
    raised = None
    produced = []
    started = asyncio.get_event_loop().time()
    try:
        async for event in wrapped(agent):
            produced.append(event)
    except Exception as exc:
        raised = exc
    elapsed = asyncio.get_event_loop().time() - started
    check("expired on its own with zero events",
          isinstance(raised, run_limits.DispatchLimitReached), type(raised).__name__)
    check("no event was produced", not produced)
    check("expired near the short deadline, not 120s",
          0.8 <= elapsed <= 5.0, f"elapsed={elapsed:.2f}s")
    check("source cleanup ran", cleanup["ran"] == 1, f"cleanup={cleanup['ran']}")
    check("stop reason recorded as wall_clock",
          run_limits._state["stop_reason"] == "wall_clock",
          str(run_limits._state["stop_reason"]))


async def scenario_b():
    print("--- B: normal stream unaffected; waiting does not renew the budget ---")
    os.environ["PRECODEX_WALL_MAX_S"] = "900"
    import importlib
    importlib.reload(run_limits)
    run_limits.arm()
    wrapped = await install(normal_source)
    agent = orchestrator.ChiefEditorAgent.__new__(orchestrator.ChiefEditorAgent)
    seen = []
    async for event in wrapped(agent):
        seen.append(event["node"])
        await asyncio.sleep(0.35)  # longer than the A deadline, inside the 900s one
    check("every event produced under a healthy deadline",
          seen == ["n0", "n1", "n2"], f"seen={seen}")


async def scenario_c():
    print("--- C: upstream TimeoutError is not reported as the run deadline ---")
    os.environ["PRECODEX_WALL_MAX_S"] = "5"
    import importlib
    importlib.reload(run_limits)
    run_limits.arm()
    wrapped = await install(upstream_timeout_source)
    agent = orchestrator.ChiefEditorAgent.__new__(orchestrator.ChiefEditorAgent)
    raised = None
    try:
        async for _ in wrapped(agent):
            pass
    except Exception as exc:
        raised = exc
    check("upstream TimeoutError propagates as TimeoutError",
          isinstance(raised, TimeoutError)
          and not isinstance(raised, run_limits.DispatchLimitReached),
          type(raised).__name__)
    check("run deadline not recorded for an upstream timeout",
          run_limits._state["stop_reason"] is None,
          str(run_limits._state["stop_reason"]))


async def scenario_d():
    print("--- D: external cancellation propagates ---")
    os.environ["PRECODEX_WALL_MAX_S"] = "900"
    import importlib
    importlib.reload(run_limits)
    run_limits.arm()
    cleanup["ran"] = 0
    wrapped = await install(cancellable_source)
    agent = orchestrator.ChiefEditorAgent.__new__(orchestrator.ChiefEditorAgent)

    async def consume():
        async for _ in wrapped(agent):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    raised = None
    try:
        await task
    except asyncio.CancelledError as exc:
        raised = exc
    check("CancelledError propagated, not converted",
          raised is not None and not isinstance(raised, run_limits.DispatchLimitReached),
          type(raised).__name__)


async def main():
    await scenario_a()
    await scenario_b()
    await scenario_c()
    await scenario_d()
    print("--- summary ---")
    for label, ok, _ in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = [c for c in checks if not c[1]]
    print(f"  {len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
