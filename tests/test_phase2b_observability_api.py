"""Public latest-run Trace API contract and aggregation tests."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from deepchoice.observability import ExternalCallKind, SQLiteTraceStore, TraceStatus
from deepchoice.observability.query import SQLiteObservabilityQuery
from deepchoice.persistence.database import connect_database
from deepchoice.runtime.lifecycle import RunStatus
from deepchoice.server import app as app_module


@pytest.fixture
def observability_client(tmp_path):
    state = app_module.app.state
    missing = object()
    names = (
        "execution_enabled",
        "checkpoint_database_path",
        "product_database_path",
        "legacy_snapshot_root",
    )
    old = {name: getattr(state, name, missing) for name in names}
    state.execution_enabled = False
    state.checkpoint_database_path = tmp_path / "checkpoints.db"
    state.product_database_path = tmp_path / "product.db"
    state.legacy_snapshot_root = tmp_path / "legacy"
    try:
        with TestClient(app_module.app) as client:
            yield client
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


def _create(client, query="compare FastAPI and Flask"):
    response = client.post("/api/v1/tasks", json={"query": query})
    assert response.status_code == 202
    return response.json()


def test_latest_run_observability_aggregates_and_exposes_only_allowlist(
    observability_client,
):
    client = observability_client
    created = _create(client)
    task_id = created["task"]["task_id"]
    run_id = created["latest_run"]["run_id"]
    state = app_module.app.state
    repository = state.task_repository
    connection = state.product_database_connection
    lock = state.product_database_lock

    async def record_trace():
        grant = await repository.acquire_run_lease(
            run_id,
            lease_owner="test-worker-secret",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
        )
        sink = SQLiteTraceStore(connection, lock).bind(
            run_id=run_id,
            execution_epoch=grant.execution_epoch,
            lease_owner="test-worker-secret",
        )
        first = await sink.start_node_attempt("query_analyzer")
        failed_call = await sink.start_external_call(
            node_attempt_id=first.node_attempt_id,
            kind=ExternalCallKind.LLM,
            provider="deepseek-flash",
            operation="chat.completions.create",
            request_summary={"retry_no": 0},
        )
        await sink.finish_external_call(
            failed_call,
            status=TraceStatus.FAILED,
            result_summary={"error_type": "PrivateError", "raw": "private body"},
        )
        await sink.finish_node_attempt(first, status=TraceStatus.FAILED)

        second = await sink.start_node_attempt("query_analyzer")
        success_call = await sink.start_external_call(
            node_attempt_id=second.node_attempt_id,
            kind=ExternalCallKind.LLM,
            provider="deepseek-flash",
            operation="chat.completions.create",
            request_summary={"retry_no": 1},
        )
        await sink.finish_external_call(
            success_call,
            status=TraceStatus.SUCCEEDED,
            usage_summary={
                "input_tokens": 15,
                "total_tokens": 17,
                "private_note": "private observability metadata",
            },
        )
        retrieval = await sink.start_external_call(
            node_attempt_id=second.node_attempt_id,
            kind=ExternalCallKind.RETRIEVAL,
            provider="tavily",
            operation="search",
        )
        await sink.finish_external_call(retrieval, status=TraceStatus.SUCCEEDED)
        await sink.finish_node_attempt(second, status=TraceStatus.SUCCEEDED)

    client.portal.call(record_trace)
    response = client.get(f"/api/v1/tasks/{task_id}/observability")

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "available"
    assert body["budget_policy_availability"] == "available"
    assert body["totals"] == {
        "node_attempts": 2,
        "node_retries": 1,
        "external_calls": 3,
        "failed_calls": 1,
        "llm_calls": 2,
        "retrieval_calls": 1,
        "input_tokens": 15,
        "output_tokens": None,
        "total_tokens": 17,
        "token_usage_complete": False,
    }
    assert [node["attempt_no"] for node in body["nodes"]] == [1, 2]
    assert body["calls"][1]["node_name"] == "query_analyzer"
    assert body["calls"][1]["node_attempt_no"] == 2
    assert body["calls"][1]["retry_no"] == 1
    assert body["calls"][1]["usage"] == {"input_tokens": 15, "total_tokens": 17}
    encoded = response.text
    for private in (
        "node_attempt_id",
        "call_id",
        "execution_epoch",
        "lease_owner",
        "checkpoint",
        "manifest",
        "PrivateError",
        "private body",
        "request_summary",
        "private_note",
        "private observability metadata",
    ):
        assert private not in encoded


def test_new_run_without_trace_is_unavailable_but_policy_is_available(
    observability_client,
):
    client = observability_client
    created = _create(client)
    response = client.get(
        f"/api/v1/tasks/{created['task']['task_id']}/observability"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "unavailable"
    assert body["unavailable_reason"] == "trace_not_recorded"
    assert body["budget_policy_availability"] == "available"
    assert body["nodes"] == []
    assert body["calls"] == []
    assert body["totals"]["input_tokens"] is None
    assert body["totals"]["token_usage_complete"] is False


def test_historical_run_without_frozen_policy_is_reported_unavailable(
    observability_client,
):
    client = observability_client
    created = _create(client)
    task_id = created["task"]["task_id"]
    run_id = created["latest_run"]["run_id"]
    connection = app_module.app.state.product_database_connection

    async def remove_policy_for_historical_fixture():
        await connection.execute("DROP TRIGGER run_budget_policies_reject_delete")
        await connection.execute(
            "DELETE FROM run_budget_policies WHERE run_id = ?", (run_id,)
        )
        await connection.commit()

    client.portal.call(remove_policy_for_historical_fixture)
    body = client.get(f"/api/v1/tasks/{task_id}/observability").json()
    assert body["availability"] == "unavailable"
    assert body["budget_policy_availability"] == "unavailable"
    assert body["budget_policy_unavailable_reason"] == "historical_run"


def test_observability_not_found_and_latest_run_empty_semantics(observability_client):
    client = observability_client
    missing = client.get("/api/v1/tasks/missing/observability")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "TASK_NOT_FOUND"

    created = _create(client)
    task_id = created["task"]["task_id"]
    state = app_module.app.state

    async def clear_latest_run():
        async with state.product_database_lock:
            await state.product_database_connection.execute(
                "UPDATE tasks SET latest_run_id = NULL WHERE task_id = ?",
                (task_id,),
            )
            await state.product_database_connection.commit()

    client.portal.call(clear_latest_run)
    body = client.get(f"/api/v1/tasks/{task_id}/observability").json()

    assert body["run_id"] is None
    assert body["availability"] == "unavailable"
    assert body["unavailable_reason"] == "no_latest_run"
    assert body["budget_policy_unavailable_reason"] == "no_latest_run"


class _GateCursor:
    def __init__(self, cursor, selected_latest, release):
        self._cursor = cursor
        self._selected_latest = selected_latest
        self._release = release

    async def fetchone(self):
        row = await self._cursor.fetchone()
        if row is not None and self._selected_latest:
            self._selected_latest = False
            self._release[0].set()
            await self._release[1].wait()
        return row

    async def fetchall(self):
        return await self._cursor.fetchall()

    async def close(self):
        await self._cursor.close()


class _LatestRunReadGate:
    def __init__(self, connection, release):
        self._connection = connection
        self._release = release

    async def execute(self, sql, parameters=()):
        cursor = await self._connection.execute(sql, parameters)
        is_latest_read = "SELECT latest_run_id FROM tasks" in sql
        return _GateCursor(cursor, is_latest_read, self._release)

    async def commit(self):
        await self._connection.commit()

    async def rollback(self):
        await self._connection.rollback()


def test_latest_run_selection_and_trace_use_one_sqlite_read_snapshot(
    observability_client,
):
    client = observability_client
    created = _create(client)
    task_id = created["task"]["task_id"]
    run_id = created["latest_run"]["run_id"]
    state = app_module.app.state

    async def read_while_latest_run_changes():
        selected_latest = asyncio.Event()
        release_reader = asyncio.Event()
        writer = await connect_database(state.product_database_path)
        try:
            reader = SQLiteObservabilityQuery(
                _LatestRunReadGate(
                    state.product_database_connection,
                    (selected_latest, release_reader),
                ),
                asyncio.Lock(),
            )
            result_task = asyncio.create_task(reader.for_task(task_id))
            await asyncio.wait_for(selected_latest.wait(), timeout=5)

            await writer.execute(
                "UPDATE tasks SET latest_run_id = NULL WHERE task_id = ?",
                (task_id,),
            )
            await writer.commit()
            release_reader.set()
            return await result_task
        finally:
            release_reader.set()
            await writer.close()

    first_snapshot = client.portal.call(read_while_latest_run_changes)
    assert first_snapshot.run_id == run_id
    assert first_snapshot.unavailable_reason == "trace_not_recorded"
    after_switch = client.portal.call(
        lambda: app_module.app.state.observability_query.for_task(task_id)
    )
    assert after_switch.run_id is None
    assert after_switch.unavailable_reason == "no_latest_run"


def test_unfinished_trace_rows_are_projected_as_interrupted_or_unknown(
    observability_client,
):
    client = observability_client
    state = app_module.app.state
    repository = state.task_repository
    connection = state.product_database_connection
    lock = state.product_database_lock

    def create_started_trace(query):
        created = _create(client, query)
        task_id = created["task"]["task_id"]
        run_id = created["latest_run"]["run_id"]

        async def record_started():
            grant = await repository.acquire_run_lease(
                run_id,
                lease_owner=f"worker-{task_id}",
                lease_ttl=timedelta(seconds=30),
                run_timeout=timedelta(minutes=5),
            )
            sink = SQLiteTraceStore(connection, lock).bind(
                run_id=run_id,
                execution_epoch=grant.execution_epoch,
                lease_owner=f"worker-{task_id}",
            )
            node = await sink.start_node_attempt("query_analyzer")
            call = await sink.start_external_call(
                node_attempt_id=node.node_attempt_id,
                kind=ExternalCallKind.LLM,
                provider="deepseek-flash",
                operation="chat.completions.create",
                request_summary={"retry_no": 0},
            )
            return grant, node, call

        grant, node, call = client.portal.call(record_started)
        return task_id, run_id, grant, node, call

    old_task, old_run, old_grant, _, _ = create_started_trace("old epoch started")

    async def advance_epoch():
        async with lock:
            await connection.execute(
                "UPDATE runs SET execution_epoch = ?, lease_owner = ? WHERE run_id = ?",
                (old_grant.execution_epoch + 1, "replacement-worker", old_run),
            )
            await connection.commit()

    client.portal.call(advance_epoch)
    old_projection = client.get(
        f"/api/v1/tasks/{old_task}/observability"
    ).json()
    assert old_projection["nodes"][0]["status"] == "interrupted"
    assert old_projection["calls"][0]["status"] == "interrupted"

    terminal_task, terminal_run, terminal_grant, _, _ = create_started_trace(
        "terminal run started"
    )

    async def finalize_with_unfinished_trace():
        return await repository.finalize_run(
            terminal_run,
            lease_owner=f"worker-{terminal_task}",
            execution_epoch=terminal_grant.execution_epoch,
            status=RunStatus.FAILED,
        )

    client.portal.call(finalize_with_unfinished_trace)
    terminal_projection = client.get(
        f"/api/v1/tasks/{terminal_task}/observability"
    ).json()
    assert terminal_projection["nodes"][0]["status"] == "unknown"
    assert terminal_projection["calls"][0]["status"] == "unknown"
    assert terminal_projection["totals"]["failed_calls"] == 1

    interrupted_task, interrupted_run, interrupted_grant, _, _ = create_started_trace(
        "interrupted run started"
    )

    async def interrupt_with_unfinished_trace():
        return await repository.finalize_run(
            interrupted_run,
            lease_owner=f"worker-{interrupted_task}",
            execution_epoch=interrupted_grant.execution_epoch,
            status=RunStatus.INTERRUPTED,
        )

    client.portal.call(interrupt_with_unfinished_trace)
    interrupted_projection = client.get(
        f"/api/v1/tasks/{interrupted_task}/observability"
    ).json()
    assert interrupted_projection["nodes"][0]["status"] == "interrupted"
    assert interrupted_projection["calls"][0]["status"] == "interrupted"
