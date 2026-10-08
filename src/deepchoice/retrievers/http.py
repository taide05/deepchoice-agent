"""Shared accounting for bounded logical retrieval HTTP operations."""
from ..budget_errors import BudgetPersistenceError


async def budgeted_http(dispatch, *, kind: str, require_budget: bool = False):
    """One logical HTTP operation, in addition to its source retrieval charge."""
    # The manifest imports retrievers while budget contracts are initialized.
    from ..budget.contracts import BudgetAmount, BudgetResource
    from ..budget.runtime import reserve_call, settle_call, unknown_call

    reservations = await reserve_call(
        (BudgetAmount(resource=BudgetResource.HTTP_CALLS, amount=1),),
        call_id=None, summary={"kind": kind},
    )
    if require_budget and not reservations:
        raise BudgetPersistenceError("HTTP retrieval requires an active budget reservation")
    try:
        response = await dispatch()
    except BaseException:
        await unknown_call(reservations)
        raise
    await settle_call(reservations, {BudgetResource.HTTP_CALLS: 1})
    return response


def check_response_size(response) -> None:
    """Bound synchronous parsing; the routed client has already read the body."""
    if len(response.content) > 1024 * 1024:
        raise ValueError("Retrieval response exceeds the 1 MiB parsing limit")
