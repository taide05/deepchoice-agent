from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents.multi_retriever import MultiRetrieverAgent
from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY, DeferredBudgetManager
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.observability import (
    ExternalCallKind,
    RuntimeTraceRecorder,
    SQLiteTraceStore,
    TraceStatus,
)
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.persistence.repository import SQLiteTaskRunRepository
from deepchoice.runtime.context import (
    RunContext,
    bind_node_attempt,
    bind_run_context,
    get_run_context,
)
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.utils import llm as llm_module


async def _running_trace(tmp_path: Path, *, suffix: str = "", acquire: bool = True):
    connection = await connect_database(tmp_path / f"product{suffix}.db")
    await run_migrations(connection)
    lock = asyncio.Lock()
    repository = SQLiteTaskRunRepository(connection, lock)
    now = datetime.now(UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    task = TaskRecord(
        task_id=f"task{suffix}",
        status=TaskStatus.QUEUED,
        request=request,
        latest_run_id=f"run{suffix}",
        created_at=now,
        updated_at=now,
    )
    run = RunRecord(
        run_id=f"run{suffix}",
        task_id=task.task_id,
        status=RunStatus.QUEUED,
        manifest=build_run_manifest(request.model_dump()),
        budget_policy=DEFAULT_RUN_BUDGET_POLICY,
        thread_id=f"run{suffix}",
        created_at=now,
        updated_at=now,
    )
    await repository.create_task_with_run(task, run)
    if not acquire:
        return connection, repository, run, None
    grant = await repository.acquire_run_lease(
        run.run_id,
        lease_owner="worker",
        lease_ttl=timedelta(minutes=1),
        run_timeout=timedelta(minutes=5),
    )
    current = await repository.get_run(run.run_id)
    sink = SQLiteTraceStore(connection, lock).bind(
        run_id=run.run_id,
        execution_epoch=grant.execution_epoch,
        lease_owner="worker",
    )
    recorder = RuntimeTraceRecorder(sink, task_id=task.task_id)
    return connection, repository, current, recorder


async def _rows(connection, sql: str):
    cursor = await connection.execute(sql)
    try:
        return await cursor.fetchall()
    finally:
        await cursor.close()


@pytest.mark.asyncio
async def test_sqlite_trace_started_terminal_and_monotonic_attempts(tmp_path):
    connection, _, _, recorder = await _running_trace(tmp_path)
    try:
        first = await recorder.start_node_attempt("query_analyzer")
        await recorder.finish_node_attempt(
            first, status=TraceStatus.SUCCEEDED, summary={"elapsed_ms": 5}
        )
        second = await recorder.start_node_attempt("query_analyzer")
        await recorder.finish_node_attempt(second, status=TraceStatus.FAILED)

        attempts = await _rows(
            connection,
            "SELECT attempt_no, status FROM node_attempts ORDER BY attempt_no",
        )
        events = await _rows(
            connection,
            "SELECT seq, event_type FROM trace_events ORDER BY seq",
        )
        assert attempts == [(1, "succeeded"), (2, "failed")]
        assert events == [
            (1, "node.started"),
            (2, "node.succeeded"),
            (3, "node.started"),
            (4, "node.failed"),
        ]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_stale_fencing_rejects_trace_without_any_write(tmp_path):
    connection, repository, current, recorder = await _running_trace(tmp_path)
    try:
        assert current is not None
        await repository.finalize_run(
            current.run_id,
            lease_owner="worker",
            execution_epoch=current.execution_epoch,
            status=RunStatus.FAILED,
        )
        assert await recorder.start_node_attempt("late_node") is None
        assert await _rows(connection, "SELECT * FROM node_attempts") == []
        assert await _rows(connection, "SELECT * FROM trace_events") == []
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_concurrent_external_calls_have_unique_call_and_event_sequences(tmp_path):
    connection, _, _, recorder = await _running_trace(tmp_path)
    try:
        node = await recorder.start_node_attempt("multi_retriever")
        assert node is not None

        async def one(index: int):
            call = await recorder.start_external_call(
                node_attempt_id=node.node_attempt_id,
                kind=ExternalCallKind.RETRIEVAL,
                provider=f"source-{index}",
                operation="retrieve",
            )
            await recorder.finish_external_call(
                call,
                status=TraceStatus.SUCCEEDED,
                result_summary={"result_count": index},
            )

        await asyncio.gather(*(one(index) for index in range(8)))
        calls = await _rows(
            connection, "SELECT call_no FROM external_calls ORDER BY call_no"
        )
        seqs = await _rows(connection, "SELECT seq FROM trace_events ORDER BY seq")
        assert calls == [(index,) for index in range(1, 9)]
        assert seqs == [(index,) for index in range(1, 18)]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_contextvar_is_out_of_band_and_isolated(tmp_path):
    connection, _, run, recorder = await _running_trace(tmp_path)
    try:
        assert run is not None

        class Cancellation:
            async def raise_if_cancelled(self):
                return None

        context = RunContext.from_run_record(
            run,
            cancellation=Cancellation(),
            trace=recorder,
            budget=DeferredBudgetManager(),
        )
        assert get_run_context() is None
        with bind_run_context(context):
            assert get_run_context() is context
            assert "trace" not in {"task": {"query": "safe"}}
        assert get_run_context() is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_call_model_records_each_retry_without_model_content(tmp_path, monkeypatch):
    connection, _, run, recorder = await _running_trace(tmp_path)
    assert run is not None

    class RetryableError(Exception):
        status_code = 500

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        model="safe-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
    )
    create = AsyncMock(
        side_effect=[RetryableError("secret body"), response]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm_module, "_get_client", lambda **_: client)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(llm_module, "_retry_sleep", no_sleep)

    class Cancellation:
        async def raise_if_cancelled(self):
            return None

    context = RunContext.from_run_record(
        run,
        cancellation=Cancellation(),
        trace=recorder,
        budget=DeferredBudgetManager(),
    )
    node = await recorder.start_node_attempt("query_analyzer")
    try:
        with bind_run_context(context), bind_node_attempt(node.node_attempt_id):
            assert await llm_module.call_model(
                [{"role": "user", "content": "private prompt"}]
            ) == "ok"
        rows = await _rows(
            connection,
            """
            SELECT status, request_summary_json, result_summary_json,
                   usage_summary_json FROM external_calls ORDER BY call_no
            """,
        )
        assert [row[0] for row in rows] == ["failed", "succeeded"]
        assert [json.loads(row[1])["retry_no"] for row in rows] == [0, 1]
        assert json.loads(rows[1][3])["total_tokens"] == 18
        serialized = json.dumps(rows)
        assert "private prompt" not in serialized
        assert "secret body" not in serialized
    finally:
        await connection.close()


