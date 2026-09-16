"""Batch 3: outbound health-check helpers (tavily direct + channel probes)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmarks.run_baseline import (
    health_check_report,
    probe_tavily_direct,
    run_health_check,
)


class TestProbeTavilyDirect:
    class _Client:
        def __init__(self, response=None):
            self.post = AsyncMock(return_value=response)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    @pytest.mark.asyncio
    async def test_ok_when_pool_returns_200(self):
        resp = MagicMock()
        resp.status_code = 200
        client = self._Client(response=resp)

        async def use_routed_post(post, payload):
            response = await post(
                "https://api.tavily.com/search",
                json={**payload, "api_key": "test-only"},
            )
            return response, "test-only"

        with patch("deepchoice.outbound.make_client", new_callable=AsyncMock,
                   return_value=client) as make_client, \
             patch("deepchoice.retrievers.tavily_keypool.post_with_failover",
                   new_callable=AsyncMock, side_effect=use_routed_post):
            ok, detail = await probe_tavily_direct()
        make_client.assert_awaited_once_with("tavily")
        client.post.assert_awaited_once_with(
            "https://api.tavily.com/search",
            json={"query": "langgraph", "max_results": 1, "api_key": "test-only"},
        )
        assert ok is True
        assert "200" in detail

    @pytest.mark.asyncio
    async def test_fail_when_no_key(self):
        client = self._Client()
        with patch("deepchoice.outbound.make_client", new_callable=AsyncMock,
                   return_value=client) as make_client, \
             patch("deepchoice.retrievers.tavily_keypool.post_with_failover",
                   new_callable=AsyncMock, return_value=(None, "no keys")):
            ok, detail = await probe_tavily_direct()
        make_client.assert_awaited_once_with("tavily")
        client.post.assert_not_awaited()
        assert ok is False
        assert "no available" in detail

    @pytest.mark.asyncio
    async def test_fail_when_pool_raises(self):
        client = self._Client()
        with patch("deepchoice.outbound.make_client", new_callable=AsyncMock,
                   return_value=client), \
             patch("deepchoice.retrievers.tavily_keypool.post_with_failover",
                   new_callable=AsyncMock, side_effect=Exception("boom")):
            ok, detail = await probe_tavily_direct()
        assert ok is False
        assert detail == "Exception"

    @pytest.mark.asyncio
    async def test_route_unavailable_is_safe_degraded_result(self):
        with patch("deepchoice.outbound.make_client", new_callable=AsyncMock,
                   side_effect=RuntimeError("private route detail")) as make_client, \
             patch("deepchoice.retrievers.tavily_keypool.post_with_failover",
                   new_callable=AsyncMock) as post_with_failover:
            ok, detail = await probe_tavily_direct()
        make_client.assert_awaited_once_with("tavily")
        post_with_failover.assert_not_awaited()
        assert ok is False
        assert detail == "RuntimeError"
        assert "private route detail" not in detail


class TestHealthCheckReport:
    @pytest.mark.asyncio
    async def test_includes_tavily_direct(self):
        class FakeResolver:
            async def health_check(self):
                return {"ok": True, "degraded_sources": [],
                        "sources": {"github": {"channel": "direct", "ok": True}}}

        with patch("deepchoice.outbound.get_resolver", return_value=FakeResolver()), \
             patch("benchmarks.run_baseline.probe_tavily_direct",
                   new_callable=AsyncMock, return_value=(True, "HTTP 200")):
            hc = await health_check_report()
        assert hc["tavily_direct"] == {"ok": True, "detail": "HTTP 200"}
        assert hc["sources"]["github"]["channel"] == "direct"

    @pytest.mark.asyncio
    async def test_tavily_route_unavailable_remains_degraded(self):
        class FakeResolver:
            async def health_check(self):
                return {
                    "ok": False,
                    "degraded_sources": ["tavily"],
                    "sources": {"tavily": {"channel": None, "ok": False}},
                }

        with patch("deepchoice.outbound.get_resolver", return_value=FakeResolver()), \
             patch("deepchoice.outbound.make_client", new_callable=AsyncMock,
                   side_effect=RuntimeError("private route detail")):
            hc = await health_check_report()

        assert hc["ok"] is False
        assert hc["degraded_sources"] == ["tavily"]
        assert hc["tavily_direct"] == {"ok": False, "detail": "RuntimeError"}


class TestRunHealthCheck:
    @pytest.mark.asyncio
    async def test_exit_zero_when_healthy(self):
        with patch("benchmarks.run_baseline.health_check_report", new_callable=AsyncMock,
                   return_value={"ok": True, "tavily_direct": {"ok": True}}):
            assert await run_health_check() == 0

    @pytest.mark.asyncio
    async def test_exit_one_when_outbound_degraded(self):
        with patch("benchmarks.run_baseline.health_check_report", new_callable=AsyncMock,
                   return_value={"ok": False, "degraded_sources": ["arxiv"],
                                 "tavily_direct": {"ok": True}}):
            assert await run_health_check() == 1

    @pytest.mark.asyncio
    async def test_exit_one_when_tavily_down(self):
        with patch("benchmarks.run_baseline.health_check_report", new_callable=AsyncMock,
                   return_value={"ok": True, "tavily_direct": {"ok": False}}):
            assert await run_health_check() == 1


def test_strip_run_keeps_token_usage():
    from benchmarks.run_baseline import _strip_run
    out = _strip_run({"case_id": "TC-1",
                      "token_usage": [{"agent": "a", "calls": 2, "total_tokens": 50}]})
    assert out["token_usage"] == [{"agent": "a", "calls": 2, "total_tokens": 50}]
