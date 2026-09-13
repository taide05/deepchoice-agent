"""Task and run lifecycle contracts.

Pure domain logic: the status vocabularies and the transition matrices that
decide which state changes are legal. This module performs no I/O and holds no
mutable global state, so it can be reused by the persistence, service, and
coordination layers that will be built on top of it.

Two distinct vocabularies are defined even though their members currently
coincide:

* :class:`TaskStatus` is the durable projection of a task.
* :class:`RunStatus` is the status of one execution attempt of that task.

They are deliberately separate types so a run record can never be passed where
a task projection is expected. A task may outlive several runs: a ``failed`` or
``timed_out`` task returns to ``queued`` by creating a *new* run, which never
rewrites the outcome already recorded for the previous one.
"""

from enum import StrEnum
from typing import Final

from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory

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


class TaskStatus(StrEnum):
    """Durable lifecycle projection of a task."""

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


class RunStatus(StrEnum):
    """Lifecycle of a single execution attempt of a task.

    Distinct from :class:`TaskStatus` on purpose: run statuses are historical
    records of one attempt and are never reopened by a retry.
    """

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


# A run that reached any of these has finished for good. Re-running a task
# creates a new run; it never moves an old run out of a terminal status.
RUN_TERMINAL_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    }
)

# Task outcomes that may be retried by queueing a brand new run.
TASK_RETRYABLE_OUTCOME_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {
        TaskStatus.FAILED,
        TaskStatus.TIMED_OUT,
    }
)

# Task outcomes that are final: a task in one of these states is never
# reopened, so no transition originates from them.
TASK_IMMUTABLE_OUTCOME_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED_WITH_WARNINGS,
        TaskStatus.CANCELLED,
    }
)

# Single source of truth for both matrices. Every legal transition appears
# exactly once; anything absent from the mapping is rejected by default.
_TASK_TRANSITIONS: Final[dict[TaskStatus, frozenset[TaskStatus]]] = {
    TaskStatus.QUEUED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_FOR_INPUT,
            TaskStatus.CANCELLING,
            TaskStatus.COMPLETED,
            TaskStatus.COMPLETED_WITH_WARNINGS,
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.INTERRUPTED,
        }
    ),
    TaskStatus.WAITING_FOR_INPUT: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.CANCELLED,
        }
    ),
    # Cancellation is cooperative: running work is only ever observed as
    # `cancelling` until it acknowledges the request.
    TaskStatus.CANCELLING: frozenset(
        {
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.INTERRUPTED: frozenset(
        {
            TaskStatus.QUEUED,
            TaskStatus.CANCELLED,
        }
    ),
    # Retry outcomes. `queued` requires an explicit new run; see
    # `_TASK_NEW_RUN_TRANSITIONS`.
    TaskStatus.FAILED: frozenset(),
    TaskStatus.TIMED_OUT: frozenset(),
    # Immutable outcomes: no outgoing transitions.
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.COMPLETED_WITH_WARNINGS: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

# Transitions that are only legal when the caller states that the task is
# queueing a fresh run rather than reviving the recorded outcome.
_TASK_NEW_RUN_TRANSITIONS: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = frozenset(
    {
        (TaskStatus.FAILED, TaskStatus.QUEUED),
        (TaskStatus.TIMED_OUT, TaskStatus.QUEUED),
    }
)

# A run covers one attempt only, so it has no new-run transitions at all.
_RUN_TRANSITIONS: Final[dict[RunStatus, frozenset[RunStatus]]] = {
    RunStatus.QUEUED: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_FOR_INPUT,
            RunStatus.CANCELLING,
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.WAITING_FOR_INPUT: frozenset(
        {
            RunStatus.QUEUED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.CANCELLING: frozenset(
        {
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.INTERRUPTED: frozenset(
        {
            RunStatus.QUEUED,
            RunStatus.CANCELLED,
        }
    ),
    # Terminal for a run: a retry is a new run, never a revived one.
    RunStatus.COMPLETED: frozenset(),
    RunStatus.COMPLETED_WITH_WARNINGS: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.TIMED_OUT: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}

_TASK_TRANSITION_ACTION: Final[str] = (
    "Reload the task status and retry the command; start a new run if it is no "
    "longer eligible."
)
_RUN_TRANSITION_ACTION: Final[str] = (
    "Reload the run status; a retry starts a new run instead of reopening this one."
)


class InvalidLifecycleTransition(DeepChoiceError):
    """Raised when a lifecycle transition is not part of the contract.

    The message and action are fixed, stable text so they can be surfaced to
    callers without leaking paths, exception representations, or internals.
    """

    def __init__(
        self,
        *,
        entity: str,
        code: str,
        current_status: str,
        target_status: str,
        action: str,
        creates_new_run: bool | None = None,
    ) -> None:
        details: dict[str, object] = {
            "entity": entity,
            "current_status": current_status,
            "target_status": target_status,
        }
        if creates_new_run is not None:
            details["creates_new_run"] = creates_new_run
        super().__init__(
            f"Invalid {entity} status transition from '{current_status}' to '{target_status}'.",
            category=ErrorCategory.CONTRACT,
            code=code,
            status_code=409,
            retryable=False,
            action=action,
            details=details,
        )


def is_task_transition_allowed(
    current: TaskStatus,
    target: TaskStatus,
    *,
    creates_new_run: bool = False,
) -> bool:
    """Return whether a task may move from ``current`` to ``target``.

    A self-transition is never a transition and is always rejected: command
    idempotency belongs to the service layer, not to the state contract.

    ``creates_new_run`` only gates the retry outcomes ``failed`` and
    ``timed_out``; the caller asserts that queueing the task starts a new run
    and leaves the previous run's recorded outcome untouched.
    """

    if current is target:
        return False
    if target in _TASK_TRANSITIONS[current]:
        return True
    return creates_new_run and (current, target) in _TASK_NEW_RUN_TRANSITIONS


def ensure_task_transition_allowed(
    current: TaskStatus,
    target: TaskStatus,
    *,
    creates_new_run: bool = False,
) -> None:
    """Raise :class:`InvalidLifecycleTransition` unless the task move is legal."""

    if is_task_transition_allowed(current, target, creates_new_run=creates_new_run):
        return
    raise InvalidLifecycleTransition(
        entity="task",
        code="TASK_STATUS_TRANSITION_INVALID",
        current_status=current.value,
        target_status=target.value,
        action=_TASK_TRANSITION_ACTION,
        creates_new_run=creates_new_run,
    )


def is_run_transition_allowed(
    current: RunStatus,
    target: RunStatus,
) -> bool:
    """Return whether a run may move from ``current`` to ``target``.

    Runs have no new-run escape hatch: a terminal run stays terminal, and a
    retry is represented by a new run record.
    """

    if current is target:
        return False
    return target in _RUN_TRANSITIONS[current]


def ensure_run_transition_allowed(
    current: RunStatus,
    target: RunStatus,
) -> None:
    """Raise :class:`InvalidLifecycleTransition` unless the run move is legal."""

    if is_run_transition_allowed(current, target):
        return
    raise InvalidLifecycleTransition(
        entity="run",
        code="RUN_STATUS_TRANSITION_INVALID",
        current_status=current.value,
        target_status=target.value,
        action=_RUN_TRANSITION_ACTION,
    )
