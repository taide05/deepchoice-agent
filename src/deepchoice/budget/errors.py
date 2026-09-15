"""Dependency-free budget exceptions safe to import at fallback boundaries."""

from __future__ import annotations

from typing import Any


class BudgetError(RuntimeError):
    """Base class for stable budget correctness failures."""


class BudgetExceededError(BudgetError):
    """A hard run limit rejected an external call before it was sent."""

    code = "RUN_BUDGET_EXCEEDED"

    def __init__(
        self,
        resource: Any,
        *,
        limit: int,
        consumed: int,
        requested: int,
    ) -> None:
        self.resource = resource
        self.limit = limit
        self.consumed = consumed
        self.requested = requested
        self.partial_state: dict | None = None
        resource_name = getattr(resource, "value", str(resource))
        super().__init__(f"Run budget exhausted for {resource_name}.")

    def attach_partial_state(self, state: dict | None) -> "BudgetExceededError":
        if self.partial_state is None and isinstance(state, dict):
            self.partial_state = dict(state)
        return self


class StaleBudgetAuthorityError(BudgetError):
    """The execution no longer holds a current, unexpired run lease."""

    code = "RUN_BUDGET_AUTHORITY_STALE"


class BudgetPersistenceError(BudgetError):
    """Budget persistence failed closed before an external call."""

    code = "RUN_BUDGET_PERSISTENCE_FAILED"


__all__ = [
    "BudgetError",
    "BudgetExceededError",
    "BudgetPersistenceError",
    "StaleBudgetAuthorityError",
]
