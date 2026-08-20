"""Tavily key pool: quota-aware failover with startup probing (mock-tested, no real keys)."""
import pytest

from deepchoice.retrievers import tavily_keypool as kp

DUMMY = ["tvly-dev-aaaa", "tvly-dev-bbbb", "tvly-dev-cccc"]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    kp._pool = []
    kp._dead = set()
    kp._index = 0
    kp._probed = False
    yield


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
        assert kp._dead == {DUMMY[0], DUMMY[2]}
        assert kp._pool == [DUMMY[1]]

    def test_network_error_keeps_key_alive(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("TAVILY_API_KEYS", ",".join(DUMMY))
        async def post(url, json=None, **kw):
            raise Exception("network down")
        asyncio.run(kp.probe(post))
        assert kp._dead == set()
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
        assert kp._dead == {DUMMY[0]}

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
