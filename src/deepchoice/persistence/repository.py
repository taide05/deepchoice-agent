"""Task/run repository contracts and their single-connection SQLite adapter."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

import aiosqlite

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory
from deepchoice.contracts.manifest import RunManifest
from deepchoice.runtime.lifecycle import (
    RunStatus,
    TaskStatus,
    TaskTransitionIntent,
    ensure_run_transition_allowed,
    ensure_task_transition_allowed,
)

from .database import _await_cleanup, _is_locked_error
from .records import (
    CheckpointReference,
    LegacyImportRecord,
    RecoveryRun,
    RunLeaseGrant,
    RunRecord,
    RunResultRecord,
    TaskRecord,
    TaskEventCursor,
    TaskEventRecord,
    TaskWithRun,
)


class RepositoryOperationError(DeepChoiceError):
    """A sanitized product-database operation failure."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__(
            "The task database operation failed.",
            category=ErrorCategory.PERSISTENCE,
            code="TASK_DATABASE_OPERATION_FAILED",
            status_code=503 if retryable else 500,
            retryable=retryable,
            action="Retry later." if retryable else "Inspect product database health.",
            scope="task_database",
        )


class TaskNotFoundError(DeepChoiceError):
    def __init__(self, task_id: str) -> None:
        super().__init__(
            "Task not found",
            category=ErrorCategory.NOT_FOUND,
            code="TASK_NOT_FOUND",
            status_code=404,
            retryable=False,
            action="Check the task identifier.",
            scope="task",
            task_id=task_id,
        )


class RunNotFoundError(DeepChoiceError):
    def __init__(self, run_id: str) -> None:
        super().__init__(
            "Run not found",
            category=ErrorCategory.NOT_FOUND,
            code="RUN_NOT_FOUND",
            status_code=404,
            retryable=False,
            action="Check the run identifier.",
            scope="run",
            run_id=run_id,
        )


class TaskVersionConflictError(DeepChoiceError):
    def __init__(self, task_id: str, *, expected: int, actual: int) -> None:
        super().__init__(
            "The task version is stale.",
            category=ErrorCategory.CONTRACT,
            code="TASK_VERSION_CONFLICT",
            status_code=409,
            retryable=False,
            action="Refresh the task and retry with its current version.",
            scope="task_lifecycle",
            task_id=task_id,
            details={"expected_version": expected, "actual_version": actual},
        )


class RunLeaseLostError(DeepChoiceError):
    """The caller no longer owns the fenced execution lease."""

    def __init__(self, run_id: str) -> None:
        super().__init__(
            "The run execution lease is no longer valid.",
            category=ErrorCategory.CONTRACT,
            code="RUN_LEASE_LOST",
            status_code=409,
            retryable=False,
            action="Stop this worker and let the current lease owner continue.",
            scope="run_lease",
            run_id=run_id,
        )


class CheckpointNotAvailableError(DeepChoiceError):
    """The product database has no compatible accepted resume checkpoint."""

    def __init__(self, run_id: str) -> None:
        super().__init__(
            "A compatible accepted checkpoint is not available for this run.",
            category=ErrorCategory.CONTRACT,
            code="RUN_CHECKPOINT_NOT_AVAILABLE",
            status_code=409,
            retryable=False,
            action="Retry the task with a new run.",
            scope="run_checkpoint",
            run_id=run_id,
        )


@runtime_checkable
class TaskRepository(Protocol):
    async def create_task_with_run(
        self, task: TaskRecord, run: RunRecord
    ) -> TaskWithRun: ...

    async def get_task(self, task_id: str) -> TaskWithRun | None: ...

    async def list_tasks(
        self,
        *,
        status: TaskStatus | None,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[TaskWithRun, ...]: ...

    async def transition_current_run(
        self,
        task_id: str,
        *,
        expected_task_version: int,
        target_task_status: TaskStatus,
        target_run_status: RunStatus,
        updated_at: datetime | None = None,
    ) -> TaskWithRun: ...

    async def cancel_task(
        self, task_id: str, *, updated_at: datetime | None = None
    ) -> TaskWithRun: ...

    async def resume_interrupted_run(
        self,
        task_id: str,
        *,
        expected_task_version: int,
        updated_at: datetime | None = None,
    ) -> TaskWithRun: ...

    async def retry_task_with_run(
        self,
        task_id: str,
        run: RunRecord,
        *,
        expected_task_version: int,
        updated_at: datetime | None = None,
    ) -> TaskWithRun: ...

    async def get_latest_checkpoint_reference(
        self,
        run_id: str,
        *,
        state_schema_version: int | None = None,
        checkpoint_ns: str | None = None,
    ) -> CheckpointReference | None: ...

    async def list_task_events(
        self, task_id: str, *, after_event_id: int = 0, limit: int = 100
    ) -> tuple[TaskEventRecord, ...]: ...

    async def get_task_event_cursor(
        self, task_id: str, *, cursor: int
    ) -> TaskEventCursor: ...

    async def get_run_result(self, run_id: str) -> RunResultRecord | None: ...

    async def record_legacy_import_failure(
        self,
        source_path: str,
        content_sha256: str,
        error_code: str,
        *,
        imported_at: datetime | None = None,
    ) -> LegacyImportRecord: ...

    async def import_legacy_task(
        self,
        source_path: str,
        content_sha256: str,
        task: TaskRecord,
        run: RunRecord,
        result: RunResultRecord | None = None,
        *,
        imported_at: datetime | None = None,
    ) -> LegacyImportRecord: ...


@runtime_checkable
class RunRepository(Protocol):
    async def get_run(self, run_id: str) -> RunRecord | None: ...

    async def acquire_run_lease(
        self,
        run_id: str,
        *,
        lease_owner: str,
        lease_ttl: timedelta,
        run_timeout: timedelta,
        now: datetime | None = None,
    ) -> RunLeaseGrant: ...

    async def heartbeat_run_lease(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        lease_ttl: timedelta,
        now: datetime | None = None,
    ) -> RunLeaseGrant: ...

    async def fence_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        now: datetime | None = None,
    ) -> RunRecord: ...

    async def finalize_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        status: RunStatus,
        error_id: str | None = None,
        now: datetime | None = None,
    ) -> TaskWithRun: ...

    async def finalize_run_with_result(
        self,
        run_id: str,
        result: RunResultRecord,
        *,
        lease_owner: str,
        execution_epoch: int,
        status: RunStatus = RunStatus.COMPLETED,
        now: datetime | None = None,
    ) -> TaskWithRun: ...

    async def add_checkpoint_reference(
        self,
        reference: CheckpointReference,
        *,
        lease_owner: str,
        execution_epoch: int,
        now: datetime | None = None,
    ) -> CheckpointReference: ...

    async def get_latest_checkpoint_reference(
        self,
        run_id: str,
        *,
        state_schema_version: int | None = None,
        checkpoint_ns: str | None = None,
    ) -> CheckpointReference | None: ...

    async def recover_runs(
        self, *, now: datetime | None = None
    ) -> tuple[RecoveryRun, ...]: ...


_TASK_COLUMNS = """
t.task_id, t.status, t.request_json, t.latest_run_id,
t.cancel_requested_at, t.version, t.created_at, t.updated_at
""".strip()

_RUN_COLUMNS = """
r.run_id, r.task_id, r.status, r.manifest_json, r.thread_id,
r.checkpoint_ns, r.execution_epoch, r.lease_owner, r.lease_expires_at,
r.deadline_at, r.started_at, r.ended_at, r.error_id, r.version, r.created_at, r.updated_at
""".strip()

