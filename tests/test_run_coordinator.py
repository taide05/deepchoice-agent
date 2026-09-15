"""Execution-control contracts with local fake workflow components."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.persistence.repository import SQLiteTaskRunRepository
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


def _records(task_id="task-1", run_id="run-1", *, status=TaskStatus.QUEUED):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    task = TaskRecord(task_id=task_id, status=status, request=request, latest_run_id=run_id, created_at=now, updated_at=now)
    run = RunRecord(run_id=run_id, task_id=task_id, status=RunStatus(status.value), manifest=build_run_manifest(request.model_dump()), budget_policy=DEFAULT_RUN_BUDGET_POLICY, thread_id=run_id, created_at=now, updated_at=now)
    return task, run


class FakeState:
    config = {"configurable": {"checkpoint_id": "cp-1", "checkpoint_ns": ""}}
    values = {"report": "# Fake durable report"}


class FakeOrchestrator:
    mode = "success"
    seen_resumes: list[bool] = []

    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs

    async def get_state(self):
        return FakeState()

    async def astream_research_task(self, *, resume=False):
        self.seen_resumes.append(resume)
        if self.mode == "error":
            raise RuntimeError("fake failure")
        if self.mode == "block":
            await asyncio.Event().wait()
        yield {"fake_node": {"resume": resume}}


class MissingCheckpointSaver:
    async def aget_tuple(self, _config):
        return None


class AcquireReturnBarrierRepository:
    """Pause after the real lease commit but before returning its grant."""

    def __init__(self, delegate: SQLiteTaskRunRepository) -> None:
        self.delegate = delegate
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    async def acquire_run_lease(self, *args, **kwargs):
        grant = await self.delegate.acquire_run_lease(*args, **kwargs)
        self.committed.set()
        await self.release.wait()
        return grant


@pytest_asyncio.fixture
async def repo(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    try:
        yield repository
    finally:
        await connection.close()


async def _wait_done(coordinator: RunCoordinator, run_id: str):
    for _ in range(400):
        if run_id not in coordinator.active_runs:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("coordinator run did not finish")


@pytest.mark.asyncio
async def test_submit_deduplicates_and_records_checkpoint_on_success(repo):
    FakeOrchestrator.mode = "success"
    FakeOrchestrator.seen_resumes.clear()
    task, run = _records()
    await repo.create_task_with_run(task, run)
    coordinator = RunCoordinator(repo, object(), owner_id="worker", lease_ttl=timedelta(seconds=1), heartbeat_interval=timedelta(milliseconds=20), run_timeout=timedelta(seconds=1), orchestrator_factory=FakeOrchestrator)
    submitted = await asyncio.gather(
        coordinator.submit(run.run_id), coordinator.submit(run.run_id)
    )
    assert sorted(submitted) == [False, True]
    await _wait_done(coordinator, run.run_id)
    current = await repo.get_run(run.run_id)
    assert current.status is RunStatus.COMPLETED
    reference = await repo.get_latest_checkpoint_reference(run.run_id)
    assert reference is not None and reference.checkpoint_id == "cp-1"
    assert FakeOrchestrator.seen_resumes == [False]
    await coordinator.stop()


@pytest.mark.asyncio
async def test_cancel_after_lease_commit_before_grant_return_finalizes_once(repo):
    task, run = _records("task-acquire-cancel", "run-acquire-cancel")
    await repo.create_task_with_run(task, run)
    barrier = AcquireReturnBarrierRepository(repo)
    coordinator = RunCoordinator(
        barrier,
        object(),
        owner_id="worker",
        orchestrator_factory=FakeOrchestrator,
    )

    assert await coordinator.submit(run.run_id, resume=False)
    await asyncio.wait_for(barrier.committed.wait(), timeout=1)
    runner = coordinator._active[run.run_id]
    stop_task = asyncio.create_task(coordinator.stop())
    await asyncio.sleep(0)
    runner.cancel()
    barrier.release.set()
    await asyncio.wait_for(stop_task, timeout=1)
    assert runner.cancelled()

    current = await repo.get_run(run.run_id)
    assert current is not None
    assert current.status is RunStatus.INTERRUPTED
    assert current.lease_owner is None
    assert current.lease_expires_at is None
    events = await repo.list_task_events(task.task_id)
    assert [event.type for event in events] == [
        "task.queued",
        "run.started",
        "run.interrupted",
    ]


@pytest.mark.asyncio
async def test_coordinator_failure_timeout_cancel_and_disabled(repo):
    FakeOrchestrator.seen_resumes.clear()
    for mode, expected in (("error", RunStatus.FAILED),):
        task, run = _records("task-error", "run-error")
        await repo.create_task_with_run(task, run)
        FakeOrchestrator.mode = mode
        coordinator = RunCoordinator(repo, object(), owner_id="worker", run_timeout=timedelta(seconds=1), orchestrator_factory=FakeOrchestrator)
        assert await coordinator.submit(run.run_id)
        await _wait_done(coordinator, run.run_id)
        assert (await repo.get_run(run.run_id)).status is expected
        await coordinator.stop()

    task, run = _records("task-timeout", "run-timeout")
    await repo.create_task_with_run(task, run)
    FakeOrchestrator.mode = "block"
    coordinator = RunCoordinator(repo, object(), owner_id="worker", lease_ttl=timedelta(seconds=1), heartbeat_interval=timedelta(milliseconds=10), run_timeout=timedelta(milliseconds=20), orchestrator_factory=FakeOrchestrator)
    assert await coordinator.submit(run.run_id)
    await _wait_done(coordinator, run.run_id)
    assert (await repo.get_run(run.run_id)).status is RunStatus.TIMED_OUT
    await coordinator.stop()

    task, run = _records("task-cancel", "run-cancel")
    await repo.create_task_with_run(task, run)
    coordinator = RunCoordinator(repo, object(), owner_id="worker", orchestrator_factory=FakeOrchestrator)
    FakeOrchestrator.mode = "block"
    await coordinator.submit(run.run_id)
    await asyncio.sleep(0.01)
    await repo.cancel_task(task.task_id)
    active_task = coordinator._active[run.run_id]
    await coordinator.cancel_active(run.run_id)
    with pytest.raises(asyncio.CancelledError):
        await active_task
    assert (await repo.get_run(run.run_id)).status is RunStatus.CANCELLED
    await coordinator.stop()

    task, run = _records("task-disabled", "run-disabled")
    await repo.create_task_with_run(task, run)
    disabled = RunCoordinator(repo, object(), enabled=False, orchestrator_factory=FakeOrchestrator)
    assert not await disabled.submit(run.run_id)
    assert (await repo.get_run(run.run_id)).status is RunStatus.QUEUED

    task, run = _records("task-stop", "run-stop")
    await repo.create_task_with_run(task, run)
    stopper = RunCoordinator(repo, object(), owner_id="worker", orchestrator_factory=FakeOrchestrator)
    await stopper.submit(run.run_id)
    await asyncio.sleep(0.05)
    await stopper.stop()
    assert (await repo.get_run(run.run_id)).status is RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_start_recovers_stale_run_with_compatible_checkpoint(repo):
    FakeOrchestrator.seen_resumes.clear()
    task, run = _records()
    await repo.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repo.acquire_run_lease(run.run_id, lease_owner="old", lease_ttl=timedelta(seconds=1), run_timeout=timedelta(minutes=1), now=now)
    from deepchoice.persistence.records import CheckpointReference
    await repo.add_checkpoint_reference(CheckpointReference(run_id=run.run_id, checkpoint_id="cp-old", state_schema_version=run.manifest.state_schema_version, execution_epoch=grant.execution_epoch, created_at=now), lease_owner="old", execution_epoch=grant.execution_epoch, now=now)
    # Expiry recovery queues the same run and marks it resumable.
    recovered = await repo.recover_runs(now=now + timedelta(seconds=2))
    assert recovered and recovered[0].resume
    FakeOrchestrator.mode = "success"
    coordinator = RunCoordinator(repo, object(), owner_id="new", orchestrator_factory=FakeOrchestrator)
    assert await coordinator.start() == (run.run_id,)
    await _wait_done(coordinator, run.run_id)
    assert (await repo.get_run(run.run_id)).status is RunStatus.COMPLETED
    assert FakeOrchestrator.seen_resumes == [True]
    await coordinator.stop()


@pytest.mark.asyncio
async def test_missing_accepted_raw_checkpoint_replaces_interrupted_run(repo):
    from deepchoice.persistence.records import CheckpointReference

    task, run = _records("task-missing", "run-missing")
    await repo.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repo.acquire_run_lease(
        run.run_id,
        lease_owner="old",
        lease_ttl=timedelta(seconds=1),
        run_timeout=timedelta(minutes=1),
        now=now,
    )
    await repo.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            checkpoint_ns="",
            storage_checkpoint_ns="missing-epoch",
            checkpoint_id="missing-checkpoint",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=grant.execution_epoch,
            created_at=now,
        ),
        lease_owner="old",
        execution_epoch=grant.execution_epoch,
        now=now,
    )
    assert await repo.recover_runs(now=now + timedelta(seconds=2))

    FakeOrchestrator.mode = "success"
    coordinator = RunCoordinator(
        repo,
        MissingCheckpointSaver(),
        owner_id="new",
        orchestrator_factory=FakeOrchestrator,
    )
    assert await coordinator.submit(run.run_id, resume=True)
    await _wait_done(coordinator, run.run_id)

    current = await repo.get_task(task.task_id)
    assert current is not None and current.latest_run is not None
    assert current.latest_run.run_id != run.run_id
    assert current.latest_run.budget_policy is not None
    assert current.latest_run.budget_policy.policy_version == "standard-enforced-v1"
    await _wait_done(coordinator, current.latest_run.run_id)
    assert (await repo.get_run(run.run_id)).status is RunStatus.INTERRUPTED
    assert (await repo.get_run(current.latest_run.run_id)).status is RunStatus.COMPLETED
    await coordinator.stop()


@pytest.mark.asyncio
async def test_remote_cancel_is_observed_by_owner_heartbeat(tmp_path: Path):
    database_path = tmp_path / "product.db"
    owner_connection = await connect_database(database_path)
    api_connection = await connect_database(database_path)
    await run_migrations(owner_connection)
    owner_repo = SQLiteTaskRunRepository(owner_connection)
    api_repo = SQLiteTaskRunRepository(api_connection)
    task, run = _records()
    await owner_repo.create_task_with_run(task, run)
    FakeOrchestrator.mode = "block"
    coordinator = RunCoordinator(
        owner_repo,
        object(),
        owner_id="owner-instance",
        lease_ttl=timedelta(seconds=1),
        heartbeat_interval=timedelta(milliseconds=10),
        run_timeout=timedelta(seconds=2),
        orchestrator_factory=FakeOrchestrator,
    )
    try:
        assert await coordinator.submit(run.run_id, resume=False)
        for _ in range(100):
            current = await owner_repo.get_run(run.run_id)
            if current is not None and current.status is RunStatus.RUNNING:
                break
            await asyncio.sleep(0.005)
        else:
            raise AssertionError("run did not acquire its lease")

        cancelling = await api_repo.cancel_task(task.task_id)
        assert cancelling.latest_run.status is RunStatus.CANCELLING
        await _wait_done(coordinator, run.run_id)
        assert (await owner_repo.get_run(run.run_id)).status is RunStatus.CANCELLED
    finally:
        await coordinator.stop()
        await api_connection.close()
        await owner_connection.close()
