"""Compatibility re-export for the dependency-free budget exceptions."""

from deepchoice.budget_errors import (
    BudgetError,
    BudgetExceededError,
    BudgetInsufficientEvidenceError,
    BudgetPersistenceError,
    StaleBudgetAuthorityError,
)


__all__ = [
    "BudgetError",
    "BudgetExceededError",
    "BudgetInsufficientEvidenceError",
    "BudgetPersistenceError",
    "StaleBudgetAuthorityError",
]
