"""Out-of-band identity and service ports for one fenced run execution.

``RunContext`` must never be inserted into ``ResearchState`` or LangGraph
checkpoints.  A later phase will bind it with ``ContextVar`` at execution
boundaries.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deepchoice.budget import BudgetManager
from deepchoice.observability import TraceSink

if TYPE_CHECKING:
    from deepchoice.persistence.records import RunRecord


@runtime_checkable
class CancellationPort(Protocol):
    async def raise_if_cancelled(self) -> None: ...


class RunContext(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    deadline_at: datetime
    cancellation: CancellationPort
    trace: TraceSink
    budget: BudgetManager

    @field_validator("deadline_at")
    @classmethod
    def _deadline_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline_at must be timezone-aware")
        return value

    @classmethod
    def from_run_record(
        cls,
        run: "RunRecord",
        *,
        cancellation: CancellationPort,
        trace: TraceSink,
        budget: BudgetManager,
    ) -> "RunContext":
        """Build identity only from a persisted, currently running run record."""

        if run.status.value != "running":
            raise ValueError("RunContext requires a running RunRecord")
        if run.execution_epoch < 1:
            raise ValueError("RunContext requires a fenced execution epoch")
        if run.deadline_at is None:
            raise ValueError("RunContext requires a persisted deadline_at")
        return cls(
            task_id=run.task_id,
            run_id=run.run_id,
            manifest_id=run.manifest.manifest_id,
            execution_epoch=run.execution_epoch,
            deadline_at=run.deadline_at,
            cancellation=cancellation,
            trace=trace,
            budget=budget,
        )


__all__ = ["CancellationPort", "RunContext"]
