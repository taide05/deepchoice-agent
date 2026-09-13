"""Contract tests for the task and run lifecycle domain rules.

The allowed-transition matrices below are written out literally from the
contract rather than derived from the implementation, so a change in
``deepchoice.runtime.lifecycle`` cannot silently redefine what is legal.
"""

from itertools import product

import pytest

import deepchoice.runtime
from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory
from deepchoice.runtime import (
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

# --- contract fixtures -------------------------------------------------------

EXPECTED_MEMBERS: dict[str, str] = {
    "QUEUED": "queued",
    "RUNNING": "running",
    "WAITING_FOR_INPUT": "waiting_for_input",
    "CANCELLING": "cancelling",
    "COMPLETED": "completed",
    "COMPLETED_WITH_WARNINGS": "completed_with_warnings",
    "FAILED": "failed",
    "TIMED_OUT": "timed_out",
    "CANCELLED": "cancelled",
    "INTERRUPTED": "interrupted",
}

# Task transitions that are legal without creating a new run.
ALLOWED_TASK_TRANSITIONS: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset(
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

# Task transitions that are legal only when a new run is created.
ALLOWED_TASK_NEW_RUN_TRANSITIONS: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset(
    {
        (TaskStatus.FAILED, TaskStatus.QUEUED),
        (TaskStatus.TIMED_OUT, TaskStatus.QUEUED),
    }
)

ALLOWED_RUN_TRANSITIONS: frozenset[tuple[RunStatus, RunStatus]] = frozenset(
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

ALL_TASK_PAIRS: list[tuple[TaskStatus, TaskStatus]] = list(product(TaskStatus, TaskStatus))
ALL_RUN_PAIRS: list[tuple[RunStatus, RunStatus]] = list(product(RunStatus, RunStatus))


# --- 1. vocabulary -----------------------------------------------------------


def test_task_status_members_match_contract() -> None:
    assert {member.name: member.value for member in TaskStatus} == EXPECTED_MEMBERS


def test_run_status_members_match_contract() -> None:
    assert {member.name: member.value for member in RunStatus} == EXPECTED_MEMBERS


def test_statuses_are_str_enums_with_identical_values() -> None:
    assert issubclass(TaskStatus, str) and issubclass(RunStatus, str)
    # Values coincide, but the types must stay distinct so a run record can
    # never be used where a task projection is expected.
    assert TaskStatus is not RunStatus
    assert [member.value for member in TaskStatus] == [member.value for member in RunStatus]
    assert len(set(TaskStatus)) == len(EXPECTED_MEMBERS)
    assert len(set(RunStatus)) == len(EXPECTED_MEMBERS)


def test_status_types_are_distinct_and_not_interchangeable() -> None:
    # Distinct classes, and neither is an instance of the other, so a run
    # record cannot be passed where a task projection is expected. (Note that
    # `==` still compares equal because str-backed enums compare by value;
    # keeping the types apart is what stops the two records being mixed up.)
    assert TaskStatus is not RunStatus
    assert not isinstance(TaskStatus.QUEUED, RunStatus)
    assert not isinstance(RunStatus.QUEUED, TaskStatus)
    assert TaskStatus.QUEUED is not RunStatus.QUEUED
    assert type(TaskStatus.QUEUED) is not type(RunStatus.QUEUED)


# --- 3. immutable status sets ------------------------------------------------


def test_run_terminal_statuses_exact() -> None:
    assert RUN_TERMINAL_STATUSES == frozenset(
        {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
        }
    )
    assert isinstance(RUN_TERMINAL_STATUSES, frozenset)


def test_task_retryable_outcome_statuses_exact() -> None:
    assert TASK_RETRYABLE_OUTCOME_STATUSES == frozenset(
        {TaskStatus.FAILED, TaskStatus.TIMED_OUT}
    )
    assert isinstance(TASK_RETRYABLE_OUTCOME_STATUSES, frozenset)


def test_task_immutable_outcome_statuses_exact() -> None:
    assert TASK_IMMUTABLE_OUTCOME_STATUSES == frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.COMPLETED_WITH_WARNINGS,
            TaskStatus.CANCELLED,
        }
    )
    assert isinstance(TASK_IMMUTABLE_OUTCOME_STATUSES, frozenset)


def test_status_sets_are_consistent_with_the_matrices() -> None:
    # Immutable task outcomes and terminal runs are sinks: nothing leaves them.
    for status in TASK_IMMUTABLE_OUTCOME_STATUSES:
        assert [pair for pair in ALLOWED_TASK_TRANSITIONS if pair[0] is status] == []
    for status in RUN_TERMINAL_STATUSES:
        assert [pair for pair in ALLOWED_RUN_TRANSITIONS if pair[0] is status] == []

    # Retryable task outcomes are exactly the sources of new-run transitions.
    assert {source for source, _ in ALLOWED_TASK_NEW_RUN_TRANSITIONS} == (
        TASK_RETRYABLE_OUTCOME_STATUSES
    )

    # Terminal outcomes are reached only from these sources. Several statuses
    # may move to `cancelled`, but the run outcomes (completed / warnings /
    # failed / timed_out) are reachable only from `running`.
    terminal_targets = TASK_IMMUTABLE_OUTCOME_STATUSES | TASK_RETRYABLE_OUTCOME_STATUSES
    sources = {
        source for source, target in ALLOWED_TASK_TRANSITIONS if target in terminal_targets
    }
    assert sources == {
        TaskStatus.RUNNING,
        TaskStatus.QUEUED,
        TaskStatus.WAITING_FOR_INPUT,
        TaskStatus.INTERRUPTED,
        TaskStatus.CANCELLING,
    }
    run_outcomes = {
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED_WITH_WARNINGS,
        TaskStatus.FAILED,
        TaskStatus.TIMED_OUT,
    }
    assert {
        source for source, target in ALLOWED_TASK_TRANSITIONS if target in run_outcomes
    } == {TaskStatus.RUNNING}


# --- 2. every listed transition passes ---------------------------------------


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED_TASK_TRANSITIONS))
def test_allowed_task_transitions_pass(current: TaskStatus, target: TaskStatus) -> None:
    assert is_task_transition_allowed(current, target) is True
    assert ensure_task_transition_allowed(current, target) is None


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED_TASK_NEW_RUN_TRANSITIONS))
def test_allowed_task_new_run_transitions_pass(
    current: TaskStatus, target: TaskStatus
) -> None:
    assert is_task_transition_allowed(current, target, creates_new_run=True) is True
    assert ensure_task_transition_allowed(current, target, creates_new_run=True) is None


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED_RUN_TRANSITIONS))
def test_allowed_run_transitions_pass(current: RunStatus, target: RunStatus) -> None:
    assert is_run_transition_allowed(current, target) is True
    assert ensure_run_transition_allowed(current, target) is None


