"""Read-only, public-safe latest-run Trace projection."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime

import aiosqlite

from deepchoice.contracts.api import (
    ObservabilityExternalCallResponse,
    ObservabilityNodeAttemptResponse,
    ObservabilityTotalsResponse,
    TaskObservabilityResponse,
)
from deepchoice.persistence.repository import TaskNotFoundError


_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
_FAILURE_STATUSES = {"failed", "timed_out", "unknown"}


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration_ms(start: str, end: str | None) -> int | None:
    started_at = _parse_datetime(start)
    ended_at = _parse_datetime(end)
    if started_at is None or ended_at is None:
        return None
    return max(0, round((ended_at - started_at).total_seconds() * 1000))


def _safe_usage(value: str) -> dict[str, int]:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        field: token_count
        for field in _TOKEN_FIELDS
        if type(token_count := decoded.get(field)) is int and token_count >= 0
    }


def _safe_retry_no(value: str) -> int | None:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    retry_no = decoded.get("retry_no")
    return retry_no if type(retry_no) is int and retry_no >= 0 else None


def _project_status(
    status: str,
    *,
    row_epoch: int,
    current_epoch: int,
    run_status: str,
) -> str:
    if status != "started":
        return status
    if row_epoch < current_epoch or run_status == "interrupted":
        return "interrupted"
    if run_status not in {"running", "cancelling"}:
        return "unknown"
    return "started"


class SQLiteObservabilityQuery:
    """Expose aggregate run Trace through the product SQLite database only."""

    def __init__(
        self, connection: aiosqlite.Connection, lock: asyncio.Lock
    ) -> None:
        self._connection = connection
        self._lock = lock

    @staticmethod
    def unavailable(
        task_id: str,
        *,
        reason: str,
        run_id: str | None = None,
        budget_policy_reason: str | None = None,
    ) -> TaskObservabilityResponse:
        return TaskObservabilityResponse(
            task_id=task_id,
            run_id=run_id,
            availability="unavailable",
            unavailable_reason=reason,
            budget_policy_availability="unavailable",
            budget_policy_unavailable_reason=budget_policy_reason or reason,
            totals=ObservabilityTotalsResponse(
                node_attempts=0,
                node_retries=0,
                external_calls=0,
                failed_calls=0,
                llm_calls=0,
                retrieval_calls=0,
                token_usage_complete=False,
            ),
        )

    async def for_task(self, task_id: str) -> TaskObservabilityResponse:
        """Read latest-run identity, status, policy, and Trace in one snapshot."""

        async with self._lock:
            began = False
            try:
                await self._connection.execute("BEGIN")
                began = True
                cursor = await self._connection.execute(
                    "SELECT latest_run_id FROM tasks WHERE task_id = ?",
                    (task_id,),
                )
                task_row = await cursor.fetchone()
                await cursor.close()
                if task_row is None:
                    raise TaskNotFoundError(task_id)
                run_id = str(task_row[0]) if task_row[0] is not None else None
                if run_id is None:
                    await self._connection.commit()
                    return self.unavailable(
                        task_id,
                        reason="no_latest_run",
                        budget_policy_reason="no_latest_run",
                    )

                cursor = await self._connection.execute(
                    "SELECT execution_epoch, status FROM runs WHERE run_id = ? AND task_id = ?",
                    (run_id, task_id),
                )
                run_row = await cursor.fetchone()
                await cursor.close()
                if run_row is None:
                    await self._connection.commit()
                    return self.unavailable(
                        task_id,
                        run_id=run_id,
                        reason="latest_run_missing",
                        budget_policy_reason="latest_run_missing",
                    )
                current_epoch = int(run_row[0])
                run_status = str(run_row[1])

                cursor = await self._connection.execute(
                    "SELECT 1 FROM run_budget_policies WHERE run_id = ?", (run_id,)
                )
                has_budget_policy = await cursor.fetchone() is not None
                await cursor.close()

                cursor = await self._connection.execute(
                    """
                    SELECT node_attempt_id, execution_epoch, node_name, status,
                           started_at, ended_at
                    FROM node_attempts
                    WHERE run_id = ?
                    ORDER BY execution_epoch, started_at, node_name, attempt_no
                    """,
                    (run_id,),
                )
                node_rows = await cursor.fetchall()
                await cursor.close()

                cursor = await self._connection.execute(
                    """
                    SELECT ec.kind, ec.provider, ec.operation, ec.call_no,
                           ec.status, ec.started_at, ec.ended_at,
                           ec.usage_summary_json, ec.request_summary_json,
                           na.node_name, na.node_attempt_id, na.execution_epoch
                    FROM external_calls AS ec
                    JOIN node_attempts AS na
                      ON na.run_id = ec.run_id
                     AND na.execution_epoch = ec.execution_epoch
                     AND na.node_attempt_id = ec.node_attempt_id
                    WHERE ec.run_id = ?
                    ORDER BY ec.execution_epoch, ec.started_at, na.node_name,
                             na.attempt_no, ec.call_no, ec.call_id
                    """,
                    (run_id,),
                )
                call_rows = await cursor.fetchall()
                await cursor.close()
                await self._connection.commit()
            except BaseException:
                if began:
                    await self._connection.rollback()
                raise

        seen_attempts: Counter[str] = Counter()
        attempt_numbers: dict[str, int] = {}
        nodes: list[ObservabilityNodeAttemptResponse] = []
        for row in node_rows:
            attempt_id = str(row[0])
            row_epoch = int(row[1])
            name = str(row[2])
            # Attempt numbers in storage restart at a new fenced epoch. The
            # public run-level ordinal stays monotonic without exposing epochs.
            seen_attempts[name] += 1
            attempt_numbers[attempt_id] = seen_attempts[name]
            nodes.append(
                ObservabilityNodeAttemptResponse(
                    node_name=name,
                    attempt_no=seen_attempts[name],
                    status=_project_status(
                        str(row[3]),
                        row_epoch=row_epoch,
                        current_epoch=current_epoch,
                        run_status=run_status,
                    ),
                    started_at=_parse_datetime(str(row[4])),
                    ended_at=_parse_datetime(str(row[5])) if row[5] is not None else None,
                    duration_ms=_duration_ms(str(row[4]), str(row[5]) if row[5] else None),
                )
            )

        calls: list[ObservabilityExternalCallResponse] = []
        usages: list[tuple[str, dict[str, int]]] = []
        for row in call_rows:
            kind = str(row[0])
            retry_no = _safe_retry_no(str(row[8]))
            row_epoch = int(row[11])
            status = _project_status(
                str(row[4]),
                row_epoch=row_epoch,
                current_epoch=current_epoch,
                run_status=run_status,
            )
            usage = _safe_usage(str(row[7]))
            if kind == "llm":
                usages.append((status, usage))
            calls.append(
                ObservabilityExternalCallResponse(
                    kind=kind,
                    node_name=str(row[9]),
                    node_attempt_no=attempt_numbers[str(row[10])],
                    retry_no=retry_no,
                    provider=str(row[1]),
                    operation=str(row[2]),
                    call_no=int(row[3]),
                    status=status,
                    started_at=_parse_datetime(str(row[5])),
                    ended_at=_parse_datetime(str(row[6])) if row[6] is not None else None,
                    duration_ms=_duration_ms(str(row[5]), str(row[6]) if row[6] else None),
                    usage=usage or None,
                )
            )

        name_counts = Counter(node.node_name for node in nodes)
        llm_calls = sum(call.kind == "llm" for call in calls)
        retrieval_calls = sum(call.kind == "retrieval" for call in calls)
        known_tokens = {
            field: sum(usage[field] for _, usage in usages if field in usage)
            if any(field in usage for _, usage in usages)
            else None
            for field in _TOKEN_FIELDS
        }
        usage_complete = bool(usages) and all(
            all(field in usage for field in _TOKEN_FIELDS)
            for _, usage in usages
        )
        trace_available = bool(nodes or calls)
        return TaskObservabilityResponse(
            task_id=task_id,
            run_id=run_id,
            availability="available" if trace_available else "unavailable",
            unavailable_reason=None if trace_available else "trace_not_recorded",
            budget_policy_availability=(
                "available" if has_budget_policy else "unavailable"
            ),
            budget_policy_unavailable_reason=(
                None if has_budget_policy else "historical_run"
            ),
            nodes=tuple(nodes),
            calls=tuple(calls),
            totals=ObservabilityTotalsResponse(
                node_attempts=len(nodes),
                node_retries=sum(max(0, count - 1) for count in name_counts.values()),
                external_calls=len(calls),
                failed_calls=sum(call.status in _FAILURE_STATUSES for call in calls),
                llm_calls=llm_calls,
                retrieval_calls=retrieval_calls,
                **known_tokens,
                token_usage_complete=usage_complete,
            ),
        )


__all__ = ["SQLiteObservabilityQuery"]
