"""Small run-window helper for the paired diagnostic.

The real stop lines are the existing `run_limits` process counters and the
launcher's process guard. This helper only makes the one shared clock and the
per-arm sub-deadline explicit so both arms are bounded by the same remaining
total; it adds no independent budget system.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable


class PairWindowError(RuntimeError):
    """The pair window is exhausted or an arm would exceed it."""


@dataclass
class PairWindow:
    total_s: float
    arm_s: float = 900.0
    clock: Callable[[], float] = time.monotonic
    started_at: float = field(init=False)
    arms: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.started_at = self.clock()

    def elapsed_s(self) -> float:
        return max(0.0, self.clock() - self.started_at)

    def remaining_total_s(self) -> float:
        return max(0.0, self.total_s - self.elapsed_s())

    def arm_timeout_s(self) -> float:
        remaining = self.remaining_total_s()
        if remaining <= 0:
            raise PairWindowError("total pair wall clock is exhausted")
        return min(self.arm_s, remaining)

    def begin_arm(self, name: str) -> dict:
        record = {"name": name, "started_at": self.clock(),
                  "timeout_s": self.arm_timeout_s()}
        self.arms.append(record)
        return record

    def end_arm(self, record: dict, *, completed: bool,
                timed_out: bool = False) -> dict:
        record.update({
            "ended_at": self.clock(),
            "elapsed_s": round(self.clock() - record["started_at"], 3),
            "completed": completed,
            "timed_out": timed_out,
        })
        return record


async def run_arm_limited(window: PairWindow, name: str, coro_factory):
    """Run one arm under min(per-arm bound, remaining total)."""
    record = window.begin_arm(name)
    try:
        result = await asyncio.wait_for(coro_factory(), timeout=record["timeout_s"])
    except asyncio.TimeoutError:
        window.end_arm(record, completed=False, timed_out=True)
        raise
    except Exception:
        window.end_arm(record, completed=False)
        raise
    window.end_arm(record, completed=True)
    return result, record
