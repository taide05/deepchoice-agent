"""Fail-closed admission of content-reviewed official development sources.

The tracked review binds exact ignored capture receipts and bodies.  It does
not make first-party documentation independent performance evidence, build a
knowledge index, or read benchmark reports/holdouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from benchmarks.product_optimization_official_intake import (
    CANONICAL_PLAN_SHA256,
    FIXTURE_ID,
    PLAN_BYTES_SHA256,
    PLAN_ID,
    ROOT,
    OfficialIntakePlan,
    load_official_intake_plan,
)
from benchmarks.product_optimization_seed import _has_prohibited_benchmark_marker


REVIEW_SCHEMA_VERSION = 1
REVIEW_ID = "product-optimization-source-review-v1"
REVIEW_STATUS = "approved_for_development_seed"
REVIEW_DATE = "2026-09-24"
REVIEWER_MODE = "gpt-only_source_content_audit"
REVIEW_BYTES_SHA256 = "8a7cfe6bd9e3a79db51e5199c688a2a4427457f218047aec4ab107925cdc740e"
CANONICAL_REVIEW_SHA256 = "fd24fc558597b749566869ecaca0121ff50425bdf8aac5dd21c750291798419b"
MAX_REVIEW_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_CAPTURE_CANDIDATES = 64
MAX_CAPTURE_BODY_BYTES = 2 * 1024 * 1024
_EXPECTED_REVIEW_PATH = ROOT / "benchmarks" / "product-optimization-source-review-v1.json"
DEFAULT_REVIEW_PATH = _EXPECTED_REVIEW_PATH
CAPTURE_ROOT = ROOT / "outputs" / "product-optimization-captures"

_EVIDENCE_POLICY = {
    "evidence_type": "first-party-product-documentation",
    "permitted_use": "bounded-factual-product-behavior-and-explicit-caveats",
    "prohibited_inference": (
        "independent-performance-reliability-cost-universal-winner-or-workload-threshold"
    ),
}
_CAPTURE_PLAN_IDENTITIES = {
    "product-optimization-official-intake-v2": (
        "94436e59a1ed4f62d2efa35774566ab6a7699cd737cc4eca3d153f05b1bb8fd0",
        "9f794b80d9b2d89ca473120a9264e3fc8dec9827f7a0ff21969f9a4dd11bff38",
    ),
    PLAN_ID: (PLAN_BYTES_SHA256, CANONICAL_PLAN_SHA256),
}
_PUBLISHERS = {
    "sqlite": "SQLite Project",
    "postgresql": "PostgreSQL Global Development Group",
    "fastapi": "FastAPI",
    "celery": "Celery Project",
    "redis": "Redis",
    "memcached": "Memcached",
}
_SCOPE_NOTES = {
    "p01-sqlite-appropriate-uses": "qualitative-use-case-guidance",
    "p01-sqlite-wal": "same-host-wal-boundary",
    "p01-sqlite-backup": "api-specific-backup-semantics",
    "p01-sqlite-fts5": "feature-documentation-not-workload-benchmark",
    "p01-postgresql-concurrency-introduction": "mechanism-overview-not-workload-benchmark",
    "p01-postgresql-backup": "chapter-overview-only",
    "p01-postgresql-text-search-introduction": "feature-mechanics-not-workload-benchmark",
    "p04-fastapi-background-tasks": "same-process-caveat-no-durability-guarantee",
    "p04-celery-introduction": "architecture-overview-no-delivery-guarantee",
    "p04-celery-task-semantics": "semantics-require-configuration-and-idempotency",
    "p08-redis-data-types": "feature-catalog-no-workload-fit",
    "p08-redis-persistence": "configuration-tradeoffs-no-durability-sla",
    "p08-redis-eviction": "policy-mechanics-no-hit-rate-claim",
    "p08-memcached-overview": "product-overview-no-durability-guarantee",
    "p08-memcached-faq": "faq-includes-warm-restart-caveat",
}
_EXCLUSIONS = {
    "36f16e5f2639ad33a040f627cdf681dfab2c32fcbbc2ebcdf8e694bd69c93d46": (
        "p01-postgresql-concurrency", "superseded-by-substantive-v3-page"
    ),
    "380a92342a66972b094880436c8089afcf798c97a6cc8a42609c7e331e73ca8e": (
        "p01-postgresql-text-search", "superseded-by-substantive-v3-page"
    ),
}
_TOP_KEYS = {
    "schema_version", "review_id", "status", "review_date", "reviewer_mode",
    "plan", "evidence_policy", "canonical_review_sha256", "approved_sources",
    "excluded_candidates",
}
_PLAN_KEYS = {"plan_id", "byte_sha256", "canonical_sha256"}
_SOURCE_KEYS = {"target_id", "receipt_sha256", "publisher", "approved_topics", "scope_note"}
_EXCLUDED_KEYS = {"target_id", "receipt_sha256", "reason"}
_RECEIPT_KEYS = {
    "schema_version", "status", "plan_id", "plan_byte_sha256",
    "plan_canonical_sha256", "development_fixture_id", "target_id",
    "parent_catalog_key", "case_ids", "evidence_topics",
    "locator_label_unverified", "start_url", "final_url", "http_status",
    "content_type", "captured_at", "raw_bytes", "raw_sha256", "extractor_id",
    "text_bytes", "text_sha256",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SourceReviewError(ValueError):
    """Body-free explanation of a rejected source review or capture."""


@dataclass(frozen=True, slots=True)
class ApprovedDevelopmentSource:
    target_id: str
    parent_catalog_key: str
    case_ids: tuple[str, ...]
    approved_topics: tuple[str, ...]
    url: str
    publisher: str
    scope_note: str
    receipt_sha256: str
    raw_sha256: str
    text_sha256: str
    captured_at: str
    content: str = field(repr=False)
    text_bytes: int


@dataclass(frozen=True, slots=True)
class ApprovedSourceReview:
    review_id: str
    canonical_review_sha256: str
    byte_sha256: str
    plan_id: str
    sources: tuple[ApprovedDevelopmentSource, ...]
    total_text_bytes: int


def _fail(message: str) -> "Any":
    raise SourceReviewError(message)


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _fail(f"{label} shape changed")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON contains duplicate object keys")
        result[key] = value
    return result


def _canonical_sha(payload: dict[str, Any]) -> str:
    identity = dict(payload)
    identity.pop("canonical_review_sha256", None)
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_redirected(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x0400
    ) or bool(hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _read_regular(path: Path, maximum: int, label: str) -> bytes:
    if _is_redirected(path):
        _fail(f"{label} is redirected")
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size <= 0:
            _fail(f"{label} is not a private regular file")
        if before.st_size > maximum:
            _fail(f"{label} exceeds its byte limit")
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SourceReviewError(f"{label} could not be read") from exc
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink)
    after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink)
    if before_id != after_id or len(payload) != after.st_size:
        _fail(f"{label} changed while being read")
    return payload


def _capture_receipts(root: Path) -> dict[str, Path]:
    try:
        if not root.is_dir() or _is_redirected(root):
            _fail("capture root is unavailable or redirected")
        directories = [
            item
            for item in root.iterdir()
            if item.is_dir() and not item.name.startswith(".pending-")
        ]
    except SourceReviewError:
        raise
    except OSError:
        raise SourceReviewError("capture root could not be scanned") from None
    if len(directories) > MAX_CAPTURE_CANDIDATES:
        _fail("capture root exceeds the candidate-count limit")
    result: dict[str, Path] = {}
    for directory in directories:
        if _is_redirected(directory):
            _fail("capture candidate is redirected")
        receipt_path = directory / "receipt.json"
        if not receipt_path.exists():
            continue
        receipt_bytes = _read_regular(receipt_path, MAX_RECEIPT_BYTES, "capture receipt")
        digest = hashlib.sha256(receipt_bytes).hexdigest()
        if digest in result:
            _fail("capture receipt SHA is duplicated")
        result[digest] = directory
    return result


def _parse_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except SourceReviewError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceReviewError(f"{label} is not strict UTF-8 JSON") from exc


def _validate_receipt(
    directory: Path,
    receipt_sha256: str,
    target: Any,
) -> tuple[dict[str, Any], str]:
    receipt_bytes = _read_regular(directory / "receipt.json", MAX_RECEIPT_BYTES, "capture receipt")
    if hashlib.sha256(receipt_bytes).hexdigest() != receipt_sha256:
        _fail("capture receipt SHA changed")
    receipt = _exact(_parse_json(receipt_bytes, "capture receipt"), _RECEIPT_KEYS, "capture receipt")
    plan_identity = _CAPTURE_PLAN_IDENTITIES.get(receipt.get("plan_id"))
    if plan_identity is None or (
        receipt.get("plan_byte_sha256"), receipt.get("plan_canonical_sha256")
    ) != plan_identity:
        _fail("capture receipt plan identity is not approved")
    if (
        receipt.get("schema_version") != 2
        or receipt.get("status") != "candidate_unapproved"
        or receipt.get("development_fixture_id") != FIXTURE_ID
        or receipt.get("target_id") != target.target_id
        or receipt.get("parent_catalog_key") != target.parent_catalog_key
        or receipt.get("case_ids") != list(target.case_ids)
        or receipt.get("evidence_topics") != list(target.evidence_topics)
        or receipt.get("start_url") != target.url
        or receipt.get("final_url") != target.url
        or receipt.get("http_status") != 200
        or receipt.get("content_type") not in {"text/html", "application/xhtml+xml"}
        or receipt.get("extractor_id") != "stdlib-html-text-v1"
    ):
        _fail("capture receipt does not match the approved target")
    raw = _read_regular(directory / "response.html", MAX_CAPTURE_BODY_BYTES, "capture response")
    text_bytes = _read_regular(directory / "body.txt", MAX_CAPTURE_BODY_BYTES, "capture text")
    if (
        receipt.get("raw_bytes") != len(raw)
        or receipt.get("raw_sha256") != hashlib.sha256(raw).hexdigest()
        or receipt.get("text_bytes") != len(text_bytes)
        or receipt.get("text_sha256") != hashlib.sha256(text_bytes).hexdigest()
    ):
        _fail("capture body hashes do not match the receipt")
    try:
        text = text_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail("capture text is not strict UTF-8")
    if not text.strip() or _has_prohibited_benchmark_marker(text):
        _fail("capture text is empty or contains a prohibited benchmark marker")
    return receipt, text


def _parse_review_bytes(
    raw: bytes,
    capture_root: Path,
    *,
    plan: OfficialIntakePlan | None = None,
) -> ApprovedSourceReview:
    if len(raw) > MAX_REVIEW_BYTES:
        _fail("source review exceeds its byte limit")
    payload = _exact(_parse_json(raw, "source review"), _TOP_KEYS, "source review")
    if (
        payload.get("schema_version") != REVIEW_SCHEMA_VERSION
        or payload.get("review_id") != REVIEW_ID
        or payload.get("status") != REVIEW_STATUS
        or payload.get("review_date") != REVIEW_DATE
        or payload.get("reviewer_mode") != REVIEWER_MODE
        or payload.get("evidence_policy") != _EVIDENCE_POLICY
        or payload.get("canonical_review_sha256") != CANONICAL_REVIEW_SHA256
        or _canonical_sha(payload) != CANONICAL_REVIEW_SHA256
    ):
        _fail("source review identity or policy changed")
    plan = plan or load_official_intake_plan()
    plan_binding = _exact(payload.get("plan"), _PLAN_KEYS, "source review plan")
    if plan_binding != {
        "plan_id": plan.plan_id,
        "byte_sha256": plan.byte_sha256,
        "canonical_sha256": plan.canonical_plan_sha256,
    }:
        _fail("source review plan binding changed")
    targets = {target.target_id: target for target in plan.targets}
    raw_sources = payload.get("approved_sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != len(targets):
        _fail("approved source count does not match the current plan")
    receipts = _capture_receipts(capture_root)
    approved: list[ApprovedDevelopmentSource] = []
    seen_targets: set[str] = set()
    seen_receipts: set[str] = set()
    for index, item in enumerate(raw_sources):
        source = _exact(item, _SOURCE_KEYS, f"approved source {index}")
        target_id = source.get("target_id")
        target = targets.get(target_id)
        receipt_sha = source.get("receipt_sha256")
        if target is None or target_id in seen_targets or not isinstance(receipt_sha, str) or not _SHA256.fullmatch(receipt_sha):
            _fail("approved source target or receipt identity is invalid")
        if receipt_sha in seen_receipts or receipt_sha not in receipts:
            _fail("approved source receipt is missing or duplicated")
        seen_targets.add(target_id)
        seen_receipts.add(receipt_sha)
        if (
            source.get("publisher") != _PUBLISHERS[target.parent_catalog_key]
            or source.get("approved_topics") != list(target.evidence_topics)
            or source.get("scope_note") != _SCOPE_NOTES.get(target_id)
        ):
            _fail("approved source scope changed")
        receipt, text = _validate_receipt(receipts[receipt_sha], receipt_sha, target)
        approved.append(ApprovedDevelopmentSource(
            target_id=target_id,
            parent_catalog_key=target.parent_catalog_key,
            case_ids=target.case_ids,
            approved_topics=target.evidence_topics,
            url=target.url,
            publisher=source["publisher"],
            scope_note=source["scope_note"],
            receipt_sha256=receipt_sha,
            raw_sha256=receipt["raw_sha256"],
            text_sha256=receipt["text_sha256"],
            captured_at=receipt["captured_at"],
            content=text,
            text_bytes=receipt["text_bytes"],
        ))
    if seen_targets != set(targets):
        _fail("approved sources do not cover the current plan")
    excluded = payload.get("excluded_candidates")
    if not isinstance(excluded, list):
        _fail("excluded candidates must be an array")
    actual_exclusions: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(excluded):
        entry = _exact(item, _EXCLUDED_KEYS, f"excluded candidate {index}")
        digest = entry.get("receipt_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest) or digest in actual_exclusions:
            _fail("excluded candidate identity is invalid")
        actual_exclusions[digest] = (entry.get("target_id"), entry.get("reason"))
    if actual_exclusions != _EXCLUSIONS or not set(actual_exclusions).issubset(receipts):
        _fail("excluded candidate set changed or is unavailable")
    approved.sort(key=lambda source: source.target_id)
    return ApprovedSourceReview(
        review_id=REVIEW_ID,
        canonical_review_sha256=CANONICAL_REVIEW_SHA256,
        byte_sha256=hashlib.sha256(raw).hexdigest(),
        plan_id=plan.plan_id,
        sources=tuple(approved),
        total_text_bytes=sum(source.text_bytes for source in approved),
    )


def _fixed_file(path: Path, expected: Path, maximum: int, label: str) -> Path:
    if path != expected or not path.is_absolute():
        _fail(f"{label} path is not approved")
    current = Path(path.anchor)
    for component in path.parts:
        if component == path.anchor:
            continue
        current /= component
        if _is_redirected(current):
            _fail(f"{label} path is redirected")
    try:
        metadata = path.stat()
    except OSError:
        raise SourceReviewError(f"{label} is unavailable or exceeds its byte limit") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > maximum:
        _fail(f"{label} is unavailable or exceeds its byte limit")
    return path


def load_approved_source_review() -> ApprovedSourceReview:
    """Load the one tracked review and its exact ignored capture bodies."""

    path = _fixed_file(DEFAULT_REVIEW_PATH, _EXPECTED_REVIEW_PATH, MAX_REVIEW_BYTES, "source review")
    raw = _read_regular(path, MAX_REVIEW_BYTES, "source review")
    if hashlib.sha256(raw).hexdigest() != REVIEW_BYTES_SHA256:
        _fail("source review byte SHA changed")
    if CAPTURE_ROOT != ROOT / "outputs" / "product-optimization-captures":
        _fail("capture root path is not approved")
    return _parse_review_bytes(raw, CAPTURE_ROOT)


__all__ = [
    "ApprovedDevelopmentSource",
    "ApprovedSourceReview",
    "SourceReviewError",
    "load_approved_source_review",
]
