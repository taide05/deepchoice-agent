"""Real SQLite cancellation at the transaction-entry boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from deepchoice.budget import SQLiteBudgetStore
from deepchoice.contracts.api import ResearchRequest
from deepchoice.observability import SQLiteTraceStore
from deepchoice.observability.query import SQLiteObservabilityQuery
from deepchoice.persistence import (
    SQLiteTaskRunRepository,
    connect_database,
    run_migrations,
)
from deepchoice.runtime.lifecycle import RunStatus
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.instance_guard import RuntimeInstanceGuard
from deepchoice.services.tasks import TaskService


NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["budget", "trace", "query", "repository"])
async def test_cancel_after_real_begin_before_entry_returns_does_not_leak_transaction(
    tmp_path, monkeypatch, entry: str
) -> None:
    """A cancelled BEGIN must leave the shared connection usable for finalize."""
    connection = await connect_database(tmp_path / f"{entry}.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    service = TaskService(repository, clock=lambda: NOW)
    shared_lock = repository._lock
    try:
        created = await service.create(ResearchRequest(query=f"entry cancellation {entry}"))
        run = created.latest_run
        assert run is not None and run.budget_policy is not None
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="entry-test-worker",
            lease_ttl=timedelta(minutes=5),
            run_timeout=timedelta(minutes=5),
            now=NOW,
        )

        if entry == "budget":
            bound = SQLiteBudgetStore(connection, shared_lock, clock=lambda: NOW).bind(
                run_id=run.run_id,
                execution_epoch=grant.execution_epoch,
                lease_owner="entry-test-worker",
                policy=run.budget_policy,
                run_started_at=NOW,
                execution_started_at=NOW,
            )

            async def operation(now):
                raise AssertionError("entry cancellation must happen before operation")

            entry_coro = bound._transaction(operation)
        elif entry == "trace":
            bound = SQLiteTraceStore(connection, shared_lock, clock=lambda: NOW).bind(
                run_id=run.run_id,
                execution_epoch=grant.execution_epoch,
                lease_owner="entry-test-worker",
            )

            async def operation():
                raise AssertionError("entry cancellation must happen before operation")

            entry_coro = bound._transaction(operation)

        elif entry == "query":
            entry_coro = SQLiteObservabilityQuery(connection, shared_lock).for_task(
                created.task.task_id
            )
        else:
            entry_coro = repository.cancel_task(created.task.task_id)

        prior_task = await repository.get_task(created.task.task_id)
        prior_events = await repository.list_task_events(created.task.task_id)

        real_execute = connection.execute
        entered = asyncio.Event()
        cancelled_inside_barrier = asyncio.Event()

        class _BeginCursorProxy:
            def __init__(self, cursor):
                self._cursor = cursor

            async def close(self):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled_inside_barrier.set()
                    raise

            def __getattr__(self, name):
                return getattr(self._cursor, name)

        async def execute_with_real_begin_barrier(sql, parameters=()):
            cursor = await real_execute(sql, parameters)
            if str(sql).strip().upper() in {"BEGIN", "BEGIN IMMEDIATE"}:
                assert sql == ("BEGIN" if entry == "query" else "BEGIN IMMEDIATE")
                return _BeginCursorProxy(cursor)
            return cursor

        monkeypatch.setattr(connection, "execute", execute_with_real_begin_barrier)
        task = asyncio.create_task(entry_coro)
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled_inside_barrier.is_set()

        # This is the key assertion: BEGIN was executed by real SQLite, but the
        # cancellation arrived before the entry await returned to _transaction.
        assert connection.in_transaction is False

        # Restore the real entry point before exercising the repository.
        monkeypatch.setattr(connection, "execute", real_execute)
        assert await repository.get_task(created.task.task_id) == prior_task
        assert await repository.list_task_events(created.task.task_id) == prior_events
        before = await repository.list_task_events(created.task.task_id)
        finalized = await repository.finalize_run(
            run.run_id,
            lease_owner="entry-test-worker",
            execution_epoch=grant.execution_epoch,
            status=RunStatus.FAILED,
            now=NOW + timedelta(seconds=1),
        )
        after = await repository.list_task_events(created.task.task_id)
        assert finalized.latest_run is not None
        assert finalized.latest_run.status is RunStatus.FAILED
        assert len(after) == len(before) + 1
        assert after[-1].type == "run.failed"
        assert after[-1].public_payload == {"status": "failed"}
    finally:
        await connection.close()


class _AcquireReturnBarrierRepository:
    """Expose a committed lease before allowing coordinator setup to continue."""

    def __init__(self, delegate):
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


def _install_one_begin_close_barrier(connection, monkeypatch):
    """Block one real BEGIN cursor close; later cleanup begins pass through."""
    real_execute = connection.execute
    entered = asyncio.Event()
    cancelled_inside_barrier = asyncio.Event()
    armed = True

    class _BeginCursorProxy:
        def __init__(self, cursor):
            self._cursor = cursor

        async def close(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_inside_barrier.set()
                raise

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    async def execute_with_one_begin_barrier(sql, parameters=()):
        nonlocal armed
        cursor = await real_execute(sql, parameters)
        if armed and str(sql).strip().upper() == "BEGIN IMMEDIATE":
            armed = False
            return _BeginCursorProxy(cursor)
        return cursor

    monkeypatch.setattr(connection, "execute", execute_with_one_begin_barrier)
    return real_execute, entered, cancelled_inside_barrier


@pytest.mark.asyncio
async def test_coordinator_stop_after_budget_begin_cancellation_finalizes_interrupted_once(
    tmp_path, monkeypatch
) -> None:
    connection = await connect_database(tmp_path / "coordinator.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    service = TaskService(repository, clock=lambda: NOW)
    try:
        created = await service.create(ResearchRequest(query="coordinator entry cancellation"))
        run = created.latest_run
        assert run is not None
        barrier_repo = _AcquireReturnBarrierRepository(repository)
        coordinator = RunCoordinator(
            barrier_repo,
            object(),
            owner_id="coordinator-worker",
            lease_ttl=timedelta(minutes=1),
            heartbeat_interval=timedelta(seconds=1),
            run_timeout=timedelta(minutes=5),
            orchestrator_factory=lambda *_args, **_kwargs: pytest.fail(
                "orchestrator must not start before budget entry barrier"
            ),
        )
        assert await coordinator.submit(run.run_id, resume=False)
        await asyncio.wait_for(barrier_repo.committed.wait(), timeout=2)

        real_execute, entered, cancelled = _install_one_begin_close_barrier(
            connection, monkeypatch
        )
        barrier_repo.release.set()
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(coordinator.stop(), timeout=2)
        assert cancelled.is_set()
        monkeypatch.setattr(connection, "execute", real_execute)

        current = await repository.get_run(run.run_id)
        assert current is not None
        assert current.status is RunStatus.INTERRUPTED
        assert current.lease_owner is None
        assert current.lease_expires_at is None
        events = await repository.list_task_events(created.task.task_id)
        assert [event.type for event in events] == [
            "task.queued", "run.started", "run.interrupted"
        ]
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["acquire", "renew"])
async def test_instance_guard_entry_cancellation_rolls_back_real_begin(
    tmp_path, monkeypatch, operation: str
) -> None:
    connection = await connect_database(tmp_path / f"instance-{operation}.db")
    await run_migrations(connection)
    current = NOW
    guard = RuntimeInstanceGuard(
        connection,
        asyncio.Lock(),
        owner_token=f"entry-{operation}",
        clock=lambda: current,
    )
    try:
        if operation == "renew":
            await guard.acquire()
        real_execute, entered, cancelled = _install_one_begin_close_barrier(
            connection, monkeypatch
        )
        task = asyncio.create_task(
            guard.acquire() if operation == "acquire" else guard.renew_once()
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert connection.in_transaction is False
        monkeypatch.setattr(connection, "execute", real_execute)

        if operation == "acquire":
            await guard.acquire()
        await guard.release()
        replacement = RuntimeInstanceGuard(
            connection,
            asyncio.Lock(),
            owner_token="replacement",
            clock=lambda: current,
        )
        await replacement.acquire()
        await replacement.release()
    finally:
        await connection.close()
