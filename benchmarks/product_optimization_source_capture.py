"""Bounded capture of one frozen official deep-link target for later review.

Captured bytes are *candidates*, not approved seed evidence.  This module
never promotes a capture into the knowledge index and never reads case data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from urllib.parse import urlsplit
import uuid

from deepchoice import outbound

from benchmarks.product_optimization_official_intake import ROOT, load_official_intake_plan


CAPTURE_SCHEMA_VERSION = 2
EXTRACTOR_ID = "stdlib-html-text-v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
CAPTURE_ROOT = ROOT / "outputs" / "product-optimization-captures"
_SAFE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SKIP_TAGS = frozenset({"script", "style", "template", "noscript", "svg"})
_BREAK_TAGS = frozenset({
    "article", "blockquote", "br", "dd", "div", "dt", "h1", "h2", "h3",
    "h4", "h5", "h6", "li", "main", "p", "pre", "section", "table", "td", "th", "tr",
})


class SourceCaptureError(ValueError):
    """Body-free capture rejection."""


@dataclass(frozen=True)
class CapturedSource:
    target_id: str
    parent_catalog_key: str
    directory: Path
    receipt_sha256: str
    raw_sha256: str
    text_sha256: str


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if not self._skip_depth and tag in _BREAK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if not self._skip_depth and tag in _BREAK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        lines = (
            re.sub(r"[ \t\f\v]+", " ", line).strip()
            for line in "".join(self._parts).splitlines()
        )
        return "\n".join(line for line in lines if line)


def _safe_final_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        port = parts.port
    except (TypeError, ValueError):
        raise SourceCaptureError("final URL is invalid") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.query
        or parts.fragment
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise SourceCaptureError("final URL is not a public canonical HTTPS identity")
    return value


def _extract_html(raw: bytes) -> bytes:
    try:
        html = raw.decode("utf-8", errors="strict")
        parser = _VisibleText()
        parser.feed(html)
        parser.close()
        text = parser.text()
        output = text.encode("utf-8")
    except (UnicodeError, ValueError):
        raise SourceCaptureError("response is not extractable UTF-8 HTML") from None
    if not text or len(output) > MAX_TEXT_BYTES:
        raise SourceCaptureError("extracted text is empty or exceeds the limit")
    return output


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    return bool(getattr(metadata, "st_file_attributes", 0) & 0x0400)


def _prepare_capture_root() -> Path:
    """Use only the dedicated ignored output root; no caller-chosen paths."""

    root = CAPTURE_ROOT
    if root != ROOT / "outputs" / "product-optimization-captures":
        raise SourceCaptureError("capture root differs from the dedicated local output root")
    parent = root.parent
    if not parent.is_dir() or any(
        _is_reparse_or_symlink(ancestor) for ancestor in (parent, *parent.parents)
    ):
        raise SourceCaptureError("capture output parent is unavailable or redirected")
    if _is_reparse_or_symlink(root):
        raise SourceCaptureError("capture output root is redirected")
    try:
        root.mkdir(exist_ok=True)
    except OSError:
        raise SourceCaptureError("capture output root could not be prepared") from None
    if not root.is_dir() or _is_reparse_or_symlink(root):
        raise SourceCaptureError("capture output root is unavailable or redirected")
    return root


async def capture_official_target(target_id: str) -> CapturedSource:
    """Fetch one exact v2 target through outbound.safe_fetch into the ignored root.

    Capture is staged in a new private directory and atomically published only
    after its two bodies and receipt have been written.  It remains unapproved.
    """

    plan = load_official_intake_plan()
    matches = [target for target in plan.targets if target.target_id == target_id]
    if len(matches) != 1 or not _SAFE_KEY.fullmatch(target_id):
        raise SourceCaptureError("target ID is not in the frozen intake plan")
    target = matches[0]
    _safe_final_url(target.url)
    root = _prepare_capture_root()

    try:
        response = await outbound.safe_fetch(
            "official", target.url, method="GET",
            allowed_content_types=("text/html", "application/xhtml+xml"),
            max_response_bytes=MAX_RESPONSE_BYTES, max_redirects=0, timeout_s=15.0,
        )
    except Exception:
        raise SourceCaptureError("bounded official source fetch failed") from None
    if response.status_code != 200:
        raise SourceCaptureError("official source did not return HTTP 200")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise SourceCaptureError("official source is not HTML")
    final_url = _safe_final_url(str(response.url))
    if final_url != target.url:
        raise SourceCaptureError("official source final URL differs from the frozen target")
    raw = response.content
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise SourceCaptureError("official source body is empty or exceeds the limit")
    text = _extract_html(raw)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    text_sha256 = hashlib.sha256(text).hexdigest()
    receipt = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "status": "candidate_unapproved",
        "plan_id": plan.plan_id,
        "plan_byte_sha256": plan.byte_sha256,
        "plan_canonical_sha256": plan.canonical_plan_sha256,
        "development_fixture_id": plan.development_fixture_id,
        "target_id": target.target_id,
        "parent_catalog_key": target.parent_catalog_key,
        "case_ids": list(target.case_ids),
        "evidence_topics": list(target.evidence_topics),
        "locator_label_unverified": target.locator_label_unverified,
        "start_url": target.url,
        "final_url": final_url,
        "http_status": 200,
        "content_type": content_type,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_bytes": len(raw),
        "raw_sha256": raw_sha256,
        "extractor_id": EXTRACTOR_ID,
        "text_bytes": len(text),
        "text_sha256": text_sha256,
    }
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary: Path | None = None
    destination = root / f"{target_id}-{uuid.uuid4().hex}"
    try:
        temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
        _write_exclusive(temporary / "response.html", raw)
        _write_exclusive(temporary / "body.txt", text)
        _write_exclusive(temporary / "receipt.json", receipt_bytes)
        temporary.rename(destination)
    except OSError:
        raise SourceCaptureError("capture files could not be published") from None
    finally:
        if temporary is not None and temporary.exists():
            try:
                shutil.rmtree(temporary)
            except OSError:
                # A failed cleanup remains under the ignored .pending-* prefix;
                # downstream admission accepts only complete published captures.
                pass
    return CapturedSource(
        target_id=target.target_id,
        parent_catalog_key=target.parent_catalog_key,
        directory=destination,
        receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        raw_sha256=raw_sha256, text_sha256=text_sha256,
    )


async def capture_official_entry(target_id: str) -> CapturedSource:
    """Compatibility name; v2 accepts only an exact frozen target ID."""

    return await capture_official_target(target_id)


__all__ = [
    "CapturedSource",
    "SourceCaptureError",
    "capture_official_entry",
    "capture_official_target",
]
