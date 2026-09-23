"""Offline admission for product-optimization knowledge-seed inputs.

This module validates source material before a later, separately authorized seed
builder consumes it.  It deliberately performs no network, model, embedding, or
Chroma work.  Source bodies are returned only in memory and are never included
in validation errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping
from types import MappingProxyType
from urllib.parse import urlsplit, urlunsplit


SCHEMA_VERSION = "product-optimization-seed-input-v1"
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_SOURCES = 256
MAX_MANIFEST_BYTES = 1024 * 1024
ADMISSION_POLICY_ID = "product-optimization-seed-admission"
ADMISSION_POLICY_VERSION = "1"
EXPECTED_BUILDER_IDENTITY = MappingProxyType(
    {"id": "deepchoice.product-optimization-seed-builder", "version": "1"}
)
EXPECTED_NORMALIZATION_IDENTITY = MappingProxyType({"id": "utf8-exact", "version": "1"})
EXPECTED_CHUNKING_IDENTITY = MappingProxyType({"id": "paragraph-window", "version": "2"})
EXPECTED_EMBEDDING_IDENTITY = MappingProxyType(
    {"model": "BAAI/bge-m3", "revision": "5617a9f61b028005a4858fdac845db406aefb181"}
)
EXPECTED_COLLECTION_IDENTITY = MappingProxyType({"name": "tech_kb", "version": "1"})
_EXPECTED_IDENTITIES = {
    "builder": EXPECTED_BUILDER_IDENTITY,
    "normalization": EXPECTED_NORMALIZATION_IDENTITY,
    "chunking": EXPECTED_CHUNKING_IDENTITY,
    "embedding": EXPECTED_EMBEDDING_IDENTITY,
    "collection": EXPECTED_COLLECTION_IDENTITY,
}

_TOP_LEVEL_KEYS = {
    "schema_version",
    "builder",
    "normalization",
    "chunking",
    "embedding",
    "collection",
    "sources",
}
_SOURCE_KEYS = {
    "stable_id",
    "path",
    "url",
    "source_kind",
    "publisher",
    "retrieved_at",
    "content_sha256",
    "encoding",
}
_IDENTITY_KEYS = {
    "builder": {"id", "version"},
    "normalization": {"id", "version"},
    "chunking": {"id", "version"},
    "embedding": {"model", "revision"},
    "collection": {"name", "version"},
}
_SOURCE_DIRS = {"official": "official", "paper": "papers"}
_DENIED_PATH_PARTS = {
    "blogs",
    "benchmarks",
    "outputs",
    "output",
    "chroma_db",
    ".git",
}
_STABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RETRIEVED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9a-fA-F]{2}")
_MARKER_PREFIX = r"^\s*(?:#{1,6}\s+)?(?:[-*+]\s+)?(?:\*\*|__|\*|_)?\s*"
_MARKER_SUFFIX = r"\s*(?:\*\*|__|\*|_)?\s*(?::|：|—|–|-|－)"
_PROHIBITED_SINGLE_MARKERS = tuple(
    re.compile(_MARKER_PREFIX + label + _MARKER_SUFFIX, re.IGNORECASE | re.MULTILINE)
    for label in (
        r"expected[ _-]?winner",
        r"benchmark[ _-]?case",
        r"ground[ _-]?truth",
        r"预期(?:获胜者|赢家)",
    )
)
_CATEGORY_MARKER = re.compile(
    _MARKER_PREFIX + r"category" + _MARKER_SUFFIX, re.IGNORECASE | re.MULTILINE
)
_ANALYSIS_MARKER = re.compile(
    _MARKER_PREFIX + r"analysis" + _MARKER_SUFFIX, re.IGNORECASE | re.MULTILINE
)
_BLOCKQUOTE_PREFIX = re.compile(r"^\s*(?:>\s*)+")
_MARKER_HTML_TAG = re.compile(
    r"</?(?:p|strong|b|em|i|code)(?:\s+[^<>]{0,512})?\s*/?>",
    re.IGNORECASE,
)
_MARKER_CODE_TICKS = re.compile(r"`{1,3}")


class SeedAdmissionError(ValueError):
    """A safe, body-free explanation of why seed admission failed."""


@dataclass(frozen=True, slots=True)
class ValidatedSeedSource:
    stable_id: str
    relative_path: str
    url: str
    source_kind: str
    publisher: str
    retrieved_at: str
    content_sha256: str
    encoding: str
    content: str = field(repr=False)
    byte_length: int


@dataclass(frozen=True, slots=True)
class ValidatedSeedManifest:
    schema_version: str
    admission_policy_id: str
    admission_policy_version: str
    max_file_bytes: int
    max_total_bytes: int
    max_sources: int
    manifest_sha256: str
    admission_identity_sha256: str
    source_hashes: tuple[tuple[str, str], ...]
    builder: tuple[tuple[str, str], ...]
    normalization: tuple[tuple[str, str], ...]
    chunking: tuple[tuple[str, str], ...]
    embedding: tuple[tuple[str, str], ...]
    collection: tuple[tuple[str, str], ...]
    records: tuple[ValidatedSeedSource, ...]
    total_bytes: int


def _fail(message: str) -> "Any":
    raise SeedAdmissionError(message)


def _require_exact_keys(value: Any, expected: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        _fail(f"{field} keys must be strings")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _fail(f"{field} has invalid keys (missing={missing}, extra={extra})")
    return value


def _require_bounded_string(value: Any, field: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        _fail(f"{field} must be a non-empty string of at most {max_length} characters")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        _fail(f"{field} contains whitespace or control characters at its boundary")
    return value


def _validate_identity(manifest: Mapping[str, Any], field: str) -> dict[str, str]:
    raw = _require_exact_keys(manifest[field], _IDENTITY_KEYS[field], field)
    identity: dict[str, str] = {}
    for key in sorted(raw):
        value = _require_bounded_string(raw[key], f"{field}.{key}")
        if not _IDENTITY_RE.fullmatch(value):
            _fail(f"{field}.{key} is not a stable identity")
        identity[key] = value
    expected = _EXPECTED_IDENTITIES.get(field)
    if expected is not None and identity != expected:
        _fail(f"{field} does not match the admission policy identity")
    return identity


def _canonical_https_url(value: Any, source_id: str) -> str:
    url = _require_bounded_string(value, f"source '{source_id}' url", max_length=2048)
    if not url.isascii() or "\\" in url:
        _fail(f"source '{source_id}' url is not canonical HTTPS")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        _fail(f"source '{source_id}' url is invalid")
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port is not None
    ):
        _fail(f"source '{source_id}' url is not canonical HTTPS")
    hostname = parts.hostname.lower()
    if parts.netloc != hostname:
        _fail(f"source '{source_id}' url is not canonical HTTPS")
    path = parts.path or "/"
    if path.startswith("//") or "/./" in path or "/../" in path or path.endswith(("/.", "/..")):
        _fail(f"source '{source_id}' url contains a non-canonical path")
    for escape in _PERCENT_ESCAPE_RE.findall(path + parts.query):
        if escape != escape.upper():
            _fail(f"source '{source_id}' url contains a non-canonical escape")
    canonical = urlunsplit(("https", hostname, path, parts.query, ""))
    if url != canonical:
        _fail(f"source '{source_id}' url is not canonical HTTPS")
    return canonical


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _validate_relative_path(value: Any, source_id: str, source_kind: str) -> PurePosixPath:
    raw = _require_bounded_string(value, f"source '{source_id}' path", max_length=512)
    if "\\" in raw:
        _fail(f"source '{source_id}' path must use portable relative separators")
    relative = PurePosixPath(raw)
    parts = relative.parts
    if (
        relative.is_absolute()
        or not parts
        or raw != relative.as_posix()
        or any(part in {"", ".", ".."} or ":" in part for part in parts)
    ):
        _fail(f"source '{source_id}' path is not a safe relative path")
    lowered = {part.casefold() for part in parts}
    if lowered & _DENIED_PATH_PARTS:
        _fail(f"source '{source_id}' path enters a prohibited directory")
    required_root = _SOURCE_DIRS[source_kind]
    if parts[0] != required_root or len(parts) < 2:
        _fail(f"source '{source_id}' path must be under {required_root}/")
    return relative


def _validate_retrieved_at(value: Any, source_id: str) -> str:
    timestamp = _require_bounded_string(value, f"source '{source_id}' retrieved_at", max_length=20)
    if not _RETRIEVED_AT_RE.fullmatch(timestamp):
        _fail(f"source '{source_id}' retrieved_at must be UTC with second precision")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"source '{source_id}' retrieved_at is invalid")
    return timestamp


def _has_prohibited_benchmark_marker(content: str) -> bool:
    # Inputs have already passed the byte cap.  This is a detection-only view,
    # not a general HTML/Markdown sanitizer: decode entities, then strip only
    # leading quotes, short allowlisted presentation tags, and code ticks.  The
    # admitted body itself remains unchanged and the view cannot exceed the
    # module's source-size bound.
    marker_lines: list[str] = []
    for line in content.splitlines():
        normalized = html.unescape(line)
        normalized = _BLOCKQUOTE_PREFIX.sub("", normalized)
        normalized = _MARKER_HTML_TAG.sub("", normalized)
        normalized = _MARKER_CODE_TICKS.sub("", normalized)
        marker_lines.append(normalized)
    marker_view = "\n".join(marker_lines)
    if len(marker_view.encode("utf-8")) > DEFAULT_MAX_FILE_BYTES:
        _fail("source marker view exceeds the admission policy hard limit")
    if any(pattern.search(marker_view) for pattern in _PROHIBITED_SINGLE_MARKERS):
        return True
    return bool(_CATEGORY_MARKER.search(marker_view) and _ANALYSIS_MARKER.search(marker_view))


def _read_source(
    root: Path,
    relative: PurePosixPath,
    source_id: str,
    *,
    max_file_bytes: int,
) -> bytes:
    current = root
    if _is_reparse_or_symlink(current):
        _fail("staging root must not be a symlink or reparse point")
    for part in relative.parts:
        current = current / part
        if not current.exists():
            _fail(f"source '{source_id}' path does not exist")
        if _is_reparse_or_symlink(current):
            _fail(f"source '{source_id}' path contains a symlink or reparse point")
    try:
        root_resolved = root.resolve(strict=True)
        resolved = current.resolve(strict=True)
        if os.path.commonpath((str(root_resolved), str(resolved))) != str(root_resolved):
            _fail(f"source '{source_id}' path escapes the staging root")
        before = current.stat()
    except (OSError, ValueError) as exc:
        raise SeedAdmissionError(f"source '{source_id}' could not be inspected") from exc
    if not stat.S_ISREG(before.st_mode):
        _fail(f"source '{source_id}' path is not a regular file")
    if before.st_nlink != 1:
        _fail(f"source '{source_id}' path must have exactly one hard link")
    if before.st_size <= 0:
        _fail(f"source '{source_id}' file is empty")
    if before.st_size > max_file_bytes:
        _fail(f"source '{source_id}' exceeds the per-file byte limit")
    try:
        with current.open("rb") as handle:
            payload = handle.read(max_file_bytes + 1)
        after = current.stat()
    except OSError as exc:
        raise SeedAdmissionError(f"source '{source_id}' could not be read") from exc
    if len(payload) > max_file_bytes:
        _fail(f"source '{source_id}' exceeds the per-file byte limit")
    if after.st_nlink != 1:
        _fail(f"source '{source_id}' path must have exactly one hard link")
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_nlink,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    )
    if before_identity != after_identity or len(payload) != after.st_size:
        _fail(f"source '{source_id}' changed during admission")
    return payload


def _canonical_manifest_for_hash(
    manifest: Mapping[str, Any], identities: Mapping[str, Mapping[str, str]], sources: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "schema_version": manifest["schema_version"],
        **{field: dict(identities[field]) for field in ("builder", "normalization", "chunking", "embedding", "collection")},
        "sources": sorted(sources, key=lambda item: item["stable_id"]),
    }


def validate_seed_manifest(
    manifest: Mapping[str, Any],
    staging_root: str | os.PathLike[str],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_sources: int = DEFAULT_MAX_SOURCES,
) -> ValidatedSeedManifest:
    """Validate a parsed manifest and load admitted UTF-8 source bodies in memory."""

    if isinstance(manifest, dict):
        manifest_map = _require_exact_keys(manifest, _TOP_LEVEL_KEYS, "manifest")
    else:
        _fail("manifest must be an object")
    if manifest_map["schema_version"] != SCHEMA_VERSION:
        _fail("manifest schema_version is unsupported")
    for name, limit in (
        ("max_file_bytes", max_file_bytes),
        ("max_total_bytes", max_total_bytes),
        ("max_sources", max_sources),
    ):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            _fail(f"{name} must be a positive integer")
    if max_file_bytes > DEFAULT_MAX_FILE_BYTES:
        _fail("max_file_bytes cannot exceed the admission policy hard limit")
    if max_total_bytes > DEFAULT_MAX_TOTAL_BYTES:
        _fail("max_total_bytes cannot exceed the admission policy hard limit")
    if max_sources > DEFAULT_MAX_SOURCES:
        _fail("max_sources cannot exceed the admission policy hard limit")

    identities = {
        field: _validate_identity(manifest_map, field)
        for field in ("builder", "normalization", "chunking", "embedding", "collection")
    }
    raw_sources = manifest_map["sources"]
    if not isinstance(raw_sources, list) or not raw_sources:
        _fail("sources must be a non-empty array")
    if len(raw_sources) > max_sources:
        _fail("sources exceed the manifest source-count limit")

    root = Path(staging_root)
    if not root.exists() or not root.is_dir():
        _fail("staging root must be an existing directory")
    if _is_reparse_or_symlink(root):
        _fail("staging root must not be a symlink or reparse point")

    normalized_sources: list[dict[str, str]] = []
    records: list[ValidatedSeedSource] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    total_bytes = 0
    for index, raw_source in enumerate(raw_sources):
        source = _require_exact_keys(raw_source, _SOURCE_KEYS, f"sources[{index}]")
        source_id = _require_bounded_string(source["stable_id"], f"sources[{index}].stable_id", max_length=128)
        if not _STABLE_ID_RE.fullmatch(source_id):
            _fail(f"sources[{index}].stable_id is invalid")
        if source_id in seen_ids:
            _fail(f"source '{source_id}' stable_id is duplicated")
        seen_ids.add(source_id)

        source_kind = source["source_kind"]
        if not isinstance(source_kind, str) or source_kind not in _SOURCE_DIRS:
            _fail(f"source '{source_id}' source_kind must be official or paper")
        relative = _validate_relative_path(source["path"], source_id, source_kind)
        relative_text = relative.as_posix()
        if relative_text.casefold() in seen_paths:
            _fail(f"source '{source_id}' path is duplicated")
        seen_paths.add(relative_text.casefold())
        url = _canonical_https_url(source["url"], source_id)
        publisher = _require_bounded_string(source["publisher"], f"source '{source_id}' publisher")
        retrieved_at = _validate_retrieved_at(source["retrieved_at"], source_id)
        content_sha256 = source["content_sha256"]
        if not isinstance(content_sha256, str) or not _SHA256_RE.fullmatch(content_sha256):
            _fail(f"source '{source_id}' content_sha256 must be lowercase SHA-256")
        if source["encoding"] != "utf-8":
            _fail(f"source '{source_id}' encoding must be utf-8")

        payload = _read_source(root, relative, source_id, max_file_bytes=max_file_bytes)
        total_bytes += len(payload)
        if total_bytes > max_total_bytes:
            _fail("admitted sources exceed the total byte limit")
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != content_sha256:
            _fail(f"source '{source_id}' content SHA-256 does not match")
        try:
            content = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            content = None
        if content is None:
            _fail(f"source '{source_id}' is not strict UTF-8")
        if not content.strip():
            _fail(f"source '{source_id}' has no textual content")
        if _has_prohibited_benchmark_marker(content):
            _fail(f"source '{source_id}' contains a prohibited benchmark-derived marker")

        normalized_source = {
            "stable_id": source_id,
            "path": relative_text,
            "url": url,
            "source_kind": source_kind,
            "publisher": publisher,
            "retrieved_at": retrieved_at,
            "content_sha256": content_sha256,
            "encoding": "utf-8",
        }
        normalized_sources.append(normalized_source)
        records.append(
            ValidatedSeedSource(
                stable_id=source_id,
                relative_path=relative_text,
                url=url,
                source_kind=source_kind,
                publisher=publisher,
                retrieved_at=retrieved_at,
                content_sha256=content_sha256,
                encoding="utf-8",
                content=content,
                byte_length=len(payload),
            )
        )

    records.sort(key=lambda record: record.stable_id)
    canonical = _canonical_manifest_for_hash(manifest_map, identities, normalized_sources)
    canonical_bytes = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    admission_identity = {
        "manifest_sha256": manifest_sha256,
        "policy": {"id": ADMISSION_POLICY_ID, "version": ADMISSION_POLICY_VERSION},
        "effective_limits": {
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_sources": max_sources,
        },
        "identities": {
            field: dict(identities[field])
            for field in (
                "builder",
                "normalization",
                "chunking",
                "embedding",
                "collection",
            )
        },
    }
    admission_identity_bytes = json.dumps(
        admission_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    admission_identity_sha256 = hashlib.sha256(admission_identity_bytes).hexdigest()
    source_hashes = tuple((record.stable_id, record.content_sha256) for record in records)
    return ValidatedSeedManifest(
        schema_version=SCHEMA_VERSION,
        admission_policy_id=ADMISSION_POLICY_ID,
        admission_policy_version=ADMISSION_POLICY_VERSION,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        max_sources=max_sources,
        manifest_sha256=manifest_sha256,
        admission_identity_sha256=admission_identity_sha256,
        source_hashes=source_hashes,
        builder=tuple(sorted(identities["builder"].items())),
        normalization=tuple(sorted(identities["normalization"].items())),
        chunking=tuple(sorted(identities["chunking"].items())),
        embedding=tuple(sorted(identities["embedding"].items())),
        collection=tuple(sorted(identities["collection"].items())),
        records=tuple(records),
        total_bytes=total_bytes,
    )


def load_and_validate_seed_manifest(
    manifest_path: str | os.PathLike[str],
    staging_root: str | os.PathLike[str],
    **limits: int,
) -> ValidatedSeedManifest:
    """Load a bounded strict-UTF-8 JSON manifest, then validate its sources."""

    path = Path(manifest_path)
    if not path.exists() or _is_reparse_or_symlink(path):
        _fail("manifest path must be a regular non-symlink file")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise SeedAdmissionError("manifest could not be inspected") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > MAX_MANIFEST_BYTES:
        _fail("manifest must be a non-empty bounded regular file")
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_MANIFEST_BYTES + 1)
        after = path.stat()
        before_identity = (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if len(payload) > MAX_MANIFEST_BYTES:
            _fail("manifest exceeds its byte limit")
        if before_identity != after_identity or len(payload) != after.st_size:
            _fail("manifest changed while being read")
    except OSError as exc:
        raise SeedAdmissionError("manifest could not be read") from exc
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        text = None
    if text is None:
        _fail("manifest is not valid strict-UTF-8 JSON")
    try:
        parsed = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        _fail("manifest is not valid strict-UTF-8 JSON")
    return validate_seed_manifest(parsed, staging_root, **limits)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("manifest JSON contains duplicate object keys")
        result[key] = value
    return result


__all__ = [
    "ADMISSION_POLICY_ID",
    "ADMISSION_POLICY_VERSION",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_SOURCES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "MAX_MANIFEST_BYTES",
    "EXPECTED_BUILDER_IDENTITY",
    "EXPECTED_COLLECTION_IDENTITY",
    "EXPECTED_CHUNKING_IDENTITY",
    "EXPECTED_EMBEDDING_IDENTITY",
    "EXPECTED_NORMALIZATION_IDENTITY",
    "SCHEMA_VERSION",
    "SeedAdmissionError",
    "ValidatedSeedManifest",
    "ValidatedSeedSource",
    "load_and_validate_seed_manifest",
    "validate_seed_manifest",
]
