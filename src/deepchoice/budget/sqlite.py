"""Fenced append-only SQLite budget accounting for one durable run."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

import aiosqlite
from pydantic import JsonValue, ValidationError

from deepchoice.contracts.safe_json import SafeJsonObject
from deepchoice.persistence.database import _await_cleanup
from deepchoice.security.redaction import redact_value

from .contracts import (
    BudgetAmount,
    BudgetEnforcementMode,
    BudgetReservation,
    BudgetResource,
    ReservationStatus,
    RunBudgetPolicy,
)
from .pricing import PriceStatus
from .errors import (
    BudgetExceededError,
    BudgetPersistenceError,
    StaleBudgetAuthorityError,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_db(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _from_db(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _summary_json(value: dict[str, JsonValue] | None) -> str:
    safe = SafeJsonObject.from_mapping(value or {})
    return json.dumps(
        redact_value(safe.to_dict()),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


T = TypeVar("T")


class SQLiteBudgetStore:
    """Factory sharing the product connection and its transaction lock."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock,
        *,
        clock: Callable[[], datetime] = _utc_now,
        reservation_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if reservation_ttl <= timedelta(0):
            raise ValueError("reservation_ttl must be positive")
        self._connection = connection
        self._lock = lock
        self._clock = clock
        self._reservation_ttl = reservation_ttl

    def bind(
        self,
        *,
        run_id: str,
        execution_epoch: int,
        lease_owner: str,
        policy: RunBudgetPolicy,
        run_started_at: datetime,
        execution_started_at: datetime | None = None,
    ) -> "SQLiteBudgetManager":
        return SQLiteBudgetManager(
            self._connection,
            self._lock,
            run_id=run_id,
            execution_epoch=execution_epoch,
            lease_owner=lease_owner,
            policy=policy,
            run_started_at=run_started_at,
            execution_started_at=execution_started_at,
            clock=self._clock,
            reservation_ttl=self._reservation_ttl,
        )


