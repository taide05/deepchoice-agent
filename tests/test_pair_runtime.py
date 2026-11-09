"""The pair window caps each arm and the remaining total without resetting counts."""
import asyncio

import pytest

from deepchoice.evaluation.pair_runtime import (
    PairWindow,
    PairWindowError,
    run_arm_limited,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_arm_timeout_is_min_of_arm_and_remaining_total():
    clock = FakeClock()
    window = PairWindow(total_s=100.0, arm_s=30.0, clock=clock)
    assert window.arm_timeout_s() == 30.0
    clock.advance(85.0)
    assert window.arm_timeout_s() == 15.0
    clock.advance(20.0)
    with pytest.raises(PairWindowError):
        window.arm_timeout_s()


def test_actual_arm_timeout_cancels_and_records():
    async def slow():
        await asyncio.sleep(0.2)
        return "late"

    window = PairWindow(total_s=10.0, arm_s=0.02)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run_arm_limited(window, "baseline", slow))
    record = window.arms[0]
    assert record["completed"] is False
    assert record["timed_out"] is True
    assert record["timeout_s"] == 0.02


def test_completed_arm_records_elapsed_and_total_stays_shared():
    async def quick():
        await asyncio.sleep(0.01)
        return "ok"

    clock = FakeClock()
    window = PairWindow(total_s=100.0, arm_s=50.0, clock=clock)
    result, record = asyncio.run(run_arm_limited(window, "candidate", quick))
    assert result == "ok"
    assert record["completed"] is True
    assert record["timed_out"] is False
    assert window.remaining_total_s() <= 100.0
