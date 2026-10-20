"""Bounded, pinned page fetching for official documentation URLs.

The previous path resolved DNS for safety and then let httpx connect by hostname,
so the validated address was not the address actually connected to. This module
builds a one-request transport that connects to a validated IP while keeping the
original URL hostname for the Host header and TLS SNI. Proxies and forwarding
channels are rejected by the caller because they cannot prove the same boundary.

All bounds are shared by tests and production: one total page deadline,
read-time byte cap, explicit content types, bounded redirects, and a caller-owned
budget that counts page attempts and actual HTTP requests separately.
"""
from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field

import httpcore
import httpx

from ..security.urls import ResolvedUrl, SafeUrlPolicy, UnsafeUrlError
from ..utils.page_text import SourceDocument, extract_page_document

DEFAULT_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
NAVIGATION_MIN_PROSE_CHARS = 120
NAVIGATION_MIN_PROSE_RATIO = 0.15


@dataclass
class OfficialFetchBudget:
    """Explicit page-attempt and HTTP-request budget for one research run."""
    max_page_attempts: int = 2
    max_http_requests: int = 6
    page_attempts: int = 0
    http_requests: int = 0
    probe_requests: int = 0
    redirects: int = 0
    body_pages: int = 0
    navigation_pages: int = 0
    failed_pages: int = 0
    bytes_read: int = 0
    failures: list[str] = field(default_factory=list)

    def begin_page(self) -> bool:
        if self.page_attempts >= self.max_page_attempts:
            return False
        self.page_attempts += 1
        return True

    def reserve_http(self) -> bool:
        if self.http_requests >= self.max_http_requests:
            return False
        self.http_requests += 1
        return True

    def record_failure(self, code: str) -> None:
        self.failed_pages += 1
        self.failures.append(str(code)[:120])

    def snapshot(self) -> dict:
        return {
            "max_page_attempts": self.max_page_attempts,
            "max_http_requests": self.max_http_requests,
            "page_attempts": self.page_attempts,
            "http_requests": self.http_requests,
            "probe_requests": self.probe_requests,
            "redirects": self.redirects,
            "body_pages": self.body_pages,
            "navigation_pages": self.navigation_pages,
            "failed_pages": self.failed_pages,
            "bytes_read": self.bytes_read,
            "failures": list(self.failures),
        }


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect TCP to exactly one validated address.

    Host/SNI/Host-header semantics still come from the URL used by httpx; only
    the network peer is replaced. No hostname is resolved again by this backend.
    """

    def __init__(self, pinned_ip: str) -> None:
        self.pinned_ip = pinned_ip
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        return await self._backend.connect_tcp(
            self.pinned_ip, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """httpx transport whose TCP peer is pinned; URL Host/SNI remain authoritative."""

    def __init__(self, pinned_ip: str) -> None:
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            retries=0,
            network_backend=_PinnedNetworkBackend(pinned_ip),
        )


def _transport_factory(pinned_ip: str) -> httpx.AsyncBaseTransport:
    """Seam for offline tests; production always pins the validated IP."""
    return PinnedAsyncHTTPTransport(pinned_ip)


def _admission_failure(document: SourceDocument) -> str | None:
    """Reject pure menus/navigation/login pages by structural prose eligibility.

    Prose elements are preferred. When a page uses div/section text instead, a
    long, low-link-density text run is still admissible; a link-heavy menu or a
    short login notice is not. This is structure, not a keyword fact score.
    """
    prose = [document.blocks[i] for i in document.prose_indices if i < len(document.blocks)]
    prose_chars = sum(len(text) for text in prose)
    total_chars = document.text_chars or sum(len(text) for text in document.blocks)
    if not document.blocks:
        return "no_text_blocks"
    if total_chars <= 0:
        return "no_visible_text"
    link_ratio = (document.link_chars / total_chars) if total_chars else 1.0
    control_ratio = (document.control_chars / total_chars) if total_chars else 1.0
    prose_ratio = (prose_chars / total_chars) if total_chars else 0.0
    if prose and prose_chars >= NAVIGATION_MIN_PROSE_CHARS and \
            prose_ratio >= NAVIGATION_MIN_PROSE_RATIO:
        return None
    # Div/section-based documentation: enough non-heading prose text, several
    # blocks, low link density, few interactive-control labels. A heading-only
    # TOC or button/label menu fails this structural check.
    if (total_chars >= 400 and len(document.blocks) >= 4
            and link_ratio <= 0.15 and control_ratio <= 0.2
            and document.non_heading_chars >= 300):
        return None
    if not prose:
        return "no_prose_blocks"
    if prose_chars < NAVIGATION_MIN_PROSE_CHARS:
        return "short_prose_only"
    return "navigation_like"


async def fetch_official_page(
    url: str,
    *,
    policy: SafeUrlPolicy,
    budget: OfficialFetchBudget,
    deadline_s: float,
    max_response_bytes: int,
    max_redirects: int,
    store_chars: int,
    allowed_content_types: tuple[str, ...] = DEFAULT_CONTENT_TYPES,
) -> dict:
    """Fetch one page under one total deadline and a shared budget.

    Returns a plain result record; remote failures never raise. A validation or
    response failure leaves no body, so the caller must keep it navigation-only.
    """
    if deadline_s <= 0 or max_response_bytes <= 0 or max_redirects < 0 or store_chars <= 0:
        raise ValueError("official fetch bounds are invalid")
    try:
        async with asyncio.timeout(deadline_s):
            return await _fetch_inner(
                url, policy=policy, budget=budget,
                max_response_bytes=max_response_bytes,
                max_redirects=max_redirects, store_chars=store_chars,
                allowed_content_types=allowed_content_types,
            )
    except TimeoutError:
        budget.record_failure("timeout")
        return {"ok": False, "url": url, "failure": "timeout",
                "budget": budget.snapshot()}
    except UnsafeUrlError as exc:
        budget.record_failure("unsafe_url")
        return {"ok": False, "url": url, "failure": "unsafe_url",
                "detail": str(exc)[:200], "budget": budget.snapshot()}
    except Exception as exc:
        budget.record_failure(type(exc).__name__)
        return {"ok": False, "url": url,
                "failure": type(exc).__name__, "budget": budget.snapshot()}


async def _fetch_inner(url: str, *, policy: SafeUrlPolicy,
                       budget: OfficialFetchBudget, max_response_bytes: int,
                       max_redirects: int, store_chars: int,
                       allowed_content_types: tuple[str, ...]) -> dict:
    current = url
    redirects = 0
    while True:
        resolved = await policy.resolve(current)
        transport = _transport_factory(resolved.addresses[0])
        # Reserve only when the request is ready to be dispatched; a transport
        # construction failure must not consume an HTTP-request slot.
        if not budget.reserve_http():
            budget.record_failure("http_budget_exhausted")
            return {"ok": False, "url": current, "failure": "http_budget_exhausted",
                    "budget": budget.snapshot()}
        async with httpx.AsyncClient(
            transport=transport, timeout=None, follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                "GET", resolved.url, headers={"Accept-Encoding": "identity"},
            ) as response:
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    if not location or redirects >= max_redirects:
                        budget.record_failure("redirect_limit")
                        return {"ok": False, "url": current,
                                "failure": "redirect_limit", "budget": budget.snapshot()}
                    current = str(httpx.URL(resolved.url).join(location))
                    redirects += 1
                    budget.redirects += 1
                    continue
                if status != 200:
                    budget.record_failure(f"http:{status}")
                    return {"ok": False, "url": current,
                            "failure": f"http:{status}", "budget": budget.snapshot()}
                media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if not media_type:
                    budget.record_failure("content_type_missing")
                    return {"ok": False, "url": current,
                            "failure": "content_type_missing", "budget": budget.snapshot()}
                if media_type not in allowed_content_types:
                    budget.record_failure("content_type")
                    return {"ok": False, "url": current,
                            "failure": f"content_type:{media_type}",
                            "budget": budget.snapshot()}
                encodings = {
                    item.strip().lower()
                    for header in response.headers.get_list("content-encoding")
                    for item in header.split(",")
                    if item.strip()
                }
                if encodings - {"identity", "gzip"}:
                    budget.record_failure("content_encoding")
                    return {"ok": False, "url": current,
                            "failure": "content_encoding", "budget": budget.snapshot()}
                declared = response.headers.get("content-length")
                if declared:
                    try:
                        if int(declared) > max_response_bytes:
                            budget.record_failure("content_too_large")
                            return {"ok": False, "url": current,
                                    "failure": "content_too_large",
                                    "budget": budget.snapshot()}
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                total = 0
                transport_truncated = False
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    remaining = max_response_bytes - total
                    if remaining <= 0:
                        transport_truncated = True
                        break
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        total += remaining
                        transport_truncated = True
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                budget.bytes_read += total
                raw = b"".join(chunks).decode("utf-8", "replace")
                document = extract_page_document(
                    raw, truncated=transport_truncated, plain_text=media_type == "text/plain")
                admission = _admission_failure(document)
                if admission is not None:
                    budget.navigation_pages += 1
                    return {"ok": False, "url": current,
                            "failure": f"not_prose:{admission}",
                            "page_chars": sum(len(b) for b in document.blocks),
                            "prose_chars": sum(len(document.blocks[i])
                                               for i in document.prose_indices),
                            "budget": budget.snapshot()}
                body = " ".join(document.blocks)
                stored = body[:store_chars].rstrip()
                page_truncated = bool(transport_truncated or document.incomplete)
                stored_truncated = len(body) > len(stored)
                budget.body_pages += 1
                return {
                    "ok": True,
                    "url": url,
                    "body_url": resolved.url,
                    "body": stored,
                    "page_chars": len(body),
                    "stored_chars": len(stored),
                    "page_truncated": page_truncated,
                    "stored_truncated": stored_truncated,
                    "truncated": bool(page_truncated or stored_truncated),
                    "prose_chars": sum(len(document.blocks[i])
                                       for i in document.prose_indices),
                    "admission": "prose_ok",
                    "content_type": media_type,
                    "bytes": total,
                    "budget": budget.snapshot(),
                }


__all__ = [
    "DEFAULT_CONTENT_TYPES", "OfficialFetchBudget", "PinnedAsyncHTTPTransport",
    "fetch_official_page", "NAVIGATION_MIN_PROSE_CHARS",
    "NAVIGATION_MIN_PROSE_RATIO",
]
