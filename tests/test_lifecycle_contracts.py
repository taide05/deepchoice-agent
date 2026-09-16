"""Behavioral contract tests for the Phase 1-A lifecycle vocabulary."""

from itertools import product

import pytest

from deepchoice.contracts.errors import ErrorCategory
from deepchoice.runtime import (
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


TASK_ALLOWED = {
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
TASK_NEW_RUN = {
    (TaskStatus.FAILED, TaskStatus.QUEUED),
    (TaskStatus.TIMED_OUT, TaskStatus.QUEUED),
    (TaskStatus.INTERRUPTED, TaskStatus.QUEUED),
}
RUN_ALLOWED = {
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
EXPECTED_STATUS_VALUES = {
    "queued",
    "running",
    "waiting_for_input",
    "cancelling",
    "completed",
    "completed_with_warnings",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
}


def test_public_exports_and_outcome_sets() -> None:
    assert TaskStatus is not RunStatus
    assert TaskStatus.QUEUED != RunStatus.QUEUED
    assert len({TaskStatus.QUEUED, RunStatus.QUEUED}) == 2
    assert TaskStatus.FAILED not in RUN_TERMINAL_STATUSES
    assert {status.value for status in TaskStatus} == EXPECTED_STATUS_VALUES
    assert {status.value for status in RunStatus} == EXPECTED_STATUS_VALUES
    assert RUN_TERMINAL_STATUSES == {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    }
    assert TASK_IMMUTABLE_OUTCOME_STATUSES == {
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED_WITH_WARNINGS,
        TaskStatus.CANCELLED,
    }
    assert TASK_RETRYABLE_OUTCOME_STATUSES == {
        TaskStatus.FAILED,
        TaskStatus.TIMED_OUT,
    }


@pytest.mark.parametrize("current,target", product(TaskStatus, TaskStatus))
def test_task_matrix_is_exhaustive(current: TaskStatus, target: TaskStatus) -> None:
    expected = (current, target) in TASK_ALLOWED
    assert is_task_transition_allowed(
        current, target, intent=TaskTransitionIntent.SAME_RUN
    ) is expected
    if expected:
        assert ensure_task_transition_allowed(
            current, target, intent=TaskTransitionIntent.SAME_RUN
        ) is None
    else:
        with pytest.raises(InvalidLifecycleTransition):
            ensure_task_transition_allowed(
                current, target, intent=TaskTransitionIntent.SAME_RUN
            )


@pytest.mark.parametrize("current,target", product(TaskStatus, TaskStatus))
def test_task_new_run_matrix_is_exhaustive(
    current: TaskStatus, target: TaskStatus
) -> None:
    expected = (current, target) in TASK_NEW_RUN
    assert is_task_transition_allowed(
        current, target, intent=TaskTransitionIntent.NEW_RUN
    ) is expected
    if expected:
        assert ensure_task_transition_allowed(
            current, target, intent=TaskTransitionIntent.NEW_RUN
        ) is None
    else:
        with pytest.raises(InvalidLifecycleTransition):
            ensure_task_transition_allowed(
                current, target, intent=TaskTransitionIntent.NEW_RUN
            )


@pytest.mark.parametrize("current,target", product(RunStatus, RunStatus))
def test_run_matrix_is_exhaustive(current: RunStatus, target: RunStatus) -> None:
    expected = (current, target) in RUN_ALLOWED
    assert is_run_transition_allowed(current, target) is expected
    if expected:
        assert ensure_run_transition_allowed(current, target) is None
    else:
        with pytest.raises(InvalidLifecycleTransition):
            ensure_run_transition_allowed(current, target)


@pytest.mark.parametrize("current", TASK_RETRYABLE_OUTCOME_STATUSES)
def test_retryable_task_outcomes_require_new_run(current: TaskStatus) -> None:
    assert is_task_transition_allowed(
        current, TaskStatus.QUEUED, intent=TaskTransitionIntent.SAME_RUN
    ) is False
    assert is_task_transition_allowed(
        current, TaskStatus.QUEUED, intent=TaskTransitionIntent.NEW_RUN
    )


def test_interrupted_task_supports_compatible_or_new_run_recovery() -> None:
    assert is_task_transition_allowed(
        TaskStatus.INTERRUPTED,
        TaskStatus.QUEUED,
        intent=TaskTransitionIntent.SAME_RUN,
    )
    assert is_task_transition_allowed(
        TaskStatus.INTERRUPTED,
        TaskStatus.QUEUED,
        intent=TaskTransitionIntent.NEW_RUN,
    )


@pytest.mark.parametrize("status", RUN_TERMINAL_STATUSES)
def test_terminal_runs_never_reopen(status: RunStatus) -> None:
    assert all(
        not is_run_transition_allowed(status, target) for target in RunStatus
    )


class BoolBomb:
    def __bool__(self) -> bool:
        raise AssertionError("creates_new_run must be type-checked")


class ReprBomb:
    def __repr__(self) -> str:
        raise AssertionError("error formatting must not call repr")


@pytest.mark.parametrize("value", ["false", 1, None, [], {}, BoolBomb()])
def test_transition_intent_requires_exact_enum(value: object) -> None:
    assert is_task_transition_allowed(
        TaskStatus.FAILED, TaskStatus.QUEUED, intent=value  # type: ignore[arg-type]
    ) is False
    with pytest.raises(TypeError):
        ensure_task_transition_allowed(
            TaskStatus.FAILED, TaskStatus.QUEUED, intent=value  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", ["queued", RunStatus.QUEUED, None, 1, True, [], {}])
def test_task_status_boundary_rejects_nonmatching_types(value: object) -> None:
    assert is_task_transition_allowed(value, TaskStatus.RUNNING) is False  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ensure_task_transition_allowed(value, TaskStatus.RUNNING)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["queued", TaskStatus.QUEUED, None, 1, True, [], {}])
def test_run_status_boundary_rejects_nonmatching_types(value: object) -> None:
    assert is_run_transition_allowed(value, RunStatus.RUNNING) is False  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ensure_run_transition_allowed(value, RunStatus.RUNNING)  # type: ignore[arg-type]


def test_type_errors_are_safe_and_do_not_repr_input() -> None:
    with pytest.raises(TypeError) as caught:
        ensure_task_transition_allowed(ReprBomb(), TaskStatus.RUNNING)  # type: ignore[arg-type]
    assert str(caught.value)
    assert "ReprBomb" not in str(caught.value)
    assert "unsupported input" not in str(caught.value)


def test_invalid_task_and_run_errors_are_independent_contracts() -> None:
    with pytest.raises(InvalidLifecycleTransition) as task_error:
        ensure_task_transition_allowed(TaskStatus.COMPLETED, TaskStatus.QUEUED)
    with pytest.raises(InvalidLifecycleTransition) as run_error:
        ensure_run_transition_allowed(RunStatus.COMPLETED, RunStatus.QUEUED)

    task_detail = task_error.value.error_detail
    run_detail = run_error.value.error_detail
    assert task_error.value.status_code == run_error.value.status_code == 409
    assert task_detail.category is run_detail.category is ErrorCategory.CONTRACT
    assert task_detail.code != run_detail.code
    assert task_detail.action and run_detail.action
    assert task_detail.details["entity"] == "task"
    assert run_detail.details["entity"] == "run"
    assert task_detail.details["current_status"] == "completed"
    assert task_detail.details["target_status"] == "queued"
    assert task_detail.details["intent"] == "same_run"
