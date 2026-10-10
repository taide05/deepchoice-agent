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
from deepchoice.citations.verifier import verify_citations
from deepchoice.utils import llm as llm_module


NOW = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("call_limit", [96, 2])
async def test_scan_preserves_budget_and_drains_admitted_work(tmp_path, monkeypatch, call_limit):
    import numpy as np
    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(total_tokens=60000, llm_calls=call_limit))
    release = asyncio.Event()
    four_started = asyncio.Event()
    dispatched = 0
    async def create(**kwargs):
        nonlocal dispatched
        assert kwargs["max_tokens"] == 512
        dispatched += 1
        if dispatched == min(4, call_limit):
            four_started.set()
        await release.wait()
        return SimpleNamespace(model="fixture", usage=SimpleNamespace(
            prompt_tokens=250, completion_tokens=50, total_tokens=300),
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"has_difference":false,"type":"none","explanation":"Different conditions"}'))])
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(conflict_module, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda titles: np.ones((len(titles), 3))))
    items = [{"title": f"source {i}", "snippet": "fixture " * 60,
              "total_score": 6} for i in range(7)]
    with bind_run_context(_context(manager)):
        pending = asyncio.create_task(conflict_module.find_contradictions(items, "fixture"))
    try:
        await asyncio.wait_for(four_started.wait(), timeout=3)
        await asyncio.sleep(0.05)
        assert dispatched == min(4, call_limit) and not pending.done()
        if call_limit == 2:
            assert isinstance(manager._exhausted, BudgetExceededError)
        else:
            assert manager._exhausted is None
        release.set()
        if call_limit == 2:
            with pytest.raises(BudgetExceededError):
                await asyncio.wait_for(pending, timeout=5)
            assert dispatched == 2  # All other queued requests stayed local.
        else:
            assert await asyncio.wait_for(pending, timeout=5) == []
            assert dispatched == 15 and manager._exhausted is None
        usage = await manager._usage()
        assert usage[BudgetResource.TOTAL_TOKENS] == dispatched * 300
        assert usage[BudgetResource.LLM_CALLS] == dispatched
        assert await _count(connection, "WHERE status='unknown_spend'") == 0
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await connection.close()


