"""Best-effort runtime facade over the fenced SQLite trace sink."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from .contracts import (
    ExternalCall,
    ExternalCallKind,
    NodeAttempt,
    RunTrace,
    TraceEvent,
    TraceStatus,
)
from .sqlite import SQLiteTraceSink


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeTraceRecorder:
    """Turn sink failures into missing telemetry, never task failures."""

    def __init__(self, sink: SQLiteTraceSink, *, task_id: str) -> None:
        self.sink = sink
        self.task_id = task_id
        self.trace_id = str(uuid.uuid4())
        self.started_at = _utc_now()

    async def _best_effort(self, awaitable):
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    async def start_run(self) -> None:
        await self.record_run(
            RunTrace(
                trace_id=self.trace_id,
                task_id=self.task_id,
                run_id=self.sink.run_id,
                execution_epoch=self.sink.execution_epoch,
                status=TraceStatus.STARTED,
                started_at=self.started_at,
            )
        )

    async def finish_run(self, status: TraceStatus) -> None:
        now = _utc_now()
        await self.record_run(
            RunTrace(
                trace_id=self.trace_id,
                task_id=self.task_id,
                run_id=self.sink.run_id,
                execution_epoch=self.sink.execution_epoch,
                status=status,
                started_at=self.started_at,
                ended_at=now,
            )
        )

    async def start_node_attempt(self, node_name: str) -> NodeAttempt | None:
        return await self._best_effort(self.sink.start_node_attempt(node_name))

    async def finish_node_attempt(
        self,
        started: NodeAttempt | None,
        *,
        status: TraceStatus,
        summary: dict | None = None,
    ) -> None:
        if started is None:
            return
        await self._best_effort(
            self.sink.finish_node_attempt(started, status=status, summary=summary)
        )

    async def start_external_call(
        self,
        *,
        node_attempt_id: str | None,
        kind: ExternalCallKind,
        provider: str,
        operation: str,
        request_summary: dict | None = None,
    ) -> ExternalCall | None:
        if node_attempt_id is None:
            return None
        return await self._best_effort(
            self.sink.start_external_call(
                node_attempt_id=node_attempt_id,
                kind=kind,
                provider=provider,
                operation=operation,
                request_summary=request_summary,
            )
        )

    async def finish_external_call(
        self,
        started: ExternalCall | None,
        *,
        status: TraceStatus,
        result_summary: dict | None = None,
        usage_summary: dict | None = None,
    ) -> None:
        if started is None:
            return
        await self._best_effort(
            self.sink.finish_external_call(
                started,
                status=status,
                result_summary=result_summary,
                usage_summary=usage_summary,
            )
        )

    # TraceSink compatibility. Direct callers receive the same best-effort
    # behavior as the production wrappers.
    async def record_run(self, trace: RunTrace) -> None:
        await self._best_effort(self.sink.record_run(trace))

    async def record_node_attempt(self, attempt: NodeAttempt) -> None:
        await self._best_effort(self.sink.record_node_attempt(attempt))

    async def record_external_call(self, call: ExternalCall) -> None:
        await self._best_effort(self.sink.record_external_call(call))

    async def record_event(self, event: TraceEvent) -> None:
        await self._best_effort(self.sink.record_event(event))


def current_trace_recorder() -> tuple[RuntimeTraceRecorder | None, str | None]:
    """Resolve recorder/node identity without creating a checkpoint dependency."""

    from deepchoice.runtime.context import get_node_attempt_id, get_run_context

    context = get_run_context()
    if context is None or not isinstance(context.trace, RuntimeTraceRecorder):
        return None, None
    return context.trace, get_node_attempt_id()


__all__ = ["RuntimeTraceRecorder", "current_trace_recorder"]