# --- 3. exhaustive rejection of everything not listed ------------------------


@pytest.mark.parametrize(("current", "target"), ALL_TASK_PAIRS)
def test_task_matrix_is_exhaustive_without_new_run(
    current: TaskStatus, target: TaskStatus
) -> None:
    expected = (current, target) in ALLOWED_TASK_TRANSITIONS
    assert is_task_transition_allowed(current, target) is expected


@pytest.mark.parametrize(("current", "target"), ALL_TASK_PAIRS)
def test_task_matrix_is_exhaustive_with_new_run(
    current: TaskStatus, target: TaskStatus
) -> None:
    expected = (current, target) in (
        ALLOWED_TASK_TRANSITIONS | ALLOWED_TASK_NEW_RUN_TRANSITIONS
    )
    assert is_task_transition_allowed(current, target, creates_new_run=True) is expected


@pytest.mark.parametrize(("current", "target"), ALL_RUN_PAIRS)
def test_run_matrix_is_exhaustive(current: RunStatus, target: RunStatus) -> None:
    expected = (current, target) in ALLOWED_RUN_TRANSITIONS
    assert is_run_transition_allowed(current, target) is expected


def test_no_self_transition_is_allowed_for_tasks() -> None:
    for status in TaskStatus:
        assert is_task_transition_allowed(status, status) is False
        assert is_task_transition_allowed(status, status, creates_new_run=True) is False


def test_no_self_transition_is_allowed_for_runs() -> None:
    for status in RunStatus:
        assert is_run_transition_allowed(status, status) is False


def test_self_transition_raises_instead_of_passing() -> None:
    for status in TaskStatus:
        with pytest.raises(InvalidLifecycleTransition):
            ensure_task_transition_allowed(status, status)
    for status in RunStatus:
        with pytest.raises(InvalidLifecycleTransition):
            ensure_run_transition_allowed(status, status)


# --- 5. retry outcomes require an explicitly new run -------------------------


@pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.TIMED_OUT])
def test_retry_outcome_to_queued_requires_new_run(status: TaskStatus) -> None:
    assert is_task_transition_allowed(status, TaskStatus.QUEUED) is False
    with pytest.raises(InvalidLifecycleTransition):
        ensure_task_transition_allowed(status, TaskStatus.QUEUED)
    assert is_task_transition_allowed(status, TaskStatus.QUEUED, creates_new_run=True)
    assert ensure_task_transition_allowed(status, TaskStatus.QUEUED, creates_new_run=True) is None


