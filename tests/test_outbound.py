"""Outbound channel layer tests (batch 1: module-level, all mocked — no network)."""
import asyncio

import httpx
import pytest

from deepchoice.outbound.channels import (
    OutboundConfig,
    SelfForwardChannel,
    build_channels,
)
from deepchoice.outbound.resolver import ChannelResolver


def _cfg(**kw) -> OutboundConfig:
    defaults = dict(channel_order=("direct",), fwd_base=None, fwd_key=None,
                    fwd_allowed=("export.arxiv.org", "api.github.com"))
    defaults.update(kw)
    return OutboundConfig(**defaults)


def _probe_script(table: dict):
    """probe_fn returning table[(source, channel_name)] -> bool; default False."""
    async def fn(source, channel):
        return table.get((source, channel.name), False)
    return fn


class TestConfig:
    def test_from_env_defaults(self, monkeypatch):
        for k in ("OUTBOUND_CHANNELS", "LOCAL_PROXY", "FWD_BASE", "FWD_KEY", "FWD_TARGETS"):
            monkeypatch.delenv(k, raising=False)
        cfg = OutboundConfig.from_env()
        assert cfg.channel_order == ("direct", "local-proxy", "self-forward", "direct-v6")
        assert cfg.fwd_base is None
        assert cfg.v6_enabled is True  # direct-v6 in default order

    def test_from_env_custom(self, monkeypatch):
        monkeypatch.setenv("OUTBOUND_CHANNELS", "direct,self-forward")
        monkeypatch.setenv("LOCAL_PROXY", "http://127.0.0.1:7897")
        monkeypatch.setenv("FWD_BASE", "https://fwd.example.com")
        monkeypatch.setenv("FWD_TARGETS", "export.arxiv.org")
        cfg = OutboundConfig.from_env()
        assert cfg.channel_order == ("direct", "self-forward")
        assert cfg.local_proxy == "http://127.0.0.1:7897"
        assert cfg.fwd_allowed == ("export.arxiv.org",)
        assert cfg.v6_enabled is False


class TestResolver:
    @pytest.mark.asyncio
    async def test_route_after_probe_and_cached(self):
        probe = _probe_script({("github", "direct"): True})
        r = ChannelResolver(cfg=_cfg(), probe_fn=probe)
        calls = {"n": 0}
        orig = probe

        async def counting(source, channel):
            calls["n"] += 1
            return await orig(source, channel)

        r._probe_fn = counting
        ch = await r.resolve("github")
        assert ch is not None and ch.name == "direct"
        assert calls["n"] == 1
        # served from route table, no re-probe
        ch2 = await r.resolve("github")
        assert ch2 is not None
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_fallback_to_next_channel(self):
        probe = _probe_script({("github", "local-proxy"): True})
        cfg = _cfg(channel_order=("direct", "local-proxy"),
                   local_proxy="http://127.0.0.1:7897")
        r = ChannelResolver(cfg=cfg, probe_fn=probe)
        ch = await r.resolve("github")
        assert ch is not None and ch.name == "local-proxy"

    @pytest.mark.asyncio
    async def test_all_fail_then_backoff(self):
        probe = _probe_script({})
        cfg = _cfg(channel_order=("direct", "local-proxy"))
        now = [0.0]
        r = ChannelResolver(cfg=cfg, probe_fn=probe, now_fn=lambda: now[0])
        assert await r.resolve("github") is None
        assert await r.resolve("github") is None  # inside backoff, no probe
        now[0] = 31.0
        ch = await r.resolve("github")
        assert ch is None  # still failing; next backoff window grows

    @pytest.mark.asyncio
    async def test_invalidate_forces_reroute(self):
        state = {"direct": True, "local-proxy": True}
        async def probe(source, channel):
            return state.get(channel.name, False)
        r = ChannelResolver(cfg=_cfg(channel_order=("direct", "local-proxy"),
                                     local_proxy="http://127.0.0.1:7897"),
                            probe_fn=probe)
        ch = await r.resolve("github")
        assert ch.name == "direct"
        await r.invalidate("github")
        state["direct"] = False
        ch2 = await r.resolve("github")
        assert ch2 is not None and ch2.name == "local-proxy"

    @pytest.mark.asyncio
    async def test_health_check(self):
        async def probe(source, channel):
            return channel.name == "direct" and source in ("github", "arxiv")
        r = ChannelResolver(cfg=_cfg(), probe_fn=probe)
        hc = await r.health_check()
        assert hc["sources"]["github"]["ok"] is True
        assert hc["sources"]["tavily"]["ok"] is False
        assert "tavily" in hc["degraded_sources"]

    @pytest.mark.asyncio
    async def test_audit_records(self):
        probe = _probe_script({("github", "direct"): True})
        r = ChannelResolver(cfg=_cfg(), probe_fn=probe)
        await r.resolve("github")
        kinds = [e.kind for e in r.audit]
        assert "probe" in kinds and "route" in kinds
        assert r.audit[-1].channel == "direct" and r.audit[-1].ok

    @pytest.mark.asyncio
    async def test_concurrent_resolve_probes_once(self):
        calls = {"n": 0}

        async def probe(source, channel):
            calls["n"] += 1
            await asyncio.sleep(0.02)  # widen the race window
            return channel.name == "direct"

        r = ChannelResolver(cfg=_cfg(), probe_fn=probe)
        results = await asyncio.gather(*(r.resolve("github") for _ in range(8)))
        assert all(ch is not None for ch in results)
        assert calls["n"] == 1  # one in-flight probe, no duplicate

    @pytest.mark.asyncio
    async def test_local_proxy_client_constructs(self):
        cfg = _cfg(channel_order=("direct", "local-proxy"),
                   local_proxy="http://127.0.0.1:7897")
        lp = [c for c in build_channels(cfg) if c.name == "local-proxy"][0]
        r = ChannelResolver(cfg=cfg, probe_fn=_probe_script({}))
        client = r._make_client(lp)
        assert isinstance(client._transport, httpx.AsyncHTTPTransport)


