"""One-shot importer for the pre-Phase-1 durable snapshot files.

The importer is deliberately kept at the server boundary. Snapshot files are
untrusted input: only the validated request, public result allowlist, and a
small amount of provenance are imported. Private state and unknown fields are
never copied into the product database.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence.records import RunRecord, RunResultRecord, TaskRecord
from deepchoice.runtime.coordinator import build_public_run_result
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SUCCESS_FILE = "research_snapshot.json"
_FAILED_FILE = "research_snapshot_failed.json"
_LEGACY_NAMESPACE = uuid.UUID("9b1d33c9-83cf-5df6-9c09-c522d6f1c1e3")
_DEFAULT_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


class _SnapshotTooLargeError(ValueError):
    def __init__(self, digest: str) -> None:
        super().__init__("legacy snapshot exceeds the import size limit")
        self.digest = digest


class _ImportBudgetExceededError(TimeoutError):
    pass


class LegacyImportRepository(Protocol):
    async def import_legacy_task(
        self, source_path: str, content_sha256: str, task: TaskRecord, run: RunRecord,
        result: RunResultRecord | None = None,
        *, imported_at: datetime | None = None
    ) -> Any: ...

    async def record_legacy_import_failure(
        self, source_path: str, content_sha256: str, error_code: str,
        *, imported_at: datetime | None = None
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class LegacyImportSummary:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    budget_exhausted: bool = False


@dataclass(frozen=True, slots=True)
class LegacyImportLimits:
    max_candidates: int = 1_000
    max_io_seconds: float = 5.0
    max_snapshot_bytes: int = _DEFAULT_MAX_SNAPSHOT_BYTES

    def __post_init__(self) -> None:
        if type(self.max_candidates) is not int or self.max_candidates <= 0:
            raise ValueError("max_candidates must be a positive integer")
        if (
            isinstance(self.max_io_seconds, bool)
            or not isinstance(self.max_io_seconds, (int, float))
            or self.max_io_seconds <= 0
        ):
            raise ValueError("max_io_seconds must be positive")
        if type(self.max_snapshot_bytes) is not int or self.max_snapshot_bytes <= 0:
            raise ValueError("max_snapshot_bytes must be a positive integer")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _invoke(call: Any, *args: Any, **kwargs: Any) -> Any:
    """Call repository methods whether an adapter is sync or async."""

    result = call(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _file_time(path: Path, clock: Any) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except (OSError, ValueError, OverflowError):
        return _as_utc(clock())


def _error_code(error: Exception | None) -> str:
    """Return a stable, non-sensitive public error code."""

    if isinstance(error, json.JSONDecodeError):
        return "LEGACY_SNAPSHOT_JSON_INVALID"
    if isinstance(error, _SnapshotTooLargeError):
        return "LEGACY_SNAPSHOT_TOO_LARGE"
    if isinstance(error, _ImportBudgetExceededError):
        return "LEGACY_IMPORT_IO_BUDGET_EXCEEDED"
    if isinstance(error, (UnicodeDecodeError, OSError)):
        return "LEGACY_SNAPSHOT_READ_FAILED"
    return "LEGACY_SNAPSHOT_SCHEMA_INVALID"


def _request(snapshot: object) -> ResearchRequest:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    task = snapshot.get("task")
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    return ResearchRequest.model_validate(task)


def _decode_snapshot(raw: bytes) -> tuple[dict[str, Any], ResearchRequest]:
    snapshot = json.loads(raw.decode("utf-8"))
    request = _request(snapshot)
    return snapshot, request


def _source_path(root: Path, path: Path) -> str:
    # The scanner only passes direct children, but resolve the relative path
    # explicitly so Windows paths are persisted in portable POSIX form.
    return path.relative_to(root).as_posix()


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _is_contained_snapshot(root: Path, task_dir: Path, snapshot_path: Path) -> bool:
    """Reject symlink/junction escapes before reading untrusted legacy files."""

    try:
        root_resolved = root.resolve(strict=True)
        if _is_link_like(task_dir) or _is_link_like(snapshot_path):
            return False
        task_resolved = task_dir.resolve(strict=True)
        snapshot_resolved = snapshot_path.resolve(strict=True)
        return (
            task_resolved.parent == root_resolved
            and snapshot_resolved.parent == task_resolved
        )
    except OSError:
        return False


def _metadata_digest(path: Path) -> str:
    """Return a stable, non-content audit key without reading an unsafe file."""

    try:
        stat = path.stat()
        identity = f"unread:{stat.st_size}:{stat.st_mtime_ns}".encode("ascii")
    except OSError:
        identity = b"unread:unknown"
    return hashlib.sha256(identity).hexdigest()


def _read_and_hash(
    path: Path,
    *,
    max_bytes: int,
    deadline: float,
    monotonic: Any,
    allowed_parent: Path,
) -> tuple[bytes, str]:
    if _is_link_like(path) or path.resolve(strict=True).parent != allowed_parent:
        raise OSError("legacy snapshot escaped its configured root")
    try:
        if path.stat().st_size > max_bytes:
            raise _SnapshotTooLargeError(_metadata_digest(path))
    except _SnapshotTooLargeError:
        raise
    except OSError:
        pass
    digest = hashlib.sha256()
    payload = bytearray()
    with path.open("rb") as stream:
        while True:
            if monotonic() >= deadline:
                raise _ImportBudgetExceededError("legacy import I/O budget exhausted")
            chunk = stream.read(min(1024 * 1024, max_bytes + 1 - len(payload)))
            if not chunk:
                break
            digest.update(chunk)
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise _SnapshotTooLargeError(_metadata_digest(path))
    return bytes(payload), digest.hexdigest()


def _list_candidates(
    root: Path,
    *,
    max_candidates: int,
    deadline: float,
    monotonic: Any,
) -> tuple[list[Path], bool]:
    candidates: list[Path] = []
    exhausted = False
    with os.scandir(root) as entries:
        for entry in entries:
            if monotonic() >= deadline or len(candidates) >= max_candidates:
                exhausted = True
                break
            candidates.append(Path(entry.path))
    candidates.sort(key=lambda item: item.name)
    return candidates, exhausted


async def import_legacy_snapshots(
    root: str | Path,
    repository: LegacyImportRepository,
    *,
    clock: Any = lambda: datetime.now(UTC),
    max_snapshot_bytes: int | None = None,
    limits: LegacyImportLimits | None = None,
    monotonic: Any = time.monotonic,
) -> LegacyImportSummary:
    """Import direct-child legacy task directories into the durable store.

    This operation is safe to repeat.  Idempotency and source/task conflict
    handling belong to the repository's atomic import transaction.
    """

    root_path = Path(root)
    scanned = imported = skipped = errors = 0
    if limits is not None and max_snapshot_bytes is not None:
        raise ValueError("pass limits or max_snapshot_bytes, not both")
    if limits is None:
        limits = LegacyImportLimits(
            max_snapshot_bytes=(
                _DEFAULT_MAX_SNAPSHOT_BYTES
                if max_snapshot_bytes is None
                else max_snapshot_bytes
            )
        )
    deadline = monotonic() + float(limits.max_io_seconds)
    if not root_path.is_dir():
        return LegacyImportSummary()

    try:
        task_directories, budget_exhausted = await asyncio.to_thread(
            _list_candidates,
            root_path,
            max_candidates=limits.max_candidates,
            deadline=deadline,
            monotonic=monotonic,
        )
    except OSError:
        return LegacyImportSummary(errors=1)

    for task_dir in task_directories:
        if monotonic() >= deadline:
            budget_exhausted = True
            break
        if not task_dir.is_dir() or not _TASK_ID_RE.fullmatch(task_dir.name):
            continue
        success = task_dir / _SUCCESS_FILE
        failed = task_dir / _FAILED_FILE
        snapshot_path = success if success.is_file() else failed if failed.is_file() else None
        if snapshot_path is None:
            continue
        if not _is_contained_snapshot(root_path, task_dir, snapshot_path):
            continue

        scanned += 1
        source_path = _source_path(root_path, snapshot_path)
        now = _file_time(snapshot_path, clock)
        digest = _metadata_digest(snapshot_path)
        try:
            raw, digest = await asyncio.to_thread(
                _read_and_hash,
                snapshot_path,
                max_bytes=limits.max_snapshot_bytes,
                deadline=deadline,
                monotonic=monotonic,
                allowed_parent=task_dir.resolve(strict=True),
            )
            snapshot, request = await asyncio.to_thread(_decode_snapshot, raw)
            if monotonic() >= deadline:
                raise _ImportBudgetExceededError("legacy import I/O budget exhausted")
            failed_snapshot = snapshot_path.name == _FAILED_FILE
            run_id = str(uuid.uuid5(_LEGACY_NAMESPACE, f"{source_path}:{digest}"))
            status = RunStatus.FAILED if failed_snapshot else RunStatus.COMPLETED
            manifest = build_run_manifest(request.model_dump(exclude_none=True)).model_copy(
                update={"created_at": now}
            )
            task = TaskRecord(
                task_id=task_dir.name,
                status=TaskStatus.FAILED if failed_snapshot else TaskStatus.COMPLETED,
                request=request,
                latest_run_id=run_id,
                version=0,
                created_at=now,
                updated_at=now,
            )
            run = RunRecord(
                run_id=run_id,
                task_id=task_dir.name,
                status=status,
                manifest=manifest,
                budget_policy=None,
                thread_id=run_id,
                checkpoint_ns="",
                execution_epoch=0,
                started_at=now,
                ended_at=now,
                error_id="LEGACY_SNAPSHOT_FAILED" if failed_snapshot else None,
                version=0,
                created_at=now,
                updated_at=now,
            )
            run_result = None
            if not failed_snapshot:
                state = type("LegacyState", (), {"values": snapshot})()
                run_result = build_public_run_result(
                    run,
                    request.model_dump(mode="json", exclude_none=True),
                    state,
                    created_at=now,
                )
            result = await _invoke(
                repository.import_legacy_task,
                source_path, digest, task, run, run_result, imported_at=now,
            )
            outcome = getattr(result, "outcome", None)
            if getattr(result, "created", True) is False:
                skipped += 1
            elif outcome == "error":
                errors += 1
            elif result is False or outcome == "skipped" or getattr(result, "skipped", False):
                skipped += 1
            else:
                imported += 1
        except Exception as exc:  # noqa: BLE001 - per-file isolation is required
            if isinstance(exc, _SnapshotTooLargeError):
                digest = exc.digest
            code = _error_code(exc)
            try:
                await _invoke(
                    repository.record_legacy_import_failure,
                    source_path, digest, code, imported_at=now,
                )
            except Exception:  # noqa: BLE001 - one bad record must not stop scanning
                pass
            errors += 1
            if isinstance(exc, _ImportBudgetExceededError):
                budget_exhausted = True
                break

    return LegacyImportSummary(
        scanned=scanned,
        imported=imported,
        skipped=skipped,
        errors=errors,
        budget_exhausted=budget_exhausted,
    )


# Short alias for callers that prefer the singular operation name.
import_legacy_snapshot = import_legacy_snapshots


__all__ = [
    "LegacyImportLimits",
    "LegacyImportSummary",
    "import_legacy_snapshot",
    "import_legacy_snapshots",
]