@pytest.mark.asyncio
async def test_committed_retrieval_waiter_survives_later_budget_denial(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    import httpx
    from deepchoice import outbound
    from deepchoice.outbound import throttle
    from deepchoice.agents.multi_retriever import _invoke_retriever_miss
    from deepchoice.retrievers.arxiv_api import ArxivSearch

    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(retrieval_calls=1))
    reserved = asyncio.Event()
    get = AsyncMock(return_value=httpx.Response(
        200, text='<feed xmlns="http://www.w3.org/2005/Atom"/>',
        request=httpx.Request('GET', 'https://fixture.example')))

    @asynccontextmanager
    async def client():
        reserved.set()  # make_client is reached only after reserve_call commits
        yield SimpleNamespace(get=get)

    monkeypatch.setattr(outbound, 'make_client', AsyncMock(side_effect=lambda _: client()))
    gate = throttle.gate_for('arxiv')
    gate.interval = 0
    pending = None

    async def invoke():
        return await _invoke_retriever_miss(
            'arxiv', ArxivSearch, query='fixture', sub_questions=[], adapted_queries=[])

    try:
        async with gate.slot():
            with bind_run_context(_context(manager)):
                pending = asyncio.create_task(invoke())
                await asyncio.wait_for(reserved.wait(), timeout=3)
                assert len(gate._queue) == 1
                with pytest.raises(BudgetExceededError):
                    await invoke()  # no second reservation / outbound call
                assert isinstance(manager.exhausted, BudgetExceededError)
                get.assert_not_awaited()
        result, _ = await asyncio.wait_for(pending, timeout=3)
        assert result.status == 'success'
        get.assert_awaited_once()
        assert (await manager._usage())[BudgetResource.RETRIEVAL_CALLS] == 1
        assert (await manager._usage())[BudgetResource.HTTP_CALLS] == 1
        assert await _count(connection, "WHERE status='settled'") == 2
        assert not gate._queue and gate._active == 0
    finally:
        if pending is not None:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await connection.close()


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
async def test_denied_admission_latches_before_queued_smaller_reservation(
    tmp_path, monkeypatch
) -> None:
    connection, lock, manager, policy, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=2)
    )
    large_in_admission = asyncio.Event()
    release_large = asyncio.Event()
    small_crossed_entry_check = asyncio.Event()
    original_check_active_elapsed = manager._check_active_elapsed
    original_reconcile = manager.reconcile

    async def block_large_admission(now):
        if asyncio.current_task().get_name() == "large-reservation":
            large_in_admission.set()
            await release_large.wait()
        await original_check_active_elapsed(now)

    async def observe_entry_check():
        if asyncio.current_task().get_name() == "small-reservation":
            small_crossed_entry_check.set()
        return await original_reconcile()

    monkeypatch.setattr(manager, "_check_active_elapsed", block_large_admission)
    monkeypatch.setattr(manager, "reconcile", observe_entry_check)

    async def reserve(amount: int):
        return await manager.reserve(
            run_id="run-1",
            execution_epoch=1,
            amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=amount),
            expires_at=NOW + timedelta(minutes=1),
        )

    try:
        large = asyncio.create_task(reserve(3), name="large-reservation")
        await large_in_admission.wait()
        small = asyncio.create_task(reserve(1), name="small-reservation")
        await small_crossed_entry_check.wait()
        release_large.set()

        large_result, small_result = await asyncio.gather(
            large, small, return_exceptions=True
        )
        assert isinstance(large_result, BudgetExceededError)
        assert isinstance(small_result, BudgetExceededError)
        assert small_result is large_result
        assert await _count(connection) == 0

        other_request = ResearchRequest(query="compare c and d")
        other_task = TaskRecord(
            task_id="task-2",
            status=TaskStatus.QUEUED,
            request=other_request,
            latest_run_id="run-2",
            created_at=NOW,
            updated_at=NOW,
        )
        other_run = RunRecord(
            run_id="run-2",
            task_id="task-2",
            status=RunStatus.QUEUED,
            manifest=build_run_manifest(other_request.model_dump(mode="json")),
            budget_policy=policy,
            thread_id="run-2",
            created_at=NOW,
            updated_at=NOW,
        )
        repository = SQLiteTaskRunRepository(connection, lock)
        await repository.create_task_with_run(other_task, other_run)
        grant = await repository.acquire_run_lease(
            "run-2",
            lease_owner="worker-2",
            lease_ttl=timedelta(minutes=10),
            run_timeout=timedelta(hours=1),
            now=NOW,
        )
        running = await repository.get_run("run-2")
        assert running is not None and running.started_at is not None
        other_manager = SQLiteBudgetStore(connection, lock, clock=clock).bind(
            run_id="run-2",
            execution_epoch=grant.execution_epoch,
            lease_owner="worker-2",
            policy=policy,
            run_started_at=running.started_at,
        )
        accepted = await other_manager.reserve(
            run_id="run-2",
            execution_epoch=grant.execution_epoch,
            amount=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
            expires_at=NOW + timedelta(minutes=1),
        )
        assert accepted.run_id == "run-2"
    finally:
        release_large.set()
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
async def test_citation_http_budget_uses_nullable_trace_call_fk(
    tmp_path, monkeypatch
) -> None:
    connection, _, manager, _, _ = await _running_budget(tmp_path)

    async def safe_fetch(*_args, **_kwargs):
        import httpx

        return httpx.Response(
            200,
            text="FastAPI supports WebSockets and asynchronous APIs." * 4,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://example.com/docs"),
        )

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", safe_fetch)
    try:
        with bind_run_context(_context(manager)):
            verification, _ = await verify_citations(
                {
                    "winner_rationale": (
                        "FastAPI supports WebSockets. [Source: FastAPI Docs]"
                    )
                },
                [{
                    "conclusion": "FastAPI Docs",
                    "sources": [{
                        "title": "FastAPI Docs",
                        "url": "https://example.com/docs",
                        "snippet": "FastAPI WebSockets",
                        "score": 8,
                    }],
                    "evidence_strength": "strong",
                    "disputed": False,
                }],
            )
        assert verification.status_counts.verified == 1
        latest = await manager._latest_rows()
        http_rows = [row for row in latest if row[5] == "http_calls"]
        assert len(http_rows) == 1
        assert http_rows[0][1] is None
        assert http_rows[0][4] == "settled"
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


