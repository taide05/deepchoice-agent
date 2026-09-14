from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import (
    CheckpointReference,
    RunRecord,
    RunResultRecord,
    TaskRecord,
)
from deepchoice.persistence.repository import (
    RunLeaseLostError,
    SQLiteTaskRunRepository,
    TaskVersionConflictError,
)
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.server.task_event_stream import (
    iter_task_event_sse,
    parse_last_event_id,
)


def _records(task_id: str = "task-1", run_id: str = "run-1") -> tuple[TaskRecord, RunRecord]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    return (
        TaskRecord(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            request=request,
            latest_run_id=run_id,
            created_at=now,
            updated_at=now,
        ),
        RunRecord(
            run_id=run_id,
            task_id=task_id,
            status=RunStatus.QUEUED,
            manifest=build_run_manifest(request.model_dump()),
            thread_id=run_id,
            created_at=now,
            updated_at=now,
        ),
    )


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
async def test_events_are_globally_cursorable_and_per_task_sequenced(repository) -> None:
    task_a, run_a = _records("task-a", "run-a")
    task_b, run_b = _records("task-b", "run-b")
    await repository.create_task_with_run(task_a, run_a)
    await repository.create_task_with_run(task_b, run_b)
    await repository.acquire_run_lease(
        run_a.run_id,
        lease_owner="owner",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    events_a = await repository.list_task_events(task_a.task_id)
    events_b = await repository.list_task_events(task_b.task_id)
    assert [event.seq for event in events_a] == [1, 2]
    assert [event.seq for event in events_b] == [1]
    assert [event.type for event in events_a] == ["task.queued", "run.started"]
    assert events_a[0].event_id < events_b[0].event_id < events_a[1].event_id
    assert not (
        await repository.get_task_event_cursor(task_a.task_id, cursor=events_b[0].event_id)
    ).cursor_valid
    assert (
        await repository.get_task_event_cursor(task_a.task_id, cursor=events_a[0].event_id)
    ).cursor_valid


@pytest.mark.asyncio
async def test_failed_cas_and_fence_leave_no_event(repository) -> None:
    task, run = _records()
    await repository.create_task_with_run(task, run)
    before = await repository.list_task_events(task.task_id)
    with pytest.raises(TaskVersionConflictError):
        await repository.transition_current_run(
            task.task_id,
            expected_task_version=9,
            target_task_status=TaskStatus.RUNNING,
            target_run_status=RunStatus.RUNNING,
        )
    with pytest.raises(RunLeaseLostError):
        await repository.add_checkpoint_reference(
            CheckpointReference(
                run_id=run.run_id,
                checkpoint_id="cp-rejected",
                node="retrieve",
                state_schema_version=run.manifest.state_schema_version,
                execution_epoch=1,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            lease_owner="nobody",
            execution_epoch=1,
        )
    assert await repository.list_task_events(task.task_id) == before


@pytest.mark.asyncio
async def test_checkpoint_progress_event_is_idempotent(repository) -> None:
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="owner",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    reference = CheckpointReference(
        run_id=run.run_id,
        checkpoint_id="cp-1",
        node="retrieve",
        state_schema_version=run.manifest.state_schema_version,
        execution_epoch=grant.execution_epoch,
        created_at=now,
    )
    await repository.add_checkpoint_reference(
        reference, lease_owner="owner", execution_epoch=grant.execution_epoch, now=now
    )
    await repository.add_checkpoint_reference(
        reference, lease_owner="owner", execution_epoch=grant.execution_epoch, now=now
    )
    progress = [
        event
        for event in await repository.list_task_events(task.task_id)
        if event.type == "run.progress"
    ]
    assert len(progress) == 1
    assert progress[0].public_payload == {"node": "retrieve"}


@pytest.mark.asyncio
async def test_cancel_and_finalization_append_public_lifecycle_events(repository) -> None:
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="owner",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    await repository.cancel_task(task.task_id, updated_at=now + timedelta(seconds=1))
    await repository.finalize_run(
        run.run_id,
        lease_owner="owner",
        execution_epoch=grant.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=now + timedelta(seconds=2),
    )
    events = await repository.list_task_events(task.task_id)
    assert [event.type for event in events] == [
        "task.queued",
        "run.started",
        "task.cancel_requested",
        "run.cancelled",
    ]
    assert all(
        set(event.public_payload) <= {"status", "node", "reason"} for event in events
    )


@pytest.mark.asyncio
async def test_startup_recovery_emits_interrupt_and_auto_resume(repository) -> None:
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="owner",
        lease_ttl=timedelta(seconds=1),
        run_timeout=timedelta(minutes=5),
        now=now,
    )
    await repository.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            checkpoint_id="cp-1",
            node="retrieve",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=grant.execution_epoch,
            created_at=now,
        ),
        lease_owner="owner",
        execution_epoch=grant.execution_epoch,
        now=now,
    )
    recovered = await repository.recover_runs(now=now + timedelta(seconds=2))
    assert recovered[0].resume
    assert [event.type for event in await repository.list_task_events(task.task_id)][-2:] == [
        "run.interrupted",
        "run.auto_resumed",
    ]


