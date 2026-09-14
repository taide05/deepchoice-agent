"""Task/run repository contracts and their single-connection SQLite adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
from .records import RunRecord, TaskRecord, TaskWithRun


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


@runtime_checkable
class RunRepository(Protocol):
    async def get_run(self, run_id: str) -> RunRecord | None: ...


_TASK_COLUMNS = """
t.task_id, t.status, t.request_json, t.latest_run_id,
t.cancel_requested_at, t.version, t.created_at, t.updated_at
""".strip()

_RUN_COLUMNS = """
r.run_id, r.task_id, r.status, r.manifest_json, r.thread_id,
r.checkpoint_ns, r.execution_epoch, r.lease_owner, r.lease_expires_at,
r.started_at, r.ended_at, r.error_id, r.version, r.created_at, r.updated_at
""".strip()


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
        started_at=_datetime_from_db(str(values[9]) if values[9] is not None else None),
        ended_at=_datetime_from_db(str(values[10]) if values[10] is not None else None),
        error_id=str(values[11]) if values[11] is not None else None,
        version=int(values[12]),
        created_at=_datetime_from_db(str(values[13])),
        updated_at=_datetime_from_db(str(values[14])),
    )


def _joined_from_row(row: tuple[object, ...]) -> TaskWithRun:
    task = _task_from_values(row[:8])
    run = _run_from_values(row[8:]) if row[8] is not None else None
    return TaskWithRun(task=task, latest_run=run)


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
                        lease_expires_at, started_at, ended_at, error_id,
                        version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


__all__ = [
    "RepositoryOperationError",
    "RunNotFoundError",
    "RunRepository",
    "SQLiteTaskRunRepository",
    "TaskNotFoundError",
    "TaskRepository",
    "TaskVersionConflictError",
]
