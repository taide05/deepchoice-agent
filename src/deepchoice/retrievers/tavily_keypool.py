"""Tavily API key pool with quota-aware failover, startup probing and persistence.

Keys come from TAVILY_API_KEYS (comma-separated) with TAVILY_API_KEY as
single-key fallback. Keys are partitioned into a usable pool and an
exhausted pool: 401 (invalid) and 432 (monthly usage exhausted) move a
key to the exhausted pool, persisted as SHA256 hashes (never plaintext)
in tavily_key_state.json. Exhausted keys are not re-probed on startup
until their entry is older than _EXHAUSTED_TTL_S, or TAVILY_REPROBE=1
forces a full re-probe. 429 (rate limit) is TRANSIENT and never
blacklists a key.
"""
import asyncio
import hashlib
import json
import os
import threading
import time

from ..budget_errors import BudgetError
from ..outbound import throttle

# Permanent dead codes: invalid key (401) or monthly usage exhausted (432).
# 429 (rate limit) is TRANSIENT — blacklisting the only alive key on a 429
# burst killed Tavily for the rest of the process in the 100-case run.
_DEAD_CODES = (401, 432)
_RATE_LIMIT_BACKOFF_S = 10.0
_EXHAUSTED_TTL_S = 28 * 86400
_PROBE_PAYLOAD = {"query": "test", "search_depth": "basic", "max_results": 1}

# Preserve the existing conservative local 5/min policy, without an initial
# five-request burst. Actual account quotas may differ; honor server feedback.
_KEY_INTERVAL_S = 12.0
_key_gates: dict[str, throttle.RequestGate] = {}

_pool: list[str] = []
_exhausted: dict[str, float] = {}  # sha256(key) -> epoch seconds when marked
_probed = False
_lock = asyncio.Lock()


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _state_path() -> str:
    return os.environ.get("TAVILY_KEY_STATE_PATH", "tavily_key_state.json")


def _load_keys() -> list[str]:
    raw = os.environ.get("TAVILY_API_KEYS", "") or os.environ.get("TAVILY_API_KEY", "")
    return list(dict.fromkeys(k.strip() for k in raw.split(",") if k.strip()))


def _load_state() -> dict[str, float]:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f).get("exhausted", {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


_state_write_lock = threading.RLock()


def _save_state(exhausted: dict[str, float]) -> None:
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"exhausted": exhausted}, f)
    os.replace(tmp, _state_path())


def _is_fresh(ts: float) -> bool:
    return time.time() - ts <= _EXHAUSTED_TTL_S


def _reset_for_tests() -> None:
    global _pool, _exhausted, _probed, _rr_idx, _key_gates, _lock
    _pool, _exhausted, _probed = [], {}, False
    _rr_idx = -1
    _key_gates = {}
    _lock = asyncio.Lock()


def _key_gate(key: str) -> throttle.RequestGate:
    return _key_gates.setdefault(
        _hash(key), throttle.RequestGate(interval=lambda: _KEY_INTERVAL_S, concurrency=1))


async def _post_once(post, key: str, payload: dict, *, probing=False):
    gate = _key_gate(key)
    async with gate.slot():
        # Another in-flight caller may have invalidated this selected key while
        # we waited. Never dispatch it again or move a 429 to another key.
        if not probing and key not in _pool:
            return None
        async with asyncio.timeout(30.0):
            resp = await post("https://api.tavily.com/search", json={**payload, "api_key": key})
        throttle.observe("tavily", resp, gate, fallback=_RATE_LIMIT_BACKOFF_S)
        if not probing and resp.status_code in _DEAD_CODES:
            mark_dead(key)
        return resp


async def _probe_one(post, key: str) -> bool:
    try:
        resp = await _post_once(post, key, _PROBE_PAYLOAD, probing=True)
        return resp.status_code not in _DEAD_CODES
    except BudgetError:
        raise
    except Exception:
        return True  # transient network errors do not blacklist a key


async def probe(post) -> None:
    """Probe usable and unknown keys; fresh exhausted keys are skipped."""
    global _exhausted, _probed
    async with _lock:
        if _probed:
            return
        keys = _load_keys()
        if not keys:
            _probed = True
            return
        saved = _load_state()
        reprobe_all = os.environ.get("TAVILY_REPROBE") == "1"
        candidates = [k for k in keys
                      if reprobe_all or not _is_fresh(saved.get(_hash(k), 0.0))]
        results = await asyncio.gather(*[_probe_one(post, k) for k in candidates], return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        now = time.time()
        for k, alive in zip(candidates, results):
            h = _hash(k)
            if alive:
                _pool.append(k)
                saved.pop(h, None)
            else:
                saved[h] = now
        _exhausted = saved
        _save_state(saved)
        _probed = True


async def ensure_probed(post) -> None:
    if not _probed:
        await probe(post)


def mark_dead(key: str) -> None:
    with _state_write_lock:
        if key in _pool:
            _pool.remove(key)
        _exhausted[_hash(key)] = time.time()
        _save_state(_exhausted)


_rr_idx = -1  # first current() call returns _pool[0]


async def current() -> str | None:
    """Round-robin across configured alive keys; retries retain a limited key."""
    global _rr_idx
    if not _pool:
        return None
    _rr_idx = (_rr_idx + 1) % len(_pool)
    return _pool[_rr_idx]


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
    for attempt in range(2):
        resp = await _post_once(post, key, payload)
        if resp is not None and resp.status_code not in (*_DEAD_CODES, 429):
            return resp, key
        if attempt == 1:
            if resp is not None and resp.status_code == 429:
                raise throttle.ProviderRateLimitError("Tavily rate limited")
            return resp, key
        if resp is None or resp.status_code in _DEAD_CODES:
            key = await current()
            if key is None:
                return resp, None
        # A 429 retry uses the same key and the same admission as any new call.
