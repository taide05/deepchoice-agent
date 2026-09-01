"""ChannelResolver: probe once, route by table, re-route on failure.

Design points (2026-08-31 spec):
- No per-request trial-and-error: probes build a route table; executions obey it.
- On failure the source is invalidated and re-probed after an exponential
  backoff (30s / 120s / 300s), then the route is refreshed.
- Every probe/route decision is appended to the audit log.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .channels import (
    BaseChannel,
    OutboundConfig,
    build_channels,
)
from .probe import PROBES, probe_source

BACKOFF_S = (30.0, 120.0, 300.0)


@dataclass
class AuditEntry:
    at: float
    source: str
    channel: str | None
    ok: bool
    kind: str  # probe | route | reroute
    detail: str = ""


class ChannelResolver:
    def __init__(self, cfg: OutboundConfig | None = None,
                 channels: list[BaseChannel] | None = None,
                 probe_fn: Callable | None = None,
                 now_fn: Callable[[], float] = time.monotonic):
        self.cfg = cfg or OutboundConfig.from_env()
        self.channels = channels or build_channels(self.cfg)
        self._probe_fn = probe_fn or probe_source
        self._now = now_fn
        self._lock = asyncio.Lock()
        self._probe_locks: dict[str, asyncio.Lock] = {}
        # source -> {"channel": channel|None, "next_probe": float, "attempts": int}
        self._routes: dict[str, dict[str, Any]] = {}
        self.audit: list[AuditEntry] = []

    # -- internals ---------------------------------------------------------

    def _record(self, source: str, channel: str | None, ok: bool, kind: str,
                detail: str = "") -> None:
        self.audit.append(AuditEntry(at=self._now(), source=source,
                                     channel=channel, ok=ok, kind=kind, detail=detail))

    def _channel(self, name: str | None) -> BaseChannel | None:
        if name is None:
            return None
        for c in self.channels:
            if c.name == name:
                return c
        return None

    async def _probe_for(self, source: str) -> BaseChannel | None:
        for channel in self.channels:
            ok = await self._probe_fn(source, channel)
            self._record(source, channel.name, ok, "probe")
            if ok:
                return channel
        return None

    def _make_client(self, channel: BaseChannel) -> httpx.AsyncClient:
        if channel.kind == "local-proxy":
            return httpx.AsyncClient(timeout=15, proxy=channel.proxy_url)
        if channel.kind == "self-forward":
            return httpx.AsyncClient(timeout=15, transport=channel.build_transport())
        return httpx.AsyncClient(timeout=15)

    # -- public api ---------------------------------------------------------

    async def resolve(self, source: str) -> BaseChannel | None:
        """Return the channel to use for `source`.

        Lazily probes on first call; afterwards serves from the route table.
        After invalidate(), re-probes only once the backoff window has passed.
        Concurrent callers share one in-flight probe per source.
        """
        async with self._lock:
            state = self._routes.get(source)
            if state is None:
                state = {"channel": None, "next_probe": 0.0, "attempts": 0}
                self._routes[source] = state

            channel = self._channel(state["channel"])
            if channel is not None:
                return channel
            if self._now() < state["next_probe"]:
                return None

        # one in-flight probe per source; re-check after acquiring.
        async with self._probe_locks.setdefault(source, asyncio.Lock()):
            async with self._lock:
                state = self._routes.setdefault(source, {
                    "channel": None, "next_probe": 0.0, "attempts": 0})
                if state["channel"] is not None:
                    return self._channel(state["channel"])
                if self._now() < state["next_probe"]:
                    return None

            chosen = await self._probe_for(source)
            async with self._lock:
                state = self._routes.setdefault(source, {
                    "channel": None, "next_probe": 0.0, "attempts": 0})
                if chosen is None:
                    state["attempts"] += 1
                    idx = min(state["attempts"] - 1, len(BACKOFF_S) - 1)
                    state["next_probe"] = self._now() + BACKOFF_S[idx]
                    self._record(source, None, False, "route", "unreachable")
                else:
                    state["channel"] = chosen.name
                    state["attempts"] = 0
                    self._record(source, chosen.name, True, "route")
                return chosen

    async def make_client(self, source: str) -> httpx.AsyncClient:
        """Client for `source` wired to the routed channel (zero trial-and-error)."""
        channel = await self.resolve(source)
        if channel is None:
            raise RuntimeError(f"no outbound channel available for source: {source}")
        return self._make_client(channel)

    async def invalidate(self, source: str) -> None:
        """Drop the current route for `source` (call after a channel failure).

        The next resolve() re-probes immediately up to the backoff window
        recorded by previous failures.
        """
        async with self._lock:
            state = self._routes.get(source)
            if state is None:
                state = {"channel": None, "next_probe": 0.0, "attempts": 0}
                self._routes[source] = state
            if state["channel"] is not None:
                self._record(source, state["channel"], False, "reroute")
            state["channel"] = None
            state["next_probe"] = 0.0

    # -- health-check ---------------------------------------------------------

    async def health_check(self, sources: list[str] | None = None) -> dict[str, Any]:
        """Probe all configured sources; returns per-source diagnostics."""
        sources = sources or list(PROBES.keys())
        results: dict[str, Any] = {}
        for source in sources:
            channel = await self._probe_for(source)
            results[source] = {
                "channel": channel.name if channel else None,
                "ok": channel is not None,
            }
        degraded = [s for s, v in results.items() if not v["ok"]]
        return {"ok": not degraded, "degraded_sources": degraded, "sources": results}
