"""Fenced SQLite persistence for best-effort execution traces."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import aiosqlite

from deepchoice.persistence.database import _await_cleanup
from deepchoice.security.redaction import redact_value

from .contracts import (
    ExternalCall,
    ExternalCallKind,
    NodeAttempt,
    RunTrace,
    TraceEvent,
    TraceStatus,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _datetime_to_db(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _summary_json(value) -> str:
    return json.dumps(
        redact_value(value.to_dict()),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class StaleTraceAuthorityError(RuntimeError):
    """The trace was rejected because this execution no longer owns the run."""


T = TypeVar("T")


class SQLiteTraceStore:
    """Share the product connection while keeping trace transactions isolated."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._connection = connection
        self._lock = lock
        self._clock = clock

    def bind(
        self, *, run_id: str, execution_epoch: int, lease_owner: str
    ) -> "SQLiteTraceSink":
        return SQLiteTraceSink(
            self._connection,
            self._lock,
            run_id=run_id,
            execution_epoch=execution_epoch,
            lease_owner=lease_owner,
            clock=self._clock,
        )


class SQLiteTraceSink:
    """A run-bound, fenced TraceSink with atomic event sequencing."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock,
        *,
        run_id: str,
        execution_epoch: int,
        lease_owner: str,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._connection = connection
        self._lock = lock
        self.run_id = run_id
        self.execution_epoch = execution_epoch
        self.lease_owner = lease_owner
        self._clock = clock

    async def _fetchone(
        self, sql: str, parameters: tuple[object, ...]
    ) -> tuple[object, ...] | None:
        cursor = await self._connection.execute(sql, parameters)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def _execute(
        self, sql: str, parameters: tuple[object, ...]
    ) -> None:
        cursor = await self._connection.execute(sql, parameters)
        await cursor.close()

    async def _assert_authority(self) -> None:
        row = await self._fetchone(
            """
            SELECT 1 FROM runs
            WHERE run_id = ? AND execution_epoch = ? AND lease_owner = ?
              AND status IN ('running', 'cancelling')
            """,
            (self.run_id, self.execution_epoch, self.lease_owner),
        )
        if row is None:
            raise StaleTraceAuthorityError("trace authority is stale")

    async def _transaction(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            began = False
            try:
                await self._execute("BEGIN IMMEDIATE", ())
                began = True
                await self._assert_authority()
                result = await operation()
                await self._connection.commit()
                return result
            except asyncio.CancelledError:
                if began:
                    await _await_cleanup(self._connection.rollback())
                raise
            except Exception:
                if began:
                    await _await_cleanup(self._connection.rollback())
                raise

    async def _next_seq(self) -> int:
        row = await self._fetchone(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_events WHERE run_id = ?",
            (self.run_id,),
        )
        return int(row[0]) if row is not None else 1

    async def _append_event(
        self,
        event_type: str,
        *,
        node_attempt_id: str | None = None,
        call_id: str | None = None,
        summary=None,
        created_at: datetime | None = None,
    ) -> None:
        from deepchoice.contracts.safe_json import SafeJsonObject

        safe_summary = SafeJsonObject.from_mapping(summary or {})
        await self._execute(
            """
            INSERT INTO trace_events(
                run_id, execution_epoch, seq, event_type,
                node_attempt_id, call_id, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.run_id,
                self.execution_epoch,
                await self._next_seq(),
                event_type,
                node_attempt_id,
                call_id,
                _summary_json(safe_summary),
                _datetime_to_db(created_at or self._clock()),
            ),
        )

    def _check_identity(self, run_id: str, execution_epoch: int) -> None:
        if run_id != self.run_id or execution_epoch != self.execution_epoch:
            raise StaleTraceAuthorityError("trace identity does not match bound run")

    async def start_node_attempt(self, node_name: str) -> NodeAttempt:
        async def operation() -> NodeAttempt:
            row = await self._fetchone(
                """
                SELECT COALESCE(MAX(attempt_no), 0) + 1
                FROM node_attempts
                WHERE run_id = ? AND execution_epoch = ? AND node_name = ?
                """,
                (self.run_id, self.execution_epoch, node_name),
            )
            attempt = NodeAttempt(
                node_attempt_id=str(uuid.uuid4()),
                run_id=self.run_id,
                execution_epoch=self.execution_epoch,
                node_name=node_name,
                attempt_no=int(row[0]) if row is not None else 1,
                status=TraceStatus.STARTED,
                started_at=self._clock(),
            )
            await self._insert_node(attempt)
            await self._append_event(
                "node.started",
                node_attempt_id=attempt.node_attempt_id,
                summary={"node_name": node_name, "attempt_no": attempt.attempt_no},
                created_at=attempt.started_at,
            )
            return attempt

        return await self._transaction(operation)

    async def finish_node_attempt(
        self,
        started: NodeAttempt,
        *,
        status: TraceStatus,
        summary: dict | None = None,
    ) -> NodeAttempt:
        if status is TraceStatus.STARTED:
            raise ValueError("terminal node status is required")
        self._check_identity(started.run_id, started.execution_epoch)
        ended_at = self._clock()
        terminal = NodeAttempt(
            node_attempt_id=started.node_attempt_id,
            run_id=started.run_id,
            execution_epoch=started.execution_epoch,
            node_name=started.node_name,
            attempt_no=started.attempt_no,
            status=status,
            started_at=started.started_at,
            ended_at=ended_at,
            summary=summary or {},
        )

        async def operation() -> NodeAttempt:
            cursor = await self._connection.execute(
                """
                UPDATE node_attempts
                SET status = ?, ended_at = ?, summary_json = ?
                WHERE node_attempt_id = ? AND run_id = ? AND execution_epoch = ?
                  AND status = 'started'
                """,
                (
                    terminal.status.value,
                    _datetime_to_db(ended_at),
                    _summary_json(terminal.summary),
                    terminal.node_attempt_id,
                    self.run_id,
                    self.execution_epoch,
                ),
            )
            changed = cursor.rowcount
            await cursor.close()
            if changed != 1:
                raise RuntimeError("node attempt is missing or already terminal")
            await self._append_event(
                f"node.{status.value}",
                node_attempt_id=terminal.node_attempt_id,
                summary={"node_name": terminal.node_name, **(summary or {})},
                created_at=ended_at,
            )
            return terminal

        return await self._transaction(operation)

    async def start_external_call(
        self,
        *,
        node_attempt_id: str,
        kind: ExternalCallKind,
        provider: str,
        operation: str,
        request_summary: dict | None = None,
    ) -> ExternalCall:
        async def transaction() -> ExternalCall:
            node = await self._fetchone(
                """
                SELECT 1 FROM node_attempts
                WHERE run_id = ? AND execution_epoch = ?
                  AND node_attempt_id = ? AND status = 'started'
                """,
                (self.run_id, self.execution_epoch, node_attempt_id),
            )
            if node is None:
                raise RuntimeError("external call requires an active node attempt")
            row = await self._fetchone(
                """
                SELECT COALESCE(MAX(call_no), 0) + 1
                FROM external_calls
                WHERE run_id = ? AND node_attempt_id = ?
                """,
                (self.run_id, node_attempt_id),
            )
            call = ExternalCall(
                call_id=str(uuid.uuid4()),
                run_id=self.run_id,
                execution_epoch=self.execution_epoch,
                node_attempt_id=node_attempt_id,
                call_no=int(row[0]) if row is not None else 1,
                kind=kind,
                provider=provider,
                operation=operation,
                status=TraceStatus.STARTED,
                started_at=self._clock(),
                request_summary=request_summary or {},
            )
            await self._insert_call(call)
            await self._append_event(
                "call.started",
                node_attempt_id=node_attempt_id,
                call_id=call.call_id,
                summary={
                    "kind": kind.value,
                    "provider": provider,
                    "operation": operation,
                    "call_no": call.call_no,
                },
                created_at=call.started_at,
            )
            return call

        return await self._transaction(transaction)

    async def finish_external_call(
        self,
        started: ExternalCall,
        *,
        status: TraceStatus,
        result_summary: dict | None = None,
        usage_summary: dict | None = None,
    ) -> ExternalCall:
        if status is TraceStatus.STARTED:
            raise ValueError("terminal call status is required")
        self._check_identity(started.run_id, started.execution_epoch)
        ended_at = self._clock()
        terminal = ExternalCall(
            call_id=started.call_id,
            run_id=started.run_id,
            execution_epoch=started.execution_epoch,
            node_attempt_id=started.node_attempt_id,
            call_no=started.call_no,
            kind=started.kind,
            provider=started.provider,
            operation=started.operation,
            status=status,
            started_at=started.started_at,
            ended_at=ended_at,
            request_summary=started.request_summary,
            result_summary=result_summary or {},
            usage_summary=usage_summary or {},
        )

        async def transaction() -> ExternalCall:
            cursor = await self._connection.execute(
                """
                UPDATE external_calls
                SET status = ?, ended_at = ?, result_summary_json = ?,
                    usage_summary_json = ?
                WHERE call_id = ? AND run_id = ? AND execution_epoch = ?
                  AND node_attempt_id = ? AND status = 'started'
                """,
                (
                    status.value,
                    _datetime_to_db(ended_at),
                    _summary_json(terminal.result_summary),
                    _summary_json(terminal.usage_summary),
                    terminal.call_id,
                    self.run_id,
                    self.execution_epoch,
                    terminal.node_attempt_id,
                ),
            )
            changed = cursor.rowcount
            await cursor.close()
            if changed != 1:
                raise RuntimeError("external call is missing or already terminal")
            await self._append_event(
                f"call.{status.value}",
                node_attempt_id=terminal.node_attempt_id,
                call_id=terminal.call_id,
                summary={
                    "kind": terminal.kind.value,
                    "provider": terminal.provider,
                    "operation": terminal.operation,
                    **(result_summary or {}),
                },
                created_at=ended_at,
            )
            return terminal

        return await self._transaction(transaction)

    async def _insert_node(self, attempt: NodeAttempt) -> None:
        await self._execute(
            """
            INSERT INTO node_attempts(
                node_attempt_id, run_id, execution_epoch, node_name, attempt_no,
                status, started_at, ended_at, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.node_attempt_id,
                attempt.run_id,
                attempt.execution_epoch,
                attempt.node_name,
                attempt.attempt_no,
                attempt.status.value,
                _datetime_to_db(attempt.started_at),
                _datetime_to_db(attempt.ended_at) if attempt.ended_at else None,
                _summary_json(attempt.summary),
            ),
        )

    async def _insert_call(self, call: ExternalCall) -> None:
        await self._execute(
            """
            INSERT INTO external_calls(
                call_id, run_id, execution_epoch, node_attempt_id, call_no,
                kind, provider, operation, status, started_at, ended_at,
                request_summary_json, result_summary_json, usage_summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call.call_id,
                call.run_id,
                call.execution_epoch,
                call.node_attempt_id,
                call.call_no,
                call.kind.value,
                call.provider,
                call.operation,
                call.status.value,
                _datetime_to_db(call.started_at),
                _datetime_to_db(call.ended_at) if call.ended_at else None,
                _summary_json(call.request_summary),
                _summary_json(call.result_summary),
                _summary_json(call.usage_summary),
            ),
        )

    async def record_run(self, trace: RunTrace) -> None:
        self._check_identity(trace.run_id, trace.execution_epoch)

        async def operation() -> None:
            await self._append_event(
                f"run_trace.{trace.status.value}",
                summary={"trace_id": trace.trace_id, **trace.summary.to_dict()},
                created_at=trace.ended_at or trace.started_at,
            )

        await self._transaction(operation)

    async def record_node_attempt(self, attempt: NodeAttempt) -> None:
        self._check_identity(attempt.run_id, attempt.execution_epoch)
        if attempt.status is TraceStatus.STARTED:
            async def operation() -> None:
                await self._insert_node(attempt)
                await self._append_event(
                    "node.started",
                    node_attempt_id=attempt.node_attempt_id,
                    summary={"node_name": attempt.node_name},
                    created_at=attempt.started_at,
                )
            await self._transaction(operation)
            return

        async def finish_operation() -> None:
            cursor = await self._connection.execute(
                """
                UPDATE node_attempts
                SET status = ?, ended_at = ?, summary_json = ?
                WHERE node_attempt_id = ? AND run_id = ? AND execution_epoch = ?
                  AND status = 'started'
                """,
                (
                    attempt.status.value,
                    _datetime_to_db(attempt.ended_at),
                    _summary_json(attempt.summary),
                    attempt.node_attempt_id,
                    self.run_id,
                    self.execution_epoch,
                ),
            )
            changed = cursor.rowcount
            await cursor.close()
            if changed != 1:
                raise RuntimeError("node attempt is missing or already terminal")
            await self._append_event(
                f"node.{attempt.status.value}",
                node_attempt_id=attempt.node_attempt_id,
                summary={"node_name": attempt.node_name},
                created_at=attempt.ended_at,
            )

        await self._transaction(finish_operation)

    async def record_external_call(self, call: ExternalCall) -> None:
        self._check_identity(call.run_id, call.execution_epoch)
        if call.status is TraceStatus.STARTED:
            async def operation() -> None:
                await self._insert_call(call)
                await self._append_event(
                    "call.started",
                    node_attempt_id=call.node_attempt_id,
                    call_id=call.call_id,
                    summary={"provider": call.provider, "operation": call.operation},
                    created_at=call.started_at,
                )
            await self._transaction(operation)
            return

        async def finish_operation() -> None:
            cursor = await self._connection.execute(
                """
                UPDATE external_calls
                SET status = ?, ended_at = ?, result_summary_json = ?,
                    usage_summary_json = ?
                WHERE call_id = ? AND run_id = ? AND execution_epoch = ?
                  AND node_attempt_id = ? AND status = 'started'
                """,
                (
                    call.status.value,
                    _datetime_to_db(call.ended_at),
                    _summary_json(call.result_summary),
                    _summary_json(call.usage_summary),
                    call.call_id,
                    self.run_id,
                    self.execution_epoch,
                    call.node_attempt_id,
                ),
            )
            changed = cursor.rowcount
            await cursor.close()
            if changed != 1:
                raise RuntimeError("external call is missing or already terminal")
            await self._append_event(
                f"call.{call.status.value}",
                node_attempt_id=call.node_attempt_id,
                call_id=call.call_id,
                summary={"provider": call.provider, "operation": call.operation},
                created_at=call.ended_at,
            )

        await self._transaction(finish_operation)

    async def record_event(self, event: TraceEvent) -> None:
        self._check_identity(event.run_id, event.execution_epoch)

        async def operation() -> None:
            await self._execute(
                """
                INSERT INTO trace_events(
                    run_id, execution_epoch, seq, event_type,
                    node_attempt_id, call_id, summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.execution_epoch,
                    event.seq,
                    event.event_type,
                    event.node_attempt_id,
                    event.call_id,
                    _summary_json(event.summary),
                    _datetime_to_db(event.created_at),
                ),
            )

        await self._transaction(operation)


__all__ = ["SQLiteTraceSink", "SQLiteTraceStore", "StaleTraceAuthorityError"]
