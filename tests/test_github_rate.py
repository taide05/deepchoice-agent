"""GitHub search rate limiter: pacing, concurrency cap, retry backoff (no real network)."""
import asyncio
import time

import pytest

from deepchoice.retrievers import github_rate as gr


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    gr._reset_for_tests()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    yield


def test_interval_auth_vs_anon(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert gr.interval_s() == pytest.approx(60.0 / 10)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    assert gr.interval_s() == pytest.approx(60.0 / 30)


def test_retry_delay_prefers_retry_after_seconds():
    assert gr.retry_delay({"Retry-After": "30"}) == pytest.approx(30.0)


def test_retry_delay_honors_x_ratelimit_reset():
    reset = time.time() + 15.0
    assert gr.retry_delay({"X-RateLimit-Reset": str(reset)}) == pytest.approx(15.0, abs=1.0)


def test_retry_delay_clamps_huge_values():
    assert gr.retry_delay({"Retry-After": "999999"}) == pytest.approx(gr._MAX_RETRY_WAIT_S)


def test_retry_delay_falls_back_when_headers_missing():
    assert gr.retry_delay({}) == pytest.approx(gr.interval_s())


def test_retry_delay_handles_garbage_retry_after():
    # Non-numeric Retry-After (GitHub never sends an HTTP date) → fall back, no crash.
    assert gr.retry_delay({"Retry-After": "not-a-number"}) == pytest.approx(gr.interval_s())


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.headers = {}


def _fake_client(statuses):
    """statuses: list of ints consumed per get() call, then repeats the last."""
    calls = {"n": 0}

    async def get(url, params=None, headers=None):
        idx = min(calls["n"], len(statuses) - 1)
        calls["n"] += 1
        return _Resp(statuses[idx])

    class _Client:
        pass

    _Client.get = staticmethod(get)
    return _Client(), calls


def test_get_with_throttle_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(gr, "retry_delay", lambda headers: 0.0)
    client, calls = _fake_client([429, 200])

    resp = asyncio.run(gr.get_with_throttle(client, "https://x"))
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_get_with_throttle_does_not_retry_non_429(monkeypatch):
    monkeypatch.setattr(gr, "retry_delay", lambda headers: 0.0)
    client, calls = _fake_client([500])

    resp = asyncio.run(gr.get_with_throttle(client, "https://x"))
    assert resp.status_code == 500
    assert calls["n"] == 1


def test_get_with_throttle_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(gr, "retry_delay", lambda headers: 0.0)
    client, calls = _fake_client([429])

    resp = asyncio.run(gr.get_with_throttle(client, "https://x"))
    assert resp.status_code == 429
    assert calls["n"] == gr._MAX_RETRIES + 1


def test_slot_caps_concurrency(monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(gr, "_pace", _noop)
    in_flight = {"n": 0, "max": 0}

    async def worker():
        async with gr.request_slot():
            in_flight["n"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["n"])
            await asyncio.sleep(0.01)
            in_flight["n"] -= 1

    async def run():
        await asyncio.gather(*[worker() for _ in range(8)])

    asyncio.run(run())
    assert in_flight["max"] <= gr._MAX_IN_FLIGHT


def test_slot_paces_requests(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    t = {"now": 0.0}
    monkeypatch.setattr(gr.time, "monotonic", lambda: t["now"])
    slept = []

    async def fake_sleep(d):
        slept.append(d)
        t["now"] += d

    monkeypatch.setattr(gr.asyncio, "sleep", fake_sleep)

    async def run():
        async with gr.request_slot():
            pass
        async with gr.request_slot():
            pass

    asyncio.run(run())
    assert slept == [pytest.approx(2.0)]
