"""Versioned, execution-independent budget contracts.

Phase 2-A only freezes these values.  Runtime enforcement and ledger writes are
deliberately left to later phases.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from deepchoice.contracts.safe_json import SafeJsonObject, coerce_safe_json_object

from .pricing import PriceStatus


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BudgetTier(StrEnum):
    STANDARD = "standard"


class BudgetEnforcementMode(StrEnum):
    OBSERVE_ONLY = "observe_only"
    ENFORCED = "enforced"


class BudgetResource(StrEnum):
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"
    COST_MICRO_USD = "cost_micro_usd"
    LLM_CALLS = "llm_calls"
    RETRIEVAL_CALLS = "retrieval_calls"
    HTTP_CALLS = "http_calls"
    ACTIVE_MILLISECONDS = "active_milliseconds"
    WALL_CLOCK_MILLISECONDS = "wall_clock_milliseconds"


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    UNKNOWN_SPEND = "unknown_spend"


class BudgetHardLimits(_FrozenContract):
    """Optional ceilings. ``None`` means deliberately uncalibrated, not zero."""

    input_tokens: int | None = Field(default=None, gt=0)
    output_tokens: int | None = Field(default=None, gt=0)
    total_tokens: int | None = Field(default=None, gt=0)
    cost_micro_usd: int | None = Field(default=None, gt=0)
    llm_calls: int | None = Field(default=None, gt=0)
    retrieval_calls: int | None = Field(default=None, gt=0)
    http_calls: int | None = Field(default=None, gt=0)
    task_concurrency: int | None = Field(default=None, gt=0)
    global_concurrency: int | None = Field(default=None, gt=0)
    active_milliseconds: int | None = Field(default=None, gt=0)
    wall_clock_milliseconds: int | None = Field(default=None, gt=0)


class RunBudgetPolicy(_FrozenContract):
    """Immutable per-run policy snapshot stored outside ``RunManifest``."""

    policy_schema_version: Literal[1] = 1
    policy_version: Literal["standard-observe-v1"] = "standard-observe-v1"
    tier: BudgetTier = BudgetTier.STANDARD
    enforcement_mode: BudgetEnforcementMode = BudgetEnforcementMode.OBSERVE_ONLY
    soft_limit_ratio: float = Field(default=0.8, gt=0, le=1)
    hard_limits: BudgetHardLimits = Field(default_factory=BudgetHardLimits)
    price_catalog_version: str = Field(min_length=1)


class BudgetAmount(_FrozenContract):
    schema_version: Literal[1] = 1
    resource: BudgetResource
    amount: int = Field(ge=0)


class BudgetReservation(_FrozenContract):
    schema_version: Literal[1] = 1
    reservation_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    call_id: str | None = Field(default=None, min_length=1)
    status: ReservationStatus
    reserved: BudgetAmount
    actual: BudgetAmount | None = None
    price_status: PriceStatus
    price_catalog_version: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    settled_at: datetime | None = None
    summary: SafeJsonObject = Field(default_factory=SafeJsonObject)

    _safe_summary = field_validator("summary", mode="before")(coerce_safe_json_object)

    @model_validator(mode="after")
    def _status_matches_actual(self) -> "BudgetReservation":
        timestamps = (self.created_at, self.updated_at, self.expires_at, self.settled_at)
        if any(
            value is not None and (value.tzinfo is None or value.utcoffset() is None)
            for value in timestamps
        ):
            raise ValueError("budget timestamps must be timezone-aware")
        is_final = self.status in {
            ReservationStatus.SETTLED,
            ReservationStatus.RELEASED,
            ReservationStatus.UNKNOWN_SPEND,
        }
        requires_actual = self.status in {
            ReservationStatus.SETTLED,
            ReservationStatus.UNKNOWN_SPEND,
        }
        if requires_actual != (self.actual is not None):
            raise ValueError("actual amount must match the reservation lifecycle state")
        if self.actual is not None and self.actual.resource is not self.reserved.resource:
            raise ValueError("reserved and actual resources must match")
        if (
            self.status is ReservationStatus.UNKNOWN_SPEND
            and self.actual is not None
            and self.actual.amount != self.reserved.amount
        ):
            raise ValueError("unknown spend must conservatively charge the reservation")
        if is_final != (self.settled_at is not None):
            raise ValueError("settled_at must match the reservation lifecycle state")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must follow created_at")
        if self.settled_at is not None and self.settled_at < self.created_at:
            raise ValueError("settled_at cannot precede created_at")
        return self


class BudgetLedgerEntry(_FrozenContract):
    """One immutable append-only reservation lifecycle fact."""

    schema_version: Literal[1] = 1
    ledger_entry_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_epoch: int = Field(ge=1)
    call_id: str | None = Field(default=None, min_length=1)
    reservation_id: str = Field(min_length=1)
    entry_sequence: int = Field(ge=1)
    status: ReservationStatus
    resource: BudgetResource
    reserved_amount: int = Field(ge=0)
    actual_amount: int | None = Field(default=None, ge=0)
    price_status: PriceStatus
    price_catalog_version: str = Field(min_length=1)
    summary: SafeJsonObject = Field(default_factory=SafeJsonObject)
    created_at: datetime
    expires_at: datetime
    settled_at: datetime | None = None

    _safe_summary = field_validator("summary", mode="before")(coerce_safe_json_object)

    @model_validator(mode="after")
    def _lifecycle_is_consistent(self) -> "BudgetLedgerEntry":
        is_final = self.status is not ReservationStatus.RESERVED
        has_actual = self.status in {
            ReservationStatus.SETTLED,
            ReservationStatus.UNKNOWN_SPEND,
        }
        if has_actual != (self.actual_amount is not None):
            raise ValueError("actual_amount must match the ledger status")
        if is_final != (self.settled_at is not None):
            raise ValueError("settled_at must match the ledger status")
        if (
            self.status is ReservationStatus.UNKNOWN_SPEND
            and self.actual_amount != self.reserved_amount
        ):
            raise ValueError("unknown spend must conservatively charge the reservation")
        timestamps = (self.created_at, self.expires_at, self.settled_at)
        if any(
            value is not None and (value.tzinfo is None or value.utcoffset() is None)
            for value in timestamps
        ):
            raise ValueError("ledger timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must follow created_at")
        if self.settled_at is not None and self.settled_at < self.created_at:
            raise ValueError("settled_at cannot precede created_at")
        return self


@runtime_checkable
class BudgetManager(Protocol):
    """Port for future atomic reservation and settlement implementations."""

    async def reserve(
        self,
        *,
        run_id: str,
        execution_epoch: int,
        amount: BudgetAmount,
        expires_at: datetime,
        call_id: str | None = None,
        summary: dict[str, JsonValue] | None = None,
    ) -> BudgetReservation: ...

    async def settle(
        self, reservation_id: str, *, actual: BudgetAmount
    ) -> BudgetReservation: ...

    async def release(self, reservation_id: str) -> BudgetReservation: ...

    async def mark_unknown_spend(
        self, reservation_id: str, *, actual: BudgetAmount
    ) -> BudgetReservation: ...


__all__ = [
    "BudgetAmount",
    "BudgetEnforcementMode",
    "BudgetHardLimits",
    "BudgetLedgerEntry",
    "BudgetManager",
    "BudgetReservation",
    "BudgetResource",
    "BudgetTier",
    "ReservationStatus",
    "RunBudgetPolicy",
]
