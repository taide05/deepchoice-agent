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

Because both vocabularies are string-backed enums, CPython's ``str`` equality
makes members of the two enums compare equal by value (``TaskStatus.QUEUED ==
RunStatus.QUEUED``). Membership in ``str``/``Enum`` makes that unavoidable
without overriding ``__eq__``, so the boundary is enforced here instead: every
public helper validates the exact runtime type of its arguments and never
relies on value equality to accept input. A string, a member of the other
vocabulary, or any unknown value is rejected.
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

# Single source of truth for both matrices, held as plain immutable data: a
# frozenset of (current, target) pairs. Each legal transition appears exactly
# once and anything absent is rejected by default, so the rules cannot be
# mutated at runtime and there is no second copy to drift out of sync.
_TASK_ALLOWED_TRANSITIONS: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = frozenset(
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
        # Cancellation is cooperative: running work is only ever observed as
        # `cancelling` until it acknowledges the request.
        (TaskStatus.CANCELLING, TaskStatus.CANCELLED),
        (TaskStatus.INTERRUPTED, TaskStatus.QUEUED),
        (TaskStatus.INTERRUPTED, TaskStatus.CANCELLED),
    }
)

# Task transitions that are legal only when the caller states that the task is
# queueing a fresh run rather than reviving the recorded outcome.
_TASK_NEW_RUN_TRANSITIONS: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = frozenset(
    {
        (TaskStatus.FAILED, TaskStatus.QUEUED),
        (TaskStatus.TIMED_OUT, TaskStatus.QUEUED),
    }
)

