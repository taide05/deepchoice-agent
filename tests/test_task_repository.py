"""Focused contracts for durable task/run persistence and pagination."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.persistence.repository import (
    RepositoryOperationError,
    SQLiteTaskRunRepository,
    TaskNotFoundError,
    TaskVersionConflictError,
)
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


def _records(task_id: str = "task-1", run_id: str = "run-1", *, created_at: datetime | None = None):
    now = created_at or datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    task = TaskRecord(task_id=task_id, status=TaskStatus.QUEUED, request=request,
                      latest_run_id=run_id, created_at=now, updated_at=now)
    run = RunRecord(run_id=run_id, task_id=task_id, status=RunStatus.QUEUED,
                    manifest=build_run_manifest(request.model_dump()), thread_id=run_id,
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