class SQLiteBudgetManager:
    """Run-bound budget gate using append-only lifecycle entries."""

    execution_enabled = True

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock,
        *,
        run_id: str,
        execution_epoch: int,
        lease_owner: str,
        policy: RunBudgetPolicy,
        run_started_at: datetime,
        execution_started_at: datetime | None = None,
        clock: Callable[[], datetime] = _utc_now,
        reservation_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if run_started_at.tzinfo is None or run_started_at.utcoffset() is None:
            raise ValueError("run_started_at must be timezone-aware")
        self._connection = connection
        self._lock = lock
        self.run_id = run_id
        self.execution_epoch = execution_epoch
        self.lease_owner = lease_owner
        self.policy = policy
        self.run_started_at = run_started_at
        self.execution_started_at = execution_started_at or clock()
        if (
            self.execution_started_at.tzinfo is None
            or self.execution_started_at.utcoffset() is None
        ):
            raise ValueError("execution_started_at must be timezone-aware")
        self._clock = clock
        self._reservation_ttl = reservation_ttl
        self._exhausted: BudgetExceededError | None = None
        self._active_recorded: BudgetReservation | None = None

    @property
    def exhausted(self) -> BudgetExceededError | None:
        return self._exhausted

    def default_expires_at(self) -> datetime:
        return self._clock() + self._reservation_ttl

    async def _fetchone(self, sql: str, params: tuple[object, ...]):
        cursor = await self._connection.execute(sql, params)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def _fetchall(self, sql: str, params: tuple[object, ...]):
        cursor = await self._connection.execute(sql, params)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()

    async def _execute(self, sql: str, params: tuple[object, ...]) -> None:
        cursor = await self._connection.execute(sql, params)
        await cursor.close()

    async def _assert_authority(
        self, now: datetime, *, require_running: bool
    ) -> None:
        row = await self._fetchone(
            """
            SELECT r.lease_expires_at, p.policy_json, r.status
            FROM runs AS r
            JOIN run_budget_policies AS p ON p.run_id = r.run_id
            WHERE r.run_id = ? AND r.execution_epoch = ? AND r.lease_owner = ?
              AND r.status IN ('running', 'cancelling')
            """,
            (self.run_id, self.execution_epoch, self.lease_owner),
        )
        if row is None or row[0] is None or _from_db(str(row[0])) <= now:
            raise StaleBudgetAuthorityError("budget authority is stale")
        if require_running and str(row[2]) != "running":
            raise StaleBudgetAuthorityError("new budget reservations require a running run")
        try:
            persisted_policy = RunBudgetPolicy.model_validate_json(str(row[1]))
        except (ValidationError, ValueError) as exc:
            raise BudgetPersistenceError("persisted budget policy is invalid") from exc
        if persisted_policy != self.policy:
            raise BudgetPersistenceError("bound budget policy does not match persisted policy")

    async def _transaction(
        self,
        operation: Callable[[datetime], Awaitable[T]],
        *,
        require_running: bool = False,
    ) -> T:
        async with self._lock:
            began = False
            try:
                await self._execute("BEGIN IMMEDIATE", ())
                began = True
                now = self._clock()
                await self._assert_authority(now, require_running=require_running)
                result = await operation(now)
                await self._connection.commit()
                return result
            except asyncio.CancelledError:
                if began:
                    await _await_cleanup(self._connection.rollback())
                raise
            except (
                BudgetExceededError,
                BudgetPersistenceError,
                StaleBudgetAuthorityError,
            ):
                if began:
                    await _await_cleanup(self._connection.rollback())
                raise
            except Exception as exc:
                if began:
                    await _await_cleanup(self._connection.rollback())
                raise BudgetPersistenceError("budget transaction failed") from exc

    async def _latest_rows(self):
        return await self._fetchall(
            """
            SELECT b.execution_epoch, b.call_id, b.reservation_id,
                   b.entry_sequence, b.status, b.resource, b.reserved_amount,
                   b.actual_amount, b.price_status, b.price_catalog_version,
                   b.summary_json, b.created_at, b.expires_at, b.settled_at
            FROM budget_ledger AS b
            JOIN (
                SELECT execution_epoch, reservation_id, MAX(entry_sequence) AS seq
                FROM budget_ledger WHERE run_id = ?
                GROUP BY execution_epoch, reservation_id
            ) AS latest
              ON latest.execution_epoch = b.execution_epoch
             AND latest.reservation_id = b.reservation_id
             AND latest.seq = b.entry_sequence
            WHERE b.run_id = ?
            """,
            (self.run_id, self.run_id),
        )

    @staticmethod
    def _charged(row) -> int:
        status = ReservationStatus(str(row[4]))
        if status is ReservationStatus.RESERVED:
            return int(row[6])
        if status in {ReservationStatus.SETTLED, ReservationStatus.UNKNOWN_SPEND}:
            return int(row[7])
        return 0

    async def _usage(self) -> dict[BudgetResource, int]:
        totals: dict[BudgetResource, int] = {}
        for row in await self._latest_rows():
            resource = BudgetResource(str(row[5]))
            totals[resource] = totals.get(resource, 0) + self._charged(row)
        return totals

    def _limit_for(self, resource: BudgetResource) -> int | None:
        value = getattr(self.policy.hard_limits, resource.value, None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _remember_exhausted(self, error: BudgetExceededError) -> None:
        if self._exhausted is None:
            self._exhausted = error

    async def _check_active_elapsed(self, now: datetime) -> None:
        if self.policy.enforcement_mode is not BudgetEnforcementMode.ENFORCED:
            return
        limit = self._limit_for(BudgetResource.ACTIVE_MILLISECONDS)
        if limit is None:
            return
        elapsed = max(
            0, round((now - self.execution_started_at).total_seconds() * 1000)
        )
        # Settled prior epochs plus the live current epoch form active runtime;
        # downtime between execution epochs is deliberately excluded.
        # This method runs inside the transaction, so reading the latest state
        # remains snapshot-consistent with the gate.
        # The async aggregate is supplied by the caller where required.
        prior = (await self._usage()).get(BudgetResource.ACTIVE_MILLISECONDS, 0)
        consumed = prior + elapsed
        if consumed >= limit:
            error = BudgetExceededError(
                BudgetResource.ACTIVE_MILLISECONDS,
                limit=limit,
                consumed=consumed,
                requested=0,
            )
            self._remember_exhausted(error)
            raise error

    async def _reconcile_in_transaction(self, now: datetime) -> int:
        reconciled = 0
        for row in await self._latest_rows():
            if ReservationStatus(str(row[4])) is not ReservationStatus.RESERVED:
                continue
            row_epoch = int(row[0])
            if row_epoch == self.execution_epoch and _from_db(str(row[12])) > now:
                continue
            await self._append_terminal_row(
                row,
                status=ReservationStatus.UNKNOWN_SPEND,
                actual_amount=int(row[6]),
                settled_at=now,
            )
            reconciled += 1
        return reconciled

    async def reconcile(self) -> int:
        return await self._transaction(self._reconcile_in_transaction)

    async def reserve_bundle(
        self,
        *,
        run_id: str,
        execution_epoch: int,
        amounts: tuple[BudgetAmount, ...],
        expires_at: datetime,
        call_id: str | None = None,
        summary: dict[str, JsonValue] | None = None,
    ) -> tuple[BudgetReservation, ...]:
        if self._exhausted is not None:
            raise self._exhausted
        if run_id != self.run_id or execution_epoch != self.execution_epoch:
            raise StaleBudgetAuthorityError("budget identity does not match bound run")
        if not amounts:
            raise BudgetPersistenceError("budget reservation bundle cannot be empty")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise BudgetPersistenceError("expires_at must be timezone-aware")
        resources = [item.resource for item in amounts]
        if len(set(resources)) != len(resources):
            raise BudgetPersistenceError("a bundle cannot repeat a resource")

        # Reconciliation is a committed accounting fact even when the following
        # enforced admission decision rejects this new bundle.
        await self.reconcile()

        async def operation(now: datetime) -> tuple[BudgetReservation, ...]:
            if expires_at <= now:
                raise ValueError("expires_at must be in the future")
            await self._check_active_elapsed(now)
            usage = await self._usage()
            if self.policy.enforcement_mode is BudgetEnforcementMode.ENFORCED:
                for amount in amounts:
                    limit = self._limit_for(amount.resource)
                    consumed = usage.get(amount.resource, 0)
                    if limit is not None and consumed + amount.amount > limit:
                        error = BudgetExceededError(
                            amount.resource,
                            limit=limit,
                            consumed=consumed,
                            requested=amount.amount,
                        )
                        self._remember_exhausted(error)
                        raise error

            reservations: list[BudgetReservation] = []
            for amount in amounts:
                reservation = BudgetReservation(
                    reservation_id=str(uuid.uuid4()),
                    run_id=self.run_id,
                    execution_epoch=self.execution_epoch,
                    call_id=call_id,
                    status=ReservationStatus.RESERVED,
                    reserved=amount,
                    price_status=PriceStatus.NOT_APPLICABLE,
                    price_catalog_version=self.policy.price_catalog_version,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                    summary=summary or {},
                )
                await self._insert_reservation(reservation)
                reservations.append(reservation)
            return tuple(reservations)

        try:
            return await self._transaction(operation, require_running=True)
        except ValidationError as exc:  # validation is also a fail-closed gate
            raise BudgetPersistenceError("budget reservation validation failed") from exc

    async def reserve(
        self,
        *,
        run_id: str,
        execution_epoch: int,
        amount: BudgetAmount,
        expires_at: datetime,
        call_id: str | None = None,
        summary: dict[str, JsonValue] | None = None,
    ) -> BudgetReservation:
        return (
            await self.reserve_bundle(
                run_id=run_id,
                execution_epoch=execution_epoch,
                amounts=(amount,),
                expires_at=expires_at,
                call_id=call_id,
                summary=summary,
            )
        )[0]

    async def _insert_reservation(self, item: BudgetReservation) -> None:
        await self._execute(
            """
            INSERT INTO budget_ledger(
                ledger_entry_id, run_id, execution_epoch, call_id,
                reservation_id, entry_sequence, status, resource,
                reserved_amount, actual_amount, price_status,
                price_catalog_version, summary_json, created_at,
                expires_at, settled_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL)
            """,
            (
                str(uuid.uuid4()), item.run_id, item.execution_epoch, item.call_id,
                item.reservation_id, item.status.value, item.reserved.resource.value,
                item.reserved.amount, item.price_status.value,
                item.price_catalog_version, _summary_json(item.summary.to_dict()),
                _to_db(item.created_at), _to_db(item.expires_at),
            ),
        )

    async def _reservation_row(self, reservation_id: str):
        return await self._fetchone(
            """
            SELECT b.execution_epoch, b.call_id, b.reservation_id,
                   b.entry_sequence, b.status, b.resource, b.reserved_amount,
                   b.actual_amount, b.price_status, b.price_catalog_version,
                   b.summary_json, b.created_at, b.expires_at, b.settled_at
            FROM budget_ledger AS b
            WHERE b.run_id = ? AND b.reservation_id = ?
            ORDER BY b.entry_sequence DESC LIMIT 1
            """,
            (self.run_id, reservation_id),
        )

    async def _append_terminal_row(
        self,
        row,
        *,
        status: ReservationStatus,
        actual_amount: int | None,
        settled_at: datetime,
    ) -> BudgetReservation:
        await self._execute(
            """
            INSERT INTO budget_ledger(
                ledger_entry_id, run_id, execution_epoch, call_id,
                reservation_id, entry_sequence, status, resource,
                reserved_amount, actual_amount, price_status,
                price_catalog_version, summary_json, created_at,
                expires_at, settled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), self.run_id, int(row[0]), row[1], row[2],
                int(row[3]) + 1, status.value, row[5], int(row[6]), actual_amount,
                row[8], row[9], row[10], row[11], row[12], _to_db(settled_at),
            ),
        )
        resource = BudgetResource(str(row[5]))
        actual = (
            BudgetAmount(resource=resource, amount=actual_amount)
            if actual_amount is not None
            else None
        )
        return BudgetReservation(
            reservation_id=str(row[2]),
            run_id=self.run_id,
            execution_epoch=int(row[0]),
            call_id=row[1],
            status=status,
            reserved=BudgetAmount(resource=resource, amount=int(row[6])),
            actual=actual,
            price_status=PriceStatus(str(row[8])),
            price_catalog_version=str(row[9]),
            created_at=_from_db(str(row[11])),
            updated_at=settled_at,
            expires_at=_from_db(str(row[12])),
            settled_at=settled_at,
            summary=json.loads(str(row[10])),
        )

    async def _finish(
        self,
        reservation_id: str,
        *,
        status: ReservationStatus,
        actual: BudgetAmount | None,
    ) -> BudgetReservation:
        async def operation(now: datetime) -> BudgetReservation:
            row = await self._reservation_row(reservation_id)
            if row is None:
                raise ValueError("budget reservation not found")
            if ReservationStatus(str(row[4])) is not ReservationStatus.RESERVED:
                raise ValueError("budget reservation is already terminal")
            resource = BudgetResource(str(row[5]))
            if actual is not None and actual.resource is not resource:
                raise ValueError("actual resource does not match reservation")
            amount = actual.amount if actual is not None else None
            if status is ReservationStatus.UNKNOWN_SPEND:
                amount = int(row[6])
            return await self._append_terminal_row(
                row, status=status, actual_amount=amount, settled_at=now
            )

        return await self._transaction(operation)

    async def settle(
        self, reservation_id: str, *, actual: BudgetAmount
    ) -> BudgetReservation:
        return await self._finish(
            reservation_id, status=ReservationStatus.SETTLED, actual=actual
        )

    async def release(self, reservation_id: str) -> BudgetReservation:
        return await self._finish(
            reservation_id, status=ReservationStatus.RELEASED, actual=None
        )

    async def mark_unknown_spend(
        self, reservation_id: str, *, actual: BudgetAmount
    ) -> BudgetReservation:
        # Contract deliberately ignores a caller's lower estimate: unknown spend
        # always charges the full conservative reservation.
        return await self._finish(
            reservation_id, status=ReservationStatus.UNKNOWN_SPEND, actual=actual
        )

    async def raise_if_exhausted(
        self, *, partial_state: dict | None = None
    ) -> None:
        if self._exhausted is not None:
            raise self._exhausted.attach_partial_state(partial_state)
        if self.policy.enforcement_mode is BudgetEnforcementMode.ENFORCED:
            async def operation(now: datetime) -> None:
                await self._reconcile_in_transaction(now)
                await self._check_active_elapsed(now)
            try:
                await self._transaction(operation)
            except BudgetExceededError as exc:
                raise exc.attach_partial_state(partial_state)

    async def record_active_milliseconds(self) -> BudgetReservation | None:
        if self._active_recorded is not None:
            return self._active_recorded

        async def operation(now: datetime) -> BudgetReservation:
            await self._reconcile_in_transaction(now)
            elapsed = max(
                0,
                round(
                    (now - self.execution_started_at).total_seconds() * 1000
                ),
            )
            created = BudgetReservation(
                reservation_id=str(uuid.uuid4()),
                run_id=self.run_id,
                execution_epoch=self.execution_epoch,
                status=ReservationStatus.RESERVED,
                reserved=BudgetAmount(
                    resource=BudgetResource.ACTIVE_MILLISECONDS, amount=elapsed
                ),
                price_status=PriceStatus.NOT_APPLICABLE,
                price_catalog_version=self.policy.price_catalog_version,
                created_at=now,
                updated_at=now,
                expires_at=now + self._reservation_ttl,
                summary={"measurement": "cumulative", "elapsed_milliseconds": elapsed},
            )
            await self._insert_reservation(created)
            row = await self._reservation_row(created.reservation_id)
            if row is None:  # pragma: no cover - guarded by the transaction
                raise RuntimeError("active-time reservation disappeared")
            return await self._append_terminal_row(
                row,
                status=ReservationStatus.SETTLED,
                actual_amount=elapsed,
                settled_at=now,
            )

        self._active_recorded = await self._transaction(operation)
        return self._active_recorded


__all__ = [
    "BudgetExceededError",
    "BudgetPersistenceError",
    "SQLiteBudgetManager",
    "SQLiteBudgetStore",
    "StaleBudgetAuthorityError",
]