class TestForwardChannel:
    def test_build_channels_keeps_self_forward_but_disabled(self):
        cfg = _cfg(channel_order=("self-forward", "direct"), fwd_base=None)
        channels = build_channels(cfg)
        # channel object exists, but reachable() fails -> resolver never selects it
        assert [c.name for c in channels] == ["self-forward", "direct"]

    @pytest.mark.asyncio
    async def test_forward_unreachable_without_base(self):
        ch = SelfForwardChannel(_cfg(fwd_base=None))
        assert await ch.reachable() is False

    @pytest.mark.asyncio
    async def test_transport_relays_and_restores(self):
        captured = {}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return httpx.Response(200, json={"status": 200, "body": "<feed/>"})

        ch = SelfForwardChannel(
            _cfg(fwd_base="https://fwd.example.com", fwd_key="k123",
                 fwd_allowed=("export.arxiv.org",)),
            http_factory=lambda: FakeClient(),
        )
        transport = ch.build_transport()
        req = httpx.Request(
            "GET",
            "https://export.arxiv.org/api/query?search_query=all:langgraph&max_results=1",
        )
        resp = await transport.handle_async_request(req)
        assert resp.status_code == 200
        assert b"<feed/>" in resp.content
        assert captured["url"] == "https://fwd.example.com"
        assert captured["json"]["target"].startswith("https://export.arxiv.org")
        assert captured["headers"]["X-Fwd-Key"] == "k123"
        # forbidden target
        bad = httpx.Request("GET", "https://evil.example.com/x")
        with pytest.raises(ValueError):
            await transport.handle_async_request(bad)


class TestClients:
    @pytest.mark.asyncio
    async def test_make_client_routes_forward(self):
        async def probe(source, channel):
            return channel.name == "self-forward"
        cfg = _cfg(channel_order=("direct", "self-forward"),
                   fwd_base="https://fwd.example.com", fwd_key="k")
        r = ChannelResolver(cfg=cfg, probe_fn=probe)
        ch = await r.resolve("arxiv")
        assert ch is not None and ch.name == "self-forward"
        client = r._make_client(ch)
        assert isinstance(client._transport, httpx.AsyncBaseTransport)

    @pytest.mark.asyncio
    async def test_make_client_raises_when_unreachable(self):
        r = ChannelResolver(cfg=_cfg(), probe_fn=_probe_script({}))
        with pytest.raises(RuntimeError, match="no outbound channel"):
            await r.make_client("github")
