"""Public-safe trace contracts for later observability wiring.

Only compact JSON summaries belong in these contracts.  Prompts, model
responses, request headers, secret-bearing queries, raw exceptions, checkpoint
identifiers, and checkpoint state are prohibited.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deepchoice.contracts.safe_json import SafeJsonObject, coerce_safe_json_object


def _validate_trace_interval(
    status: "TraceStatus", started_at: datetime, ended_at: datetime | None
) -> None:
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must be timezone-aware")
    if ended_at is not None:
        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("ended_at must be timezone-aware")
        if ended_at < started_at:
            raise ValueError("ended_at cannot precede started_at")
    if (status is TraceStatus.STARTED) != (ended_at is None):
        raise ValueError("ended_at must match the trace lifecycle status")


class _TraceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TraceStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class ExternalCallKind(StrEnum):
    LLM = "llm"
    RETRIEVAL = "retrieval"
    HTTP = "http"
    OTHER = "other"


class RunTrace(_TraceContract):
    schema_version: Literal[1] = 1
    trace_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None = None
    summary: SafeJsonObject = Field(default_factory=SafeJsonObject)

    _safe_summary = field_validator("summary", mode="before")(coerce_safe_json_object)

    @model_validator(mode="after")
    def _valid_interval(self) -> "RunTrace":
        _validate_trace_interval(self.status, self.started_at, self.ended_at)
        return self


class NodeAttempt(_TraceContract):
    schema_version: Literal[1] = 1
    node_attempt_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    node_name: str = Field(min_length=1)
    attempt_no: int = Field(ge=1)
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None = None
    summary: SafeJsonObject = Field(default_factory=SafeJsonObject)

    _safe_summary = field_validator("summary", mode="before")(coerce_safe_json_object)

    @model_validator(mode="after")
    def _valid_interval(self) -> "NodeAttempt":
        _validate_trace_interval(self.status, self.started_at, self.ended_at)
        return self


class ExternalCall(_TraceContract):
    schema_version: Literal[1] = 1
    call_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    node_attempt_id: str = Field(min_length=1)
    call_no: int = Field(ge=1)
    kind: ExternalCallKind
    provider: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None = None
    request_summary: SafeJsonObject = Field(default_factory=SafeJsonObject)
    result_summary: SafeJsonObject = Field(default_factory=SafeJsonObject)
    usage_summary: SafeJsonObject = Field(default_factory=SafeJsonObject)

    _safe_summaries = field_validator(
        "request_summary", "result_summary", "usage_summary",
        mode="before",
    )(coerce_safe_json_object)

    @model_validator(mode="after")
    def _valid_interval(self) -> "ExternalCall":
        _validate_trace_interval(self.status, self.started_at, self.ended_at)
        return self


class TraceEvent(_TraceContract):
    schema_version: Literal[1] = 1
    trace_event_id: int | None = Field(default=None, ge=1)
    run_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    seq: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    node_attempt_id: str | None = Field(default=None, min_length=1)
    call_id: str | None = Field(default=None, min_length=1)
    summary: SafeJsonObject = Field(default_factory=SafeJsonObject)
    created_at: datetime

    _safe_summary = field_validator("summary", mode="before")(coerce_safe_json_object)

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


@runtime_checkable
class TraceSink(Protocol):
    """Best-effort trace port; implementations must accept safe DTOs only."""

    async def record_run(self, trace: RunTrace) -> None: ...

    async def record_node_attempt(self, attempt: NodeAttempt) -> None: ...

    async def record_external_call(self, call: ExternalCall) -> None: ...

    async def record_event(self, event: TraceEvent) -> None: ...


__all__ = [
    "ExternalCall",
    "ExternalCallKind",
    "NodeAttempt",
    "RunTrace",
    "TraceEvent",
    "TraceSink",
    "TraceStatus",
]