# A run covers one attempt only, so it has no new-run transitions at all.
_RUN_ALLOWED_TRANSITIONS: Final[frozenset[tuple[RunStatus, RunStatus]]] = frozenset(
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

# Neutral guidance that is accurate for every illegal task transition. It
# deliberately says nothing about creating a run, because the retry outcomes
# are not the only statuses that can be rejected.
_TASK_TRANSITION_ACTION: Final[str] = (
    "Reload the task status and retry the command against its current status."
)
_RUN_TRANSITION_ACTION: Final[str] = (
    "Reload the run status; a retry starts a new run instead of reopening this one."
)

_TASK_EXPECTED_TYPE: Final[str] = "TaskStatus"
_RUN_EXPECTED_TYPE: Final[str] = "RunStatus"


# Frozen lookup indexes derived once from the matrices above. They are only
# ever read, never reassigned.
_TASK_ALLOWED_INDEX: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = (
    _TASK_ALLOWED_TRANSITIONS
)
_TASK_ALLOWED_WITH_NEW_RUN_INDEX: Final[frozenset[tuple[TaskStatus, TaskStatus]]] = (
    _TASK_ALLOWED_TRANSITIONS | _TASK_NEW_RUN_TRANSITIONS
)
_RUN_ALLOWED_INDEX: Final[frozenset[tuple[RunStatus, RunStatus]]] = _RUN_ALLOWED_TRANSITIONS


def is_task_transition_allowed(
    current: TaskStatus,
    target: TaskStatus,
    *,
    creates_new_run: bool = False,
) -> bool:
    """Return whether a task may move from ``current`` to ``target``.

    Both arguments must be exact :class:`TaskStatus` members. A member of
    another vocabulary, a raw string, or an unknown value is rejected with
    ``False`` rather than being coerced by string equality.

    A self-transition is never a transition and is always rejected: command
    idempotency belongs to the service layer, not to the state contract.

    ``creates_new_run`` only gates the retry outcomes ``failed`` and
    ``timed_out``; the caller asserts that queueing the task starts a new run
    and leaves the previous run's recorded outcome untouched.
    """

    if type(current) is not TaskStatus or type(target) is not TaskStatus:
        return False
    if current is target:
        return False
    if creates_new_run:
        return (current, target) in _TASK_ALLOWED_WITH_NEW_RUN_INDEX
    return (current, target) in _TASK_ALLOWED_INDEX


def ensure_task_transition_allowed(
    current: TaskStatus,
    target: TaskStatus,
    *,
    creates_new_run: bool = False,
) -> None:
    """Raise unless the task move is legal.

    Raises :class:`TypeError` for arguments that are not exact
    :class:`TaskStatus` members, and :class:`InvalidLifecycleTransition` for a
    well-typed but illegal transition.
    """

    _require_status(current, TaskStatus, _TASK_EXPECTED_TYPE)
    _require_status(target, TaskStatus, _TASK_EXPECTED_TYPE)
    if is_task_transition_allowed(current, target, creates_new_run=creates_new_run):
        return
    raise _InvalidTaskTransition(
        current=current,
        target=target,
        creates_new_run=bool(creates_new_run),
    )


def is_run_transition_allowed(
    current: RunStatus,
    target: RunStatus,
) -> bool:
    """Return whether a run may move from ``current`` to ``target``.

    Both arguments must be exact :class:`RunStatus` members; anything else is
    rejected with ``False``.

    Runs have no new-run escape hatch: a terminal run stays terminal, and a
    retry is represented by a new run record.
    """

    if type(current) is not RunStatus or type(target) is not RunStatus:
        return False
    if current is target:
        return False
    return (current, target) in _RUN_ALLOWED_INDEX


def ensure_run_transition_allowed(
    current: RunStatus,
    target: RunStatus,
) -> None:
    """Raise unless the run move is legal.

    Raises :class:`TypeError` for arguments that are not exact
    :class:`RunStatus` members, and :class:`InvalidLifecycleTransition` for a
    well-typed but illegal transition.
    """

    _require_status(current, RunStatus, _RUN_EXPECTED_TYPE)
    _require_status(target, RunStatus, _RUN_EXPECTED_TYPE)
    if is_run_transition_allowed(current, target):
        return
    raise _InvalidRunTransition(current=current, target=target)


def _require_status(value: object, expected: type[StrEnum], expected_name: str) -> None:
    """Reject anything that is not an exact member of the expected vocabulary.

    The message is deterministic and built only from the value's own ``repr``
    and type name, so it cannot smuggle in caller-controlled text.
    """

    if type(value) is not expected:
        raise TypeError(
            f"expected {expected_name}, got {value!r} ({type(value).__name__})"
        )


class InvalidLifecycleTransition(DeepChoiceError):
    """Raised when a lifecycle transition is not part of the contract.

    The entity, code, message, action, and details are all derived from the
    status vocabularies, so callers cannot inject their own text. Messages and
    actions are fixed strings that never contain paths, exception
    representations, or other internal state.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "InvalidLifecycleTransition is raised by the lifecycle helpers; "
            "it cannot be constructed directly."
        )


class _InvalidTaskTransition(InvalidLifecycleTransition):
    """A well-typed task transition that the contract does not allow."""

    _CODE: Final[str] = "TASK_STATUS_TRANSITION_INVALID"

    def __init__(
        self,
        *,
        current: TaskStatus,
        target: TaskStatus,
        creates_new_run: bool,
    ) -> None:
        DeepChoiceError.__init__(
            self,
            "Invalid task status transition from "
            f"'{current.value}' to '{target.value}'.",
            category=ErrorCategory.CONTRACT,
            code=self._CODE,
            status_code=409,
            retryable=False,
            action=_TASK_TRANSITION_ACTION,
            details={
                "entity": "task",
                "current_status": current.value,
                "target_status": target.value,
                "creates_new_run": creates_new_run,
            },
        )


class _InvalidRunTransition(InvalidLifecycleTransition):
    """A well-typed run transition that the contract does not allow."""

    _CODE: Final[str] = "RUN_STATUS_TRANSITION_INVALID"

    def __init__(self, *, current: RunStatus, target: RunStatus) -> None:
        DeepChoiceError.__init__(
            self,
            "Invalid run status transition from "
            f"'{current.value}' to '{target.value}'.",
            category=ErrorCategory.CONTRACT,
            code=self._CODE,
            status_code=409,
            retryable=False,
            action=_RUN_TRANSITION_ACTION,
            details={
                "entity": "run",
                "current_status": current.value,
                "target_status": target.value,
            },
        )