@pytest.mark.parametrize("call_limit", [1, 2, 6])
async def test_synthesis_correction_uses_real_budget_trace_and_transport_limits(tmp_path, monkeypatch, call_limit):
    import json
    from deepchoice.agents.conclusion_synthesizer import ConclusionSynthesizerAgent
    from deepchoice.observability import SQLiteTraceStore, RuntimeTraceRecorder
    from deepchoice.runtime.context import bind_node_attempt

    connection, lock, manager, _, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=call_limit, total_tokens=200_000))
    sink = SQLiteTraceStore(connection, lock, clock=clock).bind(
        run_id="run-1", execution_epoch=1, lease_owner="worker")
    trace = RuntimeTraceRecorder(sink, task_id="task-1")
    payload = {"source_facts": [{"id": f"F{i}", "evidence_id": 1} for i in range(1, 7)]}
    response = SimpleNamespace(model="fixture", usage=SimpleNamespace(
        prompt_tokens=11, completion_tokens=7, total_tokens=18),
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(payload)))])

    class RetryableError(Exception):
        status_code = 500

    effects = [response, response] if call_limit < 6 else [RetryableError(), RetryableError(), response] * 2
    create = AsyncMock(side_effect=effects)
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm_module, "_retry_sleep", AsyncMock())
    try:
        node = await trace.start_node_attempt("conclusion_synthesizer")
        assert node is not None
        with bind_run_context(_context(manager, trace)), bind_node_attempt(node.node_attempt_id):
            if call_limit == 1:
                with pytest.raises(BudgetExceededError):
                    await ConclusionSynthesizerAgent().run({"task": {"query": "compare a and b"}})
            else:
                state = await ConclusionSynthesizerAgent().run({"task": {"query": "compare a and b"}})
                assert state["quality_signals"][0]["structure_correction"]["outcome"] == "invalid"
                assert state["token_usage"][0]["calls"] == 2
                assert state["token_usage"][0]["total_tokens"] == 36
        assert create.await_count == call_limit
        usage = await manager._usage()
        assert usage[BudgetResource.LLM_CALLS] == call_limit
        if call_limit < 6:
            assert usage[BudgetResource.TOTAL_TOKENS] == 18 * call_limit
        else:
            assert usage[BudgetResource.TOTAL_TOKENS] > 36  # uncertain failed transmissions charged
        rows = await (await connection.execute("SELECT status FROM external_calls")).fetchall()
        assert len(rows) == (2 if call_limit == 1 else call_limit)
        assert sum(row[0] == "succeeded" for row in rows) == (1 if call_limit == 1 else 2)
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["denied", "cancelled", "success"])
async def test_official_body_real_ledger_admission_and_cancellation(tmp_path, monkeypatch, outcome):
    import httpx
    from deepchoice import outbound
    from deepchoice.agents.multi_retriever import _invoke_retriever_miss
    from deepchoice.retrievers import official

    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(retrieval_calls=1, http_calls=1 if outcome == "denied" else 2))
    root = "https://docs.acme.example/"
    monkeypatch.setattr(official, "TECH_DOCS", {"acme": {"url": root, "title": "Acme documentation"}})
    monkeypatch.setattr(official, "load_learned", lambda: {})
    monkeypatch.setattr(official, "call_model", AsyncMock(return_value={"url": None}))
    started = asyncio.Event()
    never = asyncio.Event()
    urls = []
    async def fetch(_source, url, **_kwargs):
        urls.append(url)
        if outcome == "cancelled":
            started.set()
            await never.wait()
        text = ('<a href="filtering/">Filtering</a>' if url == root else
                '<p>Acme filtering evaluates the configured fields against a predicate before returning matching records.</p>')
        return httpx.Response(200, text=text, headers={"content-type": "text/html"},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(outbound, "safe_fetch", fetch)
    pending = None
    async def invoke():
        return await _invoke_retriever_miss(
            "official", official.OfficialSearch, query="acme filtering", sub_questions=[], adapted_queries=["acme"])
    try:
        with bind_run_context(_context(manager)):
            if outcome == "cancelled":
                pending = asyncio.create_task(invoke())
                await asyncio.wait_for(started.wait(), timeout=3)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            elif outcome == "denied":
                with pytest.raises(BudgetExceededError):
                    await invoke()
            else:
                result, _ = await invoke()
                assert result.status == "success" and len(result.results) == 1
                assert result.results[0]["url"] == root + "filtering/"
        expected = 2 if outcome == "success" else 1
        assert len(urls) == expected
        usage = await manager._usage()
        assert usage[BudgetResource.HTTP_CALLS] == expected
        assert usage[BudgetResource.RETRIEVAL_CALLS] == 1
        assert await _count(connection, "WHERE status='unknown_spend'") == (1 if outcome == "cancelled" else 0)
        assert await _count(connection, "WHERE status='settled'") == (1 if outcome == "cancelled" else expected + 1)
        # The ledger is append-only: every reservation has its final entry.
        cursor = await connection.execute("""SELECT COUNT(*) FROM budget_ledger b WHERE status='reserved'
            AND NOT EXISTS (SELECT 1 FROM budget_ledger f WHERE f.reservation_id=b.reservation_id
                AND f.status IN ('settled','unknown_spend','released'))""")
        assert (await cursor.fetchone())[0] == 0
    finally:
        if pending is not None:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "rate_limit", "server_error", "connection"])
