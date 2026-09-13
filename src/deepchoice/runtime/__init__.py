"""Runtime domain contracts for task and run lifecycle.

This package currently exposes only the pure lifecycle vocabulary and
transition rules. Persistence, coordination, and API surfaces are not
implemented here yet.
"""

from .lifecycle import (
    RUN_TERMINAL_STATUSES,
    TASK_IMMUTABLE_OUTCOME_STATUSES,
    TASK_RETRYABLE_OUTCOME_STATUSES,
    InvalidLifecycleTransition,
    RunStatus,
    TaskStatus,
    ensure_run_transition_allowed,
    ensure_task_transition_allowed,
    is_run_transition_allowed,
    is_task_transition_allowed,
)

__all__ = [
    "InvalidLifecycleTransition",
    "RUN_TERMINAL_STATUSES",
    "RunStatus",
    "TASK_IMMUTABLE_OUTCOME_STATUSES",
    "TASK_RETRYABLE_OUTCOME_STATUSES",
    "TaskStatus",
    "ensure_run_transition_allowed",
    "ensure_task_transition_allowed",
    "is_run_transition_allowed",
    "is_task_transition_allowed",
]
