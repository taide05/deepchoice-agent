"""Official-page body adapter: budget + structural admission + provenance.

Network policy, pinned-IP transport, redirects, total deadline, read-time byte
caps and compression/content-type checks live in the outbound safe-fetch entry.
This module only owns the official-source budget, page-attempt accounting,
structural text extraction/admission, and the stored-body/page/window metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..outbound import safe_fetch_page
from ..security.urls import SafeUrlPolicy
from ..utils.page_text import SourceDocument, extract_page_document

DEFAULT_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
NAVIGATION_MIN_PROSE_CHARS = 120
NAVIGATION_MIN_PROSE_RATIO = 0.20


@dataclass
class OfficialFetchBudget:
    """Page-attempt and dispatched-HTTP budgets for one research identity."""
    max_page_attempts: int = 2
    max_http_requests: int = 6
    page_attempts: int = 0
    http_requests: int = 0
    redirects: int = 0
    body_pages: int = 0
    navigation_pages: int = 0
    failed_pages: int = 0
    bytes_read: int = 0
    bytes_retained: int = 0
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
            "probe_requests": 0,
            "redirects": self.redirects,
            "body_pages": self.body_pages,
            "navigation_pages": self.navigation_pages,
            "failed_pages": self.failed_pages,
            "bytes_read": self.bytes_read,
            "bytes_retained": self.bytes_retained,
            "failures": list(self.failures),
        }


def _research_identity() -> str | None:
    """Use the existing run_limits execution identity when this process has one."""
    try:
        import run_limits
    except ImportError:
        return None
    try:
        snapshot = run_limits.snapshot()
    except Exception:
        return None
    task_id = snapshot.get("task_id")
    run_started = snapshot.get("run_started_at_epoch")
    if task_id and run_started is not None:
        return f"{task_id}:{run_started}"
    return None


_RESEARCH_BUDGETS: dict[str, OfficialFetchBudget] = {}


def budget_for_research(*, max_page_attempts: int, max_http_requests: int
                        ) -> OfficialFetchBudget:
    """One budget per existing research identity; reentry accumulates."""
    identity = _research_identity()
    if identity is None:
        raise LookupError("no active research identity")
    budget = _RESEARCH_BUDGETS.get(identity)
    if budget is None:
        budget = OfficialFetchBudget(
            max_page_attempts=max_page_attempts,
            max_http_requests=max_http_requests,
        )
        _RESEARCH_BUDGETS[identity] = budget
    return budget


def reset_research_budgets() -> None:
    """Test/teardown seam; production budgets are keyed by the run identity."""
    _RESEARCH_BUDGETS.clear()


def _admission_failure(document: SourceDocument) -> str | None:
    """Reject pure menus/directories by structural prose eligibility.

    A successful fetch, a table of contents, or a few intro sentences is not a
    decisive body. Pages with a low prose ratio or link-dominated structure are
    navigation even when their text is long; no topic keywords are scored here.
    """
    prose = [document.blocks[i] for i in document.prose_indices
             if i < len(document.blocks)]
    prose_chars = sum(len(text) for text in prose)
    total_chars = document.text_chars or sum(len(text) for text in document.blocks)
    if not document.blocks:
        return "no_text_blocks"
    if total_chars <= 0:
        return "no_visible_text"
    link_ratio = (document.link_chars / total_chars) if total_chars else 1.0
    control_ratio = (document.control_chars / total_chars) if total_chars else 1.0
    prose_ratio = (prose_chars / total_chars) if total_chars else 0.0
    if document.page_role == "navigation":
        return "navigation_like"
    if document.page_role == "structured_document":
        if (total_chars >= 400 and link_ratio <= 0.15
                and control_ratio <= 0.20 and document.non_heading_chars >= 300):
            return None
        return "structured_low_prose"
    if not prose:
        return "no_prose_blocks"
    if prose_chars < NAVIGATION_MIN_PROSE_CHARS:
        return "short_prose_only"
    if prose_ratio < NAVIGATION_MIN_PROSE_RATIO:
        return "low_prose_ratio"
    if link_ratio > 0.25 or control_ratio > 0.20:
        return "navigation_like"
    return None


async def fetch_official_page(
    url: str,
    *,
    policy: SafeUrlPolicy | None = None,
    budget: OfficialFetchBudget,
    deadline_s: float,
    max_response_bytes: int,
    max_redirects: int,
    store_chars: int,
    allowed_content_types: tuple[str, ...] = DEFAULT_CONTENT_TYPES,
) -> dict:
    """Fetch via outbound's pinned safe entry, then admit/extract bounded text."""
    if deadline_s <= 0 or max_response_bytes <= 0 or max_redirects < 0 or store_chars <= 0:
        raise ValueError("official fetch bounds are invalid")
    fetched = await safe_fetch_page(
        "official", url, request_budget=budget, policy=policy,
        deadline_s=deadline_s, max_response_bytes=max_response_bytes,
        max_redirects=max_redirects,
        allowed_content_types=allowed_content_types,
    )
    if not fetched.get("ok"):
        return {
            "ok": False,
            "url": url,
            "failure": str(fetched.get("failure") or "fetch_failed"),
            "budget": budget.snapshot(),
        }
    media_type = fetched.get("content_type", "")
    raw = fetched["body_bytes"].decode("utf-8", "replace")
    document = extract_page_document(
        raw, truncated=bool(fetched.get("page_truncated")),
        plain_text=media_type == "text/plain",
    )
    admission = _admission_failure(document)
    if admission is not None:
        budget.navigation_pages += 1
        return {
            "ok": False,
            "url": url,
            "failure": f"not_prose:{admission}",
            "page_chars": sum(len(block) for block in document.blocks),
            "prose_chars": sum(len(document.blocks[i])
                               for i in document.prose_indices),
            "budget": budget.snapshot(),
        }
    body = " ".join(document.main_blocks)
    stored = body[:store_chars].rstrip()
    page_truncated = bool(fetched.get("page_truncated") or document.incomplete)
    stored_truncated = len(body) > len(stored)
    budget.body_pages += 1
    return {
        "ok": True,
        "url": url,
        "body_url": fetched.get("body_url") or url,
        "body": stored,
        "body_blocks": list(document.main_blocks),
        "page_chars": len(body),
        "stored_chars": len(stored),
        "page_truncated": page_truncated,
        "stored_truncated": stored_truncated,
        "truncated": bool(page_truncated or stored_truncated),
        "truncation_reason": fetched.get("truncation_reason"),
        "declared_content_length": fetched.get("declared_content_length"),
        "content_length_exceeded": fetched.get("content_length_exceeded", False),
        "max_response_bytes": fetched.get("max_response_bytes"),
        "prose_chars": sum(len(document.blocks[i])
                           for i in document.prose_indices),
        "main_block_count": len(document.main_blocks),
        "prose_block_count": len(document.prose_indices),
        "heading_context_count": document.heading_context_count,
        "page_role": document.page_role,
        "admission": "prose_ok",
        "content_type": media_type,
        "bytes": fetched.get("bytes_read", 0),
        "bytes_read": fetched.get("bytes_read", 0),
        "bytes_retained": fetched.get("bytes_retained", 0),
        "budget": budget.snapshot(),
    }


__all__ = [
    "DEFAULT_CONTENT_TYPES", "OfficialFetchBudget", "budget_for_research",
    "fetch_official_page", "reset_research_budgets",
    "NAVIGATION_MIN_PROSE_CHARS", "NAVIGATION_MIN_PROSE_RATIO",
]
