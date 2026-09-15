"""Focused Phase 2-C1 fenced budget-ledger tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepchoice.budget import (
    BudgetAmount,
    BudgetEnforcementMode,
    BudgetExceededError,
    BudgetHardLimits,
    BudgetPersistenceError,
    BudgetResource,
    RunBudgetPolicy,
    SQLiteBudgetStore,
    StaleBudgetAuthorityError,
    reserve_call,
    settle_call,
)
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import SQLiteTaskRunRepository, connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.runtime.context import RunContext, bind_run_context
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.agents.multi_retriever import MultiRetrieverAgent
from deepchoice.agents import conflict_detector as conflict_module
from deepchoice.agents import query_analyzer as query_analyzer_module
from deepchoice.agents.query_analyzer import QueryAnalyzerAgent
from deepchoice.utils import llm as llm_module


NOW = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _Cancellation:
    async def raise_if_cancelled(self) -> None:
        return None


class _NoTrace:
    async def record_run(self, trace): return None
    async def record_node_attempt(self, attempt): return None
    async def record_external_call(self, call): return None
    async def record_event(self, event): return None


def _context(manager, trace=None) -> RunContext:
    return RunContext(
        task_id="task-1",
        run_id="run-1",
        manifest_id="manifest-1",
        execution_epoch=1,
        deadline_at=NOW + timedelta(hours=1),
        cancellation=_Cancellation(),
        trace=trace or _NoTrace(),
        budget=manager,
    )


async def _running_budget(tmp_path, *, limits: BudgetHardLimits | None = None):
    connection = await connect_database(tmp_path / "budget.db")
    await run_migrations(connection)
    lock = asyncio.Lock()
    repository = SQLiteTaskRunRepository(connection, lock)
    policy = RunBudgetPolicy(
        enforcement_mode=(
            BudgetEnforcementMode.ENFORCED
            if limits is not None
            else BudgetEnforcementMode.OBSERVE_ONLY
        ),
        hard_limits=limits or BudgetHardLimits(),
        price_catalog_version="unpriced-v1",
    )
    request = ResearchRequest(query="compare a and b")
    task = TaskRecord(
        task_id="task-1",
        status=TaskStatus.QUEUED,
        request=request,
        latest_run_id="run-1",
        created_at=NOW,
        updated_at=NOW,
    )
    run = RunRecord(
        run_id="run-1",
        task_id="task-1",
        status=RunStatus.QUEUED,
        manifest=build_run_manifest(request.model_dump(mode="json")),
        budget_policy=policy,
        thread_id="run-1",
        created_at=NOW,
        updated_at=NOW,
    )
    await repository.create_task_with_run(task, run)
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(minutes=10),
        run_timeout=timedelta(hours=1),
        now=NOW,
    )
    running = await repository.get_run(run.run_id)
    assert running is not None and running.started_at is not None
    clock = MutableClock()
    manager = SQLiteBudgetStore(connection, lock, clock=clock).bind(
        run_id=run.run_id,
        execution_epoch=grant.execution_epoch,
        lease_owner="worker",
        policy=policy,
        run_started_at=running.started_at,
    )
    return connection, lock, manager, policy, clock


async def _count(connection, where: str = "") -> int:
    row = await (
        await connection.execute(f"SELECT count(*) FROM budget_ledger {where}")
    ).fetchone()
    return int(row[0])


@pytest.mark.asyncio
async def test_concurrent_atomic_reservations_do_not_overspend(tmp_path) -> None:
    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=2)
    )
    try:
        async def reserve_one():
            return await manager.reserve(
                run_id="run-1",
                execution_epoch=1,
                amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                expires_at=NOW + timedelta(minutes=1),
            )

        results = await asyncio.gather(
            *(reserve_one() for _ in range(5)), return_exceptions=True
        )
        assert sum(not isinstance(item, Exception) for item in results) == 2
        assert sum(isinstance(item, BudgetExceededError) for item in results) == 3
        assert await _count(connection, "WHERE status='reserved'") == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_bundle_limit_failure_writes_nothing(tmp_path) -> None:
    connection, _, manager, _, _ = await _running_budget(
        tmp_path,
        limits=BudgetHardLimits(llm_calls=4, total_tokens=100),
    )
    try:
        with pytest.raises(BudgetExceededError) as caught:
            await manager.reserve_bundle(
                run_id="run-1",
                execution_epoch=1,
                amounts=(
                    BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                    BudgetAmount(resource=BudgetResource.TOTAL_TOKENS, amount=101),
                ),
                expires_at=NOW + timedelta(minutes=1),
            )
        assert caught.value.resource is BudgetResource.TOTAL_TOKENS
        assert await _count(connection) == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_fencing_and_policy_mismatch_write_nothing(tmp_path) -> None:
    connection, _, manager, policy, _ = await _running_budget(tmp_path)
    try:
        manager.execution_epoch = 2
        with pytest.raises(StaleBudgetAuthorityError):
            await manager.reserve(
                run_id="run-1",
                execution_epoch=2,
                amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                expires_at=NOW + timedelta(minutes=1),
            )
        assert await _count(connection) == 0

        manager.execution_epoch = 1
        manager.policy = policy.model_copy(
            update={"hard_limits": BudgetHardLimits(llm_calls=1)}
        )
        with pytest.raises(BudgetPersistenceError):
            await manager.reserve(
                run_id="run-1",
                execution_epoch=1,
                amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                expires_at=NOW + timedelta(minutes=1),
            )
        assert await _count(connection) == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_new_reserve_requires_running_but_settlement_allows_cancelling(
    tmp_path,
) -> None:
    connection, _, manager, _, _ = await _running_budget(tmp_path)
    try:
        held = await manager.reserve(
            run_id="run-1",
            execution_epoch=1,
            amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
            expires_at=NOW + timedelta(minutes=1),
        )
        await connection.execute(
            "UPDATE runs SET status='cancelling' WHERE run_id='run-1'"
        )
        await connection.commit()
        with pytest.raises(StaleBudgetAuthorityError):
            await manager.reserve(
                run_id="run-1",
                execution_epoch=1,
                amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
                expires_at=NOW + timedelta(minutes=1),
            )
        settled = await manager.settle(
            held.reservation_id,
            actual=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
        )
        assert settled.actual is not None and settled.actual.amount == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_latest_state_settle_release_unknown_and_duplicate(tmp_path) -> None:
    connection, _, manager, _, _ = await _running_budget(tmp_path)
    try:
        settled, released, unknown = [] , [], []
        for target, resource, amount in (
            (settled, BudgetResource.LLM_CALLS, 2),
            (released, BudgetResource.RETRIEVAL_CALLS, 3),
            (unknown, BudgetResource.TOTAL_TOKENS, 50),
        ):
            target.append(
                await manager.reserve(
                    run_id="run-1",
                    execution_epoch=1,
                    amount=BudgetAmount(resource=resource, amount=amount),
                    expires_at=NOW + timedelta(minutes=1),
                )
            )
        await manager.settle(
            settled[0].reservation_id,
            actual=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
        )
        await manager.release(released[0].reservation_id)
        await manager.mark_unknown_spend(
            unknown[0].reservation_id,
            actual=BudgetAmount(resource=BudgetResource.TOTAL_TOKENS, amount=1),
        )
        assert await manager._usage() == {
            BudgetResource.LLM_CALLS: 1,
            BudgetResource.RETRIEVAL_CALLS: 0,
            BudgetResource.TOTAL_TOKENS: 50,
        }
        before = await _count(connection)
        with pytest.raises(BudgetPersistenceError):
            await manager.release(settled[0].reservation_id)
        assert await _count(connection) == before
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_reconcile_stale_epoch_as_unknown_spend(tmp_path) -> None:
    connection, lock, manager, policy, clock = await _running_budget(tmp_path)
    try:
        reservation = await manager.reserve(
            run_id="run-1",
            execution_epoch=1,
            amount=BudgetAmount(resource=BudgetResource.TOTAL_TOKENS, amount=99),
            expires_at=NOW + timedelta(minutes=1),
        )
        await connection.execute(
            "UPDATE runs SET execution_epoch=2, lease_owner='worker-2', "
            "lease_expires_at=? WHERE run_id='run-1'",
            ((NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),),
        )
        await connection.commit()
        resumed = SQLiteBudgetStore(connection, lock, clock=clock).bind(
            run_id="run-1",
            execution_epoch=2,
            lease_owner="worker-2",
            policy=policy,
            run_started_at=NOW,
        )
        assert await resumed.reconcile() == 1
        row = await (
            await connection.execute(
                "SELECT entry_sequence,status,actual_amount FROM budget_ledger "
                "WHERE reservation_id=? ORDER BY entry_sequence DESC LIMIT 1",
                (reservation.reservation_id,),
            )
        ).fetchone()
        assert tuple(row) == (2, "unknown_spend", 99)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_active_limit_and_cumulative_delta_recording(tmp_path) -> None:
    connection, lock, manager, policy, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(active_milliseconds=1000)
    )
    try:
        clock.value = NOW + timedelta(milliseconds=1001)
        with pytest.raises(BudgetExceededError) as caught:
            await manager.raise_if_exhausted(partial_state={"current_phase": "x"})
        assert caught.value.resource is BudgetResource.ACTIVE_MILLISECONDS
        assert caught.value.partial_state == {"current_phase": "x"}

        first = await manager.record_active_milliseconds()
        assert first is not None and first.actual.amount == 1001

        clock.value = NOW + timedelta(milliseconds=1500)
        resumed = SQLiteBudgetStore(connection, lock, clock=clock).bind(
            run_id="run-1",
            execution_epoch=1,
            lease_owner="worker",
            policy=policy,
            run_started_at=NOW,
        )
        clock.value = NOW + timedelta(milliseconds=2000)
        second = await resumed.record_active_milliseconds()
        assert second is not None and second.actual.amount == 500
        assert (await resumed._usage())[BudgetResource.ACTIVE_MILLISECONDS] == 1501
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_llm_retry_gates_each_attempt_and_settles_usage(tmp_path, monkeypatch) -> None:
    connection, _, manager, _, _ = await _running_budget(
        tmp_path,
        limits=BudgetHardLimits(llm_calls=2, total_tokens=20_000),
    )

    class RetryableError(Exception):
        status_code = 500

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        model="safe-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
    )
    create = AsyncMock(side_effect=[RetryableError("private"), response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: client)
    monkeypatch.setattr(llm_module, "_retry_sleep", AsyncMock())
    try:
        with bind_run_context(_context(manager)):
            assert await llm_module.call_model(
                [{"role": "user", "content": "safe"}]
            ) == "ok"
        assert create.await_count == 2
        assert all(
            call.kwargs["max_tokens"] == llm_module.MAX_OUTPUT_TOKENS
            for call in create.await_args_list
        )
        usage = await manager._usage()
        assert usage[BudgetResource.LLM_CALLS] == 2
        # First uncertain attempt charges its conservative reservation; the
        # successful retry settles to provider usage.
        assert usage[BudgetResource.TOTAL_TOKENS] > 18
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_llm_deny_never_calls_provider_and_missing_usage_is_unknown(
    tmp_path, monkeypatch
) -> None:
    connection, _, manager, _, _ = await _running_budget(
        tmp_path,
        limits=BudgetHardLimits(llm_calls=1, total_tokens=10_000),
    )
    response = SimpleNamespace(
        usage=None,
        model="safe-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
    )
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: client)
    try:
        with bind_run_context(_context(manager)):
            assert await llm_module.call_model(
                [{"role": "user", "content": "first"}]
            ) == "ok"
            with pytest.raises(BudgetExceededError):
                await llm_module.call_model(
                    [{"role": "user", "content": "denied"}]
                )
        assert create.await_count == 1
        latest = await manager._latest_rows()
        token_rows = [row for row in latest if row[5] == "total_tokens"]
        assert len(token_rows) == 1 and token_rows[0][4] == "unknown_spend"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_retriever_concurrency_denial_propagates_without_overcalling(tmp_path) -> None:
    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(retrieval_calls=1)
    )
    invoked: list[str] = []

    class Retriever:
        async def search(self, query, sub_questions, *, adapted_queries):
            invoked.append(query)
            await asyncio.sleep(0)
            return {
                "source": "source",
                "status": "success",
                "results": [],
                "error": None,
                "latency_ms": 1,
            }

    try:
        with bind_run_context(_context(manager)):
            with pytest.raises(BudgetExceededError):
                await MultiRetrieverAgent(
                    retriever_registry={"one": Retriever, "two": Retriever}
                ).run(
                    {
                        "task": {"query": "a sufficiently detailed query"},
                        "sub_questions": ["a sufficiently detailed sub question"],
                    }
                )
        assert len(invoked) == 1
        assert (await manager._usage())[BudgetResource.RETRIEVAL_CALLS] == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_conflict_direct_llm_budget_denial_never_calls_provider(
    tmp_path, monkeypatch
) -> None:
    connection, _, manager, _, _ = await _running_budget(
        tmp_path,
        limits=BudgetHardLimits(llm_calls=1, total_tokens=20_000),
    )
    create = AsyncMock()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: client)
    try:
        held = await manager.reserve(
            run_id="run-1",
            execution_epoch=1,
            amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
            expires_at=NOW + timedelta(minutes=1),
        )
        await manager.settle(
            held.reservation_id,
            actual=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
        )
        with bind_run_context(_context(manager)):
            with pytest.raises(BudgetExceededError):
                await conflict_module._gather_evidence(
                    "topic", "claim a", "claim b", max_iterations=1
                )
        assert create.await_count == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_budget_persistence_error_bypasses_agent_fallback(monkeypatch) -> None:
    async def fail_closed(*_args, **_kwargs):
        raise BudgetPersistenceError("ledger unavailable")

    monkeypatch.setattr(query_analyzer_module, "call_model", fail_closed)
    with pytest.raises(BudgetPersistenceError):
        await QueryAnalyzerAgent().run(
            {"task": {"query": "compare a and b", "constraints": []}}
        )


@pytest.mark.asyncio
async def test_coordinator_without_trace_store_still_binds_budget_context(
    tmp_path,
) -> None:
    connection = await connect_database(tmp_path / "coordinator-budget.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection, asyncio.Lock())
    now = datetime.now(UTC)
    request = ResearchRequest(query="compare a and b")
    policy = RunBudgetPolicy(
        enforcement_mode=BudgetEnforcementMode.OBSERVE_ONLY,
        hard_limits=BudgetHardLimits(),
        price_catalog_version="unpriced-v1",
    )
    task = TaskRecord(
        task_id="task-no-trace",
        status=TaskStatus.QUEUED,
        request=request,
        latest_run_id="run-no-trace",
        created_at=now,
        updated_at=now,
    )
    run = RunRecord(
        run_id="run-no-trace",
        task_id=task.task_id,
        status=RunStatus.QUEUED,
        manifest=build_run_manifest(request.model_dump(mode="json")),
        budget_policy=policy,
        thread_id="run-no-trace",
        created_at=now,
        updated_at=now,
    )

    class BudgetOnlyOrchestrator:
        checkpoint_ns = ""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def astream_research_task(self, *, resume=False):
            reservations = await reserve_call(
                (BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),),
                call_id=None,
            )
            await settle_call(reservations, {BudgetResource.LLM_CALLS: 1})
            yield {"budget_node": {"resume": resume}}

        async def get_state(self):
            return SimpleNamespace(
                config={},
                values={"report": "# Budgeted result"},
            )

    coordinator = RunCoordinator(
        repository,
        object(),
        owner_id="worker-no-trace",
        run_timeout=timedelta(seconds=2),
        orchestrator_factory=BudgetOnlyOrchestrator,
    )
    try:
        await repository.create_task_with_run(task, run)
        assert await coordinator.submit(run.run_id)
        for _ in range(400):
            if run.run_id not in coordinator.active_runs:
                break
            await asyncio.sleep(0.005)
        else:
            raise AssertionError("coordinator run did not finish")

        completed = await repository.get_run(run.run_id)
        assert completed is not None and completed.status is RunStatus.COMPLETED
        row = await (
            await connection.execute(
                "SELECT status, actual_amount FROM budget_ledger "
                "WHERE run_id=? AND resource='llm_calls' "
                "ORDER BY entry_sequence DESC LIMIT 1",
                (run.run_id,),
            )
        ).fetchone()
        assert tuple(row) == ("settled", 1)
    finally:
        await coordinator.stop()
        await connection.close()