@pytest.mark.asyncio
async def test_legacy_import_is_atomic_safe_and_exact_replay_is_noop(repository) -> None:
    task, run = _records("legacy-task", "legacy-run")
    ended = datetime(2026, 1, 2, tzinfo=UTC)
    task = task.model_copy(
        update={"status": TaskStatus.COMPLETED, "updated_at": ended}
    )
    run = run.model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "started_at": task.created_at,
            "ended_at": ended,
            "updated_at": ended,
        }
    )
    digest = "a" * 64
    result = RunResultRecord(
        run_id=run.run_id,
        snapshot={"task": task.request.model_dump(mode="json"), "report": "# Legacy"},
        report="# Legacy",
        report_format=task.request.report_format,
        created_at=ended,
    )
    imported = await repository.import_legacy_task(
        "snapshots/task.json", digest, task, run, result, imported_at=ended
    )
    replay = await repository.import_legacy_task(
        "snapshots/task.json", digest, task, run, result, imported_at=ended
    )
    changed = await repository.import_legacy_task(
        "snapshots/task.json", "b" * 64, task, run, result, imported_at=ended
    )
    assert imported.outcome == "imported" and imported.created
    assert replay.outcome == "imported" and not replay.created
    assert changed.outcome == "error" and changed.error_code == "LEGACY_SOURCE_CHANGED"
    assert changed.task_id is None and changed.run_id is None
    assert [event.type for event in await repository.list_task_events(task.task_id)] == [
        "legacy.imported",
        "run.completed",
    ]
    assert (await repository.get_run_result(run.run_id)).report == "# Legacy"


@pytest.mark.asyncio
async def test_sse_replays_after_disconnect_resyncs_foreign_cursor_and_closes(repository) -> None:
    task, run = _records()
    other_task, other_run = _records("other", "other-run")
    await repository.create_task_with_run(task, run)
    await repository.create_task_with_run(other_task, other_run)
    await repository.cancel_task(task.task_id)
    task_events = await repository.list_task_events(task.task_id)
    other_event = (await repository.list_task_events(other_task.task_id))[0]

    async def snapshot_loader(task_id: str):
        loaded = await repository.get_task(task_id)
        assert loaded is not None
        return {"task_id": loaded.task.task_id, "status": loaded.task.status.value}

    replay = [
        item
        async for item in iter_task_event_sse(
            repository,
            task.task_id,
            last_event_id=task_events[0].event_id,
            snapshot_loader=snapshot_loader,
            poll_interval=0,
        )
    ]
    assert len(replay) == 1
    assert "event: task.cancelled" in replay[0]

    resync = [
        item
        async for item in iter_task_event_sse(
            repository,
            task.task_id,
            last_event_id=other_event.event_id,
            snapshot_loader=snapshot_loader,
            poll_interval=0,
        )
    ]
    assert len(resync) == 1
    assert "event: resync_required" in resync[0]
    assert '"latest_event_id":' in resync[0]


@pytest.mark.parametrize("value", ["-1", "+1", " 1", "1 ", "1.0", "x", "9223372036854775808"])
def test_last_event_id_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_last_event_id(value)
