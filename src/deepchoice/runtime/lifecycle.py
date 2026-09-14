"""Pure lifecycle contracts for persisted research tasks and runs.

This module deliberately contains no persistence or orchestration behavior.  In
particular, a ``NEW_RUN`` task transition only expresses domain permission; the
later repository layer must create the new run and update the task atomically.
"""

from enum import Enum
from typing import Final

from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory


class TaskStatus(Enum):
    """User-visible status of a durable research task."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RunStatus(Enum):
    """Execution status of one manifest-bound research run."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskTransitionIntent(Enum):
    """Whether a task transition keeps or replaces its current run."""

    SAME_RUN = "same_run"
    NEW_RUN = "new_run"


RUN_TERMINAL_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    }
)

# Successful and cancelled tasks are immutable outcomes. Failed and timed-out
# tasks are outcomes too, but may explicitly start a new run.
TASK_IMMUTABLE_OUTCOME_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED_WITH_WARNINGS,
        TaskStatus.CANCELLED,
    }
)
TASK_RETRYABLE_OUTCOME_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {TaskStatus.FAILED, TaskStatus.TIMED_OUT}
)


_TASK_SAME_RUN_TRANSITIONS: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = (
    frozenset(
        {
            (TaskStatus.QUEUED, TaskStatus.RUNNING),
            (TaskStatus.QUEUED, TaskStatus.CANCELLED),
            (TaskStatus.RUNNING, TaskStatus.WAITING_FOR_INPUT),
            (TaskStatus.RUNNING, TaskStatus.CANCELLING),
            (TaskStatus.RUNNING, TaskStatus.COMPLETED),
            (TaskStatus.RUNNING, TaskStatus.COMPLETED_WITH_WARNINGS),
            (TaskStatus.RUNNING, TaskStatus.FAILED),
            (TaskStatus.RUNNING, TaskStatus.TIMED_OUT),
            (TaskStatus.RUNNING, TaskStatus.INTERRUPTED),
            (TaskStatus.WAITING_FOR_INPUT, TaskStatus.QUEUED),
            (TaskStatus.WAITING_FOR_INPUT, TaskStatus.CANCELLED),
            (TaskStatus.CANCELLING, TaskStatus.CANCELLED),
            (TaskStatus.INTERRUPTED, TaskStatus.QUEUED),
            (TaskStatus.INTERRUPTED, TaskStatus.CANCELLED),
        }
    )
)
_TASK_NEW_RUN_TRANSITIONS: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = (
    frozenset(
        {
            (TaskStatus.FAILED, TaskStatus.QUEUED),
            (TaskStatus.TIMED_OUT, TaskStatus.QUEUED),
            (TaskStatus.INTERRUPTED, TaskStatus.QUEUED),
        }
    )
)
_RUN_SAME_RUN_TRANSITIONS: Final[frozenset[tuple[RunStatus, RunStatus]]] = (
    frozenset(
        {
            (RunStatus.QUEUED, RunStatus.RUNNING),
            (RunStatus.QUEUED, RunStatus.CANCELLED),
            (RunStatus.RUNNING, RunStatus.WAITING_FOR_INPUT),
            (RunStatus.RUNNING, RunStatus.CANCELLING),
            (RunStatus.RUNNING, RunStatus.COMPLETED),
            (RunStatus.RUNNING, RunStatus.COMPLETED_WITH_WARNINGS),
            (RunStatus.RUNNING, RunStatus.FAILED),
            (RunStatus.RUNNING, RunStatus.TIMED_OUT),
            (RunStatus.RUNNING, RunStatus.INTERRUPTED),
            (RunStatus.WAITING_FOR_INPUT, RunStatus.QUEUED),
            (RunStatus.WAITING_FOR_INPUT, RunStatus.CANCELLED),
            (RunStatus.CANCELLING, RunStatus.CANCELLED),
            (RunStatus.INTERRUPTED, RunStatus.QUEUED),
            (RunStatus.INTERRUPTED, RunStatus.CANCELLED),
        }
    )
)


class InvalidLifecycleTransition(DeepChoiceError):
    """A well-typed lifecycle transition rejected by the domain matrix."""

    def __init__(
        self,
        current: TaskStatus | RunStatus,
        target: TaskStatus | RunStatus,
        *,
        intent: TaskTransitionIntent = TaskTransitionIntent.SAME_RUN,
    ) -> None:
        if type(intent) is not TaskTransitionIntent:
            raise TypeError("Lifecycle transition intent must be TaskTransitionIntent.")

        if type(current) is TaskStatus and type(target) is TaskStatus:
            domain = "task"
            code = "TASK_STATUS_TRANSITION_NOT_ALLOWED"
        elif type(current) is RunStatus and type(target) is RunStatus:
            domain = "run"
            code = "RUN_STATUS_TRANSITION_NOT_ALLOWED"
        else:
            raise TypeError("Lifecycle transition statuses must use one matching status enum.")

        message = (
            f"The {domain} status transition from {current.value} to "
            f"{target.value} is not allowed for {intent.value}."
        )
        super().__init__(
            message,
            category=ErrorCategory.CONTRACT,
            code=code,
            status_code=409,
            retryable=False,
            action="Refresh the task state and use an allowed lifecycle operation.",
            scope=f"{domain}_lifecycle",
            details={
                "entity": domain,
                "current_status": current.value,
                "target_status": target.value,
                "intent": intent.value,
            },
        )
        self.current_status = current
        self.target_status = target
        self.intent = intent


def is_task_transition_allowed(
    current: object,
    target: object,
    *,
    intent: object = TaskTransitionIntent.SAME_RUN,
) -> bool:
    """Return whether an exactly typed task transition is permitted."""

    if (
        type(current) is not TaskStatus
        or type(target) is not TaskStatus
        or type(intent) is not TaskTransitionIntent
    ):
        return False
    if intent is TaskTransitionIntent.SAME_RUN:
        return (current, target) in _TASK_SAME_RUN_TRANSITIONS
    return (current, target) in _TASK_NEW_RUN_TRANSITIONS


def ensure_task_transition_allowed(
    current: object,
    target: object,
    *,
    intent: object = TaskTransitionIntent.SAME_RUN,
) -> None:
    """Raise a stable contract error unless a task transition is permitted."""

    if type(current) is not TaskStatus or type(target) is not TaskStatus:
        raise TypeError("Task lifecycle transition requires TaskStatus values.")
    if type(intent) is not TaskTransitionIntent:
        raise TypeError("Task lifecycle transition requires TaskTransitionIntent.")
    if not is_task_transition_allowed(current, target, intent=intent):
        raise InvalidLifecycleTransition(current, target, intent=intent)


def is_run_transition_allowed(current: object, target: object) -> bool:
    """Return whether an exactly typed same-run transition is permitted."""

    if type(current) is not RunStatus or type(target) is not RunStatus:
        return False
    return (current, target) in _RUN_SAME_RUN_TRANSITIONS


def ensure_run_transition_allowed(current: object, target: object) -> None:
    """Raise a stable contract error unless a run transition is permitted."""

    if type(current) is not RunStatus or type(target) is not RunStatus:
        raise TypeError("Run lifecycle transition requires RunStatus values.")
    if not is_run_transition_allowed(current, target):
        raise InvalidLifecycleTransition(current, target)


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
