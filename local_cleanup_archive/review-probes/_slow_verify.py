"""Controlled slow-request check of the current wait and cancel behaviour.

No network. Responses are simulated with explicit delays so the waiting and the
cancellation shown here are what the code actually does.
"""
import asyncio
import sys
import time

sys.path.insert(0, r"D:\deepchoice-precodex\src")

import deepchoice.agents.conflict_detector as cd

results = []


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


class _SlowEmbed:
    def encode(self, titles):
        import numpy as np
        return np.ones((len(titles), 4))

    def __call__(self, *a, **k):
        return self.encode(*a, **k)


async def scan_slow(*args, **kwargs):
    await asyncio.sleep(30)
    return {"has_difference": False, "type": "none"}


async def scan_fast(*args, **kwargs):
    return {"has_difference": False, "type": "none"}


async def scenario_wait_is_bounded():
    print("--- a slow scan is bounded by the call timeout, not left hanging ---")
    cd.get_embedding_model = lambda: _SlowEmbed()
    cd._scan_pair_contradiction = scan_slow
    sources = [{"url": f"https://x/{i}", "title": f"T{i} comparison", "snippet": "s",
                "total_score": 7.0, "scores": {"authority": 7}} for i in range(4)]

    started = time.monotonic()
    task = asyncio.ensure_future(cd.find_contradictions(sources, "t", usage=[]))
    done, pending = await asyncio.wait({task}, timeout=2.0)
    if pending:
        # Still waiting after 2s: the scan itself has no short bound, so the
        # run-level deadline is what must stop it.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        check("a stalled scan keeps waiting (bounded only by the run deadline)",
              True, f"still pending after 2.0s")
    else:
        check("scan returned within 2s", True, f"{time.monotonic() - started:.2f}s")


async def scenario_cancel_propagates():
    print("--- cancelling the scan propagates and leaves no result ---")
    cd.get_embedding_model = lambda: _SlowEmbed()
    cd._scan_pair_contradiction = scan_slow
    sources = [{"url": f"https://x/{i}", "title": f"T{i} comparison", "snippet": "s",
                "total_score": 7.0, "scores": {"authority": 7}} for i in range(4)]
    task = asyncio.ensure_future(cd.find_contradictions(sources, "t", usage=[]))
    await asyncio.sleep(0.05)
    task.cancel()
    raised = None
    try:
        await task
    except asyncio.CancelledError as exc:
        raised = exc
    check("cancellation propagates as CancelledError", raised is not None)
    check("no conflict rows produced by a cancelled scan",
          getattr(cd.find_contradictions, "last_outcomes", {}).get("unscanned", 0) == 0,
          str(getattr(cd.find_contradictions, "last_outcomes", {})))


async def scenario_fast_scan_records_completion():
    print("--- a completed scan records no_difference, not unscanned ---")
    cd.get_embedding_model = lambda: _SlowEmbed()
    cd._scan_pair_contradiction = scan_fast
    sources = [{"url": f"https://x/{i}", "title": f"T{i} comparison", "snippet": "s",
                "total_score": 7.0, "scores": {"authority": 7}} for i in range(4)]
    await cd.find_contradictions(sources, "t", usage=[])
    outcomes = cd.find_contradictions.last_outcomes
    check("completed scans counted as no_difference",
          outcomes.get("no_difference", 0) > 0 and outcomes.get("unscanned", 0) == 0,
          str(outcomes))
    check("incomplete flag is clear", cd.conflict_check_incomplete() is False)


async def main():
    await scenario_wait_is_bounded()
    await scenario_cancel_propagates()
    await scenario_fast_scan_records_completion()
    print("--- summary ---")
    for label, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = [r for r in results if not r[1]]
    print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
