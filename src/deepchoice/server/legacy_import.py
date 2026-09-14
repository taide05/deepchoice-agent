"""One-shot importer for the pre-Phase-1 durable snapshot files.

The importer is deliberately kept at the server boundary.  Snapshot files are
untrusted input and are never copied into the product database; only the
validated request and a small amount of provenance are imported.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence.records import RunRecord, TaskRecord
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


class LegacyImportRepository(Protocol):
    async def import_legacy_task(
        self, source_path: str, content_sha256: str, task: TaskRecord, run: RunRecord,
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


def _source_path(root: Path, path: Path) -> str:
    # The scanner only passes direct children, but resolve the relative path
    # explicitly so Windows paths are persisted in portable POSIX form.
    return path.relative_to(root).as_posix()


def _read_and_hash(path: Path, *, max_bytes: int) -> tuple[bytes, str]:
    digest = hashlib.sha256()
    payload = bytearray()
    oversized = False
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            if not oversized and len(payload) + len(chunk) <= max_bytes:
                payload.extend(chunk)
            else:
                oversized = True
    encoded_digest = digest.hexdigest()
    if oversized:
        raise _SnapshotTooLargeError(encoded_digest)
    return bytes(payload), encoded_digest


async def import_legacy_snapshots(
    root: str | Path,
    repository: LegacyImportRepository,
    *,
    clock: Any = lambda: datetime.now(UTC),
    max_snapshot_bytes: int = _DEFAULT_MAX_SNAPSHOT_BYTES,
) -> LegacyImportSummary:
    """Import direct-child legacy task directories into the durable store.

    This operation is safe to repeat.  Idempotency and source/task conflict
    handling belong to the repository's atomic import transaction.
    """

    root_path = Path(root)
    scanned = imported = skipped = errors = 0
    if type(max_snapshot_bytes) is not int or max_snapshot_bytes <= 0:
        raise ValueError("max_snapshot_bytes must be a positive integer")
    if not root_path.is_dir():
        return LegacyImportSummary()

    try:
        task_directories = sorted(root_path.iterdir(), key=lambda item: item.name)
    except OSError:
        return LegacyImportSummary(errors=1)

    for task_dir in task_directories:
        if not task_dir.is_dir() or not _TASK_ID_RE.fullmatch(task_dir.name):
            continue
        success = task_dir / _SUCCESS_FILE
        failed = task_dir / _FAILED_FILE
        snapshot_path = success if success.is_file() else failed if failed.is_file() else None
        if snapshot_path is None:
            continue

        scanned += 1
        source_path = _source_path(root_path, snapshot_path)
        now = _file_time(snapshot_path, clock)
        try:
            raw, digest = _read_and_hash(
                snapshot_path,
                max_bytes=max_snapshot_bytes,
            )
            snapshot = json.loads(raw.decode("utf-8"))
            request = _request(snapshot)
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
            result = await _invoke(
                repository.import_legacy_task,
                source_path, digest, task, run, imported_at=now,
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
            else:
                try:
                    _, digest = _read_and_hash(
                        snapshot_path,
                        max_bytes=max_snapshot_bytes,
                    )
                except _SnapshotTooLargeError as size_error:
                    digest = size_error.digest
                except OSError:
                    digest = hashlib.sha256(b"").hexdigest()
            code = _error_code(exc)
            try:
                await _invoke(
                    repository.record_legacy_import_failure,
                    source_path, digest, code, imported_at=now,
                )
            except Exception:  # noqa: BLE001 - one bad record must not stop scanning
                pass
            errors += 1

    return LegacyImportSummary(scanned=scanned, imported=imported, skipped=skipped, errors=errors)


# Short alias for callers that prefer the singular operation name.
import_legacy_snapshot = import_legacy_snapshots


__all__ = ["LegacyImportSummary", "import_legacy_snapshot", "import_legacy_snapshots"]
