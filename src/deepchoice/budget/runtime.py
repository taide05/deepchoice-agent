"""Small runtime helpers for budgeted external-call wrappers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .contracts import BudgetAmount, BudgetReservation, BudgetResource


def current_budget_manager():
    from deepchoice.runtime.context import get_run_context

    context = get_run_context()
    return context.budget if context is not None else None


async def reserve_call(
    amounts: tuple[BudgetAmount, ...],
    *,
    call_id: str | None,
    summary: dict | None = None,
) -> tuple[BudgetReservation, ...]:
    manager = current_budget_manager()
    if (
        manager is None
        or getattr(manager, "execution_enabled", True) is False
        or not hasattr(manager, "run_id")
        or not hasattr(manager, "execution_epoch")
        or not callable(getattr(manager, "reserve_bundle", None))
    ):
        return ()
    expires = getattr(manager, "default_expires_at", None)
    expires_at = (
        expires()
        if callable(expires)
        else datetime.now(UTC) + timedelta(minutes=5)
    )
    return await manager.reserve_bundle(
        run_id=manager.run_id,
        execution_epoch=manager.execution_epoch,
        amounts=amounts,
        expires_at=expires_at,
        call_id=call_id,
        summary=summary,
    )


async def settle_call(
    reservations: tuple[BudgetReservation, ...],
    actuals: dict[BudgetResource, int | None],
) -> None:
    manager = current_budget_manager()
    if manager is None:
        return
    for reservation in reservations:
        actual = actuals.get(reservation.reserved.resource)
        if actual is None:
            await manager.mark_unknown_spend(
                reservation.reservation_id,
                actual=reservation.reserved,
            )
        else:
            await manager.settle(
                reservation.reservation_id,
                actual=BudgetAmount(
                    resource=reservation.reserved.resource,
                    amount=actual,
                ),
            )


async def unknown_call(
    reservations: tuple[BudgetReservation, ...],
    *,
    known_actuals: dict[BudgetResource, int] | None = None,
) -> None:
    known = known_actuals or {}
    await settle_call(
        reservations,
        {
            item.reserved.resource: known.get(item.reserved.resource)
            for item in reservations
        },
    )


__all__ = ["current_budget_manager", "reserve_call", "settle_call", "unknown_call"]
