"""ChannelResolver: probe once, route by table, re-route on failure.

Design points (2026-08-31 spec):
- No per-request trial-and-error: probes build a route table; executions obey it.
- On failure the source is invalidated and re-probed after an exponential
  backoff (30s / 120s / 300s), then the route is refreshed.
- Every probe/route decision is appended to the audit log.
"""
from __future__ import annotations

import asyncio
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from ..security.urls import ResolvedUrl, SafeFetchFailure, SafeUrlPolicy, UnsafeUrlError

from .channels import (
    BaseChannel,
    OutboundConfig,
    build_channels,
)
from .probe import PROBES, probe_source
from .tunnel import PinnedProxyTransport, proxy_endpoint_identity

SAFE_DEFAULT_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

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
                 now_fn: Callable[[], float] = time.monotonic,
                 safe_url_policy: SafeUrlPolicy | None = None,
                 safe_transport_factory: Callable[[ResolvedUrl, str], httpx.AsyncBaseTransport] | None = None,
                 safe_proxy_transport_factory: Callable[[ResolvedUrl, str, str], httpx.AsyncBaseTransport] | None = None):
        self.cfg = cfg or OutboundConfig.from_env()
        self.channels = channels or build_channels(self.cfg)
        self._probe_fn = probe_fn or self._default_probe
        self._now = now_fn
        self._safe_url_policy = safe_url_policy or SafeUrlPolicy()
        self._safe_transport_factory = safe_transport_factory or _pinned_transport
        self._safe_proxy_transport_factory = safe_proxy_transport_factory or PinnedProxyTransport
        self._lock = asyncio.Lock()
        self._probe_locks: dict[str, asyncio.Lock] = {}
        # source -> {"channel": channel|None, "next_probe": float, "attempts": int}
        self._routes: dict[str, dict[str, Any]] = {}
        self.audit: list[AuditEntry] = []

    async def _default_probe(self, source: str, channel: BaseChannel) -> bool:
        """Probe through a client wired to the very channel being tested —
        otherwise the probe silently measures direct connectivity and the
        reported channel is a lie (github/community 'self-forward' bug)."""
        return await probe_source(source, channel,
                                  make_client=lambda _s: self._make_client(channel))

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
        by_name = {ch.name: ch for ch in self.channels}
        for name in self.cfg.order_for(source):
            channel = by_name.get(name)
            if channel is None:
                continue
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

    async def safe_fetch(
        self,
        source: str,
        url: str,
        *,
        method: str = "GET",
        allowed_content_types: tuple[str, ...] = SAFE_DEFAULT_CONTENT_TYPES,
        max_response_bytes: int = 64 * 1024,
        max_redirects: int = 3,
        timeout_s: float = 15.0,
        head_fallback_to_range_get: bool = False,
        allow_response_truncation: bool = False,
    ) -> httpx.Response:
        """Fetch a dynamic URL after DNS validation and connection pinning.

        Direct connections are pinned locally. Only an explicitly trusted,
        matching loopback HTTP proxy may tunnel a validated IP for HTTPS:443.
        Forwarding and other proxy capabilities continue to fail closed.
        """
        if method.upper() not in {"GET", "HEAD"}:
            raise ValueError("safe_fetch only supports GET and HEAD")
        if (
            max_response_bytes <= 0
            or max_redirects < 0
            or timeout_s <= 0
            or not allowed_content_types
        ):
            raise ValueError("safe_fetch limits are invalid")
        from ..runtime.context import get_run_context

        context = get_run_context()
        proxy_identity = self.cfg.safe_fetch_proxy_sha256
        if context is not None and (
            context.safe_fetch_proxy_sha256 != proxy_identity
            or context.security_policy_version != "outbound-url-v5"
        ):
            raise UnsafeUrlError("Safe fetch configuration differs from the frozen run", failure=SafeFetchFailure.ROUTE_UNSUPPORTED)
        channel = await self.resolve(source)
        if channel is None:
            raise UnsafeUrlError("No outbound channel is available", failure=SafeFetchFailure.ROUTE_UNAVAILABLE)
        proxy_url = None
        if channel.kind == "local-proxy" and self.cfg.safe_fetch_trusted_local_proxy is not None:
            if context is None:
                raise UnsafeUrlError("Trusted proxy requires a frozen durable run", failure=SafeFetchFailure.ROUTE_UNSUPPORTED)
            proxy_url = self.cfg.safe_fetch_trusted_local_proxy
            if proxy_endpoint_identity(channel.proxy_url) != proxy_url:
                raise UnsafeUrlError("Selected proxy differs from the trusted endpoint", failure=SafeFetchFailure.ROUTE_UNSUPPORTED)
        elif channel.kind != "direct":
            raise UnsafeUrlError("Selected outbound channel cannot bind the validated target", failure=SafeFetchFailure.ROUTE_UNSUPPORTED)

        async def fetch():
            try:
                return await asyncio.wait_for(
                    self._safe_fetch_direct(
                        url, source=source, method=method.upper(),
                        allowed_content_types=allowed_content_types,
                        max_response_bytes=max_response_bytes, max_redirects=max_redirects,
                        timeout_s=timeout_s,
                        head_fallback_to_range_get=head_fallback_to_range_get,
                        allow_response_truncation=allow_response_truncation,
                        proxy_url=proxy_url,
                    ),
                    timeout=timeout_s,
                )
            except TimeoutError as exc:
                raise UnsafeUrlError("Safe URL fetch exceeded the total timeout", failure=SafeFetchFailure.TIMEOUT) from exc
            except httpx.DecodingError:
                # httpx may raise while opening the response stream or while
                # iterating it, depending on the transport implementation.
                raise UnsafeUrlError(
                    "Response content encoding could not be decoded",
                    failure=SafeFetchFailure.RESPONSE_REJECTED,
                ) from None

        if source == "official":
            from . import throttle

            # The bounded logical URL check includes its safe redirects/HEAD
            # fallback. Queue time is outside the original total network limit.
            async with throttle.gate_for("official-web").slot():
                return await fetch()
        return await fetch()

    async def _safe_fetch_direct(
        self,
        url: str,
        *,
        source: str = "",
        method: str,
        allowed_content_types: tuple[str, ...],
        max_response_bytes: int,
        max_redirects: int,
        timeout_s: float,
        head_fallback_to_range_get: bool,
        allow_response_truncation: bool,
        proxy_url: str | None = None,
    ) -> httpx.Response:
        current_url = url
        current_method = method
        # Dynamic safe fetches need byte-count enforcement on the exact
        # representation consumed below.  Asking for identity also avoids a
        # broken intermediary/server combination advertising gzip after the
        # body has already been decoded.  Servers may ignore this request, so
        # decoding failures still fail closed below.
        headers: dict[str, str] = {"Accept-Encoding": "identity"}
        redirects = 0
        while True:
            if proxy_url is not None:
                try:
                    target = urlsplit(current_url)
                    https_target = target.scheme.lower() == "https" and target.port in {None, 443}
                except ValueError:
                    https_target = False
                if not https_target:
                    raise UnsafeUrlError("Trusted proxy supports only HTTPS on port 443", failure=SafeFetchFailure.ROUTE_UNSUPPORTED)
            resolved = await self._safe_url_policy.resolve(current_url)
            # Pick only from the validated set. A fresh transport per hop keeps
            # pool reuse from crossing hostname/address validation boundaries.
            pinned_ip = resolved.addresses[0]
            transport = (
                self._safe_proxy_transport_factory(resolved, pinned_ip, proxy_url)
                if proxy_url is not None else self._safe_transport_factory(resolved, pinned_ip)
            )
            async with httpx.AsyncClient(
                transport=transport,
                timeout=timeout_s,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                try:
                    async with client.stream(current_method, resolved.url, headers=headers) as streamed:
                        status = streamed.status_code
                        response_headers = streamed.headers
                        if source == "official":
                            from . import throttle

                            # A 429 may have a JSON/plain-text body. Publish only
                            # its safe status/headers before content validation;
                            # never read or expose the provider error body.
                            if throttle.observe(source, streamed, throttle.gate_for("official-web")):
                                raise throttle.ProviderRateLimitError("official URL rate limited")
                        if status in {301, 302, 303, 307, 308}:
                            location = streamed.headers.get("location")
                            if not location:
                                raise UnsafeUrlError("Redirect response has no location", failure=SafeFetchFailure.RESPONSE_REJECTED)
                            if redirects >= max_redirects:
                                raise UnsafeUrlError("Too many redirects", failure=SafeFetchFailure.RESPONSE_REJECTED)
                            current_url = urljoin(resolved.url, location)
                            redirects += 1
                            if status == 303 and current_method != "HEAD":
                                current_method = "GET"
                            continue
                        if (
                            current_method == "HEAD"
                            and head_fallback_to_range_get
                            and status in {405, 501}
                        ):
                            current_method = "GET"
                            headers = {
                                **headers,
                                "Range": f"bytes=0-{max_response_bytes - 1}",
                            }
                            # Re-resolve and repin even for the same logical URL.
                            continue

                        content_encodings = tuple(
                            encoding.strip().lower()
                            for header in response_headers.get_list("content-encoding")
                            for encoding in header.split(",")
                            if encoding.strip()
                        )
                        if any(
                            encoding not in {"identity", "gzip"}
                            for encoding in content_encodings
                        ):
                            raise UnsafeUrlError(
                                "Response content encoding is not allowed",
                                failure=SafeFetchFailure.RESPONSE_REJECTED,
                            )
                        media_type = response_headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if not any(
                            media_type == allowed.lower() for allowed in allowed_content_types
                        ):
                            raise UnsafeUrlError("Response content type is not allowed", failure=SafeFetchFailure.RESPONSE_REJECTED)
                        body = bytearray()
                        body_truncated = False
                        try:
                            async for chunk in streamed.aiter_bytes(
                                chunk_size=min(8192, max_response_bytes)
                            ):
                                remaining = max_response_bytes - len(body)
                                if len(chunk) > remaining:
                                    if allow_response_truncation:
                                        body.extend(chunk[:remaining])
                                        body_truncated = True
                                        break
                                    raise UnsafeUrlError("Response body exceeds the allowed size", failure=SafeFetchFailure.RESPONSE_REJECTED)
                                body.extend(chunk)
                        except httpx.DecodingError:
                            raise UnsafeUrlError(
                                "Response stream could not be consumed safely",
                                failure=SafeFetchFailure.RESPONSE_REJECTED,
                            ) from None
                        decoded_headers = httpx.Headers(response_headers)
                        # aiter_bytes() returns the decoded representation.  Do
                        # not attach the upstream representation headers to those
                        # bytes or downstream httpx consumers will decode again.
                        for header_name in (
                            "content-encoding",
                            "content-length",
                            "transfer-encoding",
                        ):
                            decoded_headers.pop(header_name, None)
                        decoded_headers["content-length"] = str(len(body))
                        return httpx.Response(
                            status_code=status,
                            headers=decoded_headers,
                            content=bytes(body),
                            request=streamed.request,
                            extensions={"deepchoice_body_truncated": body_truncated},
                        )
                except httpx.StreamError:
                    raise UnsafeUrlError(
                        "Response stream could not be consumed safely",
                        failure=SafeFetchFailure.RESPONSE_REJECTED,
                    ) from None

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

    def summary(self) -> dict[str, Any]:
        """Compact route table + audit export for benchmark reports."""
        routes = {
            source: {"channel": st["channel"], "attempts": st["attempts"],
                     "next_probe_s": round(max(0.0, st["next_probe"] - self._now()), 1)}
            for source, st in self._routes.items()
        }
        return {
            "routes": routes,
            "audit": [vars(e) for e in self.audit],
        }

    async def health_check(self, sources: list[str] | None = None) -> dict[str, Any]:
        """Probe all configured sources; returns per-source diagnostics."""
        sources = sources or list(PROBES.keys())
        results: dict[str, Any] = {}
        for source in sources:
            from . import throttle

            try:
                channel = await self._probe_for(source)
            except throttle.ProviderAdmissionError as exc:
                status = "rate_limited" if isinstance(exc, throttle.ProviderRateLimitError) else "admission_blocked"
                results[source] = {"channel": None, "ok": False, "status": status}
                continue
            limited = source != "tavily" and source in PROBES and throttle.gate_for(source).unavailable()
            if source == "official":
                limited = limited or throttle.gate_for("official-web").unavailable()
            results[source] = {
                "channel": channel.name if channel else None,
                "ok": channel is not None and not limited,
            }
            if limited:
                results[source]["status"] = "rate_limited"
        degraded = [s for s, v in results.items() if not v["ok"]]
        return {"ok": not degraded, "degraded_sources": degraded, "sources": results}


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect TCP to one validated address while httpcore retains Host/SNI."""

    def __init__(self, pinned_ip: str) -> None:
        self.pinned_ip = pinned_ip
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await self._backend.connect_tcp(
            self.pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, pinned_ip: str) -> None:
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            retries=0,
            network_backend=_PinnedNetworkBackend(pinned_ip),
        )


def _pinned_transport(_resolved: ResolvedUrl, pinned_ip: str) -> httpx.AsyncBaseTransport:
    return _PinnedAsyncHTTPTransport(pinned_ip)