@pytest.mark.parametrize(
    "status", [TaskStatus.COMPLETED, TaskStatus.COMPLETED_WITH_WARNINGS, TaskStatus.CANCELLED]
)
def test_creates_new_run_does_not_unlock_other_transitions(status: TaskStatus) -> None:
    # The flag only gates the retry outcomes; it is not a general override.
    for target in TaskStatus:
        assert is_task_transition_allowed(status, target, creates_new_run=True) is False
        with pytest.raises(InvalidLifecycleTransition):
            ensure_task_transition_allowed(status, target, creates_new_run=True)


# --- 6. immutable outcomes are never reopened --------------------------------


@pytest.mark.parametrize(
    "status",
    [TaskStatus.COMPLETED, TaskStatus.COMPLETED_WITH_WARNINGS, TaskStatus.CANCELLED],
)
def test_immutable_task_outcomes_are_never_reopened(status: TaskStatus) -> None:
    for target in TaskStatus:
        assert is_task_transition_allowed(status, target) is False
        assert is_task_transition_allowed(status, target, creates_new_run=True) is False


# --- 7. runs have no retry escape hatch --------------------------------------


@pytest.mark.parametrize("status", sorted(RUN_TERMINAL_STATUSES))
def test_terminal_runs_never_transition(status: RunStatus) -> None:
    for target in RunStatus:
        assert is_run_transition_allowed(status, target) is False
        with pytest.raises(InvalidLifecycleTransition):
            ensure_run_transition_allowed(status, target)


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.TIMED_OUT])
def test_failed_run_never_returns_to_queued(status: RunStatus) -> None:
    assert is_run_transition_allowed(status, RunStatus.QUEUED) is False
    with pytest.raises(InvalidLifecycleTransition):
        ensure_run_transition_allowed(status, RunStatus.QUEUED)


def test_run_transition_helpers_accept_no_new_run_flag() -> None:
    # A retry intent cannot be expressed for a run at all.
    with pytest.raises(TypeError):
        ensure_run_transition_allowed(  # type: ignore[call-arg]
            RunStatus.FAILED, RunStatus.QUEUED, creates_new_run=True
        )


# --- running must pass through cancelling ------------------------------------


def test_running_cannot_go_straight_to_cancelled() -> None:
    assert is_task_transition_allowed(TaskStatus.RUNNING, TaskStatus.CANCELLED) is False
    assert is_run_transition_allowed(RunStatus.RUNNING, RunStatus.CANCELLED) is False
    with pytest.raises(InvalidLifecycleTransition):
        ensure_task_transition_allowed(TaskStatus.RUNNING, TaskStatus.CANCELLED)
    with pytest.raises(InvalidLifecycleTransition):
        ensure_run_transition_allowed(RunStatus.RUNNING, RunStatus.CANCELLED)


def test_queued_and_waiting_for_input_cancel_directly() -> None:
    for status in (TaskStatus.QUEUED, TaskStatus.WAITING_FOR_INPUT):
        assert is_task_transition_allowed(status, TaskStatus.CANCELLED) is True
    for status in (RunStatus.QUEUED, RunStatus.WAITING_FOR_INPUT):
        assert is_run_transition_allowed(status, RunStatus.CANCELLED) is True


# --- 9. error contract -------------------------------------------------------


def test_error_inherits_project_error_and_policy() -> None:
    assert issubclass(InvalidLifecycleTransition, DeepChoiceError)

    error = InvalidLifecycleTransition(
        entity="task",
        code="TASK_STATUS_TRANSITION_INVALID",
        current_status="completed",
        target_status="running",
        action="Reload the task status.",
        creates_new_run=False,
    )
    detail = error.error_detail
    assert error.status_code == 409
    assert detail.category is ErrorCategory.CONTRACT
    assert detail.code == "TASK_STATUS_TRANSITION_INVALID"
    assert detail.retryable is False


def test_task_error_details_payload() -> None:
    error = InvalidLifecycleTransition(
        entity="task",
        code="TASK_STATUS_TRANSITION_INVALID",
        current_status="failed",
        target_status="queued",
        action="Reload the task status.",
        creates_new_run=False,
    )
    assert error.error_detail.details == {
        "entity": "task",
        "current_status": "failed",
        "target_status": "queued",
        "creates_new_run": False,
    }


def test_run_error_details_payload() -> None:
    error = InvalidLifecycleTransition(
        entity="run",
        code="RUN_STATUS_TRANSITION_INVALID",
        current_status="failed",
        target_status="queued",
        action="Reload the run status.",
    )
    assert error.error_detail.details == {
        "entity": "run",
        "current_status": "failed",
        "target_status": "queued",
    }


