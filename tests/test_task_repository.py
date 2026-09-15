"""Focused contracts for durable task/run persistence and pagination."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import _expected_manifest_id, build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import CheckpointReference, RunRecord, TaskRecord
from deepchoice.persistence.repository import (
    CheckpointNotAvailableError,
    RepositoryOperationError,
    RunLeaseLostError,
    SQLiteTaskRunRepository,
    TaskNotFoundError,
    TaskVersionConflictError,
)
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.services.tasks import TaskService


def _records(task_id: str = "task-1", run_id: str = "run-1", *, created_at: datetime | None = None):
    now = created_at or datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    task = TaskRecord(task_id=task_id, status=TaskStatus.QUEUED, request=request,
                      latest_run_id=run_id, created_at=now, updated_at=now)
    run = RunRecord(run_id=run_id, task_id=task_id, status=RunStatus.QUEUED,
                    manifest=build_run_manifest(request.model_dump()),
                    budget_policy=DEFAULT_RUN_BUDGET_POLICY, thread_id=run_id,
                    created_at=now, updated_at=now)
    return task, run


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    connection = await connect_database(tmp_path / "deepchoice.db")
    await run_migrations(connection)
    repo = SQLiteTaskRunRepository(connection)
    try:
        yield repo
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_get_roundtrip_and_not_found(repository):
    task, run = _records()
    created = await repository.create_task_with_run(task, run)
    loaded = await repository.get_task(task.task_id)
    assert loaded == created
    assert loaded.latest_run is not None
    assert loaded.latest_run.thread_id == run.thread_id
    assert await repository.get_task("missing") is None
    assert await repository.get_run("missing") is None


@pytest.mark.asyncio
async def test_create_rolls_back_when_run_insert_fails(repository):
    task, run = _records()
    duplicate = _records("task-2", "run-1")[0]
    await repository.create_task_with_run(task, run)
    with pytest.raises(RepositoryOperationError):
        await repository.create_task_with_run(duplicate, _records("task-2", "run-1")[1])
    assert await repository.get_task("task-2") is None


@pytest.mark.asyncio
async def test_transition_is_atomic_cas_and_invalid_transition_writes_nothing(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    updated = await repository.transition_current_run(
        task.task_id, expected_task_version=0,
        target_task_status=TaskStatus.RUNNING, target_run_status=RunStatus.RUNNING,
    )
    assert updated.task.version == 1 and updated.latest_run.version == 1
    with pytest.raises(TaskVersionConflictError):
        await repository.transition_current_run(
            task.task_id, expected_task_version=0,
            target_task_status=TaskStatus.WAITING_FOR_INPUT,
            target_run_status=RunStatus.WAITING_FOR_INPUT,
        )
    current = await repository.get_task(task.task_id)
    assert current.task.status is TaskStatus.RUNNING and current.task.version == 1
    with pytest.raises(ValueError, match="target statuses must match"):
        await repository.transition_current_run(
            task.task_id, expected_task_version=1,
            target_task_status=TaskStatus.COMPLETED,
            target_run_status=RunStatus.QUEUED,
        )
    current = await repository.get_task(task.task_id)
    assert current.task.status is TaskStatus.RUNNING and current.latest_run.version == 1


@pytest.mark.asyncio
async def test_two_concurrent_cas_calls_only_one_succeeds(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    calls = [repository.transition_current_run(
        task.task_id, expected_task_version=0,
        target_task_status=TaskStatus.RUNNING, target_run_status=RunStatus.RUNNING,
    ) for _ in range(2)]
    results = await asyncio.gather(*calls, return_exceptions=True)
    assert sum(isinstance(result, TaskVersionConflictError) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1


@pytest.mark.asyncio
async def test_keyset_order_and_same_timestamp_tie_break(repository):
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    for task_id in ("a", "c", "b"):
        await repository.create_task_with_run(*_records(task_id, f"run-{task_id}", created_at=timestamp))
    page = await repository.list_tasks(status=None, before=None, limit=3)
    assert [item.task.task_id for item in page] == ["c", "b", "a"]
    next_page = await repository.list_tasks(
        status=None, before=(page[-1].task.created_at, page[-1].task.task_id), limit=3
    )
    assert not next_page


@pytest.mark.asyncio
async def test_lease_is_single_owner_epoch_fenced_and_heartbeat_validates(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id, lease_owner="worker-a", lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5), now=now,
    )
    assert grant.execution_epoch == 1
    assert grant.status is RunStatus.RUNNING
    with pytest.raises(RunLeaseLostError):
        await repository.acquire_run_lease(
            run.run_id, lease_owner="worker-b", lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5), now=now,
        )
    beat = await repository.heartbeat_run_lease(
        run.run_id, lease_owner="worker-a", execution_epoch=1,
        lease_ttl=timedelta(seconds=30), now=now + timedelta(seconds=1),
    )
    assert beat.execution_epoch == 1
    assert beat.status is RunStatus.RUNNING
    with pytest.raises(RunLeaseLostError):
        await repository.heartbeat_run_lease(
            run.run_id, lease_owner="worker-b", execution_epoch=1,
            lease_ttl=timedelta(seconds=30), now=now + timedelta(seconds=1),
        )
    await repository.finalize_run(
        run.run_id, lease_owner="worker-a", execution_epoch=1,
        status=RunStatus.COMPLETED, now=now + timedelta(seconds=2),
    )


@pytest.mark.asyncio
async def test_checkpoint_reference_is_idempotent_and_old_epoch_is_fenced(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id, lease_owner="worker-a", lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5), now=now,
    )
    reference = CheckpointReference(
        run_id=run.run_id, checkpoint_id="cp-1", node="retrieve",
        state_schema_version=run.manifest.state_schema_version,
        execution_epoch=grant.execution_epoch, created_at=now + timedelta(seconds=1),
    )
    await repository.add_checkpoint_reference(reference, lease_owner="worker-a", execution_epoch=1, now=now + timedelta(seconds=1))
    await repository.add_checkpoint_reference(reference, lease_owner="worker-a", execution_epoch=1, now=now + timedelta(seconds=1))
    assert (await repository.get_latest_checkpoint_reference(run.run_id)).checkpoint_id == "cp-1"
    with pytest.raises(RunLeaseLostError):
        await repository.add_checkpoint_reference(reference, lease_owner="worker-a", execution_epoch=0, now=now + timedelta(seconds=1))


@pytest.mark.asyncio
async def test_latest_checkpoint_prefers_new_epoch_over_clock_timestamp(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker-a",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    await repository.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            storage_checkpoint_ns="epoch-1",
            checkpoint_id="cp-epoch-1",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=first.execution_epoch,
            created_at=now + timedelta(minutes=10),
        ),
        lease_owner="worker-a",
        execution_epoch=first.execution_epoch,
        now=now,
    )
    interrupted = await repository.finalize_run(
        run.run_id,
        lease_owner="worker-a",
        execution_epoch=first.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=now + timedelta(seconds=1),
    )
    await repository.resume_interrupted_run(
        task.task_id,
        expected_task_version=interrupted.task.version,
        updated_at=now + timedelta(seconds=1),
    )
    second = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker-b",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now + timedelta(seconds=2),
    )
    await repository.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            storage_checkpoint_ns="epoch-2",
            checkpoint_id="cp-epoch-2",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=second.execution_epoch,
            created_at=now,
        ),
        lease_owner="worker-b",
        execution_epoch=second.execution_epoch,
        now=now + timedelta(seconds=2),
    )

    latest = await repository.get_latest_checkpoint_reference(
        run.run_id,
        state_schema_version=run.manifest.state_schema_version,
        checkpoint_ns="",
    )
    assert latest is not None
    assert latest.execution_epoch == second.execution_epoch
    assert latest.storage_checkpoint_ns == "epoch-2"


@pytest.mark.asyncio
async def test_cancel_queued_is_idempotent_and_running_becomes_cancelling(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    cancelled = await repository.cancel_task(task.task_id, updated_at=now)
    assert cancelled.task.status is TaskStatus.CANCELLED
    assert (await repository.cancel_task(task.task_id, updated_at=now)).task.status is TaskStatus.CANCELLED

    task2, run2 = _records("task-2", "run-2")
    await repository.create_task_with_run(task2, run2)
    await repository.acquire_run_lease(run2.run_id, lease_owner="worker", lease_ttl=timedelta(seconds=30), run_timeout=timedelta(minutes=5), now=now)
    cancelling = await repository.cancel_task(task2.task_id, updated_at=now + timedelta(seconds=1))
    assert cancelling.task.status is TaskStatus.CANCELLING
    await repository.finalize_run(run2.run_id, lease_owner="worker", execution_epoch=1, status=RunStatus.COMPLETED, now=now + timedelta(seconds=2))
    assert (await repository.get_task(task2.task_id)).task.status is TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_expired_recovery_without_checkpoint_is_interrupted(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    await repository.acquire_run_lease(run.run_id, lease_owner="worker", lease_ttl=timedelta(seconds=1), run_timeout=timedelta(minutes=5), now=now)
    recovered = await repository.recover_runs(now=now + timedelta(seconds=2))
    assert recovered == ()
    current = await repository.get_task(task.task_id)
    assert current.task.status is TaskStatus.INTERRUPTED
    assert current.latest_run.status is RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_expired_recovery_after_deadline_is_timed_out(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(seconds=1),
        run_timeout=timedelta(seconds=2),
        now=now,
    )

    recovered = await repository.recover_runs(now=now + timedelta(seconds=3))

    assert recovered == ()
    current = await repository.get_task(task.task_id)
    assert current.task.status is TaskStatus.TIMED_OUT
    assert current.latest_run.status is RunStatus.TIMED_OUT
    assert current.latest_run.deadline_at == grant.deadline_at
    assert current.latest_run.ended_at == now + timedelta(seconds=3)


@pytest.mark.asyncio
async def test_expired_recovery_prioritizes_cancel_over_deadline(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(seconds=1),
        run_timeout=timedelta(seconds=1),
        now=now,
    )
    await repository.cancel_task(
        task.task_id, updated_at=now + timedelta(milliseconds=500)
    )

    assert await repository.recover_runs(now=now + timedelta(seconds=2)) == ()
    current = await repository.get_task(task.task_id)
    assert current.task.status is TaskStatus.CANCELLED
    assert current.latest_run.status is RunStatus.CANCELLED
    assert current.latest_run.deadline_at is None


@pytest.mark.asyncio
async def test_interrupted_resume_reuses_compatible_checkpoint(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    await repository.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            checkpoint_id="cp-compatible",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=grant.execution_epoch,
            created_at=now,
        ),
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        now=now,
    )
    interrupted = await repository.finalize_run(
        run.run_id,
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=now + timedelta(seconds=1),
    )
    service = TaskService(repository)
    resumed = await service.resume(
        task.task_id, expected_task_version=interrupted.task.version
    )
    assert resumed.task.status is TaskStatus.QUEUED
    assert resumed.latest_run.run_id == run.run_id
    assert resumed.latest_run.thread_id == run.thread_id
    assert resumed.latest_run.manifest == run.manifest


@pytest.mark.asyncio
async def test_interrupted_v1_checkpoint_retries_as_current_v3_run(repository):
    task, run = _records()
    old_manifest = run.manifest.model_copy(
        update={
            "workflow_version": "research-v1",
            "workflow_nodes": tuple(
                node
                for node in run.manifest.workflow_nodes
                if node not in {"citation_validator", "evidence_decision_gate"}
            ),
            "state_schema_version": 1,
            "citation_policy_version": None,
            "hitl_policy_version": None,
        }
    )
    old_manifest = old_manifest.model_copy(
        update={"manifest_id": _expected_manifest_id(old_manifest)}
    )
    run = run.model_copy(update={"manifest": old_manifest})
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    await repository.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            checkpoint_id="cp-v1",
            state_schema_version=1,
            execution_epoch=grant.execution_epoch,
            created_at=now,
        ),
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        now=now,
    )
    interrupted = await repository.finalize_run(
        run.run_id,
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=now + timedelta(seconds=1),
    )

    resumed = await TaskService(repository).resume(
        task.task_id, expected_task_version=interrupted.task.version
    )

    assert resumed.latest_run.run_id != run.run_id
    assert resumed.latest_run.manifest.workflow_version == "research-v3"
    assert resumed.latest_run.manifest.state_schema_version == 3
    assert resumed.latest_run.manifest.citation_policy_version == (
        "deterministic-citation-v1"
    )
    assert resumed.latest_run.manifest.hitl_policy_version == "evidence-insufficient-v1"
    assert (await repository.get_run(run.run_id)).status is RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_interrupted_without_checkpoint_retries_as_new_run_with_cas(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    interrupted = await repository.finalize_run(
        run.run_id,
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=now + timedelta(seconds=1),
    )
    service = TaskService(repository)
    results = await asyncio.gather(
        service.resume(task.task_id, expected_task_version=interrupted.task.version),
        service.resume(task.task_id, expected_task_version=interrupted.task.version),
        return_exceptions=True,
    )
    resumed = next(result for result in results if not isinstance(result, Exception))
    assert sum(isinstance(result, TaskVersionConflictError) for result in results) == 1
    assert resumed.latest_run.run_id != run.run_id
    assert resumed.latest_run.thread_id == resumed.latest_run.run_id
    assert (await repository.get_run(run.run_id)).status is RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_interrupted_non_root_checkpoint_retries_as_new_run(repository):
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    await repository.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            checkpoint_ns="subgraph:worker",
            storage_checkpoint_ns="physical-subgraph",
            checkpoint_id="cp-subgraph",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=grant.execution_epoch,
            created_at=now,
        ),
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        now=now,
    )
    interrupted = await repository.finalize_run(
        run.run_id,
        lease_owner="worker",
        execution_epoch=grant.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=now + timedelta(seconds=1),
    )
    with pytest.raises(CheckpointNotAvailableError):
        await repository.resume_interrupted_run(
            task.task_id,
            expected_task_version=interrupted.task.version,
        )

    resumed = await TaskService(repository).resume(
        task.task_id, expected_task_version=interrupted.task.version
    )

    assert resumed.latest_run.run_id != run.run_id
    assert resumed.latest_run.execution_epoch == 0
