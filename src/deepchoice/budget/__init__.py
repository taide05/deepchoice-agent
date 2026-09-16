"""Budget policy, reservation, price catalog, and runtime adapters."""

from .errors import (
    BudgetError,
    BudgetExceededError,
    BudgetInsufficientEvidenceError,
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


STANDARD_OBSERVE_RUN_BUDGET_POLICY = RunBudgetPolicy(
    price_catalog_version=CURRENT_PRICE_CATALOG.catalog_version
)
STANDARD_ENFORCED_RUN_BUDGET_POLICY = RunBudgetPolicy(
    policy_version="standard-enforced-v1",
    enforcement_mode=BudgetEnforcementMode.ENFORCED,
    hard_limits=BudgetHardLimits(
        total_tokens=60_000,
        llm_calls=96,
        retrieval_calls=72,
        active_milliseconds=900_000,
    ),
    price_catalog_version=CURRENT_PRICE_CATALOG.catalog_version,
)

# The product default applies only when a new durable run identity is created.
# Existing runs always load and retain their own frozen policy snapshot.
DEFAULT_RUN_BUDGET_POLICY = STANDARD_ENFORCED_RUN_BUDGET_POLICY


__all__ = [
    "BudgetAmount",
    "BudgetEnforcementMode",
    "BudgetExecutionDeferredError",
    "BudgetError",
    "BudgetExceededError",
    "BudgetInsufficientEvidenceError",
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
    "STANDARD_ENFORCED_RUN_BUDGET_POLICY",
    "STANDARD_OBSERVE_RUN_BUDGET_POLICY",
    "SQLiteBudgetManager",
    "SQLiteBudgetStore",
    "StaleBudgetAuthorityError",
    "current_budget_manager",
    "reserve_call",
    "settle_call",
    "unknown_call",
]
