"""Tavily key pool: quota-aware failover with startup probing (mock-tested, no real keys)."""
import json
import time

import pytest

from deepchoice.retrievers import tavily_keypool as kp

DUMMY = ["tvly-dev-aaaa", "tvly-dev-bbbb", "tvly-dev-cccc"]


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    kp._pool = []
    kp._exhausted = {}
    kp._probed = False
    monkeypatch.setenv("TAVILY_KEY_STATE_PATH", str(tmp_path / "state.json"))
    yield


def _hash(key):
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        pass


def _fake_post_factory(results_by_key):
    """Returns an async post(url, json=...) that maps api_key -> response."""
    async def post(url, json=None, **kw):
        key = (json or {}).get("api_key", "")
        return _FakeResp(results_by_key.get(key, 200))
    return post


class TestLoadKeys:
    def test_comma_separated_list(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEYS", "a, b ,c")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert kp._load_keys() == ["a", "b", "c"]

    def test_single_key_fallback(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEYS", raising=False)
        monkeypatch.setenv("TAVILY_API_KEY", "solo")
        assert kp._load_keys() == ["solo"]

    def test_empty_env(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEYS", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert kp._load_keys() == []


class TestProbe:
    async def _probe(self, monkeypatch, statuses):
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        async def post(url, json=None, **kw):
            key = (json or {}).get("api_key", "")
            return _FakeResp(statuses.get(key, 200))
        await kp.probe(post)
        return post

    def test_dead_keys_blacklisted_after_probe(self, monkeypatch):
        import asyncio
        statuses = {DUMMY[0]: 432, DUMMY[1]: 200, DUMMY[2]: 401}
        asyncio.run(self._probe(monkeypatch, statuses))
        assert set(kp._exhausted) == {_hash(DUMMY[0]), _hash(DUMMY[2])}
        assert kp._pool == [DUMMY[1]]

    def test_network_error_keeps_key_alive(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        async def post(url, json=None, **kw):
            raise Exception("network down")
        asyncio.run(kp.probe(post))
        assert kp._exhausted == {}
        assert set(kp._pool) == set(DUMMY)

    def test_probe_only_runs_once(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        calls = {"n": 0}
        async def post(url, json=None, **kw):
            calls["n"] += 1
            return _FakeResp(200)
        asyncio.run(kp.ensure_probed(post))
        asyncio.run(kp.ensure_probed(post))
        assert calls["n"] == len(DUMMY)


class TestStateFile:
    def _write_state(self, tmp_path, exhausted: dict):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"exhausted": exhausted}), encoding="utf-8")
        return path

    def test_dead_key_persisted_after_probe(self, monkeypatch, tmp_path):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        statuses = {DUMMY[0]: 432}
        asyncio.run(kp.probe(_fake_post_factory(statuses)))
        path = tmp_path / "state.json"
        assert path.exists()
        state = json.loads(path.read_text(encoding="utf-8"))
        assert _hash(DUMMY[0]) in state["exhausted"]
        assert _hash(DUMMY[1]) not in state["exhausted"]

    def test_state_file_never_contains_plaintext_key(self, monkeypatch, tmp_path):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        statuses = {DUMMY[0]: 432}
        asyncio.run(kp.probe(_fake_post_factory(statuses)))
        raw = (tmp_path / "state.json").read_text(encoding="utf-8")
        assert DUMMY[0] not in raw
        assert "tvly-" not in raw

    def test_fresh_exhausted_key_skipped_on_startup(self, monkeypatch, tmp_path):
        import asyncio
        self._write_state(tmp_path, {_hash(DUMMY[0]): time.time()})
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        probed_keys = []
        async def post(url, json=None, **kw):
            probed_keys.append((json or {}).get("api_key", ""))
            return _FakeResp(200)
        asyncio.run(kp.probe(post))
        assert DUMMY[0] not in probed_keys
        assert kp._pool == [DUMMY[1], DUMMY[2]]

    def test_expired_exhausted_key_reprobed_and_recovered(self, monkeypatch, tmp_path):
        import asyncio
        self._write_state(tmp_path, {_hash(DUMMY[0]): time.time() - 29 * 86400})
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        probed_keys = []
        async def post(url, json=None, **kw):
            probed_keys.append((json or {}).get("api_key", ""))
            return _FakeResp(200)
        asyncio.run(kp.probe(post))
        assert DUMMY[0] in probed_keys
        assert kp._pool == DUMMY
        state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert state["exhausted"] == {}

    def test_reprobe_env_forces_probe_of_exhausted(self, monkeypatch, tmp_path):
        import asyncio
        self._write_state(tmp_path, {_hash(DUMMY[0]): time.time()})
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        monkeypatch.setenv("TAVILY_REPROBE", "1")
        probed_keys = []
        async def post(url, json=None, **kw):
            probed_keys.append((json or {}).get("api_key", ""))
            return _FakeResp(200)
        asyncio.run(kp.probe(post))
        assert probed_keys == DUMMY
        assert kp._pool == DUMMY


class TestFailover:
    def test_432_rotates_and_retries_with_next_key(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        statuses = {DUMMY[0]: 432}
        post = _fake_post_factory(statuses)

        async def run():
            resp, key = await kp.post_with_failover(post, {"query": "q"})
            return resp.status_code, key

        status, key = asyncio.run(run())
        assert status == 200
        assert key == DUMMY[1]
        assert set(kp._exhausted) == {_hash(DUMMY[0])}

    def test_432_persists_to_state_file(self, monkeypatch, tmp_path):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        statuses = {DUMMY[0]: 432}
        asyncio.run(kp.post_with_failover(_fake_post_factory(statuses), {"query": "q"}))
        state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert _hash(DUMMY[0]) in state["exhausted"]

    def test_429_retries_same_key_without_blacklisting(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        monkeypatch.setattr(kp, "_RATE_LIMIT_BACKOFF_S", 0.0)
        calls = {"n": 0}
        statuses = [429, 200]

        async def post(url, json=None, **kw):
            if (json or {}).get("query") == "test":
                return _FakeResp(200)  # probe passes for all keys
            s = statuses[min(calls["n"], 1)]
            calls["n"] += 1
            return _FakeResp(s)

        async def run():
            resp, key = await kp.post_with_failover(post, {"query": "q"})
            return resp.status_code, key

        status, key = asyncio.run(run())
        assert status == 200 and key == DUMMY[0]
        assert kp._exhausted == {}, "429 must not blacklist a key"
        assert calls["n"] == 2

    def test_no_keys_available_returns_none(self, monkeypatch):
        import asyncio
        monkeypatch.delenv("TAVILY_API_KEYS", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        async def post(url, json=None, **kw):
            return _FakeResp(200)
        resp, key = asyncio.run(kp.post_with_failover(post, {"query": "q"}))
        assert resp is None and key is None

    def test_all_keys_dead_returns_none(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        async def post(url, json=None, **kw):
            return _FakeResp(432)
        asyncio.run(kp.probe(post))
        assert asyncio.run(kp.current()) is None
