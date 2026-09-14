"""Immutable typed records stored in the product database."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_id: str | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class TaskWithRun(_FrozenRecord):
    """A task and the run referenced by its ``latest_run_id``."""

    task: TaskRecord
    latest_run: RunRecord | None


__all__ = ["RunRecord", "TaskRecord", "TaskWithRun"]
