"""Small end-to-end acceptance checks for the Phase 1 durable surface."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import MIGRATIONS, connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.persistence.repository import (
    RunLeaseLostError,
    SQLiteTaskRunRepository,
    TaskVersionConflictError,
)
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


def _seed_sql():
    request = ResearchRequest(query="legacy acceptance")
    manifest = build_run_manifest(request.model_dump()).model_dump_json()
    return request, manifest


@pytest.mark.asyncio
@pytest.mark.parametrize("starting_version", [1, 2, 3, 4])
async def test_legacy_schema_steps_to_current_without_losing_task_run_checkpoint(
    tmp_path: Path, starting_version: int
) -> None:
    connection = await connect_database(tmp_path / f"legacy-{starting_version}.db")
    try:
        await run_migrations(connection, MIGRATIONS[:starting_version])
        request, manifest = _seed_sql()
        await connection.execute(
            "INSERT INTO tasks(task_id,status,request_json,latest_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("legacy-task", "queued", request.model_dump_json(), "legacy-run", "2026-01-01", "2026-01-01"),
        )
        await connection.execute(
            "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("legacy-run", "legacy-task", "queued", manifest, "legacy-run", "2026-01-01", "2026-01-01"),
        )
        if starting_version >= 3:
            await connection.execute(
                "INSERT INTO run_checkpoints(run_id,checkpoint_ns,storage_checkpoint_ns,checkpoint_id,node,state_schema_version,execution_epoch,created_at) VALUES(?,?,?,?,?,?,?,?)",
                ("legacy-run", "", "", "legacy-cp",  "retrieve", 1, 1, "2026-01-01"),
            )
        applied = await run_migrations(connection)
        assert applied == tuple(range(starting_version + 1, 8))
        assert await (await connection.execute("SELECT task_id FROM tasks WHERE task_id='legacy-task'")).fetchone() == ("legacy-task",)
        assert await (await connection.execute("SELECT run_id FROM runs WHERE run_id='legacy-run'")).fetchone() == ("legacy-run",)
        assert await (await connection.execute("SELECT COUNT(*) FROM task_events WHERE task_id='legacy-task'")).fetchone() == (0,)
        if starting_version >= 3:
            assert await (await connection.execute("SELECT checkpoint_id FROM run_checkpoints WHERE run_id='legacy-run'")).fetchone() == ("legacy-cp",)
    finally:
        await connection.close()


def _records():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="CAS acceptance")
    task = TaskRecord(task_id="cas-task", status=TaskStatus.QUEUED, request=request, latest_run_id="cas-run", created_at=now, updated_at=now)
    run = RunRecord(run_id="cas-run", task_id="cas-task", status=RunStatus.QUEUED, manifest=build_run_manifest(request.model_dump()), thread_id="cas-run", created_at=now, updated_at=now)
    return task, run


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    connection = await connect_database(tmp_path / "acceptance.db")
    await run_migrations(connection)
    repo = SQLiteTaskRunRepository(connection)
    try:
        yield repo
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_concurrent_cas_has_one_winner_and_one_event_log(repository) -> None:
    task, run = _records()
    await repository.create_task_with_run(task, run)
    results = await asyncio.gather(
        *[
            repository.transition_current_run(
                task.task_id,
                expected_task_version=0,
                target_task_status=TaskStatus.RUNNING,
                target_run_status=RunStatus.RUNNING,
            )
            for _ in range(2)
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(item, TaskVersionConflictError) for item in results) == 1
    assert sum(not isinstance(item, Exception) for item in results) == 1
    events = await repository.list_task_events(task.task_id)
    assert [event.type for event in events] == ["task.queued", "run.status_changed"]
    assert len({event.seq for event in events}) == len(events)


@pytest.mark.asyncio
async def test_stale_recovery_has_no_running_row_and_fences_old_owner(repository) -> None:
    task, run = _records()
    await repository.create_task_with_run(task, run)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    await repository.acquire_run_lease(
        run.run_id,
        lease_owner="old-owner",
        lease_ttl=timedelta(seconds=1),
        run_timeout=timedelta(minutes=1),
        now=now,
    )
    recovered = await repository.recover_runs(now=now + timedelta(seconds=2))
    assert recovered == ()
    current = await repository.get_run(run.run_id)
    assert current.status is RunStatus.INTERRUPTED
    with pytest.raises(RunLeaseLostError):
        await repository.fence_run(
            run.run_id,
            lease_owner="old-owner",
            execution_epoch=1,
            now=now + timedelta(seconds=2),
        )
    assert await (await repository._connection.execute("SELECT COUNT(*) FROM runs WHERE status='running'")).fetchone() == (0,)
