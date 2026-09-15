"""Explicit Phase 2-B adapter for budget execution that is not wired yet."""

from __future__ import annotations

from datetime import datetime

from pydantic import JsonValue

from .contracts import BudgetAmount, BudgetReservation


class BudgetExecutionDeferredError(RuntimeError):
    """Raised if Phase 2-B code accidentally attempts budget enforcement."""


class DeferredBudgetManager:
    """A fail-closed marker adapter; Phase 2-C will replace this implementation."""

    @staticmethod
    def _deferred() -> BudgetReservation:
        raise BudgetExecutionDeferredError(
            "Budget reservation and settlement are deferred until Phase 2-C."
        )

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
        return self._deferred()

    async def settle(
        self, reservation_id: str, *, actual: BudgetAmount
    ) -> BudgetReservation:
        return self._deferred()

    async def release(self, reservation_id: str) -> BudgetReservation:
        return self._deferred()

    async def mark_unknown_spend(
        self, reservation_id: str, *, actual: BudgetAmount
    ) -> BudgetReservation:
        return self._deferred()


__all__ = ["BudgetExecutionDeferredError", "DeferredBudgetManager"]
