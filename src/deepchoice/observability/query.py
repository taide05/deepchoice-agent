"""Read-only, public-safe latest-run Trace projection."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime

import aiosqlite

from deepchoice.contracts.api import (
    ObservabilityBudgetResourceResponse,
    ObservabilityBudgetSummaryResponse,
    ObservabilityExternalCallResponse,
    ObservabilityNodeAttemptResponse,
    ObservabilityTotalsResponse,
    TaskObservabilityResponse,
)
from deepchoice.persistence.repository import TaskNotFoundError


_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
_FAILURE_STATUSES = {"failed", "timed_out", "unknown"}
_BUDGET_RESOURCES = {
    "input_tokens", "output_tokens", "total_tokens", "cost_micro_usd",
    "llm_calls", "retrieval_calls", "http_calls", "active_milliseconds",
    "wall_clock_milliseconds",
}
_BUDGET_DENIAL_ERROR_IDS = {
    "RUN_BUDGET_EXCEEDED",
    "BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE",
}


def _unavailable_budget(
    *, admission_denied: bool = False, denied_resource: str | None = None
) -> ObservabilityBudgetSummaryResponse:
    return ObservabilityBudgetSummaryResponse(
        availability="unavailable",
        admission_denied=admission_denied,
        denied_resource=denied_resource,
        price_availability="unavailable",
    )


def _policy_summary(value: str) -> tuple[dict[str, int], dict[str, object]] | None:
    """Parse only versioned public policy fields and positive integer limits."""

    try:
        policy = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(policy, dict):
        return None
    version = policy.get("policy_version")
    tier = policy.get("tier")
    mode = policy.get("enforcement_mode")
    ratio = policy.get("soft_limit_ratio")
    price_version = policy.get("price_catalog_version")
    limits = policy.get("hard_limits")
    if (
        version not in {"standard-observe-v1", "standard-enforced-v1"}
        or tier != "standard"
        or mode not in {"observe_only", "enforced"}
        or type(ratio) not in {float, int}
        or not 0 < ratio <= 1
        or not isinstance(price_version, str)
        or not isinstance(limits, dict)
    ):
        return None
    configured = {
        key: amount
        for key, amount in limits.items()
        if key in _BUDGET_RESOURCES and type(amount) is int and amount > 0
    }
    return configured, {
        "policy_version": version,
        "tier": tier,
        "enforcement_mode": mode,
        "soft_limit_ratio": float(ratio),
        "price_catalog_version": price_version,
    }


def _budget_summary(
    *,
    policy_json: str | None,
    ledger_rows: list[tuple[str, str, int, int | None, str]],
    admission_denied: bool = False,
    denied_resource: str | None = None,
) -> ObservabilityBudgetSummaryResponse:
    if policy_json is None:
        return _unavailable_budget(
            admission_denied=admission_denied, denied_resource=denied_resource
        )
    parsed = _policy_summary(policy_json)
    if parsed is None:
        return _unavailable_budget(
            admission_denied=admission_denied, denied_resource=denied_resource
        )
    limits, metadata = parsed

    usage: dict[str, dict[str, int]] = {}
    cost_unpriced = metadata["price_catalog_version"] == "unpriced-v1"
    for resource, status, reserved_amount, actual_amount, price_status in ledger_rows:
        if resource not in _BUDGET_RESOURCES:
            continue
        if resource == "cost_micro_usd" and price_status == "unknown":
            cost_unpriced = True
        totals = usage.setdefault(
            resource, {"settled": 0, "unknown_spend": 0, "reserved": 0}
        )
        if status == "reserved":
            totals["reserved"] += reserved_amount
        elif status == "settled":
            totals["settled"] += actual_amount or 0
        elif status == "unknown_spend":
            totals["unknown_spend"] += actual_amount or 0

    resources: dict[str, ObservabilityBudgetResourceResponse] = {}
    for resource, limit in limits.items():
        if resource == "cost_micro_usd" and cost_unpriced:
            resources[resource] = ObservabilityBudgetResourceResponse(
                availability="unavailable"
            )
            continue
        amounts = usage.get(
            resource, {"settled": 0, "unknown_spend": 0, "reserved": 0}
        )
        consumed = sum(amounts.values())
        resources[resource] = ObservabilityBudgetResourceResponse(
            availability="available",
            hard_limit=limit,
            settled=amounts["settled"],
            unknown_spend=amounts["unknown_spend"],
            reserved=amounts["reserved"],
            remaining=max(0, limit - consumed),
            soft_limit_reached=consumed >= limit * float(metadata["soft_limit_ratio"]),
            exhausted=consumed >= limit,
        )
    if cost_unpriced and "cost_micro_usd" not in resources:
        resources["cost_micro_usd"] = ObservabilityBudgetResourceResponse(
            availability="unavailable"
        )
    return ObservabilityBudgetSummaryResponse(
        availability="available",
        policy_version=metadata["policy_version"],
        tier=metadata["tier"],
        enforcement_mode=metadata["enforcement_mode"],
        soft_limit_ratio=metadata["soft_limit_ratio"],
        admission_denied=admission_denied,
        denied_resource=denied_resource,
        price_availability="unavailable" if cost_unpriced else "priced",
        resources=resources,
    )


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
            budget=_unavailable_budget(),
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
                    "SELECT execution_epoch, status, error_id FROM runs WHERE run_id = ? AND task_id = ?",
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
                run_error_id = str(run_row[2]) if run_row[2] is not None else None
                denied_resource: str | None = None
                marker_denied = False
                cursor = await self._connection.execute(
                    """
                    SELECT json_extract(snapshot_json, '$.budget_limited.limited'),
                           json_extract(snapshot_json, '$.budget_limited.exhausted_resource'),
                           json_extract(snapshot_json, '$.budget_limited.reason'),
                           json_extract(snapshot_json, '$.budget_limited.minimum_evidence_met'),
                           json_extract(snapshot_json, '$.budget_limited.policy_version')
                    FROM run_results WHERE run_id = ?
                    """,
                    (run_id,),
                )
                result_marker = await cursor.fetchone()
                await cursor.close()
                if result_marker is not None:
                    (
                        marker_limited,
                        marker_resource,
                        marker_reason,
                        marker_has_minimum_evidence,
                        marker_policy_version,
                    ) = result_marker
                    marker_denied = (
                        marker_limited in (1, True)
                        and marker_reason == "RUN_BUDGET_EXCEEDED"
                        and marker_has_minimum_evidence in (1, True)
                        and marker_policy_version
                        in {"standard-observe-v1", "standard-enforced-v1"}
                    )
                    if (
                        marker_denied
                        and isinstance(marker_resource, str)
                        and marker_resource in _BUDGET_RESOURCES
                    ):
                        denied_resource = marker_resource
                admission_denied = marker_denied or (
                    run_status == "failed"
                    and run_error_id in _BUDGET_DENIAL_ERROR_IDS
                )

                cursor = await self._connection.execute(
                    "SELECT policy_json FROM run_budget_policies WHERE run_id = ?",
                    (run_id,),
                )
                policy_row = await cursor.fetchone()
                await cursor.close()
                has_budget_policy = policy_row is not None
                policy_json = str(policy_row[0]) if policy_row is not None else None

                ledger_rows: list[tuple[str, str, int, int | None, str]] = []
                if has_budget_policy:
                    cursor = await self._connection.execute(
                        """
                        WITH ranked AS (
                            SELECT resource, status, reserved_amount, actual_amount,
                                   price_status,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY execution_epoch, reservation_id
                                       ORDER BY entry_sequence DESC
                                   ) AS row_no
                            FROM budget_ledger WHERE run_id = ?
                        )
                        SELECT resource, status, reserved_amount, actual_amount,
                               price_status
                        FROM ranked WHERE row_no = 1
                        """,
                        (run_id,),
                    )
                    rows = await cursor.fetchall()
                    await cursor.close()
                    ledger_rows = [
                        (
                            str(row[0]),
                            str(row[1]),
                            int(row[2]),
                            int(row[3]) if row[3] is not None else None,
                            str(row[4]),
                        )
                        for row in rows
                    ]

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
            budget=_budget_summary(
                policy_json=policy_json,
                ledger_rows=ledger_rows,
                admission_denied=admission_denied,
                denied_resource=denied_resource,
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
