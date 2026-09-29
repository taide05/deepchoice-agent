"""Offline run-heartbeat contention, fencing and diagnostic regressions."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.persistence.repository import (
    RepositoryOperationError, RunLeaseLostError, SQLiteTaskRunRepository,
)
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


NOW = datetime(2026, 9, 29, tzinfo=UTC)


class ObservedHeartbeatRepository(SQLiteTaskRunRepository):
    """Observe a real SQLite failure before permitting the coordinator to react."""

    def __init__(self, connection):
        super().__init__(connection)
        self.failed = asyncio.Event()
        self.release_failure = asyncio.Event()
        self.succeeded = asyncio.Event()
        self.calls = 0
        self.retryable = None

    async def heartbeat_run_lease(self, *args, **kwargs):
        self.calls += 1
        try:
            grant = await super().heartbeat_run_lease(*args, **kwargs)
        except RepositoryOperationError as exc:
            self.retryable = exc.error_detail.retryable
            self.failed.set()
            await self.release_failure.wait()
            raise
        self.succeeded.set()
        return grant


@pytest_asyncio.fixture
async def database_connections(tmp_path):
    primary = await connect_database(tmp_path / "product.db")
    lease = None
    try:
        await run_migrations(primary)
        lease = await connect_database(tmp_path / "product.db", busy_timeout_ms=20)
        yield primary, lease
    finally:
        if lease is not None:
            await lease.close()
        await primary.rollback()
        await primary.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["recover", "still_busy", "expired", "fenced"])
async def test_real_sqlite_contention_has_one_fenced_retry(database_connections, outcome):
    primary, lease = database_connections
    repo = SQLiteTaskRunRepository(primary)
    heartbeat_repo = ObservedHeartbeatRepository(lease)
    request = ResearchRequest(query="offline heartbeat regression")
    task = TaskRecord(task_id="task", status=TaskStatus.QUEUED, request=request,
                      latest_run_id="run", created_at=NOW, updated_at=NOW)
    run = RunRecord(run_id="run", task_id="task", status=RunStatus.QUEUED,
                    manifest=build_run_manifest(request.model_dump()),
                    budget_policy=DEFAULT_RUN_BUDGET_POLICY, thread_id="run",
                    created_at=NOW, updated_at=NOW)
    await repo.create_task_with_run(task, run)
    grant = await repo.acquire_run_lease("run", lease_owner="owner-private",
        lease_ttl=timedelta(seconds=30), run_timeout=timedelta(minutes=5), now=NOW)
    current = NOW + timedelta(seconds=10)
    coordinator = RunCoordinator(repo, None, owner_id="owner-private", clock=lambda: current,
        heartbeat_interval=timedelta(milliseconds=1), heartbeat_repository=heartbeat_repo)
    runner = asyncio.create_task(asyncio.Event().wait())
    await primary.execute("BEGIN IMMEDIATE")
    heartbeat = asyncio.create_task(coordinator._heartbeat("run", grant.execution_epoch, runner))
    try:
        await asyncio.wait_for(heartbeat_repo.failed.wait(), 2)
        assert heartbeat_repo.retryable is True  # Real SQLite SQLITE_BUSY, not an injected exception.
        if outcome == "fenced":
            await primary.execute("UPDATE runs SET execution_epoch = execution_epoch + 1 WHERE run_id='run'")
            await primary.commit()
        elif outcome != "still_busy":
            await primary.rollback()
        if outcome == "expired":
            current = NOW + timedelta(seconds=31)
        heartbeat_repo.release_failure.set()
        if outcome == "recover":
            await asyncio.wait_for(heartbeat_repo.succeeded.wait(), 2)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            assert not runner.done()
            assert (await repo.get_run("run")).lease_expires_at == current + timedelta(seconds=30)
        else:
            await asyncio.wait_for(heartbeat, 2)
            with pytest.raises(asyncio.CancelledError):
                await runner
            await primary.rollback()
            assert (await repo.get_run("run")).lease_expires_at == grant.lease_expires_at
        assert heartbeat_repo.calls == 2
        assert not lease.in_transaction
        stats = coordinator.heartbeat_observations()
        assert stats["retries"] == 1
        assert stats["recovered_retries"] == int(outcome == "recover")
        assert stats["failures"] == int(outcome != "recover")
        assert stats["failure_categories"]["database_busy"] == (2 if outcome == "still_busy" else 1)
        assert stats["lease_losses"] == int(outcome in {"expired", "fenced"})
        assert (await (await primary.execute("SELECT count(*) FROM task_events")).fetchone())[0] == 2
        assert (await (await primary.execute("SELECT count(*) FROM run_checkpoints")).fetchone())[0] == 0
    finally:
        heartbeat_repo.release_failure.set()
        heartbeat.cancel()
        runner.cancel()
        await asyncio.gather(heartbeat, runner, return_exceptions=True)
        await primary.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,category", [
    (RepositoryOperationError(retryable=False), "database_error"),
    (RunLeaseLostError("private-run"), "lease_lost"),
    (RuntimeError("secret-provider-payload/private-path"), "unexpected_error"),
])
async def test_non_retryable_heartbeat_fails_closed_with_safe_diagnostics(exception, category, caplog):
    repository = SimpleNamespace(heartbeat_run_lease=AsyncMock(side_effect=exception))
    coordinator = RunCoordinator(repository, None, budget_store=object(),
        heartbeat_interval=timedelta(milliseconds=1))
    runner = asyncio.create_task(asyncio.Event().wait())
    await coordinator._heartbeat("private-run", 88, runner)
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert repository.heartbeat_run_lease.await_count == 1
    stats = coordinator.heartbeat_observations()
    assert stats["failure_categories"] == {category: 1}
    assert stats["retries"] == stats["successes"] == 0
    assert stats["failures"] == 1
    assert category in caplog.text
    for private in ("private-run", "secret-provider-payload", "private-path", "Traceback"):
        assert private not in json.dumps(stats) + caplog.text


@pytest.mark.asyncio
async def test_remote_cancel_after_busy_does_not_retry_or_resume_work():
    repository = SimpleNamespace(heartbeat_run_lease=AsyncMock(side_effect=[
        RepositoryOperationError(retryable=True), SimpleNamespace(status=RunStatus.CANCELLING)]))
    coordinator = RunCoordinator(repository, None, budget_store=object(),
        heartbeat_interval=timedelta(milliseconds=1))
    runner = asyncio.create_task(asyncio.Event().wait())
    await coordinator._heartbeat("run", 1, runner)
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert repository.heartbeat_run_lease.await_count == 2
    assert coordinator.heartbeat_observations()["failures"] == 0


@pytest.mark.asyncio
async def test_cancellation_during_retry_propagates_without_failure_or_third_call():
    entered = asyncio.Event()
    async def block():
        entered.set()
        await asyncio.Event().wait()
    repository = SimpleNamespace()
    calls = 0
    async def renew(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RepositoryOperationError(retryable=True)
        await block()
    repository.heartbeat_run_lease = renew
    coordinator = RunCoordinator(repository, None, budget_store=object(),
        heartbeat_interval=timedelta(milliseconds=1))
    runner = asyncio.create_task(asyncio.Event().wait())
    heartbeat = asyncio.create_task(coordinator._heartbeat("run", 1, runner))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        heartbeat.cancel()
        with pytest.raises(asyncio.CancelledError):
            await heartbeat
        assert calls == 2 and not runner.done()
        assert coordinator.heartbeat_observations()["failures"] == 0
    finally:
        heartbeat.cancel()
        runner.cancel()
        await asyncio.gather(heartbeat, runner, return_exceptions=True)
