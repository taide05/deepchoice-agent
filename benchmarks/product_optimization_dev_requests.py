"""Load the frozen, development-only request projection.

This module intentionally reads one small fixture and no benchmark dataset or
snapshot.  The source snapshot hashes are retained as provenance only; they are
not dereferenced by the loader.
"""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepchoice.contracts.api import ResearchRequest


ROOT = Path(__file__).resolve().parent.parent
_EXPECTED_FIXTURE_PATH = ROOT / "benchmarks" / "product-optimization-dev-requests-v1.json"
DEFAULT_FIXTURE_PATH = _EXPECTED_FIXTURE_PATH
FIXTURE_ID = "product-optimization-dev-requests-v1"
FIXTURE_SCHEMA_VERSION = 1
FIXTURE_FREEZE_DATE = "2026-09-23"
MAX_FIXTURE_BYTES = 64 * 1024
FIXTURE_BYTES_SHA256 = "9c47d8071ed911ede5f810bceda8ba9a4ab19748201f310cf9c033399714871d"
EXPECTED_CASE_IDS = ("P01", "P04", "P08")

_TOP_LEVEL_KEYS = {
    "schema_version",
    "fixture_id",
    "status",
    "freeze_date",
    "projection",
    "cases",
}
_PROJECTION_KEYS = {"source_kind", "request_fields", "source_content_access"}
_CASE_KEYS = {
    "case_id",
    "role",
    "source_snapshot_path",
    "source_snapshot_sha256",
    "request_sha256",
    "request",
}
_REQUEST_KEYS = {
    "schema_version",
    "query",
    "scene_context",
    "constraints",
    "candidate_techs",
    "complexity",
    "report_format",
    "sub_questions",
    "gather_evidence",
    "language",
}

# These are the approved S0 development bindings.  They are metadata only;
# loading this fixture never opens the referenced snapshot files.
_EXPECTED_CASES = {
    "P01": {
        "role": "regression",
        "source_snapshot_path": "outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/collections/serial-r1/development/snapshots/P01.json",
        "source_snapshot_sha256": "beab5029af1d367e7d2688253224e54fee43d79898ea867ba033d73342da9fb2",
        "request_sha256": "738af60c92a6c97360c43c191881cf4fa93836039395663887b04debdf275ea9",
    },
    "P04": {
        "role": "target",
        "source_snapshot_path": "outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/collections/serial-r1/development/snapshots/P04.json",
        "source_snapshot_sha256": "5a464ee1eece9fff7a24c8ca79c4da7cf55b4d9669c983fd6850795ce2d8c6cb",
        "request_sha256": "9ee6fca21018d59483fcdd9a772df685fdb909776c5c0ee1bdfdf3d889a9b937",
    },
    "P08": {
        "role": "target",
        "source_snapshot_path": "outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/collections/serial-r1/development/snapshots/P08.json",
        "source_snapshot_sha256": "4468a403ea1e017edc7c29bade793f7f77a9413b7852993860d9964d6c092c4f",
        "request_sha256": "7382e2a4c3be83a75a6d0df606a48bce0fc4d55ca33789bccc609c2f2cbbfa88",
    },
}


class DevelopmentRequestFixtureError(ValueError):
    """Raised when the frozen development projection is missing or altered."""


@dataclass(frozen=True)
class DevelopmentRequest:
    case_id: str
    role: str
    source_snapshot_path: str
    source_snapshot_sha256: str
    request_sha256: str
    request: ResearchRequest


@dataclass(frozen=True)
class DevelopmentRequestFixture:
    fixture_id: str
    freeze_date: str
    byte_sha256: str
    cases: tuple[DevelopmentRequest, ...]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DevelopmentRequestFixtureError(f"{label} must be an object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DevelopmentRequestFixtureError(
                f"duplicate JSON object key: {key}"
            )
        result[key] = value
    return result