def test_ensure_raises_task_error_with_contract_fields() -> None:
    with pytest.raises(InvalidLifecycleTransition) as caught:
        ensure_task_transition_allowed(TaskStatus.COMPLETED, TaskStatus.RUNNING)

    error = caught.value
    detail = error.error_detail
    assert error.status_code == 409
    assert detail.category is ErrorCategory.CONTRACT
    assert detail.code == "TASK_STATUS_TRANSITION_INVALID"
    assert detail.retryable is False
    assert detail.details == {
        "entity": "task",
        "current_status": "completed",
        "target_status": "running",
        "creates_new_run": False,
    }


def test_ensure_raises_task_error_reporting_new_run_intent() -> None:
    with pytest.raises(InvalidLifecycleTransition) as caught:
        ensure_task_transition_allowed(
            TaskStatus.COMPLETED, TaskStatus.RUNNING, creates_new_run=True
        )
    assert caught.value.error_detail.details["creates_new_run"] is True


def test_ensure_raises_run_error_with_contract_fields() -> None:
    with pytest.raises(InvalidLifecycleTransition) as caught:
        ensure_run_transition_allowed(RunStatus.FAILED, RunStatus.QUEUED)

    error = caught.value
    detail = error.error_detail
    assert error.status_code == 409
    assert detail.category is ErrorCategory.CONTRACT
    assert detail.code == "RUN_STATUS_TRANSITION_INVALID"
    assert detail.retryable is False
    assert detail.details == {
        "entity": "run",
        "current_status": "failed",
        "target_status": "queued",
    }


def test_error_codes_are_distinct_per_entity() -> None:
    with pytest.raises(InvalidLifecycleTransition) as task_error:
        ensure_task_transition_allowed(TaskStatus.QUEUED, TaskStatus.FAILED)
    with pytest.raises(InvalidLifecycleTransition) as run_error:
        ensure_run_transition_allowed(RunStatus.QUEUED, RunStatus.FAILED)
    assert task_error.value.error_detail.code == "TASK_STATUS_TRANSITION_INVALID"
    assert run_error.value.error_detail.code == "RUN_STATUS_TRANSITION_INVALID"


# --- error text is safe and stable -------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [(TaskStatus.COMPLETED, TaskStatus.RUNNING), (TaskStatus.QUEUED, TaskStatus.FAILED)],
)
def test_task_error_text_is_safe_and_stable(
    current: TaskStatus, target: TaskStatus
) -> None:
    first = _capture_task_error(current, target)
    second = _capture_task_error(current, target)
    detail = first.error_detail

    assert detail.message == f"Invalid task status transition from '{current}' to '{target}'."
    assert detail.message == second.error_detail.message
    assert detail.action == second.error_detail.action
    assert detail.message == str(first)

    for text in (detail.message, detail.action or ""):
        assert text
        assert ":\\" not in text and ":/" not in text
        assert "Traceback" not in text
        assert "0x" not in text
        assert "<" not in text
        assert "object at" not in text


def test_run_error_text_is_safe_and_stable() -> None:
    with pytest.raises(InvalidLifecycleTransition) as caught:
        ensure_run_transition_allowed(RunStatus.COMPLETED, RunStatus.RUNNING)

    detail = caught.value.error_detail
    assert detail.message == "Invalid run status transition from 'completed' to 'running'."
    assert detail.action
    assert ":\\" not in detail.action and "Traceback" not in detail.action


def _capture_task_error(current: TaskStatus, target: TaskStatus) -> InvalidLifecycleTransition:
    with pytest.raises(InvalidLifecycleTransition) as caught:
        ensure_task_transition_allowed(current, target)
    return caught.value


# --- 10. package surface -----------------------------------------------------


def test_public_symbols_are_available_from_package() -> None:
    for name in (
        "TaskStatus",
        "RunStatus",
        "InvalidLifecycleTransition",
        "RUN_TERMINAL_STATUSES",
        "TASK_RETRYABLE_OUTCOME_STATUSES",
        "TASK_IMMUTABLE_OUTCOME_STATUSES",
        "is_task_transition_allowed",
        "ensure_task_transition_allowed",
        "is_run_transition_allowed",
        "ensure_run_transition_allowed",
    ):
        assert hasattr(deepchoice.runtime, name), name
        assert name in deepchoice.runtime.__all__, name

    assert deepchoice.runtime.TaskStatus is TaskStatus
    assert deepchoice.runtime.is_task_transition_allowed is is_task_transition_allowed


def test_package_exports_only_stable_lifecycle_symbols() -> None:
    assert set(deepchoice.runtime.__all__) == {
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
    }
