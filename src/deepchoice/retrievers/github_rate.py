"""Shared rate limiter for the GitHub search API (single GITHUB_TOKEN).

GitHub throttles search with two distinct mechanisms, so this limiter models
both instead of reusing tavily's per-key quota bucket:

1. Primary quota — 30 authenticated / 10 unauthenticated search requests per
   60-second window (search/repositories). A token bucket is the wrong tool
   here: a fresh bucket of 30 would release all 30 requests at once and trip
   the secondary limit below. A minimum spacing between request starts bounds
   the rate without ever permitting a burst.
2. Secondary (abuse) limit — bursts of concurrent requests return 403/429
   with a Retry-After header. Bounded by a small in-flight semaphore, plus a
   retry that honors Retry-After / X-RateLimit-Reset (GitHub's own backoff
   signals rather than a guessed refill rate).

Both call sites share one token budget — currently only github_api.GitHubSearch
hits api.github.com/search/repositories; the limiter is a module-level singleton
so any future search path reuses it instead of doubling the effective rate.

Reference: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager

# Primary search quota: authenticated / unauthenticated requests per minute.
_AUTH_SEARCH_PER_MIN = 30
_ANON_SEARCH_PER_MIN = 10
# Secondary/abuse limit: max search requests in flight per token.
_MAX_IN_FLIGHT = 2
# Retry budget for 403/429 responses.
_MAX_RETRIES = 2
# Upper bound on any single backoff (one full search window), so a bogus
# Retry-After value can never stall a run indefinitely.
_MAX_RETRY_WAIT_S = 60.0

_sem = asyncio.Semaphore(_MAX_IN_FLIGHT)
_next_start = 0.0  # monotonic instant before which the next request must wait
_lock = asyncio.Lock()


def interval_s() -> float:
    """Minimum spacing between search request starts (auth-aware)."""
    per_min = _AUTH_SEARCH_PER_MIN if os.environ.get("GITHUB_TOKEN") else _ANON_SEARCH_PER_MIN
    return 60.0 / per_min


async def _pace() -> None:
    """Wait until `interval_s()` has elapsed since the previous request start."""
    global _next_start
    async with _lock:
        now = time.monotonic()
        if now < _next_start:
            await asyncio.sleep(_next_start - now)
            now = time.monotonic()
        _next_start = now + interval_s()


@asynccontextmanager
async def request_slot():
    """Bound in-flight concurrency and pace starts; yield for one GET."""
    await _sem.acquire()
    try:
        await _pace()
        yield
    finally:
        _sem.release()


def retry_delay(headers) -> float:
    """Backoff (seconds) after a 403/429, from Retry-After / X-RateLimit-Reset.

    GitHub sends Retry-After as integer seconds (secondary/abuse limit) and
    X-RateLimit-Reset as epoch seconds (primary window reset) — never an HTTP
    date — so only those two forms are parsed. Falls back to interval_s() when
    headers are absent or unparseable; always returns a bounded positive float.
    """
    try:
        raw = headers.get("Retry-After")
        if raw is not None:
            secs = float(raw)
            if secs > 0.0:
                return min(secs, _MAX_RETRY_WAIT_S)
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        reset = headers.get("X-RateLimit-Reset")
        if reset is not None:
            delta = float(reset) - time.time()
            if delta > 0.0:
                return min(delta, _MAX_RETRY_WAIT_S)
    except (AttributeError, TypeError, ValueError):
        pass
    return interval_s()


async def get_with_throttle(client, url, *, params=None, headers=None,
                            max_retries: int = _MAX_RETRIES):
    """Rate-limited GET against the GitHub search API.

    Paces and bounds concurrency via request_slot(), and retries 403/429 up to
    max_retries times honoring the response's backoff headers. Returns the final
    response; callers keep their own status handling (raise / partial / error).
    """
    last_resp = None
    for attempt in range(max_retries + 1):
        async with request_slot():
            last_resp = await client.get(url, params=params, headers=headers)
        if last_resp.status_code not in (403, 429) or attempt == max_retries:
            return last_resp
        await asyncio.sleep(retry_delay(last_resp.headers))
    return last_resp


def _reset_for_tests() -> None:
    global _sem, _next_start, _lock
    _sem = asyncio.Semaphore(_MAX_IN_FLIGHT)
    _next_start = 0.0
    _lock = asyncio.Lock()