class _CoordinatorState:
    config = {"configurable": {}}
    values = {"report": "# Durable report"}


class _CoordinatorOrchestrator:
    saw_context = False

    def __init__(self, *_args, **_kwargs):
        pass

    async def astream_research_task(self, *, resume=False):
        self.__class__.saw_context = get_run_context() is not None
        yield {"fake": {}}

    async def get_state(self):
        return _CoordinatorState()


@pytest.mark.asyncio
async def test_coordinator_binds_context_and_trace_failure_does_not_change_result(
    tmp_path,
):
    connection, repository, _, _ = await _running_trace(
        tmp_path, suffix="-coord", acquire=False
    )

    class FailingSink:
        run_id = "run-coord"
        execution_epoch = 1

        async def record_run(self, _trace):
            raise OSError("trace store unavailable")

        async def record_node_attempt(self, _attempt):
            raise OSError("trace store unavailable")

        async def record_external_call(self, _call):
            raise OSError("trace store unavailable")

        async def record_event(self, _event):
            raise OSError("trace store unavailable")

    class FailingStore:
        def bind(self, **_kwargs):
            return FailingSink()

    coordinator = RunCoordinator(
        repository,
        object(),
        owner_id="coordinator",
        trace_store=FailingStore(),
        orchestrator_factory=_CoordinatorOrchestrator,
    )
    try:
        _CoordinatorOrchestrator.saw_context = False
        assert await coordinator.submit("run-coord", resume=False)
        for _ in range(300):
            if "run-coord" not in coordinator.active_runs:
                break
            await asyncio.sleep(0.005)
        current = await repository.get_run("run-coord")
        assert current is not None and current.status is RunStatus.COMPLETED
        assert _CoordinatorOrchestrator.saw_context
        assert get_run_context() is None
        assert await repository.get_run_result("run-coord") is not None
        events = await repository.list_task_events("task-coord")
        assert events[-1].type == "run.completed"
    finally:
        await coordinator.stop()
        await connection.close()


@pytest.mark.asyncio
async def test_multi_retriever_records_one_call_per_source(tmp_path):
    connection, _, run, recorder = await _running_trace(tmp_path)
    assert run is not None

    class FakeRetriever:
        async def search(self, query, sub_questions, *, adapted_queries):
            return {
                "source": "ignored",
                "status": "success",
                "results": [],
                "error": None,
                "latency_ms": 1,
            }

    class Cancellation:
        async def raise_if_cancelled(self):
            return None

    context = RunContext.from_run_record(
        run,
        cancellation=Cancellation(),
        trace=recorder,
        budget=DeferredBudgetManager(),
    )
    node = await recorder.start_node_attempt("multi_retriever")
    registry = {"alpha": FakeRetriever, "beta": FakeRetriever}
    try:
        with bind_run_context(context), bind_node_attempt(node.node_attempt_id):
            await MultiRetrieverAgent(retriever_registry=registry).run(
                {
                    "task": {"query": "a sufficiently detailed comparison query"},
                    "sub_questions": ["a sufficiently detailed comparison question"],
                }
            )
        rows = await _rows(
            connection, "SELECT provider, status FROM external_calls ORDER BY provider"
        )
        assert rows == [("alpha", "succeeded"), ("beta", "succeeded")]
    finally:
        await connection.close()
