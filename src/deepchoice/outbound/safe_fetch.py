"""The single pinned-IP safe-fetch entry for outbound HTTP content.

The retriever does not build a client or connect directly. This module owns the
validated-IP transport, redirect loop, read-time byte cap, content-encoding and
content-type checks. The resolver selects the direct route from configuration
(no network probe) and records an audit entry; it does not infer request counts
from audit entries.
"""
from __future__ import annotations

import asyncio
import ssl
from typing import Any

import httpcore
import httpx

from ..security.urls import SafeUrlPolicy, UnsafeUrlError

DEFAULT_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
MAX_REDIRECTS = 3


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect TCP to exactly one validated address; Host/SNI stay URL-based."""

    def __init__(self, pinned_ip: str) -> None:
        self.pinned_ip = pinned_ip
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        return await self._backend.connect_tcp(
            self.pinned_ip, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, pinned_ip: str) -> None:
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            retries=0,
            network_backend=_PinnedNetworkBackend(pinned_ip),
        )


def _transport_factory(pinned_ip: str) -> httpx.AsyncBaseTransport:
    """Test seam; production always pins the validated IP."""
    return PinnedAsyncHTTPTransport(pinned_ip)


def select_direct_channel(cfg, channels, source: str = "official"
                          ) -> tuple[Any | None, str | None]:
    """Select the configured direct channel without probing or audit counting."""
    if cfg is None or not isinstance(channels, list):
        return None, "route_unavailable"
    by_name = {getattr(channel, "name", ""): channel for channel in channels}
    for name in cfg.order_for(source):
        channel = by_name.get(name)
        if channel is None:
            continue
        if name == "local-proxy" and not getattr(channel, "proxy_url", None):
            continue
        if name == "self-forward" and not getattr(channel, "base", None):
            continue
        if getattr(channel, "kind", "") != "direct":
            return None, "route_unsupported"
        return channel, None
    return None, "route_unavailable"


async def fetch_pinned_bytes(
    url: str,
    *,
    policy: SafeUrlPolicy,
    request_budget,
    deadline_s: float,
    max_response_bytes: int,
    max_redirects: int = MAX_REDIRECTS,
    allowed_content_types: tuple[str, ...] = DEFAULT_CONTENT_TYPES,
) -> dict:
    """GET a URL under one total deadline through a validated-IP transport.

    Returns raw bytes, not extracted text. Every dispatched request reserves one
    request-budget slot immediately before the stream is opened; redirects are
    separate requests. A compressed response is rejected before reading because
    the request asks for identity and a decoded large body would bypass the raw
    byte cap. ``bytes_read`` counts bytes consumed from the stream, while
    ``bytes_retained`` counts bytes kept under the cap.
    """
    if deadline_s <= 0 or max_response_bytes <= 0 or max_redirects < 0:
        raise ValueError("safe fetch bounds are invalid")
    try:
        async with asyncio.timeout(deadline_s):
            return await _fetch_inner(
                url, policy=policy, request_budget=request_budget,
                max_response_bytes=max_response_bytes, max_redirects=max_redirects,
                allowed_content_types=allowed_content_types,
            )
    except TimeoutError:
        request_budget.record_failure("timeout")
        return {"ok": False, "url": url, "failure": "timeout"}
    except UnsafeUrlError as exc:
        request_budget.record_failure("unsafe_url")
        return {"ok": False, "url": url, "failure": "unsafe_url",
                "detail": str(exc)[:200]}
    except Exception as exc:
        request_budget.record_failure(type(exc).__name__)
        return {"ok": False, "url": url, "failure": type(exc).__name__}


async def _fetch_inner(url: str, *, policy: SafeUrlPolicy, request_budget,
                       max_response_bytes: int, max_redirects: int,
                       allowed_content_types: tuple[str, ...]) -> dict:
    current = url
    redirects = 0
    while True:
        resolved = await policy.resolve(current)
        transport = _transport_factory(resolved.addresses[0])
        async with httpx.AsyncClient(
            transport=transport, timeout=None, follow_redirects=False,
            trust_env=False,
        ) as client:
            # Reserve after client construction, immediately before dispatch.
            if not request_budget.reserve_http():
                request_budget.record_failure("http_budget_exhausted")
                return {"ok": False, "url": current,
                        "failure": "http_budget_exhausted"}
            async with client.stream(
                "GET", resolved.url, headers={"Accept-Encoding": "identity"},
            ) as response:
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    if not location or redirects >= max_redirects:
                        request_budget.record_failure("redirect_limit")
                        return {"ok": False, "url": current,
                                "failure": "redirect_limit"}
                    current = str(httpx.URL(resolved.url).join(location))
                    redirects += 1
                    request_budget.redirects += 1
                    continue
                if status != 200:
                    request_budget.record_failure(f"http:{status}")
                    return {"ok": False, "url": current,
                            "failure": f"http:{status}"}
                media_type = (response.headers.get("content-type", "")
                              .split(";")[0].strip().lower())
                if not media_type:
                    request_budget.record_failure("content_type_missing")
                    return {"ok": False, "url": current,
                            "failure": "content_type_missing"}
                if media_type not in allowed_content_types:
                    request_budget.record_failure("content_type")
                    return {"ok": False, "url": current,
                            "failure": f"content_type:{media_type}"}
                encodings = {
                    item.strip().lower()
                    for header in response.headers.get_list("content-encoding")
                    for item in header.split(",")
                    if item.strip()
                }
                # The request asks for identity. HTTPX can still transparently
                # decode gzip; other encodings are rejected before aiter_bytes
                # because the decoder is not bounded here. The decoded stream is
                # read through the same retained-byte cap below.
                unsupported = {encoding for encoding in encodings
                               if encoding not in {"identity", "gzip"}}
                if unsupported:
                    request_budget.record_failure("content_encoding")
                    return {"ok": False, "url": current,
                            "failure": f"content_encoding:{','.join(sorted(unsupported))}"}
                declared = response.headers.get("content-length")
                declared_bytes = None
                declared_exceeded = False
                if declared:
                    try:
                        declared_bytes = int(declared)
                        declared_exceeded = declared_bytes > max_response_bytes
                    except ValueError:
                        declared_bytes = None
                # A declared oversize body is read through the same bounded
                # stream as an unknown-length body: do not turn one into a hard
                # rejection while silently truncating the other. The stream is
                # stopped at the cap and truncation is explicit.
                chunks: list[bytes] = []
                read_bytes = 0
                retained_bytes = 0
                transport_truncated = False
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    read_bytes += len(chunk)
                    remaining = max_response_bytes - retained_bytes
                    if remaining <= 0:
                        transport_truncated = True
                        break
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        retained_bytes += remaining
                        transport_truncated = True
                        break
                    chunks.append(chunk)
                    retained_bytes += len(chunk)
                capped = bool(transport_truncated or declared_exceeded)
                request_budget.bytes_read += read_bytes
                request_budget.bytes_retained += retained_bytes
                return {
                    "ok": True,
                    "url": url,
                    "body_url": resolved.url,
                    "body_bytes": b"".join(chunks),
                    "content_type": media_type,
                    "bytes_read": read_bytes,
                    "bytes_retained": retained_bytes,
                    "declared_content_length": declared_bytes,
                    "content_length_exceeded": declared_exceeded,
                    "page_truncated": capped,
                    "truncation_reason": "response_size_cap" if capped else None,
                    "max_response_bytes": max_response_bytes,
                }


__all__ = [
    "DEFAULT_CONTENT_TYPES", "PinnedAsyncHTTPTransport", "fetch_pinned_bytes",
    "select_direct_channel",
]
