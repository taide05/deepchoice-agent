"""Tavily API key pool with quota-aware failover and startup probing.

Keys come from TAVILY_API_KEYS (comma-separated) with TAVILY_API_KEY as
single-key fallback. On first use the pool probes every key with a minimal
query and blacklists dead ones for the process lifetime. Dead codes: 401
(invalid), 403, 429 (rate limit), 432 (Tavily monthly usage exhausted).
During requests, callers detect a dead code, mark the key, and retry with
the next alive key — at most one rotation per request.
"""
import asyncio
import os

_DEAD_CODES = (401, 403, 429, 432)
_PROBE_PAYLOAD = {"query": "test", "search_depth": "basic", "max_results": 1}

_pool: list[str] = []
_dead: set[str] = set()
_index = 0
_probed = False
_lock = asyncio.Lock()


def _load_keys() -> list[str]:
    raw = os.environ.get("TAVILY_API_KEYS", "") or os.environ.get("TAVILY_API_KEY", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _reset_for_tests() -> None:
    global _pool, _dead, _index, _probed
    _pool, _dead, _index, _probed = [], set(), 0, False


async def _probe_one(post, key: str) -> bool:
    try:
        resp = await post(
            "https://api.tavily.com/search",
            json={**_PROBE_PAYLOAD, "api_key": key},
        )
        return resp.status_code not in _DEAD_CODES
    except Exception:
        return True  # transient network errors do not blacklist a key


async def probe(post) -> None:
    """Probe all configured keys; alive keys populate the pool in order."""
    global _pool, _dead, _probed
    async with _lock:
        if _probed:
            return
        keys = _load_keys()
        if not keys:
            _probed = True
            return
        results = await asyncio.gather(*[_probe_one(post, k) for k in keys])
        _pool = [k for k, alive in zip(keys, results) if alive]
        _dead = {k for k, alive in zip(keys, results) if not alive}
        _probed = True


async def ensure_probed(post) -> None:
    if not _probed:
        await probe(post)


def mark_dead(key: str) -> None:
    _dead.add(key)
    if key in _pool:
        _pool.remove(key)


async def current() -> str | None:
    if not _pool:
        return None
    return _pool[0]


async def post_with_failover(post, payload: dict):
    """POST to the Tavily search endpoint with key failover.

    Returns (response, key_used); response is None when no key is available.
    On a dead-code response the key is blacklisted and the request retried
    once with the next alive key.
    """
    await ensure_probed(post)
    key = await current()
    if key is None:
        return None, None
    resp = await post("https://api.tavily.com/search", json={**payload, "api_key": key})
    if resp.status_code in _DEAD_CODES:
        mark_dead(key)
        key = await current()
        if key:
            resp = await post("https://api.tavily.com/search", json={**payload, "api_key": key})
    return resp, key
