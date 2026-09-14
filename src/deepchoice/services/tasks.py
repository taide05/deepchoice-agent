"""Task application service and opaque history pagination."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence.records import RunRecord, TaskRecord, TaskWithRun
from deepchoice.persistence.repository import (
    CheckpointNotAvailableError,
    TaskNotFoundError,
    TaskRepository,
    TaskVersionConflictError,
)
from deepchoice.runtime.lifecycle import (
    RunStatus,
    TaskStatus,
    TaskTransitionIntent,
    ensure_task_transition_allowed,
)


class TaskPage(BaseModel):
    """One stable keyset-paginated page of task history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[TaskWithRun, ...]
    next_cursor: str | None = None


class InvalidTaskCursorError(DeepChoiceError):
    def __init__(self) -> None:
        super().__init__(
            "The task history cursor is invalid.",
            category=ErrorCategory.VALIDATION,
            code="INVALID_TASK_CURSOR",
            status_code=422,
            retryable=False,
            action="Restart pagination without a cursor.",
            scope="task_history",
        )


class InvalidTaskLimitError(DeepChoiceError):
    def __init__(self) -> None:
        super().__init__(
            "The task history limit must be between 1 and 100.",
            category=ErrorCategory.VALIDATION,
            code="INVALID_TASK_LIMIT",
            status_code=422,
            retryable=False,
            action="Use a limit from 1 through 100.",
            scope="task_history",
        )


def _datetime_to_cursor(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _encode_cursor(position: tuple[datetime, str]) -> str:
    payload = json.dumps(
        {"created_at": _datetime_to_cursor(position[0]), "task_id": position[1]},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    if not isinstance(cursor, str) or not cursor:
        raise InvalidTaskCursorError()
    try:
        raw = cursor.encode("ascii")
        raw += b"=" * (-len(raw) % 4)
        decoded = base64.b64decode(raw, altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"created_at", "task_id"}:
            raise ValueError
        if not isinstance(payload["created_at"], str):
            raise ValueError
        if not isinstance(payload["task_id"], str) or not payload["task_id"]:
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at.astimezone(UTC), payload["task_id"]
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error):
        raise InvalidTaskCursorError() from None


class TaskService:
    """Create and query durable tasks without starting research execution."""

    def __init__(
        self,
        repository: TaskRepository,
        *,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._uuid_factory = uuid_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(self, request: ResearchRequest) -> TaskWithRun:
        task_id = str(self._uuid_factory())
        run_id = str(self._uuid_factory())
        created_at = self._clock()
        manifest = build_run_manifest(request.model_dump(exclude_none=True))
        task = TaskRecord(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            request=request,
            latest_run_id=run_id,
            version=0,
            created_at=created_at,
            updated_at=created_at,
        )
        run = RunRecord(
            run_id=run_id,
            task_id=task_id,
            status=RunStatus.QUEUED,
            manifest=manifest,
            thread_id=run_id,
            checkpoint_ns="",
            version=0,
            created_at=created_at,
            updated_at=created_at,
        )
        return await self._repository.create_task_with_run(task, run)

    async def get(self, task_id: str) -> TaskWithRun:
        result = await self._repository.get_task(task_id)
        if result is None:
            raise TaskNotFoundError(task_id)
        return result

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> TaskPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidTaskLimitError()
        if status is not None and type(status) is not TaskStatus:
            raise TypeError("status must be TaskStatus or None")
        before = _decode_cursor(cursor) if cursor is not None else None
        records = await self._repository.list_tasks(
            status=status,
            before=before,
            limit=limit + 1,
        )
        items = records[:limit]
        next_cursor = None
        if len(records) > limit and items:
            last = items[-1].task
            next_cursor = _encode_cursor((last.created_at, last.task_id))
        return TaskPage(items=items, next_cursor=next_cursor)

    async def transition(
        self,
        task_id: str,
        *,
        expected_task_version: int,
        target_status: TaskStatus,
    ) -> TaskWithRun:
        if type(target_status) is not TaskStatus:
            raise TypeError("target_status must be TaskStatus")
        return await self._repository.transition_current_run(
            task_id,
            expected_task_version=expected_task_version,
            target_task_status=target_status,
            target_run_status=RunStatus(target_status.value),
            updated_at=self._clock(),
        )

    async def cancel(self, task_id: str) -> TaskWithRun:
        return await self._repository.cancel_task(task_id, updated_at=self._clock())

    async def resume(
        self, task_id: str, *, expected_task_version: int
    ) -> TaskWithRun:
        if type(expected_task_version) is not int or expected_task_version < 0:
            raise ValueError("expected_task_version must be a non-negative integer")
        current = await self.get(task_id)
        if current.task.version != expected_task_version:
            raise TaskVersionConflictError(
                task_id,
                expected=expected_task_version,
                actual=current.task.version,
            )
        if current.task.status is TaskStatus.INTERRUPTED:
            latest_run = current.latest_run
            if latest_run is None:
                raise TaskNotFoundError(task_id)
            checkpoint = await self._repository.get_latest_checkpoint_reference(
                latest_run.run_id,
                state_schema_version=latest_run.manifest.state_schema_version,
                checkpoint_ns=latest_run.checkpoint_ns,
            )
            if (
                checkpoint is not None
                and latest_run.manifest.workflow_version == "research-v1"
            ):
                try:
                    return await self._repository.resume_interrupted_run(
                        task_id,
                        expected_task_version=expected_task_version,
                        updated_at=self._clock(),
                    )
                except CheckpointNotAvailableError:
                    # A concurrent checkpoint change makes this a new-run retry.
                    pass
        if current.task.status in {
            TaskStatus.INTERRUPTED,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
        }:
            ensure_task_transition_allowed(
                current.task.status,
                TaskStatus.QUEUED,
                intent=TaskTransitionIntent.NEW_RUN,
            )
            run_id = str(self._uuid_factory())
            created_at = self._clock()
            request_payload = current.task.request.model_dump(exclude_none=True)
            replacement = RunRecord(
                run_id=run_id,
                task_id=task_id,
                status=RunStatus.QUEUED,
                manifest=build_run_manifest(request_payload),
                thread_id=run_id,
                checkpoint_ns="",
                version=0,
                created_at=created_at,
                updated_at=created_at,
            )
            return await self._repository.retry_task_with_run(
                task_id,
                replacement,
                expected_task_version=expected_task_version,
                updated_at=created_at,
            )
        ensure_task_transition_allowed(current.task.status, TaskStatus.QUEUED)
        raise AssertionError("unreachable lifecycle transition")


__all__ = [
    "InvalidTaskCursorError",
    "InvalidTaskLimitError",
    "TaskPage",
    "TaskService",
]