def _require_exact_keys(mapping: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DevelopmentRequestFixtureError(
            f"{label} keys changed; missing={missing}, extra={extra}"
        )


def _parse_fixture_bytes(raw: bytes) -> DevelopmentRequestFixture:
    """Parse synthetic or already-read fixture bytes without opening a path."""

    if len(raw) > MAX_FIXTURE_BYTES:
        raise DevelopmentRequestFixtureError(
            f"development request fixture exceeds {MAX_FIXTURE_BYTES} bytes"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except DevelopmentRequestFixtureError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DevelopmentRequestFixtureError("invalid development request JSON") from exc
    return _parse_fixture_payload(payload, hashlib.sha256(raw).hexdigest())


def _parse_fixture_payload(payload: Any, byte_sha256: str) -> DevelopmentRequestFixture:
    payload = _require_mapping(payload, "fixture")
    _require_exact_keys(payload, _TOP_LEVEL_KEYS, "fixture")
    if payload["schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise DevelopmentRequestFixtureError("unsupported fixture schema version")
    if payload["fixture_id"] != FIXTURE_ID or payload["status"] != "frozen":
        raise DevelopmentRequestFixtureError("fixture identity or status changed")
    if payload["freeze_date"] != FIXTURE_FREEZE_DATE:
        raise DevelopmentRequestFixtureError("fixture freeze_date changed")

    projection = _require_mapping(payload["projection"], "projection")
    _require_exact_keys(projection, _PROJECTION_KEYS, "projection")
    if projection != {
        "source_kind": "s0_snapshot_task_projection",
        "request_fields": "complete_research_request",
        "source_content_access": "metadata_only",
    }:
        raise DevelopmentRequestFixtureError("projection contract changed")

    cases = payload["cases"]
    if not isinstance(cases, list) or tuple(
        item.get("case_id") if isinstance(item, dict) else None for item in cases
    ) != EXPECTED_CASE_IDS:
        raise DevelopmentRequestFixtureError(
            f"fixture case IDs must be exactly {EXPECTED_CASE_IDS} in frozen order"
        )

    parsed: list[DevelopmentRequest] = []
    for item in cases:
        case = _require_mapping(item, "case")
        _require_exact_keys(case, _CASE_KEYS, f"case {case.get('case_id', '<unknown>')}")
        case_id = case["case_id"]
        expected = _EXPECTED_CASES[case_id]
        for field in ("role", "source_snapshot_path", "source_snapshot_sha256", "request_sha256"):
            if case[field] != expected[field]:
                raise DevelopmentRequestFixtureError(
                    f"{case_id} {field} does not match the frozen binding"
                )

        request_payload = _require_mapping(case["request"], f"{case_id}.request")
        _require_exact_keys(request_payload, _REQUEST_KEYS, f"{case_id}.request")
        try:
            request = ResearchRequest.model_validate(request_payload)
        except Exception as exc:  # pydantic validation errors are fixture failures
            raise DevelopmentRequestFixtureError(
                f"{case_id}.request is not a valid ResearchRequest"
            ) from exc
        normalized_request = request.model_dump(mode="json", exclude_none=False)
        if normalized_request != request_payload:
            raise DevelopmentRequestFixtureError(
                f"{case_id}.request is not the complete canonical request identity"
            )
        if _canonical_sha256(normalized_request) != expected["request_sha256"]:
            raise DevelopmentRequestFixtureError(
                f"{case_id}.request_sha256 does not match the frozen request"
            )
        parsed.append(
            DevelopmentRequest(
                case_id=case_id,
                role=case["role"],
                source_snapshot_path=case["source_snapshot_path"],
                source_snapshot_sha256=case["source_snapshot_sha256"],
                request_sha256=case["request_sha256"],
                request=request,
            )
        )
    return DevelopmentRequestFixture(
        fixture_id=payload["fixture_id"],
        freeze_date=payload["freeze_date"],
        byte_sha256=byte_sha256,
        cases=tuple(parsed),
    )


def _is_reparse_or_symlink(metadata: Any) -> bool:
    reparse_point = 0x0400
    return bool(stat.S_ISLNK(metadata.st_mode)) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_point
    )


def _validate_fixed_fixture_path() -> Path:
    path = DEFAULT_FIXTURE_PATH
    if path != _EXPECTED_FIXTURE_PATH or not path.is_absolute():
        raise DevelopmentRequestFixtureError("development fixture path is not approved")

    current = Path(path.anchor)
    for component in path.parts:
        if component == path.anchor:
            continue
        current /= component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise DevelopmentRequestFixtureError(
                f"development fixture path component is unavailable: {current}"
            ) from exc
        if _is_reparse_or_symlink(metadata):
            raise DevelopmentRequestFixtureError(
                f"development fixture path contains a symlink or reparse point: {current}"
            )

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DevelopmentRequestFixtureError("development fixture is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise DevelopmentRequestFixtureError("development fixture is not a regular file")
    if metadata.st_size > MAX_FIXTURE_BYTES:
        raise DevelopmentRequestFixtureError(
            f"development request fixture exceeds {MAX_FIXTURE_BYTES} bytes"
        )
    return path


def load_dev_requests() -> DevelopmentRequestFixture:
    """Load the one approved development request fixture.

    The public entry point has no path parameter by design.  Source snapshot
    paths stored in the fixture are provenance metadata and are never opened.
    """

    path = _validate_fixed_fixture_path()
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_FIXTURE_BYTES + 1)
    except OSError as exc:
        raise DevelopmentRequestFixtureError("cannot read development request fixture") from exc
    if len(raw) > MAX_FIXTURE_BYTES:
        raise DevelopmentRequestFixtureError(
            f"development request fixture exceeds {MAX_FIXTURE_BYTES} bytes"
        )
    byte_sha256 = hashlib.sha256(raw).hexdigest()
    if byte_sha256 != FIXTURE_BYTES_SHA256:
        raise DevelopmentRequestFixtureError("development fixture byte SHA changed")
    return _parse_fixture_bytes(raw)