_EVENT_COLUMNS = """
event_id, task_id, run_id, seq, type, public_payload_json, created_at
""".strip()

_RESULT_COLUMNS = """
run_id, result_schema_version, snapshot_json, report, report_format, created_at
""".strip()

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _datetime_to_db(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _datetime_from_db(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _task_from_values(values: tuple[object, ...]) -> TaskRecord:
    return TaskRecord(
        task_id=str(values[0]),
        status=TaskStatus(str(values[1])),
        request=ResearchRequest.model_validate_json(str(values[2])),
        latest_run_id=str(values[3]) if values[3] is not None else None,
        cancel_requested_at=_datetime_from_db(
            str(values[4]) if values[4] is not None else None
        ),
        version=int(values[5]),
        created_at=_datetime_from_db(str(values[6])),
        updated_at=_datetime_from_db(str(values[7])),
    )


def _run_from_values(values: tuple[object, ...]) -> RunRecord:
    return RunRecord(
        run_id=str(values[0]),
        task_id=str(values[1]),
        status=RunStatus(str(values[2])),
        manifest=RunManifest.model_validate_json(str(values[3])),
        thread_id=str(values[4]),
        checkpoint_ns=str(values[5]),
        execution_epoch=int(values[6]),
        lease_owner=str(values[7]) if values[7] is not None else None,
        lease_expires_at=_datetime_from_db(
            str(values[8]) if values[8] is not None else None
        ),
        deadline_at=_datetime_from_db(str(values[9]) if values[9] is not None else None),
        started_at=_datetime_from_db(str(values[10]) if values[10] is not None else None),
        ended_at=_datetime_from_db(str(values[11]) if values[11] is not None else None),
        error_id=str(values[12]) if values[12] is not None else None,
        version=int(values[13]),
        created_at=_datetime_from_db(str(values[14])),
        updated_at=_datetime_from_db(str(values[15])),
    )


def _joined_from_row(row: tuple[object, ...]) -> TaskWithRun:
    task = _task_from_values(row[:8])
    run = _run_from_values(row[8:]) if row[8] is not None else None
    return TaskWithRun(task=task, latest_run=run)


def _event_from_values(values: tuple[object, ...]) -> TaskEventRecord:
    return TaskEventRecord(
        event_id=int(values[0]),
        task_id=str(values[1]),
        run_id=str(values[2]) if values[2] is not None else None,
        seq=int(values[3]),
        type=str(values[4]),
        public_payload=json.loads(str(values[5])),
        created_at=_datetime_from_db(str(values[6])),
    )


def _result_from_values(values: tuple[object, ...]) -> RunResultRecord:
    return RunResultRecord(
        run_id=str(values[0]),
        result_schema_version=int(values[1]),
        snapshot=json.loads(str(values[2])),
        report=str(values[3]),
        report_format=str(values[4]),
        created_at=_datetime_from_db(str(values[5])),
    )


def _legacy_import_from_values(values: tuple[object, ...]) -> LegacyImportRecord:
    return LegacyImportRecord(
        source_path=str(values[0]),
        content_sha256=str(values[1]),
        outcome=str(values[2]),
        task_id=str(values[3]) if values[3] is not None else None,
        run_id=str(values[4]) if values[4] is not None else None,
        error_code=str(values[5]) if values[5] is not None else None,
        imported_at=_datetime_from_db(str(values[6])),
    )


class SQLiteTaskRunRepository(TaskRepository, RunRepository):
    """Serialize every operation over one lifespan-owned SQLite connection."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._connection = connection
        self._lock = lock if lock is not None else asyncio.Lock()

    async def _rollback(self) -> None:
        await _await_cleanup(self._connection.rollback())

    async def _fetchone(
        self, sql: str, parameters: tuple[object, ...]
    ) -> tuple[object, ...] | None:
        cursor = await self._connection.execute(sql, parameters)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def _fetchall(
        self, sql: str, parameters: tuple[object, ...]
    ) -> list[tuple[object, ...]]:
        cursor = await self._connection.execute(sql, parameters)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()

    async def _begin(self) -> None:
        cursor = await self._connection.execute("BEGIN IMMEDIATE")
        await cursor.close()

    async def _current_task_unlocked(self, task_id: str) -> TaskWithRun | None:
        row = await self._fetchone(
            f"""
            SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
            FROM tasks AS t
            LEFT JOIN runs AS r ON r.run_id = t.latest_run_id
            WHERE t.task_id = ?
            """,
            (task_id,),
        )
        return _joined_from_row(row) if row is not None else None

    async def _run_unlocked(self, run_id: str) -> RunRecord | None:
        row = await self._fetchone(
            f"SELECT {_RUN_COLUMNS} FROM runs AS r WHERE r.run_id = ?",
            (run_id,),
        )
        return _run_from_values(row) if row is not None else None

    async def _append_event_unlocked(
        self,
        *,
        task_id: str,
        run_id: str | None,
        event_type: str,
        public_payload: dict[str, object],
        created_at: datetime,
    ) -> TaskEventRecord:
        """Append under the caller's write transaction.

        ``BEGIN IMMEDIATE`` plus the repository lock serializes the per-task
        sequence allocation.  Only deliberately public payloads reach this
        helper; execution ownership and checkpoint identifiers are excluded.
        """

        row = await self._fetchone(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM task_events WHERE task_id = ?",
            (task_id,),
        )
        seq = int(row[0]) if row is not None else 1
        encoded_payload = json.dumps(
            public_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        cursor = await self._connection.execute(
            """
            INSERT INTO task_events(
                task_id, run_id, seq, type, public_payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                run_id,
                seq,
                event_type,
                encoded_payload,
                _datetime_to_db(created_at),
            ),
        )
        event_id = cursor.lastrowid
        await cursor.close()
        return TaskEventRecord(
            event_id=int(event_id),
            task_id=task_id,
            run_id=run_id,
            seq=seq,
            type=event_type,
            public_payload=public_payload,
            created_at=created_at,
        )

    async def _legacy_import_unlocked(
        self, source_path: str, content_sha256: str
    ) -> LegacyImportRecord | None:
        row = await self._fetchone(
            """
            SELECT source_path, content_sha256, outcome, task_id, run_id,
                   error_code, imported_at
            FROM legacy_imports
            WHERE source_path = ? AND content_sha256 = ?
            """,
            (source_path, content_sha256),
        )
        return _legacy_import_from_values(row) if row is not None else None

    @staticmethod
    def _validate_legacy_import_identity(
        source_path: str, content_sha256: str
    ) -> None:
        if not source_path:
            raise ValueError("source_path must be non-empty")
        if not _SHA256_RE.fullmatch(content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")

    async def create_task_with_run(
        self, task: TaskRecord, run: RunRecord
    ) -> TaskWithRun:
        if task.status is not TaskStatus.QUEUED or run.status is not RunStatus.QUEUED:
            raise ValueError("new tasks and runs must be queued")
        if task.task_id != run.task_id:
            raise ValueError("task and run identifiers do not match")
        if task.latest_run_id != run.run_id:
            raise ValueError("latest_run_id must reference the new run")
        if run.thread_id != run.run_id:
            raise ValueError("thread_id must equal run_id")

        async with self._lock:
            transaction_started = False
            try:
                cursor = await self._connection.execute("BEGIN IMMEDIATE")
                await cursor.close()
                transaction_started = True
                task_cursor = await self._connection.execute(
                    """
                    INSERT INTO tasks(
                        task_id, status, request_json, latest_run_id,
                        cancel_requested_at, version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.status.value,
                        task.request.model_dump_json(),
                        task.latest_run_id,
                        _datetime_to_db(task.cancel_requested_at)
                        if task.cancel_requested_at is not None
                        else None,
                        task.version,
                        _datetime_to_db(task.created_at),
                        _datetime_to_db(task.updated_at),
                    ),
                )
                await task_cursor.close()
                run_cursor = await self._connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, task_id, status, manifest_json, thread_id,
                        checkpoint_ns, execution_epoch, lease_owner,
                        lease_expires_at, deadline_at, started_at, ended_at, error_id,
                        version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        run.task_id,
                        run.status.value,
                        run.manifest.model_dump_json(),
                        run.thread_id,
                        run.checkpoint_ns,
                        run.execution_epoch,
                        run.lease_owner,
                        _datetime_to_db(run.lease_expires_at)
                        if run.lease_expires_at is not None
                        else None,
                        _datetime_to_db(run.deadline_at)
                        if run.deadline_at is not None
                        else None,
                        _datetime_to_db(run.started_at)
                        if run.started_at is not None
                        else None,
                        _datetime_to_db(run.ended_at)
                        if run.ended_at is not None
                        else None,
                        run.error_id,
                        run.version,
                        _datetime_to_db(run.created_at),
                        _datetime_to_db(run.updated_at),
                    ),
                )
                await run_cursor.close()
                await self._append_event_unlocked(
                    task_id=task.task_id,
                    run_id=run.run_id,
                    event_type="task.queued",
                    public_payload={"status": TaskStatus.QUEUED.value},
                    created_at=task.created_at,
                )
                await self._connection.commit()
                transaction_started = False
                return TaskWithRun(task=task, latest_run=run)
            except asyncio.CancelledError:
                if transaction_started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if transaction_started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if transaction_started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def acquire_run_lease(
        self,
        run_id: str,
        *,
        lease_owner: str,
        lease_ttl: timedelta,
        run_timeout: timedelta,
        now: datetime | None = None,
    ) -> RunLeaseGrant:
        if not lease_owner:
            raise ValueError("lease_owner must be non-empty")
        if lease_ttl <= timedelta(0) or run_timeout <= timedelta(0):
            raise ValueError("lease_ttl and run_timeout must be positive")
        changed_at = now or datetime.now(UTC)
        encoded_now = _datetime_to_db(changed_at)
        lease_expires_at = changed_at + lease_ttl
        deadline_at = changed_at + run_timeout

        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                run = await self._run_unlocked(run_id)
                if run is None:
                    raise RunNotFoundError(run_id)
                current = await self._current_task_unlocked(run.task_id)
                if (
                    current is None
                    or current.latest_run is None
                    or current.task.latest_run_id != run_id
                    or current.task.status is not TaskStatus.QUEUED
                    or run.status is not RunStatus.QUEUED
                    or (
                        run.lease_owner is not None
                        and (
                            run.lease_expires_at is None
                            or run.lease_expires_at > changed_at
                        )
                    )
                ):
                    raise RunLeaseLostError(run_id)
                checkpoint = await self._fetchone(
                    """
                    SELECT checkpoint_id FROM run_checkpoints
                    WHERE run_id = ? AND checkpoint_ns = ? AND state_schema_version = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (run_id, run.checkpoint_ns, run.manifest.state_schema_version),
                )
                next_epoch = run.execution_epoch + 1
                cursor = await self._connection.execute(
                    """
                    UPDATE runs
                    SET status = ?, execution_epoch = ?, lease_owner = ?,
                        lease_expires_at = ?, started_at = COALESCE(started_at, ?),
                        deadline_at = ?, ended_at = NULL, error_id = NULL,
                        version = version + 1, updated_at = ?
                    WHERE run_id = ? AND version = ? AND status = ?
                    """,
                    (
                        RunStatus.RUNNING.value,
                        next_epoch,
                        lease_owner,
                        _datetime_to_db(lease_expires_at),
                        encoded_now,
                        _datetime_to_db(deadline_at),
                        encoded_now,
                        run_id,
                        run.version,
                        RunStatus.QUEUED.value,
                    ),
                )
                updated = cursor.rowcount
                await cursor.close()
                if updated != 1:
                    raise RunLeaseLostError(run_id)
                cursor = await self._connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, version = version + 1, updated_at = ?
                    WHERE task_id = ? AND latest_run_id = ? AND version = ? AND status = ?
                    """,
                    (
                        TaskStatus.RUNNING.value,
                        encoded_now,
                        run.task_id,
                        run_id,
                        current.task.version,
                        TaskStatus.QUEUED.value,
                    ),
                )
                task_updated = cursor.rowcount
                await cursor.close()
                if task_updated != 1:
                    raise RunLeaseLostError(run_id)
                await self._append_event_unlocked(
                    task_id=run.task_id,
                    run_id=run_id,
                    event_type="run.started",
                    public_payload={"status": RunStatus.RUNNING.value},
                    created_at=changed_at,
                )
                await self._connection.commit()
                started = False
                return RunLeaseGrant(
                    task_id=run.task_id,
                    run_id=run_id,
                    lease_owner=lease_owner,
                    execution_epoch=next_epoch,
                    lease_expires_at=lease_expires_at,
                    deadline_at=deadline_at,
                    status=RunStatus.RUNNING,
                    resume=checkpoint is not None,
                )
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def heartbeat_run_lease(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        lease_ttl: timedelta,
        now: datetime | None = None,
    ) -> RunLeaseGrant:
        changed_at = now or datetime.now(UTC)
        if not lease_owner or execution_epoch < 1 or lease_ttl <= timedelta(0):
            raise ValueError("invalid lease heartbeat")
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                run = await self._run_unlocked(run_id)
                if (
                    run is None
                    or run.lease_owner != lease_owner
                    or run.execution_epoch != execution_epoch
                    or run.status not in {RunStatus.RUNNING, RunStatus.CANCELLING}
                    or run.lease_expires_at is None
                    or run.lease_expires_at <= changed_at
                    or run.deadline_at is None
                ):
                    raise RunLeaseLostError(run_id)
                lease_expires_at = changed_at + lease_ttl
                cursor = await self._connection.execute(
                    """
                    UPDATE runs SET lease_expires_at = ?, updated_at = ?
                    WHERE run_id = ? AND lease_owner = ? AND execution_epoch = ?
                      AND status IN (?, ?) AND lease_expires_at > ?
                    """,
                    (
                        _datetime_to_db(lease_expires_at),
                        _datetime_to_db(changed_at),
                        run_id,
                        lease_owner,
                        execution_epoch,
                        RunStatus.RUNNING.value,
                        RunStatus.CANCELLING.value,
                        _datetime_to_db(changed_at),
                    ),
                )
                updated = cursor.rowcount
                await cursor.close()
                if updated != 1:
                    raise RunLeaseLostError(run_id)
                await self._connection.commit()
                started = False
                return RunLeaseGrant(
                    task_id=run.task_id,
                    run_id=run_id,
                    lease_owner=lease_owner,
                    execution_epoch=execution_epoch,
                    lease_expires_at=lease_expires_at,
                    deadline_at=run.deadline_at,
                    status=run.status,
                    resume=True,
                )
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def fence_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        now: datetime | None = None,
    ) -> RunRecord:
        checked_at = now or datetime.now(UTC)
        async with self._lock:
            try:
                run = await self._run_unlocked(run_id)
                if (
                    run is None
                    or run.lease_owner != lease_owner
                    or run.execution_epoch != execution_epoch
                    or run.status not in {RunStatus.RUNNING, RunStatus.CANCELLING}
                    or run.lease_expires_at is None
                    or run.lease_expires_at <= checked_at
                ):
                    raise RunLeaseLostError(run_id)
                return run
            except DeepChoiceError:
                raise
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def add_checkpoint_reference(
        self,
        reference: CheckpointReference,
        *,
        lease_owner: str,
        execution_epoch: int,
        now: datetime | None = None,
    ) -> CheckpointReference:
        checked_at = now or datetime.now(UTC)
        if reference.execution_epoch != execution_epoch:
            raise RunLeaseLostError(reference.run_id)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                run = await self._run_unlocked(reference.run_id)
                if (
                    run is None
                    or run.lease_owner != lease_owner
                    or run.execution_epoch != execution_epoch
                    or run.status not in {RunStatus.RUNNING, RunStatus.CANCELLING}
                    or run.lease_expires_at is None
                    or run.lease_expires_at <= checked_at
                ):
                    raise RunLeaseLostError(reference.run_id)
                cursor = await self._connection.execute(
                    """
                    INSERT OR IGNORE INTO run_checkpoints(
                        run_id, checkpoint_ns, storage_checkpoint_ns,
                        checkpoint_id, node,
                        state_schema_version, execution_epoch, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reference.run_id,
                        reference.checkpoint_ns,
                        reference.storage_checkpoint_ns,
                        reference.checkpoint_id,
                        reference.node,
                        reference.state_schema_version,
                        reference.execution_epoch,
                        _datetime_to_db(reference.created_at),
                    ),
                )
                inserted = cursor.rowcount
                await cursor.close()
                if inserted == 1:
                    payload: dict[str, object] = {}
                    if reference.node is not None:
                        payload["node"] = reference.node
                    await self._append_event_unlocked(
                        task_id=run.task_id,
                        run_id=reference.run_id,
                        event_type="run.progress",
                        public_payload=payload,
                        created_at=reference.created_at,
                    )
                await self._connection.commit()
                started = False
                return reference
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def get_latest_checkpoint_reference(
        self,
        run_id: str,
        *,
        state_schema_version: int | None = None,
        checkpoint_ns: str | None = None,
    ) -> CheckpointReference | None:
        clauses = "run_id = ?"
        parameters: tuple[object, ...] = (run_id,)
        if state_schema_version is not None:
            clauses += " AND state_schema_version = ?"
            parameters += (state_schema_version,)
        if checkpoint_ns is not None:
            clauses += " AND checkpoint_ns = ?"
            parameters += (checkpoint_ns,)
        async with self._lock:
            try:
                row = await self._fetchone(
                    f"""
                    SELECT run_id, checkpoint_ns, storage_checkpoint_ns,
                           checkpoint_id, node,
                           state_schema_version, execution_epoch, created_at
                    FROM run_checkpoints WHERE {clauses}
                    ORDER BY execution_epoch DESC, created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    parameters,
                )
                if row is None:
                    return None
                return CheckpointReference(
                    run_id=str(row[0]),
                    checkpoint_ns=str(row[1]),
                    storage_checkpoint_ns=str(row[2]),
                    checkpoint_id=str(row[3]),
                    node=str(row[4]) if row[4] is not None else None,
                    state_schema_version=int(row[5]),
                    execution_epoch=int(row[6]),
                    created_at=_datetime_from_db(str(row[7])),
                )
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def get_task(self, task_id: str) -> TaskWithRun | None:
        async with self._lock:
            try:
                row = await self._fetchone(
                    f"""
                    SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
                    FROM tasks AS t
                    LEFT JOIN runs AS r ON r.run_id = t.latest_run_id
                    WHERE t.task_id = ?
                    """,
                    (task_id,),
                )
                return _joined_from_row(row) if row is not None else None
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._lock:
            try:
                row = await self._fetchone(
                    f"SELECT {_RUN_COLUMNS} FROM runs AS r WHERE r.run_id = ?",
                    (run_id,),
                )
                return _run_from_values(row) if row is not None else None
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def get_run_result(self, run_id: str) -> RunResultRecord | None:
        async with self._lock:
            try:
                row = await self._fetchone(
                    f"SELECT {_RESULT_COLUMNS} FROM run_results WHERE run_id = ?",
                    (run_id,),
                )
                return _result_from_values(row) if row is not None else None
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def list_task_events(
        self, task_id: str, *, after_event_id: int = 0, limit: int = 100
    ) -> tuple[TaskEventRecord, ...]:
        if type(after_event_id) is not int or after_event_id < 0:
            raise ValueError("after_event_id must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        async with self._lock:
            try:
                task = await self._fetchone(
                    "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
                )
                if task is None:
                    raise TaskNotFoundError(task_id)
                rows = await self._fetchall(
                    f"""
                    SELECT {_EVENT_COLUMNS} FROM task_events
                    WHERE task_id = ? AND event_id > ?
                    ORDER BY event_id ASC LIMIT ?
                    """,
                    (task_id, after_event_id, limit),
                )
                return tuple(_event_from_values(row) for row in rows)
            except DeepChoiceError:
                raise
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def get_task_event_cursor(
        self, task_id: str, *, cursor: int
    ) -> TaskEventCursor:
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        async with self._lock:
            try:
                task = await self._fetchone(
                    "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
                )
                if task is None:
                    raise TaskNotFoundError(task_id)
                bounds = await self._fetchone(
                    "SELECT MIN(event_id), MAX(event_id) FROM task_events WHERE task_id = ?",
                    (task_id,),
                )
                first = int(bounds[0]) if bounds and bounds[0] is not None else None
                latest = int(bounds[1]) if bounds and bounds[1] is not None else None
                owned = cursor == 0
                if cursor != 0:
                    owner = await self._fetchone(
                        "SELECT task_id FROM task_events WHERE event_id = ?", (cursor,)
                    )
                    owned = owner is not None and str(owner[0]) == task_id
                return TaskEventCursor(
                    task_id=task_id,
                    first_event_id=first,
                    latest_event_id=latest,
                    cursor=cursor,
                    cursor_valid=owned,
                )
            except DeepChoiceError:
                raise
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def record_legacy_import_failure(
        self,
        source_path: str,
        content_sha256: str,
        error_code: str,
        *,
        imported_at: datetime | None = None,
    ) -> LegacyImportRecord:
        self._validate_legacy_import_identity(source_path, content_sha256)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code):
            raise ValueError("error_code must be a safe stable code")
        changed_at = imported_at or datetime.now(UTC)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                existing = await self._legacy_import_unlocked(source_path, content_sha256)
                if existing is not None:
                    await self._connection.commit()
                    started = False
                    return existing.model_copy(update={"created": False})
                cursor = await self._connection.execute(
                    """
                    INSERT INTO legacy_imports(
                        source_path, content_sha256, outcome, task_id, run_id,
                        error_code, imported_at
                    ) VALUES (?, ?, 'error', NULL, NULL, ?, ?)
                    """,
                    (
                        source_path,
                        content_sha256,
                        error_code,
                        _datetime_to_db(changed_at),
                    ),
                )
                await cursor.close()
                result = await self._legacy_import_unlocked(source_path, content_sha256)
                await self._connection.commit()
                started = False
                if result is None:  # pragma: no cover
                    raise RepositoryOperationError(retryable=False)
                return result
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def import_legacy_task(
        self,
        source_path: str,
        content_sha256: str,
        task: TaskRecord,
        run: RunRecord,
        result: RunResultRecord | None = None,
        *,
        imported_at: datetime | None = None,
    ) -> LegacyImportRecord:
        self._validate_legacy_import_identity(source_path, content_sha256)
        if task.task_id != run.task_id or task.latest_run_id != run.run_id:
            raise ValueError("legacy task and run identifiers do not match")
        if task.status.value != run.status.value:
            raise ValueError("legacy task and run statuses must match")
        terminal = {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
            RunStatus.INTERRUPTED,
        }
        if run.status not in terminal:
            raise ValueError("legacy imports must describe a terminal run")
        if run.status in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS}:
            if result is None or result.run_id != run.run_id:
                raise ValueError("successful legacy imports require a matching result")
            if result.snapshot.get("report") != result.report or not result.report.strip():
                raise ValueError("legacy result report must be non-empty and match snapshot")
            if result.report_format != task.request.report_format:
                raise ValueError("legacy result format must match the task request")
        elif result is not None:
            raise ValueError("unsuccessful legacy imports cannot publish a result")
        changed_at = imported_at or datetime.now(UTC)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                existing = await self._legacy_import_unlocked(source_path, content_sha256)
                if existing is not None:
                    await self._connection.commit()
                    started = False
                    return existing.model_copy(update={"created": False})

                prior_source = await self._fetchone(
                    "SELECT 1 FROM legacy_imports WHERE source_path = ? LIMIT 1",
                    (source_path,),
                )
                conflict = await self._fetchone(
                    "SELECT 1 FROM tasks WHERE task_id = ? UNION ALL SELECT 1 FROM runs WHERE run_id = ? LIMIT 1",
                    (task.task_id, run.run_id),
                )
                error_code = (
                    "LEGACY_SOURCE_CHANGED"
                    if prior_source is not None
                    else "LEGACY_ID_CONFLICT"
                    if conflict is not None
                    else None
                )
                if error_code is not None:
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO legacy_imports(
                            source_path, content_sha256, outcome, task_id, run_id,
                            error_code, imported_at
                        ) VALUES (?, ?, 'error', NULL, NULL, ?, ?)
                        """,
                        (
                            source_path,
                            content_sha256,
                            error_code,
                            _datetime_to_db(changed_at),
                        ),
                    )
                    await cursor.close()
                else:
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO tasks(
                            task_id, status, request_json, latest_run_id,
                            cancel_requested_at, version, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task.task_id,
                            task.status.value,
                            task.request.model_dump_json(),
                            task.latest_run_id,
                            _datetime_to_db(task.cancel_requested_at)
                            if task.cancel_requested_at is not None
                            else None,
                            task.version,
                            _datetime_to_db(task.created_at),
                            _datetime_to_db(task.updated_at),
                        ),
                    )
                    await cursor.close()
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO runs(
                            run_id, task_id, status, manifest_json, thread_id,
                            checkpoint_ns, execution_epoch, lease_owner,
                            lease_expires_at, deadline_at, started_at, ended_at,
                            error_id, version, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run.run_id,
                            run.task_id,
                            run.status.value,
                            run.manifest.model_dump_json(),
                            run.thread_id,
                            run.checkpoint_ns,
                            run.execution_epoch,
                            None,
                            None,
                            _datetime_to_db(run.deadline_at)
                            if run.deadline_at is not None
                            else None,
                            _datetime_to_db(run.started_at)
                            if run.started_at is not None
                            else None,
                            _datetime_to_db(run.ended_at)
                            if run.ended_at is not None
                            else None,
                            run.error_id,
                            run.version,
                            _datetime_to_db(run.created_at),
                            _datetime_to_db(run.updated_at),
                        ),
                    )
                    await cursor.close()
                    if result is not None:
                        cursor = await self._connection.execute(
                            """
                            INSERT INTO run_results(
                                run_id, result_schema_version, snapshot_json,
                                report, report_format, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                result.run_id,
                                result.result_schema_version,
                                json.dumps(
                                    result.snapshot,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ),
                                result.report,
                                result.report_format,
                                _datetime_to_db(result.created_at),
                            ),
                        )
                        await cursor.close()
                    await self._append_event_unlocked(
                        task_id=task.task_id,
                        run_id=run.run_id,
                        event_type="legacy.imported",
                        public_payload={"status": run.status.value},
                        created_at=changed_at,
                    )
                    await self._append_event_unlocked(
                        task_id=task.task_id,
                        run_id=run.run_id,
                        event_type=f"run.{run.status.value}",
                        public_payload={"status": run.status.value},
                        created_at=changed_at,
                    )
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO legacy_imports(
                            source_path, content_sha256, outcome, task_id, run_id,
                            error_code, imported_at
                        ) VALUES (?, ?, 'imported', ?, ?, NULL, ?)
                        """,
                        (
                            source_path,
                            content_sha256,
                            task.task_id,
                            run.run_id,
                            _datetime_to_db(changed_at),
                        ),
                    )
                    await cursor.close()
                result = await self._legacy_import_unlocked(source_path, content_sha256)
                await self._connection.commit()
                started = False
                if result is None:  # pragma: no cover
                    raise RepositoryOperationError(retryable=False)
                return result
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def list_tasks(
        self,
        *,
        status: TaskStatus | None,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[TaskWithRun, ...]:
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        clauses: list[str] = []
        parameters: list[object] = []
        if status is not None:
            clauses.append("t.status = ?")
            parameters.append(status.value)
        if before is not None:
            before_created_at, before_task_id = before
            clauses.append("(t.created_at < ? OR (t.created_at = ? AND t.task_id < ?))")
            encoded_time = _datetime_to_db(before_created_at)
            parameters.extend((encoded_time, encoded_time, before_task_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)

        async with self._lock:
            try:
                rows = await self._fetchall(
                    f"""
                    SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
                    FROM tasks AS t
                    LEFT JOIN runs AS r ON r.run_id = t.latest_run_id
                    {where}
                    ORDER BY t.created_at DESC, t.task_id DESC
                    LIMIT ?
                    """,
                    tuple(parameters),
                )
                return tuple(_joined_from_row(row) for row in rows)
            except Exception as exc:
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def transition_current_run(
        self,
        task_id: str,
        *,
        expected_task_version: int,
        target_task_status: TaskStatus,
        target_run_status: RunStatus,
        updated_at: datetime | None = None,
    ) -> TaskWithRun:
        if type(expected_task_version) is not int or expected_task_version < 0:
            raise ValueError("expected_task_version must be a non-negative integer")
        if type(target_task_status) is not TaskStatus:
            raise TypeError("target_task_status must be TaskStatus")
        if type(target_run_status) is not RunStatus:
            raise TypeError("target_run_status must be RunStatus")
        if target_task_status.value != target_run_status.value:
            raise ValueError("task and run target statuses must match")
        changed_at = updated_at or datetime.now(UTC)

        async with self._lock:
            transaction_started = False
            try:
                cursor = await self._connection.execute("BEGIN IMMEDIATE")
                await cursor.close()
                transaction_started = True
                row = await self._fetchone(
                    f"""
                    SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
                    FROM tasks AS t
                    LEFT JOIN runs AS r ON r.run_id = t.latest_run_id
                    WHERE t.task_id = ?
                    """,
                    (task_id,),
                )
                if row is None:
                    raise TaskNotFoundError(task_id)
                current = _joined_from_row(row)
                if current.task.version != expected_task_version:
                    raise TaskVersionConflictError(
                        task_id,
                        expected=expected_task_version,
                        actual=current.task.version,
                    )
                if current.latest_run is None:
                    raise RunNotFoundError(current.task.latest_run_id or "")
                if current.task.status.value != current.latest_run.status.value:
                    raise RepositoryOperationError(retryable=False)

                ensure_task_transition_allowed(
                    current.task.status,
                    target_task_status,
                    intent=TaskTransitionIntent.SAME_RUN,
                )
                ensure_run_transition_allowed(
                    current.latest_run.status,
                    target_run_status,
                )
                encoded_changed_at = _datetime_to_db(changed_at)
                task_cursor = await self._connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, version = version + 1, updated_at = ?
                    WHERE task_id = ? AND version = ? AND latest_run_id = ?
                    """,
                    (
                        target_task_status.value,
                        encoded_changed_at,
                        task_id,
                        expected_task_version,
                        current.latest_run.run_id,
                    ),
                )
                try:
                    task_updated = task_cursor.rowcount
                finally:
                    await task_cursor.close()
                if task_updated != 1:
                    raise TaskVersionConflictError(
                        task_id,
                        expected=expected_task_version,
                        actual=current.task.version,
                    )
                run_cursor = await self._connection.execute(
                    """
                    UPDATE runs
                    SET status = ?, version = version + 1, updated_at = ?
                    WHERE run_id = ? AND version = ?
                    """,
                    (
                        target_run_status.value,
                        encoded_changed_at,
                        current.latest_run.run_id,
                        current.latest_run.version,
                    ),
                )
                try:
                    run_updated = run_cursor.rowcount
                finally:
                    await run_cursor.close()
                if run_updated != 1:
                    raise TaskVersionConflictError(
                        task_id,
                        expected=expected_task_version,
                        actual=current.task.version,
                    )

                updated_row = await self._fetchone(
                    f"""
                    SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
                    FROM tasks AS t
                    LEFT JOIN runs AS r ON r.run_id = t.latest_run_id
                    WHERE t.task_id = ?
                    """,
                    (task_id,),
                )
                if updated_row is None:  # pragma: no cover - guarded by transaction
                    raise TaskNotFoundError(task_id)
                await self._append_event_unlocked(
                    task_id=task_id,
                    run_id=current.latest_run.run_id,
                    event_type="run.status_changed",
                    public_payload={"status": target_run_status.value},
                    created_at=changed_at,
                )
                await self._connection.commit()
                transaction_started = False
                return _joined_from_row(updated_row)
            except asyncio.CancelledError:
                if transaction_started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if transaction_started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if transaction_started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def finalize_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        status: RunStatus,
        error_id: str | None = None,
        now: datetime | None = None,
    ) -> TaskWithRun:
        return await self._finalize_run_transaction(
            run_id,
            lease_owner=lease_owner,
            execution_epoch=execution_epoch,
            status=status,
            error_id=error_id,
            result=None,
            now=now,
        )

    async def finalize_run_with_result(
        self,
        run_id: str,
        result: RunResultRecord,
        *,
        lease_owner: str,
        execution_epoch: int,
        status: RunStatus = RunStatus.COMPLETED,
        now: datetime | None = None,
    ) -> TaskWithRun:
        if result.run_id != run_id:
            raise ValueError("result.run_id must match run_id")
        if result.snapshot.get("report") != result.report:
            raise ValueError("result report must match snapshot report")
        if not result.report.strip():
            raise ValueError("result report must be non-empty")
        if status not in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS}:
            raise ValueError("a run result requires a successful final status")
        return await self._finalize_run_transaction(
            run_id,
            lease_owner=lease_owner,
            execution_epoch=execution_epoch,
            status=status,
            error_id=None,
            result=result,
            now=now,
        )

    async def _finalize_run_transaction(
        self,
        run_id: str,
        *,
        lease_owner: str,
        execution_epoch: int,
        status: RunStatus,
        error_id: str | None,
        result: RunResultRecord | None,
        now: datetime | None,
    ) -> TaskWithRun:
        allowed = {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
            RunStatus.INTERRUPTED,
        }
        if status not in allowed:
            raise ValueError("finalize status is not supported")
        changed_at = now or datetime.now(UTC)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                run = await self._run_unlocked(run_id)
                current = (
                    await self._current_task_unlocked(run.task_id)
                    if run is not None
                    else None
                )
                if (
                    run is None
                    or current is None
                    or current.latest_run is None
                    or current.task.latest_run_id != run_id
                    or run.lease_owner != lease_owner
                    or run.execution_epoch != execution_epoch
                    or run.status not in {RunStatus.RUNNING, RunStatus.CANCELLING}
                    or run.lease_expires_at is None
                    or run.lease_expires_at <= changed_at
                ):
                    raise RunLeaseLostError(run_id)
                if (
                    current.task.cancel_requested_at is not None
                    or run.status is RunStatus.CANCELLING
                    or current.task.status is TaskStatus.CANCELLING
                ):
                    final_status = RunStatus.CANCELLED
                elif run.deadline_at is not None and run.deadline_at <= changed_at:
                    final_status = RunStatus.TIMED_OUT
                else:
                    final_status = status
                task_status = TaskStatus(final_status.value)
                encoded_now = _datetime_to_db(changed_at)
                ended_at = (
                    encoded_now
                    if final_status
                    in {
                        RunStatus.COMPLETED,
                        RunStatus.COMPLETED_WITH_WARNINGS,
                        RunStatus.FAILED,
                        RunStatus.TIMED_OUT,
                        RunStatus.CANCELLED,
                    }
                    else None
                )
                cursor = await self._connection.execute(
                    """
                    UPDATE runs
                    SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                        deadline_at = CASE WHEN ? = ? THEN NULL ELSE deadline_at END,
                        ended_at = ?, error_id = ?, version = version + 1, updated_at = ?
                    WHERE run_id = ? AND version = ? AND lease_owner = ?
                      AND execution_epoch = ? AND lease_expires_at > ?
                    """,
                    (
                        final_status.value,
                        final_status.value,
                        RunStatus.INTERRUPTED.value,
                        ended_at,
                        error_id,
                        encoded_now,
                        run_id,
                        run.version,
                        lease_owner,
                        execution_epoch,
                        encoded_now,
                    ),
                )
                updated = cursor.rowcount
                await cursor.close()
                if updated != 1:
                    raise RunLeaseLostError(run_id)
                cursor = await self._connection.execute(
                    """
                    UPDATE tasks SET status = ?, version = version + 1, updated_at = ?
                    WHERE task_id = ? AND latest_run_id = ? AND version = ?
                    """,
                    (
                        task_status.value,
                        encoded_now,
                        run.task_id,
                        run_id,
                        current.task.version,
                    ),
                )
                task_updated = cursor.rowcount
                await cursor.close()
                if task_updated != 1:
                    raise RunLeaseLostError(run_id)
                if (
                    result is not None
                    and final_status
                    in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS}
                ):
                    if result.report_format != current.task.request.report_format:
                        raise ValueError(
                            "result report_format must match the task request"
                        )
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO run_results(
                            run_id, result_schema_version, snapshot_json,
                            report, report_format, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result.run_id,
                            result.result_schema_version,
                            json.dumps(
                                result.snapshot,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            result.report,
                            result.report_format,
                            _datetime_to_db(result.created_at),
                        ),
                    )
                    await cursor.close()
                result = await self._current_task_unlocked(run.task_id)
                await self._append_event_unlocked(
                    task_id=run.task_id,
                    run_id=run_id,
                    event_type=f"run.{final_status.value}",
                    public_payload={"status": final_status.value},
                    created_at=changed_at,
                )
                await self._connection.commit()
                started = False
                if result is None:  # pragma: no cover
                    raise TaskNotFoundError(run.task_id)
                return result
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def cancel_task(
        self, task_id: str, *, updated_at: datetime | None = None
    ) -> TaskWithRun:
        changed_at = updated_at or datetime.now(UTC)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                current = await self._current_task_unlocked(task_id)
                if current is None:
                    raise TaskNotFoundError(task_id)
                if current.latest_run is None:
                    raise RunNotFoundError(current.task.latest_run_id or "")
                if current.task.status.value != current.latest_run.status.value:
                    raise RepositoryOperationError(retryable=False)
                if current.task.status in {
                    TaskStatus.CANCELLING,
                    TaskStatus.COMPLETED,
                    TaskStatus.COMPLETED_WITH_WARNINGS,
                    TaskStatus.FAILED,
                    TaskStatus.TIMED_OUT,
                    TaskStatus.CANCELLED,
                }:
                    await self._connection.commit()
                    started = False
                    return current
                target = (
                    TaskStatus.CANCELLING
                    if current.task.status is TaskStatus.RUNNING
                    else TaskStatus.CANCELLED
                )
                encoded_now = _datetime_to_db(changed_at)
                ended_at = encoded_now if target is TaskStatus.CANCELLED else None
                cursor = await self._connection.execute(
                    """
                    UPDATE tasks SET status = ?, cancel_requested_at = ?,
                        version = version + 1, updated_at = ?
                    WHERE task_id = ? AND version = ? AND latest_run_id = ?
                    """,
                    (
                        target.value,
                        encoded_now,
                        encoded_now,
                        task_id,
                        current.task.version,
                        current.latest_run.run_id,
                    ),
                )
                await cursor.close()
                cursor = await self._connection.execute(
                    """
                    UPDATE runs SET status = ?, ended_at = ?,
                        lease_owner = CASE WHEN ? = ? THEN NULL ELSE lease_owner END,
                        lease_expires_at = CASE WHEN ? = ? THEN NULL ELSE lease_expires_at END,
                        deadline_at = CASE WHEN ? = ? THEN NULL ELSE deadline_at END,
                        version = version + 1, updated_at = ?
                    WHERE run_id = ? AND version = ?
                    """,
                    (
                        target.value,
                        ended_at,
                        target.value,
                        TaskStatus.CANCELLED.value,
                        target.value,
                        TaskStatus.CANCELLED.value,
                        target.value,
                        TaskStatus.CANCELLED.value,
                        encoded_now,
                        current.latest_run.run_id,
                        current.latest_run.version,
                    ),
                )
                await cursor.close()
                result = await self._current_task_unlocked(task_id)
                await self._append_event_unlocked(
                    task_id=task_id,
                    run_id=current.latest_run.run_id,
                    event_type=(
                        "task.cancel_requested"
                        if target is TaskStatus.CANCELLING
                        else "task.cancelled"
                    ),
                    public_payload={"status": target.value},
                    created_at=changed_at,
                )
                await self._connection.commit()
                started = False
                if result is None:  # pragma: no cover
                    raise TaskNotFoundError(task_id)
                return result
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def resume_interrupted_run(
        self,
        task_id: str,
        *,
        expected_task_version: int,
        updated_at: datetime | None = None,
    ) -> TaskWithRun:
        changed_at = updated_at or datetime.now(UTC)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                current = await self._current_task_unlocked(task_id)
                if current is None:
                    raise TaskNotFoundError(task_id)
                if current.task.version != expected_task_version:
                    raise TaskVersionConflictError(
                        task_id, expected=expected_task_version, actual=current.task.version
                    )
                if current.latest_run is None:
                    raise RunNotFoundError(current.task.latest_run_id or "")
                ensure_task_transition_allowed(
                    current.task.status,
                    TaskStatus.QUEUED,
                    intent=TaskTransitionIntent.SAME_RUN,
                )
                ensure_run_transition_allowed(current.latest_run.status, RunStatus.QUEUED)
                checkpoint = await self._fetchone(
                    """
                    SELECT 1 FROM run_checkpoints
                    WHERE run_id = ? AND checkpoint_ns = ?
                      AND state_schema_version = ?
                    LIMIT 1
                    """,
                    (
                        current.latest_run.run_id,
                        current.latest_run.checkpoint_ns,
                        current.latest_run.manifest.state_schema_version,
                    ),
                )
                if (
                    checkpoint is None
                    or current.latest_run.manifest.workflow_version != "research-v1"
                ):
                    raise CheckpointNotAvailableError(current.latest_run.run_id)
                encoded_now = _datetime_to_db(changed_at)
                cursor = await self._connection.execute(
                    """
                    UPDATE tasks SET status = ?, cancel_requested_at = NULL,
                        version = version + 1, updated_at = ?
                    WHERE task_id = ? AND version = ? AND latest_run_id = ?
                    """,
                    (
                        TaskStatus.QUEUED.value,
                        encoded_now,
                        task_id,
                        expected_task_version,
                        current.latest_run.run_id,
                    ),
                )
                await cursor.close()
                cursor = await self._connection.execute(
                    """
                    UPDATE runs SET status = ?, lease_owner = NULL,
                        lease_expires_at = NULL, deadline_at = NULL,
                        ended_at = NULL, error_id = NULL,
                        version = version + 1, updated_at = ?
                    WHERE run_id = ? AND version = ?
                    """,
                    (
                        RunStatus.QUEUED.value,
                        encoded_now,
                        current.latest_run.run_id,
                        current.latest_run.version,
                    ),
                )
                await cursor.close()
                result = await self._current_task_unlocked(task_id)
                await self._append_event_unlocked(
                    task_id=task_id,
                    run_id=current.latest_run.run_id,
                    event_type="run.resumed",
                    public_payload={"status": RunStatus.QUEUED.value},
                    created_at=changed_at,
                )
                await self._connection.commit()
                started = False
                if result is None:  # pragma: no cover
                    raise TaskNotFoundError(task_id)
                return result
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def retry_task_with_run(
        self,
        task_id: str,
        run: RunRecord,
        *,
        expected_task_version: int,
        updated_at: datetime | None = None,
    ) -> TaskWithRun:
        changed_at = updated_at or datetime.now(UTC)
        if run.task_id != task_id or run.status is not RunStatus.QUEUED:
            raise ValueError("replacement run must be a queued run for this task")
        if run.thread_id != run.run_id or run.checkpoint_ns:
            raise ValueError("new run must use its run id and the root checkpoint namespace")
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                current = await self._current_task_unlocked(task_id)
                if current is None:
                    raise TaskNotFoundError(task_id)
                if current.task.version != expected_task_version:
                    raise TaskVersionConflictError(
                        task_id, expected=expected_task_version, actual=current.task.version
                    )
                ensure_task_transition_allowed(
                    current.task.status,
                    TaskStatus.QUEUED,
                    intent=TaskTransitionIntent.NEW_RUN,
                )
                encoded_now = _datetime_to_db(changed_at)
                cursor = await self._connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, task_id, status, manifest_json, thread_id,
                        checkpoint_ns, execution_epoch, lease_owner, lease_expires_at,
                        deadline_at, started_at, ended_at, error_id, version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        task_id,
                        run.status.value,
                        run.manifest.model_dump_json(),
                        run.thread_id,
                        run.checkpoint_ns,
                        run.execution_epoch,
                        run.lease_owner,
                        None,
                        None,
                        None,
                        None,
                        None,
                        run.version,
                        _datetime_to_db(run.created_at),
                        _datetime_to_db(run.updated_at),
                    ),
                )
                await cursor.close()
                cursor = await self._connection.execute(
                    """
                    UPDATE tasks SET status = ?, latest_run_id = ?,
                        cancel_requested_at = NULL, version = version + 1, updated_at = ?
                    WHERE task_id = ? AND version = ?
                    """,
                    (
                        TaskStatus.QUEUED.value,
                        run.run_id,
                        encoded_now,
                        task_id,
                        expected_task_version,
                    ),
                )
                updated = cursor.rowcount
                await cursor.close()
                if updated != 1:
                    raise TaskVersionConflictError(
                        task_id, expected=expected_task_version, actual=current.task.version
                    )
                result = await self._current_task_unlocked(task_id)
                await self._append_event_unlocked(
                    task_id=task_id,
                    run_id=run.run_id,
                    event_type="run.retry_queued",
                    public_payload={"status": RunStatus.QUEUED.value},
                    created_at=changed_at,
                )
                await self._connection.commit()
                started = False
                if result is None:  # pragma: no cover
                    raise TaskNotFoundError(task_id)
                return result
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None

    async def recover_runs(
        self, *, now: datetime | None = None
    ) -> tuple[RecoveryRun, ...]:
        """Project expired leases and return runs safe to submit."""

        changed_at = now or datetime.now(UTC)
        encoded_now = _datetime_to_db(changed_at)
        async with self._lock:
            started = False
            try:
                await self._begin()
                started = True
                rows = await self._fetchall(
                    f"""
                    SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
                    FROM tasks AS t JOIN runs AS r ON r.run_id = t.latest_run_id
                    WHERE r.status IN (?, ?)
                      AND (r.lease_expires_at IS NULL OR r.lease_expires_at <= ?)
                    """,
                    (
                        RunStatus.RUNNING.value,
                        RunStatus.CANCELLING.value,
                        encoded_now,
                    ),
                )
                for row in rows:
                    current = _joined_from_row(row)
                    run = current.latest_run
                    if run is None:  # pragma: no cover
                        continue
                    cancelled = (
                        current.task.cancel_requested_at is not None
                        or current.task.status is TaskStatus.CANCELLING
                        or run.status is RunStatus.CANCELLING
                    )
                    deadline_expired = (
                        run.deadline_at is not None and run.deadline_at <= changed_at
                    )
                    if cancelled:
                        target = RunStatus.CANCELLED
                    elif deadline_expired:
                        target = RunStatus.TIMED_OUT
                    else:
                        target = RunStatus.INTERRUPTED
                    ended_at = (
                        encoded_now
                        if target in {RunStatus.CANCELLED, RunStatus.TIMED_OUT}
                        else None
                    )
                    deadline_at = (
                        _datetime_to_db(run.deadline_at)
                        if target is RunStatus.TIMED_OUT and run.deadline_at is not None
                        else None
                    )
                    cursor = await self._connection.execute(
                        """
                        UPDATE runs SET status = ?, lease_owner = NULL,
                            lease_expires_at = NULL, deadline_at = ?, ended_at = ?,
                            version = version + 1, updated_at = ?
                        WHERE run_id = ? AND version = ?
                        """,
                        (
                            target.value,
                            deadline_at,
                            ended_at,
                            encoded_now,
                            run.run_id,
                            run.version,
                        ),
                    )
                    await cursor.close()
                    await self._append_event_unlocked(
                        task_id=current.task.task_id,
                        run_id=run.run_id,
                        event_type=f"run.{target.value}",
                        public_payload={"status": target.value, "reason": "startup_recovery"},
                        created_at=changed_at,
                    )
                    cursor = await self._connection.execute(
                        """
                        UPDATE tasks SET status = ?, version = version + 1, updated_at = ?
                        WHERE task_id = ? AND version = ? AND latest_run_id = ?
                        """,
                        (
                            TaskStatus(target.value).value,
                            encoded_now,
                            current.task.task_id,
                            current.task.version,
                            run.run_id,
                        ),
                    )
                    await cursor.close()
                interrupted = await self._fetchall(
                    f"""
                    SELECT {_TASK_COLUMNS}, {_RUN_COLUMNS}
                    FROM tasks AS t JOIN runs AS r ON r.run_id = t.latest_run_id
                    WHERE t.status = ? AND r.status = ?
                      AND EXISTS (
                        SELECT 1 FROM run_checkpoints AS rc
                        WHERE rc.run_id = r.run_id
                          AND rc.checkpoint_ns = r.checkpoint_ns
                          AND rc.state_schema_version = json_extract(
                              r.manifest_json, '$.state_schema_version')
                          AND json_extract(r.manifest_json, '$.workflow_version') = 'research-v1'
                      )
                    """,
                    (TaskStatus.INTERRUPTED.value, RunStatus.INTERRUPTED.value),
                )
                for row in interrupted:
                    current = _joined_from_row(row)
                    run = current.latest_run
                    if run is None:  # pragma: no cover
                        continue
                    cursor = await self._connection.execute(
                        """
                        UPDATE runs SET status = ?, deadline_at = NULL, ended_at = NULL,
                            error_id = NULL, version = version + 1, updated_at = ?
                        WHERE run_id = ? AND version = ?
                        """,
                        (RunStatus.QUEUED.value, encoded_now, run.run_id, run.version),
                    )
                    await cursor.close()
                    cursor = await self._connection.execute(
                        """
                        UPDATE tasks SET status = ?, version = version + 1, updated_at = ?
                        WHERE task_id = ? AND version = ? AND latest_run_id = ?
                        """,
                        (
                            TaskStatus.QUEUED.value,
                            encoded_now,
                            current.task.task_id,
                            current.task.version,
                            run.run_id,
                        ),
                    )
                    await cursor.close()
                    await self._append_event_unlocked(
                        task_id=current.task.task_id,
                        run_id=run.run_id,
                        event_type="run.auto_resumed",
                        public_payload={
                            "status": RunStatus.QUEUED.value,
                            "reason": "startup_recovery",
                        },
                        created_at=changed_at,
                    )

                queued = await self._fetchall(
                    """
                    SELECT t.task_id, r.run_id,
                           EXISTS (
                             SELECT 1 FROM run_checkpoints AS rc
                             WHERE rc.run_id = r.run_id
                               AND rc.checkpoint_ns = r.checkpoint_ns
                               AND rc.state_schema_version = json_extract(
                                   r.manifest_json, '$.state_schema_version')
                               AND json_extract(r.manifest_json, '$.workflow_version') = 'research-v1'
                           )
                    FROM tasks AS t JOIN runs AS r ON r.run_id = t.latest_run_id
                    WHERE t.status = ? AND r.status = ?
                    ORDER BY t.created_at, t.task_id
                    """,
                    (TaskStatus.QUEUED.value, RunStatus.QUEUED.value),
                )
                await self._connection.commit()
                started = False
                return tuple(
                    RecoveryRun(task_id=str(row[0]), run_id=str(row[1]), resume=bool(row[2]))
                    for row in queued
                )
            except asyncio.CancelledError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except DeepChoiceError:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise
            except Exception as exc:
                if started or self._connection.in_transaction:
                    await self._rollback()
                raise RepositoryOperationError(retryable=_is_locked_error(exc)) from None


__all__ = [
    "CheckpointNotAvailableError",
    "RepositoryOperationError",
    "RunNotFoundError",
    "RunLeaseLostError",
    "RunRepository",
    "SQLiteTaskRunRepository",
    "TaskNotFoundError",
    "TaskRepository",
    "TaskVersionConflictError",
]
