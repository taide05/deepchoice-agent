"""Immutable typed records stored in the product database."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import RunManifest
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


class _FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskRecord(_FrozenRecord):
    """One durable user research intent."""

    task_id: str = Field(min_length=1)
    status: TaskStatus
    request: ResearchRequest
    latest_run_id: str | None = Field(default=None, min_length=1)
    cancel_requested_at: datetime | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class RunRecord(_FrozenRecord):
    """One manifest-bound execution attempt for a task."""

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: RunStatus
    manifest: RunManifest
    thread_id: str = Field(min_length=1)
    checkpoint_ns: str = ""
    execution_epoch: int = Field(default=0, ge=0)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    deadline_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_id: str | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class CheckpointReference(_FrozenRecord):
    """A product-owned reference to one durable LangGraph checkpoint."""

    run_id: str = Field(min_length=1)
    checkpoint_ns: str = ""
    storage_checkpoint_ns: str = ""
    checkpoint_id: str = Field(min_length=1)
    node: str | None = None
    state_schema_version: int = Field(gt=0)
    execution_epoch: int = Field(ge=1)
    created_at: datetime


class RunLeaseGrant(_FrozenRecord):
    """A fencing token granted to exactly one execution attempt."""

    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    lease_owner: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    lease_expires_at: datetime
    deadline_at: datetime
    status: RunStatus
    resume: bool = False


class RecoveryRun(_FrozenRecord):
    """A queued run selected by startup/periodic recovery."""

    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    resume: bool = False


class TaskWithRun(_FrozenRecord):
    """A task and the run referenced by its ``latest_run_id``."""

    task: TaskRecord
    latest_run: RunRecord | None


class TaskEventRecord(_FrozenRecord):
    """One public, replayable lifecycle event for a task."""

    event_id: int = Field(gt=0)
    task_id: str = Field(min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    seq: int = Field(gt=0)
    type: str = Field(min_length=1)
    public_payload: dict[str, JsonValue]
    created_at: datetime


class TaskEventCursor(_FrozenRecord):
    """Bounds and ownership result for a task-scoped SSE cursor."""

    task_id: str = Field(min_length=1)
    first_event_id: int | None = Field(default=None, gt=0)
    latest_event_id: int | None = Field(default=None, gt=0)
    cursor: int = Field(ge=0)
    cursor_valid: bool


class LegacyImportRecord(_FrozenRecord):
    """A safe audit record for one legacy snapshot import attempt."""

    source_path: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["imported", "error"]
    task_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    error_code: str | None = Field(default=None, min_length=1)
    imported_at: datetime
    created: bool = True


__all__ = [
    "CheckpointReference",
    "LegacyImportRecord",
    "RecoveryRun",
    "RunLeaseGrant",
    "RunRecord",
    "TaskRecord",
    "TaskEventCursor",
    "TaskEventRecord",
    "TaskWithRun",
]
