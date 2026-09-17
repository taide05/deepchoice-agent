"""Process-wide, bounded admission for retrieval provider requests.

These are conservative local policies, not claims about an account's quota.
The supported deployment has one process. Transport changes do not reset a
provider's cooldown. No credentials, URLs or payloads are retained here.
"""
from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC
from email.utils import parsedate_to_datetime

QUEUE_TIMEOUT_S = 600.0
MAX_WAITERS = 256
_clock = time.monotonic
_sleep = asyncio.sleep


class ProviderAdmissionError(RuntimeError):
    """A bounded local queue/cooldown prevented dispatch; not a route failure."""


class ProviderRateLimitError(ProviderAdmissionError):
    status_code = 429


class RequestGate:
    """FIFO admission with cancellation cleanup and no lock held across await.

    Thread-owned state avoids asyncio primitives bound to a previous event loop.
    Waiting tasks own no in-flight permit; each retry joins the queue again.
    The interval separates committed permit grants (sampled under the lock),
    not client invocation timestamps or physical packets. Caller scheduling,
    connection setup and a relay can delay/reorder those later observations.
    The permit remains active until slot exit, including such caller delays.
    Already granted callers are not revoked by subsequent cooldown feedback;
    queued callers must observe it before their own grant. This local admission
    policy cannot guarantee provider quota availability on a shared exit IP.
    """

    def __init__(self, *, interval=0.0, concurrency=1):
        self.interval = interval
        self.concurrency = concurrency
        self._lock = threading.Lock()
        self._queue = deque()
        self._active = 0
        self._next_start = 0.0
        self._cooldown = 0.0
        self._limited = False

    def defer(self, seconds: float) -> None:
        if math.isfinite(seconds) and seconds > 0:
            with self._lock:
                self._cooldown = max(self._cooldown, _clock() + seconds)

    def cooling_down(self) -> bool:
        with self._lock:
            return self._cooldown > _clock()

    def record_limit(self, limited: bool) -> None:
        with self._lock:
            self._limited = limited

    def unavailable(self) -> bool:
        with self._lock:
            return self._limited or self._cooldown > _clock()

    @asynccontextmanager
    async def slot(self, *, timeout=None):
        deadline = _clock() + (QUEUE_TIMEOUT_S if timeout is None else timeout)
        ticket = object()
        admitted = False
        with self._lock:
            if len(self._queue) >= MAX_WAITERS:
                raise ProviderAdmissionError("provider queue is full")
            self._queue.append(ticket)
        try:
            while True:
                with self._lock:
                    now = _clock()
                    if now >= deadline:
                        raise ProviderAdmissionError("provider queue timed out")
                    if self._cooldown >= deadline:
                        # Keep the full server deadline; do not truncate it and
                        # send early merely to fit our local waiting budget.
                        raise ProviderRateLimitError("provider cooldown exceeds queue deadline")
                    wait = max(self._next_start, self._cooldown) - now
                    if self._queue[0] is ticket and self._active < self.concurrency:
                        if wait <= 0:
                            self._queue.popleft()
                            self._active += 1
                            interval = self.interval() if callable(self.interval) else self.interval
                            self._next_start = now + interval
                            admitted = True
                            break
                        delay = min(wait, deadline - now)
                    else:
                        delay = min(0.05, deadline - now)
                await _sleep(delay)
            # Budget authority belongs to the logical caller's atomic
            # reservation. A later denial must not cancel committed work.
            yield
        finally:
            with self._lock:
                if admitted:
                    self._active -= 1
                else:
                    self._queue.remove(ticket)


def github_interval() -> float:
    return 60.0 / (30 if os.environ.get("GITHUB_TOKEN") else 10)


def _new_gates():
    return {
        "github": RequestGate(interval=github_interval, concurrency=2),
        "arxiv": RequestGate(interval=3.0, concurrency=1),
        "community": RequestGate(interval=1.0, concurrency=1),
        "official": RequestGate(interval=0.5, concurrency=2),
        "official-web": RequestGate(interval=0.5, concurrency=2),
    }


_gates = _new_gates()


def gate_for(source: str) -> RequestGate:
    return _gates[source]


def _seconds(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, OverflowError):
        return None


def _header(headers, name):
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None and hasattr(headers, "items"):
        value = next((v for k, v in headers.items() if isinstance(k, str) and k.lower() == name.lower()), None)
    return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def retry_after(headers, *, default: float, github=False) -> float:
    value = _header(headers, "Retry-After")
    delay = _seconds(value)
    if delay is None and isinstance(value, str):
        try:
            instant = parsedate_to_datetime(value)
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=UTC)
            delay = max(0.0, instant.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    delays = [delay] if delay is not None else []
    if github:
        reset = _seconds(_header(headers, "X-RateLimit-Reset"))
        if reset is not None:
            delays.append(max(0.0, reset - time.time()))
    return max(delays) if delays else default


def _body(response) -> dict:
    try:
        value = response.json()
        return value if isinstance(value, dict) else {}
    except (ValueError, AttributeError):
        return {}


def is_limited(source: str, response) -> bool:
    if response.status_code == 429:
        return True
    headers = getattr(response, "headers", {})
    if source == "github" and response.status_code == 403:
        message = _body(response).get("message", "")
        return (_header(headers, "Retry-After") is not None
                or str(_header(headers, "X-RateLimit-Remaining")) == "0"
                or (isinstance(message, str) and "rate limit" in message.lower()))
    if source == "community":
        body = _body(response)
        return (body.get("error_id") == 502
                or body.get("error_name") == "throttle_violation")
    return False


def observe(source: str, response, gate: RequestGate, *, fallback=5.0) -> bool:
    limited = is_limited(source, response)
    gate.record_limit(limited)
    headers = getattr(response, "headers", {})
    if limited:
        gate.defer(retry_after(headers, default=fallback, github=source == "github"))
    if response.status_code in (500, 502, 503, 504):
        gate.defer(retry_after(headers, default=fallback))
    if source == "github" and str(_header(headers, "X-RateLimit-Remaining")) == "0":
        gate.defer(retry_after(headers, default=60.0, github=True))
    if source == "community":
        delay = _seconds(_body(response).get("backoff"))
        if delay is not None:
            gate.defer(delay)
    return limited


async def get(source, client, url, *, max_retries=2, request_timeout=30.0, **kwargs):
    """One provider queue for probes and all business request attempts."""
    gate = gate_for(source)
    for attempt in range(max_retries + 1):
        async with gate.slot():
            async with asyncio.timeout(request_timeout):
                response = await client.get(url, **kwargs)
            limited = observe(source, response, gate, fallback=5.0 * (2 ** attempt))
            transient = response.status_code in (500, 502, 503, 504)
        if not (limited or transient) or attempt == max_retries:
            if limited:
                raise ProviderRateLimitError("provider rate limit remained after retries")
            return response


def reset_for_tests() -> None:
    global _gates
    _gates = _new_gates()
