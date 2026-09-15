"""Stable runtime domain contracts."""

from .context import (
    CancellationPort,
    RunContext,
    bind_node_attempt,
    bind_run_context,
    get_node_attempt_id,
    get_run_context,
)
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
    "CancellationPort",
    "InvalidLifecycleTransition",
    "RUN_TERMINAL_STATUSES",
    "RunStatus",
    "RunContext",
    "bind_node_attempt",
    "bind_run_context",
    "get_node_attempt_id",
    "get_run_context",
    "TASK_IMMUTABLE_OUTCOME_STATUSES",
    "TASK_RETRYABLE_OUTCOME_STATUSES",
    "TaskStatus",
    "TaskTransitionIntent",
    "ensure_run_transition_allowed",
    "ensure_task_transition_allowed",
    "is_run_transition_allowed",
    "is_task_transition_allowed",
]
