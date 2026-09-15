"""Out-of-band identity and service ports for one fenced run execution.

``RunContext`` must never be inserted into ``ResearchState`` or LangGraph
checkpoints.  A later phase will bind it with ``ContextVar`` at execution
boundaries.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Iterator, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deepchoice.budget import BudgetManager
from deepchoice.observability import TraceSink, TraceStatus

if TYPE_CHECKING:
    from deepchoice.persistence.records import RunRecord


@runtime_checkable
class CancellationPort(Protocol):
    async def raise_if_cancelled(self) -> None: ...


@runtime_checkable
class AsyncEventPort(Protocol):
    async def wait(self) -> bool: ...


@runtime_checkable
class RetrievalFlightClaim(Protocol):
    is_leader: bool
    invocation: tuple[object, bool] | None
    error: Exception | None
    retry: bool
    released: AsyncEventPort


@runtime_checkable
class RetrievalCachePort(Protocol):
    enabled: bool

    def make_key(self, *, source: str, request: object, manifest_id: str) -> str: ...

    async def get(self, cache_key: str) -> object | None: ...

    async def put(self, cache_key: str, result: object, *, source: str) -> bool: ...

    async def claim(
        self, run_id: str, cache_key: str
    ) -> RetrievalFlightClaim: ...

    async def wait(self, claim: RetrievalFlightClaim) -> None: ...

    def publish(
        self,
        claim: RetrievalFlightClaim,
        *,
        invocation: tuple[object, bool] | None = None,
        error: Exception | None = None,
        retry: bool = False,
    ) -> None: ...

    async def complete(
        self, run_id: str, cache_key: str, claim: RetrievalFlightClaim
    ) -> None: ...


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
    retrieval_cache: RetrievalCachePort | None = None

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
        retrieval_cache: RetrievalCachePort | None = None,
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
            retrieval_cache=retrieval_cache,
        )


_current_run_context: ContextVar[RunContext | None] = ContextVar(
    "deepchoice_run_context", default=None
)
_current_node_attempt_id: ContextVar[str | None] = ContextVar(
    "deepchoice_node_attempt_id", default=None
)


def get_run_context() -> RunContext | None:
    """Return the out-of-band durable run context for the current async task."""

    return _current_run_context.get()


def get_node_attempt_id() -> str | None:
    return _current_node_attempt_id.get()


def classify_cancelled_trace_status(
    context: RunContext | None = None,
    *,
    now: datetime | None = None,
) -> TraceStatus:
    """Distinguish an asyncio deadline cancellation from user/shutdown cancel.

    ``asyncio.timeout`` injects ``CancelledError`` into the inner operation and
    only converts it to ``TimeoutError`` after control leaves the context.  The
    persisted, timezone-aware run deadline is therefore the stable signal at
    node/call boundaries.  Equality belongs to the timed-out side.
    """

    active = context if context is not None else get_run_context()
    if active is None:
        return TraceStatus.CANCELLED
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return (
        TraceStatus.TIMED_OUT
        if observed_at >= active.deadline_at
        else TraceStatus.CANCELLED
    )


@contextmanager
def bind_run_context(context: RunContext) -> Iterator[None]:
    """Bind context without ever adding it to ResearchState/checkpoints."""

    context_token = _current_run_context.set(context)
    node_token = _current_node_attempt_id.set(None)
    try:
        yield
    finally:
        _current_node_attempt_id.reset(node_token)
        _current_run_context.reset(context_token)


@contextmanager
def bind_node_attempt(node_attempt_id: str | None) -> Iterator[None]:
    token = _current_node_attempt_id.set(node_attempt_id)
    try:
        yield
    finally:
        _current_node_attempt_id.reset(token)


__all__ = [
    "AsyncEventPort",
    "CancellationPort",
    "RetrievalCachePort",
    "RetrievalFlightClaim",
    "RunContext",
    "bind_node_attempt",
    "bind_run_context",
    "classify_cancelled_trace_status",
    "get_node_attempt_id",
    "get_run_context",
]
