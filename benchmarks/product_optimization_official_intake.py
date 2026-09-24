"""Load the frozen development-only official deep-link intake plan.

Version 2 preserves the historical 93-URL v1 locator plan by identity and adds
only exact P01/P04/P08 document locators.  A target is still unapproved: this
module performs no network access and makes no claim about captured content.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from benchmarks.product_optimization_dev_requests import (
    EXPECTED_CASE_IDS,
    FIXTURE_BYTES_SHA256,
    FIXTURE_ID,
)
from deepchoice.utils.official_catalog import TECH_DOCS


ROOT = Path(__file__).resolve().parent.parent
_EXPECTED_PLAN_PATH = ROOT / "benchmarks" / "product-optimization-official-intake-v2.json"
DEFAULT_PLAN_PATH = _EXPECTED_PLAN_PATH

PLAN_ID = "product-optimization-official-intake-v2"
PLAN_SCHEMA_VERSION = 2
PLAN_FREEZE_DATE = "2026-09-24"
PLAN_STATUS = "frozen_locator_candidates"
PLAN_PURPOSE = (
    "Development-only exact official-document locators for P01, P04, and P08; "
    "locator inclusion is not source approval or claim verification."
)
MAX_PLAN_BYTES = 256 * 1024
PLAN_BYTES_SHA256 = "94436e59a1ed4f62d2efa35774566ab6a7699cd737cc4eca3d153f05b1bb8fd0"
CANONICAL_PLAN_SHA256 = "9f794b80d9b2d89ca473120a9264e3fc8dec9827f7a0ff21969f9a4dd11bff38"
EXPECTED_TARGET_COUNT = 15

PARENT_PLAN_ID = "product-optimization-official-intake-v1"
PARENT_PLAN_BYTES_SHA256 = "6ee9a9fddf9367aa507bd262014502fa1e135184ade921b5b2adc13d506964c0"
PARENT_CANONICAL_PLAN_SHA256 = "0d0dfc114923e62e231f4ab1472d713165d48408929036883a019ab5b34c88b6"
CATALOG_GIT_OBJECT = "2dcbcdcc539b3d2de14710ab588856b44c5fd2fb"
CATALOG_PAYLOAD_SHA256 = "5bd5f76bd4a453ed1bf5878673db2bab9b5b383d6050290a86a7c6ec562b8544"
EXPECTED_CATALOG_ENTRY_COUNT = 96

_TOP_LEVEL_KEYS = {
    "schema_version",
    "plan_id",
    "status",
    "freeze_date",
    "purpose",
    "parent_plan",
    "development_fixture",
    "canonical_plan_sha256",
    "targets",
}
_PARENT_PLAN_KEYS = {
    "plan_id",
    "byte_sha256",
    "canonical_plan_sha256",
    "catalog_git_object",
}
_DEVELOPMENT_FIXTURE_KEYS = {"fixture_id", "byte_sha256", "case_ids"}
_TARGET_KEYS = {
    "target_id",
    "parent_catalog_key",
    "case_ids",
    "evidence_topics",
    "url",
    "locator_label_unverified",
}
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
_SAFE_TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_CASE_PARENT_KEYS = {
    "P01": frozenset({"sqlite", "postgresql"}),
    "P04": frozenset({"fastapi", "celery"}),
    "P08": frozenset({"redis", "memcached"}),
}
_CASE_TOPIC_ALLOWLIST = {
    "P01": frozenset(
        {
            "backup",
            "full-text-search",
            "migration-triggers",
            "operational-complexity",
            "write-concurrency",
        }
    ),
    "P04": frozenset(
        {
            "delivery-semantics",
            "execution-boundary",
            "operational-components",
            "recovery-semantics",
        }
    ),
    "P08": frozenset(
        {
            "data-model",
            "ephemeral-boundary",
            "eviction",
            "persistence",
            "unknown-decision-constraints",
        }
    ),
}
_CASE_REQUIRED_TOPICS = _CASE_TOPIC_ALLOWLIST


class OfficialIntakePlanError(ValueError):
    """Raised when the frozen official intake plan is missing or altered."""


@dataclass(frozen=True)
class OfficialIntakeTarget:
    target_id: str
    parent_catalog_key: str
    case_ids: tuple[str, ...]
    evidence_topics: tuple[str, ...]
    url: str
    locator_label_unverified: str


@dataclass(frozen=True)
class OfficialIntakePlan:
    plan_id: str
    freeze_date: str
    parent_plan_id: str
    development_fixture_id: str
    canonical_plan_sha256: str
    byte_sha256: str
    targets: tuple[OfficialIntakeTarget, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OfficialIntakePlanError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OfficialIntakePlanError(f"{label} must be an object")
    return value


def _require_exact_keys(mapping: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise OfficialIntakePlanError(
            f"{label} keys changed; missing={missing}, extra={extra}"
        )


def _canonical_plan_sha256(payload: dict[str, Any]) -> str:
    identity = dict(payload)
    identity.pop("canonical_plan_sha256", None)
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_url_identity(url: Any) -> str:
    if (
        not isinstance(url, str)
        or not url.isascii()
        or "\\" in url
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in url)
    ):
        raise OfficialIntakePlanError("target URL is not a safe HTTPS identity")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise OfficialIntakePlanError("target URL is not a safe HTTPS identity") from None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.path.startswith("//")
        or "/./" in parsed.path
        or "/../" in parsed.path
        or parsed.path.endswith(("/.", "/.."))
    ):
        raise OfficialIntakePlanError("target URL is not a safe HTTPS identity")
    hostname = parsed.hostname.casefold()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise OfficialIntakePlanError("target URL is not a safe HTTPS identity")
    if address is None and (
        hostname == "localhost" or hostname.endswith(".local") or "." not in hostname
    ):
        raise OfficialIntakePlanError("target URL is not a safe HTTPS identity")
    return hostname


def _catalog_identity() -> dict[str, dict[str, str]]:
    current_payload_sha = hashlib.sha256(
        json.dumps(
            TECH_DOCS,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if current_payload_sha != CATALOG_PAYLOAD_SHA256:
        raise OfficialIntakePlanError("TECH_DOCS catalog payload drifted")
    if len(TECH_DOCS) != EXPECTED_CATALOG_ENTRY_COUNT:
        raise OfficialIntakePlanError("TECH_DOCS catalog cardinality changed")
    result: dict[str, dict[str, str]] = {}
    for key, value in TECH_DOCS.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise OfficialIntakePlanError("TECH_DOCS entry shape changed")
        url = value.get("url")
        title = value.get("title")
        if not isinstance(url, str) or not isinstance(title, str):
            raise OfficialIntakePlanError("TECH_DOCS metadata changed")
        result[key] = {"url": url, "title": title}
    return result


def _bounded_string(value: Any, label: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise OfficialIntakePlanError(f"{label} is invalid")
    return value


def _parse_plan_payload(payload: Any, byte_sha256: str) -> OfficialIntakePlan:
    payload = _require_mapping(payload, "plan")
    _require_exact_keys(payload, _TOP_LEVEL_KEYS, "plan")
    if payload["schema_version"] != PLAN_SCHEMA_VERSION:
        raise OfficialIntakePlanError("unsupported plan schema version")
    if payload["plan_id"] != PLAN_ID or payload["status"] != PLAN_STATUS:
        raise OfficialIntakePlanError("plan identity or status changed")
    if payload["freeze_date"] != PLAN_FREEZE_DATE or payload["purpose"] != PLAN_PURPOSE:
        raise OfficialIntakePlanError("plan metadata changed")
    if payload["canonical_plan_sha256"] != CANONICAL_PLAN_SHA256:
        raise OfficialIntakePlanError("canonical plan SHA changed")
    if _canonical_plan_sha256(payload) != CANONICAL_PLAN_SHA256:
        raise OfficialIntakePlanError("canonical plan contents changed")

    parent_plan = _require_mapping(payload["parent_plan"], "parent_plan")
    _require_exact_keys(parent_plan, _PARENT_PLAN_KEYS, "parent_plan")
    if parent_plan != {
        "plan_id": PARENT_PLAN_ID,
        "byte_sha256": PARENT_PLAN_BYTES_SHA256,
        "canonical_plan_sha256": PARENT_CANONICAL_PLAN_SHA256,
        "catalog_git_object": CATALOG_GIT_OBJECT,
    }:
        raise OfficialIntakePlanError("parent v1 plan identity changed")

    fixture = _require_mapping(payload["development_fixture"], "development_fixture")
    _require_exact_keys(fixture, _DEVELOPMENT_FIXTURE_KEYS, "development_fixture")
    if fixture != {
        "fixture_id": FIXTURE_ID,
        "byte_sha256": FIXTURE_BYTES_SHA256,
        "case_ids": list(EXPECTED_CASE_IDS),
    }:
        raise OfficialIntakePlanError("development fixture identity changed")

    catalog = _catalog_identity()
    raw_targets = payload["targets"]
    if not isinstance(raw_targets, list) or len(raw_targets) != EXPECTED_TARGET_COUNT:
        raise OfficialIntakePlanError(
            f"plan targets must contain exactly {EXPECTED_TARGET_COUNT} locators"
        )

    parsed: list[OfficialIntakeTarget] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    covered_topics = {case_id: set() for case_id in EXPECTED_CASE_IDS}
    for index, raw_target in enumerate(raw_targets):
        target = _require_mapping(raw_target, f"target {index}")
        _require_exact_keys(target, _TARGET_KEYS, f"target {index}")
        target_id = _bounded_string(target["target_id"], f"target {index} id", maximum=96)
        if not _SAFE_ID.fullmatch(target_id) or target_id in seen_ids:
            raise OfficialIntakePlanError("target ID is invalid or duplicated")
        seen_ids.add(target_id)

        parent_key = _bounded_string(
            target["parent_catalog_key"], f"target {target_id} parent", maximum=64
        )
        case_ids = target["case_ids"]
        if (
            not isinstance(case_ids, list)
            or len(case_ids) != 1
            or case_ids[0] not in EXPECTED_CASE_IDS
            or parent_key not in _CASE_PARENT_KEYS[case_ids[0]]
            or not target_id.startswith(case_ids[0].casefold() + "-")
        ):
            raise OfficialIntakePlanError(
                f"target {target_id} case or parent binding is invalid"
            )
        case_id = case_ids[0]
        if parent_key not in catalog:
            raise OfficialIntakePlanError(f"target {target_id} parent is absent from catalog")

        topics = target["evidence_topics"]
        if (
            not isinstance(topics, list)
            or not topics
            or len(topics) != len(set(topics))
            or topics != sorted(topics)
            or any(
                not isinstance(topic, str)
                or not _SAFE_TOPIC.fullmatch(topic)
                or topic not in _CASE_TOPIC_ALLOWLIST[case_id]
                for topic in topics
            )
        ):
            raise OfficialIntakePlanError(f"target {target_id} evidence topics are invalid")

        url = target["url"]
        hostname = _validate_url_identity(url)
        if url in seen_urls:
            raise OfficialIntakePlanError(f"duplicate exact target URL: {url}")
        seen_urls.add(url)
        parent_hostname = urlsplit(catalog[parent_key]["url"]).hostname
        if parent_hostname is None:
            raise OfficialIntakePlanError("catalog parent URL has no hostname")
        parent_hostname = parent_hostname.casefold()
        if hostname != parent_hostname and not hostname.endswith("." + parent_hostname):
            raise OfficialIntakePlanError(
                f"target {target_id} leaves its parent catalog hostname"
            )

        label = _bounded_string(
            target["locator_label_unverified"],
            f"target {target_id} locator label",
            maximum=256,
        )
        covered_topics[case_id].update(topics)
        parsed.append(
            OfficialIntakeTarget(
                target_id=target_id,
                parent_catalog_key=parent_key,
                case_ids=(case_id,),
                evidence_topics=tuple(topics),
                url=url,
                locator_label_unverified=label,
            )
        )

    for case_id, required in _CASE_REQUIRED_TOPICS.items():
        if covered_topics[case_id] != set(required):
            raise OfficialIntakePlanError(f"{case_id} evidence topic coverage changed")

    return OfficialIntakePlan(
        plan_id=payload["plan_id"],
        freeze_date=payload["freeze_date"],
        parent_plan_id=parent_plan["plan_id"],
        development_fixture_id=fixture["fixture_id"],
        canonical_plan_sha256=payload["canonical_plan_sha256"],
        byte_sha256=byte_sha256,
        targets=tuple(parsed),
    )


def _parse_plan_bytes(raw: bytes) -> OfficialIntakePlan:
    if len(raw) > MAX_PLAN_BYTES:
        raise OfficialIntakePlanError(
            f"official intake plan exceeds {MAX_PLAN_BYTES} bytes"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except OfficialIntakePlanError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OfficialIntakePlanError("invalid official intake plan JSON") from exc
    return _parse_plan_payload(payload, hashlib.sha256(raw).hexdigest())


def _is_reparse_or_symlink(metadata: Any) -> bool:
    return bool(stat.S_ISLNK(metadata.st_mode)) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x0400
    )


def _validate_fixed_plan_path() -> Path:
    path = DEFAULT_PLAN_PATH
    if path != _EXPECTED_PLAN_PATH or not path.is_absolute():
        raise OfficialIntakePlanError("official intake plan path is not approved")
    current = Path(path.anchor)
    for component in path.parts:
        if component == path.anchor:
            continue
        current /= component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise OfficialIntakePlanError(
                f"official intake plan path unavailable: {current}"
            ) from exc
        if _is_reparse_or_symlink(metadata):
            raise OfficialIntakePlanError(
                "official intake plan path contains a symlink or reparse point"
            )
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OfficialIntakePlanError("official intake plan is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise OfficialIntakePlanError("official intake plan is not a regular file")
    if metadata.st_size > MAX_PLAN_BYTES:
        raise OfficialIntakePlanError(
            f"official intake plan exceeds {MAX_PLAN_BYTES} bytes"
        )
    return path


def load_official_intake_plan() -> OfficialIntakePlan:
    """Load the one current approved locator plan; no caller path is accepted."""

    path = _validate_fixed_plan_path()
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_PLAN_BYTES + 1)
    except OSError as exc:
        raise OfficialIntakePlanError("cannot read official intake plan") from exc
    if len(raw) > MAX_PLAN_BYTES:
        raise OfficialIntakePlanError(
            f"official intake plan exceeds {MAX_PLAN_BYTES} bytes"
        )
    byte_sha256 = hashlib.sha256(raw).hexdigest()
    if byte_sha256 != PLAN_BYTES_SHA256:
        raise OfficialIntakePlanError("official intake plan byte SHA changed")
    return _parse_plan_bytes(raw)


__all__ = [
    "OfficialIntakePlan",
    "OfficialIntakePlanError",
    "OfficialIntakeTarget",
    "PLAN_BYTES_SHA256",
    "_parse_plan_bytes",
    "load_official_intake_plan",
]