async def test_evidence_gather_sdk_dispatch_matches_budget_and_trace(tmp_path, monkeypatch, failure):
    """Exercise real SDK retries through an in-memory transport, not mocked create()."""
    import json
    import httpx
    from openai import AsyncOpenAI
    from deepchoice.observability import RuntimeTraceRecorder, SQLiteTraceStore
    from deepchoice.runtime.context import bind_node_attempt

    connection, lock, manager, _, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=1, total_tokens=20000))
    trace = RuntimeTraceRecorder(SQLiteTraceStore(connection, lock, clock=clock).bind(
        run_id="run-1", execution_epoch=1, lease_owner="worker"), task_id="task-1")
    node = await trace.start_node_attempt("conflict_detector")
    assert node is not None
    clients = []
    dispatches = []

    async def handle(request):
        # The real admission must already be committed before any transport dispatch.
        assert await _count(connection, "WHERE status='reserved'") == 2
        dispatches.append(request)
        if len(dispatches) == 1 and failure:
            if failure == "connection":
                raise httpx.ConnectError("fixture unavailable", request=request)
            return httpx.Response(429 if failure == "rate_limit" else 503,
                headers={"retry-after-ms": "1"},
                json={"error": {"message": "fixture unavailable", "type": "fixture_error"}})
        return httpx.Response(200, json={
            "id": "fixture", "object": "chat.completion", "created": 0,
            "model": "fixture", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "bounded evidence"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        })

    def client_factory(**kwargs):
        client = AsyncOpenAI(**kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        clients.append(client)
        return client

    monkeypatch.setitem(llm_module.TIERS, "deepseek-flash", {
        **llm_module.TIERS["deepseek-flash"], "key": "fixture-only", "base": "https://fixture.invalid/v1"})
    monkeypatch.setattr(llm_module, "AsyncOpenAI", client_factory)
    usage = []
    try:
        with bind_run_context(_context(manager, trace)), bind_node_attempt(node.node_attempt_id):
            result = await conflict_module._gather_evidence(
                "generic topic", "claim a", "claim b", usage=usage)
        assert len(dispatches) == 1
        assert result == ("" if failure else "bounded evidence")
        assert (await manager._usage())[BudgetResource.LLM_CALLS] == 1
        cursor = await connection.execute(
            "SELECT count(DISTINCT reservation_id) FROM budget_ledger WHERE resource='llm_calls'")
        assert (await cursor.fetchone())[0] == 1
        await cursor.close()
        cursor = await connection.execute(
            "SELECT status, result_summary_json FROM external_calls WHERE kind='llm'")
        rows = await cursor.fetchall()
        await cursor.close()
        assert len(rows) == 1
        assert rows[0][0] == ("failed" if failure else "succeeded")
        if failure:
            assert not usage
            assert await _count(connection, "WHERE status='unknown_spend'") == 1
            assert json.loads(rows[0][1])["failure_category"]
        else:
            assert usage[0]["total_tokens"] == 150
            assert (await manager._usage())[BudgetResource.TOTAL_TOKENS] == 150
            assert await _count(connection, "WHERE status='unknown_spend'") == 0
    finally:
        for client in clients:
            await client.close()
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "denied", "failed", "cancelled"])
async def test_discovered_page_real_ledger_dispatch_boundary(tmp_path, monkeypatch, outcome):
    import httpx
    from types import SimpleNamespace
    from deepchoice import outbound
    from deepchoice.agents.multi_retriever import _invoke_retriever_miss
    from deepchoice.retrievers import official
    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(retrieval_calls=1, http_calls=1))
    url = "https://docs.unlisted.example/docs/filtering"
    monkeypatch.setattr(official, "TECH_DOCS", {})
    monkeypatch.setattr(official, "load_learned", lambda: {"unlisted": {"url": url, "title": "Unlisted docs"}})
    monkeypatch.setattr(official, "call_model", AsyncMock(return_value={"url": None}))
    monkeypatch.setattr(outbound, "get_resolver", lambda: SimpleNamespace(invalidate=AsyncMock()))
    dispatched = []
    entered = asyncio.Event()
    async def fetch(_source, target, **kwargs):
        assert kwargs["max_redirects"] == 0
        dispatched.append(target)
        entered.set()
        if outcome == "cancelled":
            await asyncio.Event().wait()
        if outcome == "failed":
            raise httpx.ConnectError("fixture unavailable")
        return httpx.Response(200, text=("<p>Unlisted filtering evaluates configured fields against a predicate "
            "before returning matching records. Access restrictions remain separate.</p>"),
            headers={"content-type": "text/html"}, request=httpx.Request("GET", target))
    monkeypatch.setattr(outbound, "safe_fetch", fetch)
    async def invoke():
        return await _invoke_retriever_miss("official", official.OfficialSearch,
            query="unlisted filtering", sub_questions=[], adapted_queries=["unlisted"])
    pending = None
    try:
        if outcome == "denied":
            previous = await manager.reserve(
                run_id="run-1", execution_epoch=1,
                amount=BudgetAmount(resource=BudgetResource.HTTP_CALLS, amount=1),
                expires_at=NOW + timedelta(minutes=1),
            )
            await manager.settle(previous.reservation_id,
                actual=BudgetAmount(resource=BudgetResource.HTTP_CALLS, amount=1))
        with bind_run_context(_context(manager)):
            if outcome == "cancelled":
                pending = asyncio.create_task(invoke())
                await asyncio.wait_for(entered.wait(), timeout=3)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            elif outcome == "denied":
                with pytest.raises(BudgetExceededError):
                    await invoke()
            else:
                result, _ = await invoke()
                assert result.status == ("failed" if outcome == "failed" else "success")
        assert dispatched == ([] if outcome == "denied" else [url])
        usage = await manager._usage()
        assert usage[BudgetResource.HTTP_CALLS] == 1
        assert usage[BudgetResource.RETRIEVAL_CALLS] == 1
        assert await _count(connection, "WHERE status='unknown_spend'") == (
            1 if outcome in {"failed", "cancelled"} else 0)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("content,status", [
    ('{"has_difference":true,"type":"tradeoff_disagreement","explanation":"Incompatible counts"}', "confirmed"),
    ('{"has_difference":"true"}', "unknown"),
    ('{"has_difference":true,"type":"tradeoff_disagreement","explanation":"Incompatible counts","ranges_a":[[0,1]],"ranges_b":[[0,1]]}', "confirmed"),
])
async def test_scan_only_agent_reserves_and_traces_only_scan(tmp_path, monkeypatch, content, status):
    import numpy as np
    from deepchoice.observability import RuntimeTraceRecorder, SQLiteTraceStore
    from deepchoice.runtime.context import bind_node_attempt

    connection, lock, manager, _, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=1, total_tokens=20000))
    trace = RuntimeTraceRecorder(SQLiteTraceStore(connection, lock, clock=clock).bind(
        run_id="run-1", execution_epoch=1, lease_owner="worker"), task_id="task-1")
    node = await trace.start_node_attempt("conflict_detector")
    assert node is not None
    async def create(**kwargs):
        assert kwargs["max_tokens"] == 512
        assert await _count(connection, "WHERE status='reserved'") == 2
        return SimpleNamespace(model="fixture", usage=SimpleNamespace(
            prompt_tokens=100, completion_tokens=20, total_tokens=120),
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    create_mock = AsyncMock(side_effect=create)
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))))
    monkeypatch.setattr(conflict_module, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda titles: np.ones((len(titles), 3))))
    gather = AsyncMock(side_effect=AssertionError("no default evidence gathering"))
    monkeypatch.setattr(conflict_module, "_gather_evidence", gather)
    sources = [{"title": "Comparable capacity", "snippet": f"Alpha supports {i} writers.",
                "url": f"https://source{i}.example/docs", "total_score": 7} for i in [1, 2]]
    try:
        with bind_run_context(_context(manager, trace)), bind_node_attempt(node.node_attempt_id):
            result = await conflict_module.ConflictDetectorAgent(gather_evidence=True).run(
                {"task": {"query": "Select a store"}, "source_scores": sources})
        assert result["conflicts"][0]["scan_status"] == status
        if '"ranges_a"' in content:
            assert result["conflicts"][0]["source_a"]["conflict_scope"]["ranges"] == [[0, 1]]
            assert result["conflicts"][0]["source_b"]["conflict_scope"]["ranges"] == [[0, 1]]
        create_mock.assert_awaited_once()
        gather.assert_not_awaited()
        usage = await manager._usage()
        assert usage[BudgetResource.LLM_CALLS] == 1
        assert usage[BudgetResource.TOTAL_TOKENS] == 120
        assert usage.get(BudgetResource.RETRIEVAL_CALLS, 0) == 0
        cursor = await connection.execute("SELECT status FROM external_calls WHERE kind='llm'")
        rows = await cursor.fetchall()
        await cursor.close()
        assert len(rows) == 1 and rows[0][0] == "succeeded"
        assert await _count(connection, "WHERE status='unknown_spend'") == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_empty_self_review_uses_no_llm_budget_trace_or_sdk_dispatch(tmp_path, monkeypatch):
    from deepchoice.agents.self_reviewer import SelfReviewerAgent
    from deepchoice.observability import RuntimeTraceRecorder, SQLiteTraceStore
    from deepchoice.runtime.context import bind_node_attempt
    connection, lock, manager, _, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=1, total_tokens=20000))
    trace = RuntimeTraceRecorder(SQLiteTraceStore(connection, lock, clock=clock).bind(
        run_id="run-1", execution_epoch=1, lease_owner="worker"), task_id="task-1")
    create = AsyncMock(side_effect=AssertionError("empty review cannot dispatch"))
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    try:
        node = await trace.start_node_attempt("self_reviewer")
        assert node is not None
        with bind_run_context(_context(manager, trace)), bind_node_attempt(node.node_attempt_id):
            result = await SelfReviewerAgent().run({"task": {"query": "Select a store"},
                "final_recommendation": {"decision_analysis": [], "confidence": "low"}})
        create.assert_not_awaited()
        assert result["quality_signals"][0]["review_status"] == "not_run"
        assert result["token_usage"] == []
        usage = await manager._usage()
        assert usage.get(BudgetResource.LLM_CALLS, 0) == 0
        assert await _count(connection) == 0
        cursor = await connection.execute("SELECT COUNT(*) FROM external_calls")
        assert (await cursor.fetchone())[0] == 0
        await cursor.close()
    finally:
        await connection.close()


