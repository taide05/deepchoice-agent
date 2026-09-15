"""Budget policy, reservation, price catalog, and runtime adapters."""

from .errors import (
    BudgetError,
    BudgetExceededError,
    BudgetPersistenceError,
    StaleBudgetAuthorityError,
)

from .contracts import (
    BudgetAmount,
    BudgetEnforcementMode,
    BudgetHardLimits,
    BudgetLedgerEntry,
    BudgetManager,
    BudgetReservation,
    BudgetResource,
    BudgetTier,
    ReservationStatus,
    RunBudgetPolicy,
)
from .pricing import (
    CURRENT_PRICE_CATALOG,
    ModelTokenPrice,
    PriceCatalog,
    PriceQuote,
    PriceStatus,
)
from .deferred import BudgetExecutionDeferredError, DeferredBudgetManager
from .sqlite import (
    SQLiteBudgetManager,
    SQLiteBudgetStore,
)
from .runtime import current_budget_manager, reserve_call, settle_call, unknown_call


DEFAULT_RUN_BUDGET_POLICY = RunBudgetPolicy(
    price_catalog_version=CURRENT_PRICE_CATALOG.catalog_version
)


__all__ = [
    "BudgetAmount",
    "BudgetEnforcementMode",
    "BudgetExecutionDeferredError",
    "BudgetError",
    "BudgetExceededError",
    "BudgetPersistenceError",
    "BudgetHardLimits",
    "BudgetLedgerEntry",
    "BudgetManager",
    "BudgetReservation",
    "BudgetResource",
    "BudgetTier",
    "CURRENT_PRICE_CATALOG",
    "DEFAULT_RUN_BUDGET_POLICY",
    "DeferredBudgetManager",
    "ModelTokenPrice",
    "PriceCatalog",
    "PriceQuote",
    "PriceStatus",
    "ReservationStatus",
    "RunBudgetPolicy",
    "SQLiteBudgetManager",
    "SQLiteBudgetStore",
    "StaleBudgetAuthorityError",
    "current_budget_manager",
    "reserve_call",
    "settle_call",
    "unknown_call",
]
