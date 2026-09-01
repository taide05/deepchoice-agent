r"""Outbound channel layer: direct / local-proxy / self-forward / direct-v6.

Design (2026-08-31, D:\ai-career\DC-网络层-设计-2026-08-31.md):
- Channels are probed first, routed by table, executed with zero per-request
  trial-and-error.
- self-forward passes each request through a user-owned forward endpoint
  (Cloudflare Worker / n8n) so machines without any proxy client can still
  reach blocked hosts.
"""
import os
from dataclasses import dataclass
from typing import Callable

import httpx

DEFAULT_CHANNEL_ORDER = "direct,local-proxy,self-forward,direct-v6"

FWD_ALLOWED_DEFAULT = "export.arxiv.org,api.github.com"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutboundConfig:
    channel_order: tuple[str, ...] = ("direct", "local-proxy", "self-forward")
    local_proxy: str | None = None
    fwd_base: str | None = None
    fwd_key: str | None = None
    fwd_allowed: tuple[str, ...] = ()
    v6_enabled: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "OutboundConfig":
        env = env if env is not None else os.environ
        order = env.get("OUTBOUND_CHANNELS", DEFAULT_CHANNEL_ORDER)
        channels = tuple(c.strip() for c in order.split(",") if c.strip())
        fwd_allowed = tuple(
            h.strip() for h in env.get("FWD_TARGETS", FWD_ALLOWED_DEFAULT).split(",") if h.strip()
        )
        return cls(
            channel_order=channels,
            local_proxy=env.get("LOCAL_PROXY") or None,
            fwd_base=env.get("FWD_BASE") or None,
            fwd_key=env.get("FWD_KEY") or None,
            fwd_allowed=fwd_allowed,
            v6_enabled="direct-v6" in channels,
        )


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

class BaseChannel:
    name: str = "base"
    kind: str = "direct"  # direct / local-proxy / self-forward

    def __init__(self, cfg: OutboundConfig):
        self.cfg = cfg

    async def reachable(self) -> bool:
        """Cheap connectivity check for the channel itself (not the target)."""
        return True

    def build_transport(self) -> httpx.AsyncBaseTransport | None:
        """Return a transport for httpx.AsyncClient, or None for default."""
        return None


class DirectChannel(BaseChannel):
    name = "direct"
    kind = "direct"


class DirectV6Channel(BaseChannel):
    """Only used when probing found an AAAA and a v6 connection works.
    The request itself goes through a normal client (httpx happy-eyeballs
    tries both families once the v6 probe passed)."""

    name = "direct-v6"
    kind = "direct"

    async def reachable(self, host: str = "export.arxiv.org") -> bool:
        import asyncio
        import socket

        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET6)
        except OSError:
            return False
        if not infos:
            return False
        addr = infos[0][4]
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(addr[0], 443, family=socket.AF_INET6), timeout=5
            )
            writer.close()
            return True
        except Exception:
            return False


class LocalProxyChannel(BaseChannel):
    name = "local-proxy"
    kind = "local-proxy"

    def __init__(self, cfg: OutboundConfig):
        super().__init__(cfg)
        self.proxy_url = cfg.local_proxy

    async def reachable(self) -> bool:
        if not self.proxy_url:
            return False
        import asyncio
        from urllib.parse import urlparse

        parsed = urlparse(self.proxy_url)
        if not parsed.hostname:
            return False
        port = parsed.port or 7897
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.hostname, port), timeout=3
            )
            writer.close()
            return True
        except Exception:
            return False


class SelfForwardChannel(BaseChannel):
    """Each request is relayed through the user-owned forward endpoint.

    Endpoint contract (design doc): POST {FWD_BASE} with header X-Fwd-Key and
    body {"target": "<url>"}; returns {"status": ..., "body": ...}.
    """

    name = "self-forward"
    kind = "self-forward"

    def __init__(self, cfg: OutboundConfig,
                 http_factory: Callable[[], httpx.AsyncClient] | None = None):
        super().__init__(cfg)
        self.base = cfg.fwd_base
        self.key = cfg.fwd_key
        self.allowed = cfg.fwd_allowed
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(timeout=15))

    def is_allowed(self, target: str) -> bool:
        low = target.lower()
        return any(low.startswith("https://" + h + "/") or low == "https://" + h
                   for h in self.allowed)

    async def reachable(self) -> bool:
        if not self.base:
            return False
        try:
            async with self._http_factory() as c:
                r = await c.post(self.base, json={
                    "target": "https://export.arxiv.org/api/query?search_query=all:langgraph&max_results=1",
                }, headers={"X-Fwd-Key": self.key or ""})
                return r.status_code == 200
        except Exception:
            return False

    def build_transport(self) -> httpx.AsyncBaseTransport:
        return _ForwardTransport(self)


class _ForwardTransport(httpx.AsyncBaseTransport):
    """Relays every request through the forward endpoint."""

    def __init__(self, channel: SelfForwardChannel):
        self.channel = channel
        self._http_factory = channel._http_factory

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target = str(request.url)
        if not self.channel.is_allowed(target):
            raise ValueError(f"target not allowed by forward endpoint: {target}")
        async with self._http_factory() as c:
            r = await c.post(self.channel.base, json={"target": target},
                             headers={"X-Fwd-Key": self.channel.key or ""})
            try:
                data = r.json()
            except Exception:
                data = {"status": r.status_code if r.status_code else 502,
                        "body": r.text}
        return httpx.Response(
            status_code=int(data.get("status", 502)),
            content=str(data.get("body", "")).encode("utf-8"),
            request=request,
        )


def build_channels(cfg: OutboundConfig) -> list[BaseChannel]:
    channels: list[BaseChannel] = []
    for name in cfg.channel_order:
        if name == "direct":
            channels.append(DirectChannel(cfg))
        elif name == "local-proxy":
            channels.append(LocalProxyChannel(cfg))
        elif name == "self-forward":
            channels.append(SelfForwardChannel(cfg))
        elif name == "direct-v6":
            channels.append(DirectV6Channel(cfg))
    return channels
