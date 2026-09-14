"""Stable runtime domain contracts."""

from .lifecycle import (
    RUN_TERMINAL_STATUSES,
    TASK_IMMUTABLE_OUTCOME_STATUSES,
    TASK_RETRYABLE_OUTCOME_STATUSES,
    InvalidLifecycleTransition,
    RunStatus,
    TaskStatus,
    TaskTransitionIntent,
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
    "TaskTransitionIntent",
    "ensure_run_transition_allowed",
    "ensure_task_transition_allowed",
    "is_run_transition_allowed",
    "is_task_transition_allowed",
]
