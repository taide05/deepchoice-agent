"""Load the frozen, offline-only official source intake plan.

The plan is an identity manifest, not a downloader.  It deliberately contains
only the deduplicated URLs already present in ``TECH_DOCS`` and never opens a
benchmark, snapshot, learned-docs, or knowledge-base path.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from deepchoice.utils.official_catalog import TECH_DOCS


ROOT = Path(__file__).resolve().parent.parent
_EXPECTED_PLAN_PATH = ROOT / "benchmarks" / "product-optimization-official-intake-v1.json"
DEFAULT_PLAN_PATH = _EXPECTED_PLAN_PATH

PLAN_ID = "product-optimization-official-intake-v1"
PLAN_SCHEMA_VERSION = 1
PLAN_FREEZE_DATE = "2026-09-23"
MAX_PLAN_BYTES = 256 * 1024
# Locked after the plan was frozen.  This is deliberately a byte hash rather
# than a hash of a payload containing its own digest.
PLAN_BYTES_SHA256 = "6ee9a9fddf9367aa507bd262014502fa1e135184ade921b5b2adc13d506964c0"
CANONICAL_PLAN_SHA256 = "0d0dfc114923e62e231f4ab1472d713165d48408929036883a019ab5b34c88b6"
CATALOG_GIT_OBJECT = "2dcbcdcc539b3d2de14710ab588856b44c5fd2fb"
CATALOG_PAYLOAD_SHA256 = "5bd5f76bd4a453ed1bf5878673db2bab9b5b383d6050290a86a7c6ec562b8544"
EXPECTED_CATALOG_ENTRY_COUNT = 96
EXPECTED_UNIQUE_URL_COUNT = 93

_TOP_LEVEL_KEYS = {
    "schema_version",
    "plan_id",
    "status",
    "freeze_date",
    "purpose",
    "catalog",
    "canonical_plan_sha256",
    "entries",
}
_CATALOG_KEYS = {
    "module",
    "git_object",
    "git_object_algorithm",
    "catalog_payload_sha256",
    "entry_count",
    "unique_url_count",
}
_ENTRY_KEYS = {"catalog_key", "url", "title", "catalog_label_unverified"}


class OfficialIntakePlanError(ValueError):
    """Raised when the frozen official intake plan is missing or altered."""


@dataclass(frozen=True)
class OfficialIntakeEntry:
    catalog_key: str
    url: str
    title: str
    catalog_label_unverified: str


@dataclass(frozen=True)
class OfficialIntakePlan:
    plan_id: str
    freeze_date: str
    catalog_git_object: str
    canonical_plan_sha256: str
    byte_sha256: str
    entries: tuple[OfficialIntakeEntry, ...]


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


def _catalog_snapshot() -> tuple[dict[str, str], ...]:
    """Return first-key-wins URL identities from the current catalog."""

    entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for key, doc in TECH_DOCS.items():
        if not isinstance(key, str) or not isinstance(doc, dict):
            raise OfficialIntakePlanError("TECH_DOCS entry shape changed")
        url = doc.get("url")
        title = doc.get("title")
        if not isinstance(url, str) or not isinstance(title, str):
            raise OfficialIntakePlanError("TECH_DOCS metadata changed")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        if " — " not in title:
            raise OfficialIntakePlanError("TECH_DOCS catalog display label is missing")
        # The catalog has no independently audited publisher field.  Preserve
        # this display suffix only as an unverified locator label.
        catalog_label_unverified = title.split(" — ", 1)[1]
        entries.append(
            {
                "catalog_key": key,
                "url": url,
                "title": title,
                "catalog_label_unverified": catalog_label_unverified,
            }
        )
    return tuple(entries)


def _validate_url_identity(url: Any) -> None:
    if not isinstance(url, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise OfficialIntakePlanError("entry URL is not a safe HTTPS identity")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise OfficialIntakePlanError("entry URL is not a safe HTTPS identity")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or "\\" in url
    ):
        raise OfficialIntakePlanError("entry URL is not a safe HTTPS identity")
    hostname = parsed.hostname.casefold()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise OfficialIntakePlanError("entry URL is not a safe HTTPS identity")
    if address is None and (
        hostname == "localhost" or hostname.endswith(".local") or "." not in hostname
    ):
        raise OfficialIntakePlanError("entry URL is not a safe HTTPS identity")


def _parse_plan_payload(payload: Any, byte_sha256: str) -> OfficialIntakePlan:
    payload = _require_mapping(payload, "plan")
    _require_exact_keys(payload, _TOP_LEVEL_KEYS, "plan")
    if payload["schema_version"] != PLAN_SCHEMA_VERSION:
        raise OfficialIntakePlanError("unsupported plan schema version")
    if payload["plan_id"] != PLAN_ID or payload["status"] != "frozen":
        raise OfficialIntakePlanError("plan identity or status changed")
    if payload["freeze_date"] != PLAN_FREEZE_DATE:
        raise OfficialIntakePlanError("freeze_date changed")
    if payload["canonical_plan_sha256"] != CANONICAL_PLAN_SHA256:
        raise OfficialIntakePlanError("canonical plan SHA changed")
    if _canonical_plan_sha256(payload) != CANONICAL_PLAN_SHA256:
        raise OfficialIntakePlanError("canonical plan contents changed")

    catalog = _require_mapping(payload["catalog"], "catalog")
    _require_exact_keys(catalog, _CATALOG_KEYS, "catalog")
    expected_catalog = {
        "module": "src/deepchoice/utils/official_catalog.py",
        "git_object": CATALOG_GIT_OBJECT,
        "git_object_algorithm": "git-blob-sha1",
        "catalog_payload_sha256": CATALOG_PAYLOAD_SHA256,
        "entry_count": EXPECTED_CATALOG_ENTRY_COUNT,
        "unique_url_count": EXPECTED_UNIQUE_URL_COUNT,
    }
    if catalog != expected_catalog:
        raise OfficialIntakePlanError("catalog identity changed")

    current_payload_sha = hashlib.sha256(
        json.dumps(TECH_DOCS, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if current_payload_sha != CATALOG_PAYLOAD_SHA256:
        raise OfficialIntakePlanError("TECH_DOCS catalog payload drifted")
    snapshot = _catalog_snapshot()
    if len(TECH_DOCS) != EXPECTED_CATALOG_ENTRY_COUNT or len(snapshot) != EXPECTED_UNIQUE_URL_COUNT:
        raise OfficialIntakePlanError("TECH_DOCS catalog cardinality changed")

    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) != EXPECTED_UNIQUE_URL_COUNT:
        raise OfficialIntakePlanError("plan entries must contain exactly 93 URLs")
    parsed: list[OfficialIntakeEntry] = []
    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    for index, raw_entry in enumerate(raw_entries):
        entry = _require_mapping(raw_entry, f"entry {index}")
        _require_exact_keys(entry, _ENTRY_KEYS, f"entry {index}")
        _validate_url_identity(entry["url"])
        key = entry["catalog_key"]
        url = entry["url"]
        if key in seen_keys:
            raise OfficialIntakePlanError(f"duplicate catalog key: {key}")
        if url in seen_urls:
            raise OfficialIntakePlanError(f"duplicate exact URL: {url}")
        seen_keys.add(key)
        seen_urls.add(url)
        expected = snapshot[index]
        if entry != expected:
            raise OfficialIntakePlanError(
                f"entry {index} does not exactly match the TECH_DOCS snapshot"
            )
        parsed.append(
            OfficialIntakeEntry(
                catalog_key=entry["catalog_key"],
                url=entry["url"],
                title=entry["title"],
                catalog_label_unverified=entry["catalog_label_unverified"],
            )
        )
    return OfficialIntakePlan(
        plan_id=payload["plan_id"],
        freeze_date=payload["freeze_date"],
        catalog_git_object=catalog["git_object"],
        canonical_plan_sha256=payload["canonical_plan_sha256"],
        byte_sha256=byte_sha256,
        entries=tuple(parsed),
    )


def _parse_plan_bytes(raw: bytes) -> OfficialIntakePlan:
    if len(raw) > MAX_PLAN_BYTES:
        raise OfficialIntakePlanError(f"official intake plan exceeds {MAX_PLAN_BYTES} bytes")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except OfficialIntakePlanError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OfficialIntakePlanError("invalid official intake plan JSON") from exc
    return _parse_plan_payload(payload, hashlib.sha256(raw).hexdigest())


def _is_reparse_or_symlink(metadata: Any) -> bool:
    reparse_point = 0x0400
    return bool(stat.S_ISLNK(metadata.st_mode)) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_point
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
            raise OfficialIntakePlanError(f"official intake plan path unavailable: {current}") from exc
        if _is_reparse_or_symlink(metadata):
            raise OfficialIntakePlanError("official intake plan path contains a symlink or reparse point")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OfficialIntakePlanError("official intake plan is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise OfficialIntakePlanError("official intake plan is not a regular file")
    if metadata.st_size > MAX_PLAN_BYTES:
        raise OfficialIntakePlanError(f"official intake plan exceeds {MAX_PLAN_BYTES} bytes")
    return path


def load_official_intake_plan() -> OfficialIntakePlan:
    """Load the one approved plan; no caller-supplied path is accepted."""

    path = _validate_fixed_plan_path()
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_PLAN_BYTES + 1)
    except OSError as exc:
        raise OfficialIntakePlanError("cannot read official intake plan") from exc
    if len(raw) > MAX_PLAN_BYTES:
        raise OfficialIntakePlanError(f"official intake plan exceeds {MAX_PLAN_BYTES} bytes")
    byte_sha256 = hashlib.sha256(raw).hexdigest()
    if byte_sha256 != PLAN_BYTES_SHA256:
        raise OfficialIntakePlanError("official intake plan byte SHA changed")
    return _parse_plan_bytes(raw)


__all__ = [
    "OfficialIntakeEntry",
    "OfficialIntakePlan",
    "OfficialIntakePlanError",
    "PLAN_BYTES_SHA256",
    "_parse_plan_bytes",
    "load_official_intake_plan",
]