@pytest.mark.parametrize("offer_basis", [True, False])
async def test_joint_question_uses_one_real_admission_and_no_phantom_call(tmp_path, monkeypatch, offer_basis):
    import json
    from tests.staged_synthesis_helpers import run_staged
    from deepchoice.agents import conclusion_synthesizer as synth
    from deepchoice.observability import SQLiteTraceStore, RuntimeTraceRecorder
    from deepchoice.runtime.context import bind_node_attempt

    task = {"query": "Can Alpha replay retained records?", "candidate_techs": ["Alpha"]}
    chains = [{"sources": [{"title": "Alpha guide", "url": "https://alpha.example/guide",
                            "snippet": "Alpha retains records. Consumers can replay retained records."}]}]
    payload = {"source_view_ids": ["S1"], "decision_analysis": [{
        "kind": "answer", "option": "", "question_id": "R0", "basis_refs": ["S1B1", "S1B2"],
        "reasoning": "Replay depends on retained records.", "assumptions": [],
        "change_condition": "Reconsider if records expire."}]}
    response = SimpleNamespace(model="fixture", usage=SimpleNamespace(
        prompt_tokens=11, completion_tokens=7, total_tokens=18),
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(payload)))])
    create = AsyncMock(return_value=response)
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    if not offer_basis:
        monkeypatch.setattr(synth, "selection_view_packet", lambda *_, **__: ("No saved source views.", {}))
    connection, lock, manager, _, clock = await _running_budget(
        tmp_path, limits=BudgetHardLimits(llm_calls=1, total_tokens=200_000))
    sink = SQLiteTraceStore(connection, lock, clock=clock).bind(
        run_id="run-1", execution_epoch=1, lease_owner="worker")
    trace = RuntimeTraceRecorder(sink, task_id="task-1")
    try:
        node = await trace.start_node_attempt("conclusion_synthesizer")
        with bind_run_context(_context(manager, trace)), bind_node_attempt(node.node_attempt_id):
            agent = synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task))
            state = await run_staged(agent, {"task": task, "evidence_chains": chains})
        assert len(state["final_recommendation"]["decision_analysis"]) == int(offer_basis)
        assert sum(row["calls"] for row in state["token_usage"]) == int(offer_basis)
        assert create.await_count == int(offer_basis)
        usage = await manager._usage()
        assert usage.get(BudgetResource.LLM_CALLS, 0) == int(offer_basis)
        assert usage.get(BudgetResource.TOTAL_TOKENS, 0) == int(offer_basis) * 18
        rows = await (await connection.execute("SELECT status, result_summary_json FROM external_calls")).fetchall()
        summaries = [json.loads(row[1]) for row in rows if row[0] == "succeeded"]
        assert [item["diagnostics"]["profile"] for item in summaries] == (["joint-question-v1"] if offer_basis else [])
        assert all("retained records" not in row[1] for row in rows)
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('source,outcome,raw_fallback', [
    (source, outcome, False) for source in ('arxiv', 'community')
    for outcome in ('success', 'denied', 'timeout', 'cancelled', 'http_failure', 'oversized')
] + [(source, outcome, True) for source in ('arxiv', 'community') for outcome in ('success', 'cancelled')])
async def test_native_multiquery_http_budget_and_stop_boundaries(tmp_path, monkeypatch, source, outcome, raw_fallback):
    from contextlib import asynccontextmanager
    import importlib
    import httpx
    from deepchoice import outbound
    from deepchoice.outbound import throttle
    from deepchoice.agents.multi_retriever import _invoke_retriever_miss

    module = importlib.import_module('deepchoice.retrievers.' + ('arxiv_api' if source == 'arxiv' else source))
    cls = module.ArxivSearch if source == 'arxiv' else module.CommunitySearch
    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(http_calls=1 if outcome == 'denied' else 10))
    monkeypatch.setattr(throttle.gate_for(source), 'interval', 0)
    if outcome == 'timeout':
        monkeypatch.setattr(module, '_SEARCH_TIMEOUT_S', 0.5)
    original = 'durable state ' + 'boundary ' * 400 + ' versus Omega; preserve late conditions.'
    entered = asyncio.Event()
    calls = []
    routes = []

    async def get(url, *, params, **kwargs):
        query = params.get('q', params.get('search_query'))
        calls.append(query)
        if len(calls) == (1 if raw_fallback else 2) and outcome in {'timeout', 'cancelled'}:
            entered.set()
            await asyncio.Event().wait()
        if len(calls) == 2 and outcome == 'oversized':
            return httpx.Response(200, content=b'x' * (1024 * 1024 + 1), request=httpx.Request('GET', url))
        status = 400 if len(calls) == 2 and outcome == 'http_failure' else 200
        text = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/{len(calls)}</id><title>durable state</title><summary>State survives a restart.</summary></entry></feed>'
        return httpx.Response(status, text=text, request=httpx.Request('GET', url)) if source == 'arxiv' else httpx.Response(
            status, json={'items':[{'link':f'https://stackoverflow.com/questions/{len(calls)}', 'title':'durable state',
                                  'body':'<p>State survives a restart when journaling is enabled.</p>'}]}, request=httpx.Request('GET', url))

    @asynccontextmanager
    async def client(name):
        # Routing is inside each granted logical HTTP operation.
        assert (await manager._usage())[BudgetResource.HTTP_CALLS] >= len(routes) + 1
        routes.append(name)
        yield SimpleNamespace(get=get)

    monkeypatch.setattr(outbound, 'make_client', AsyncMock(side_effect=lambda name: client(name)))
    pending = None
    try:
        with bind_run_context(_context(manager)):
            pending = asyncio.create_task(_invoke_retriever_miss(source, cls,
                query=original if raw_fallback else 'durable state', sub_questions=[], adapted_queries=[] if raw_fallback else [
                    'durable state', 'durable recovery', 'durable retention']))
            if outcome == 'cancelled':
                await asyncio.wait_for(entered.wait(), 3)
                pending.cancel()
            if outcome == 'denied':
                with pytest.raises(BudgetExceededError):
                    await pending
            elif outcome == 'cancelled':
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                result, _ = await pending
                assert result.status == ('success' if outcome == 'success' else 'failed')
                assert len(result.results) == ((1 if raw_fallback else 3) if outcome == 'success' else 0)
        expected = 1 if raw_fallback else 3 if outcome == 'success' else 1 if outcome == 'denied' else 2
        if raw_fallback:
            assert calls == [('all:' if source == 'arxiv' else '') + original]
        assert len(calls) == len(routes) == expected
        usage = await manager._usage()
        assert usage[BudgetResource.RETRIEVAL_CALLS] == 1
        assert usage[BudgetResource.HTTP_CALLS] == expected
        assert await _count(connection, "WHERE status='unknown_spend'") == (1 if outcome in {'timeout', 'cancelled'} else 0)
        assert await _count(connection, "WHERE status='settled'") == expected + 1 - (outcome in {'timeout', 'cancelled'})
    finally:
        if pending is not None:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await connection.close()
