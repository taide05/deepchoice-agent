"""Contracts for immutable durable results and their public API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, RunResultRecord, TaskRecord
from deepchoice.persistence.repository import (
    RepositoryOperationError,
    RunLeaseLostError,
    SQLiteTaskRunRepository,
)
from deepchoice.runtime.coordinator import build_public_run_result
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.server import app as app_module


def _records(task_id: str = "task-result", run_id: str = "run-result"):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    task = TaskRecord(
        task_id=task_id,
        status=TaskStatus.QUEUED,
        request=request,
        latest_run_id=run_id,
        created_at=now,
        updated_at=now,
    )
    run = RunRecord(
        run_id=run_id,
        task_id=task_id,
        status=RunStatus.QUEUED,
        manifest=build_run_manifest(request.model_dump()),
        thread_id=run_id,
        created_at=now,
        updated_at=now,
    )
    return task, run


def _result(run_id: str, *, report_format: str = "what_why_how"):
    report = "# Durable report"
    return RunResultRecord(
        run_id=run_id,
        snapshot={
            "task": {"query": "compare FastAPI and Flask", "report_format": report_format},
            "evidence_chains": [],
            "confidence": "high",
            "report": report,
        },
        report=report,
        report_format=report_format,
        created_at=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_result_and_successful_terminal_event_commit_together(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    task, run = _records()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        await repository.create_task_with_run(task, run)
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
            now=now,
        )
        finalized = await repository.finalize_run_with_result(
            run.run_id,
            _result(run.run_id),
            lease_owner="worker",
            execution_epoch=grant.execution_epoch,
            now=now + timedelta(seconds=2),
        )

        assert finalized.task.status is TaskStatus.COMPLETED
        assert (await repository.get_run_result(run.run_id)).report == "# Durable report"
        assert (await repository.list_task_events(task.task_id))[-1].type == "run.completed"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await connection.execute(
                "UPDATE run_results SET report='changed' WHERE run_id=?", (run.run_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await connection.execute("DELETE FROM run_results WHERE run_id=?", (run.run_id,))
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_stale_epoch_and_result_insert_failure_write_nothing(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    task, run = _records()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        await repository.create_task_with_run(task, run)
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
            now=now,
        )
        before = await repository.get_task(task.task_id)
        before_events = await repository.list_task_events(task.task_id)

        with pytest.raises(RunLeaseLostError):
            await repository.finalize_run_with_result(
                run.run_id,
                _result(run.run_id),
                lease_owner="worker",
                execution_epoch=grant.execution_epoch + 1,
                now=now + timedelta(seconds=1),
            )
        assert await repository.get_task(task.task_id) == before
        assert await repository.get_run_result(run.run_id) is None
        assert await repository.list_task_events(task.task_id) == before_events

        # The format mismatch is detected after lifecycle UPDATE statements;
        # the enclosing transaction must roll every prior write back.
        with pytest.raises(RepositoryOperationError):
            await repository.finalize_run_with_result(
                run.run_id,
                _result(run.run_id, report_format="evidence_first"),
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
                now=now + timedelta(seconds=1),
            )
        assert await repository.get_task(task.task_id) == before
        assert await repository.get_run_result(run.run_id) is None
        assert await repository.list_task_events(task.task_id) == before_events
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_cancel_or_deadline_wins_without_publishing_result(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    task, run = _records()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        await repository.create_task_with_run(task, run)
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(minutes=10),
            run_timeout=timedelta(seconds=1),
            now=now,
        )
        finalized = await repository.finalize_run_with_result(
            run.run_id,
            _result(run.run_id),
            lease_owner="worker",
            execution_epoch=grant.execution_epoch,
            now=now + timedelta(seconds=2),
        )
        assert finalized.task.status is TaskStatus.TIMED_OUT
        assert await repository.get_run_result(run.run_id) is None
        assert (await repository.list_task_events(task.task_id))[-1].type == "run.timed_out"
    finally:
        await connection.close()


def test_public_result_uses_allowlist_and_removes_private_nested_values():
    task, run = _records()
    state = type(
        "State",
        (),
        {
            "values": {
                "task": {"query": "mutated"},
                "report": "# Public",
                "confidence": "high",
                "evidence_chains": [
                    {
                        "claim": "supported",
                        "checkpoint_id": "private-cp",
                        "_error": "raw secret exception",
                        "api_key": "sk-private-api-key",
                        "Authorization": "Bearer private-token",
                        "provider_password": "private-password",
                        "nested": {
                            "credentials": "private-credential",
                            "accessToken": "private-access-token",
                            "clientSecret": "private-client-secret",
                            "privateKey": "private-key-material",
                            "apiKey": "private-camel-api-key",
                        },
                    }
                ],
                "token_usage": {"input_tokens": 12, "output_tokens": 7},
                "run_manifest": {"manifest_id": "private"},
                "unknown_state": "private",
            }
        },
    )()
    result = build_public_run_result(
        run,
        task.request.model_dump(mode="json", exclude_none=True),
        state,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    encoded = result.model_dump_json()
    assert result.snapshot["task"]["query"] == task.request.query
    assert "run_manifest" not in result.snapshot
    assert "unknown_state" not in result.snapshot
    assert "checkpoint_id" not in encoded
    assert "raw secret exception" not in encoded
    assert "sk-private-api-key" not in encoded
    assert "private-token" not in encoded
    assert "private-password" not in encoded
    assert "private-credential" not in encoded
    assert "private-access-token" not in encoded
    assert "private-client-secret" not in encoded
    assert "private-key-material" not in encoded
    assert "private-camel-api-key" not in encoded
    assert result.snapshot["token_usage"]["input_tokens"] == 12


def test_public_result_rejects_success_without_report():
    task, run = _records()
    state = type("State", (), {"values": {"confidence": "high"}})()
    with pytest.raises(ValueError, match="non-empty public report"):
        build_public_run_result(
            run,
            task.request.model_dump(mode="json", exclude_none=True),
            state,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


@pytest.fixture
def durable_client(tmp_path: Path):
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


def test_durable_result_api_and_legacy_fallback(durable_client, monkeypatch):
    client = durable_client
    created = client.post(
        "/api/v1/tasks", json={"query": "compare FastAPI and Flask"}
    ).json()
    task_id = created["task"]["task_id"]
    run_id = created["latest_run"]["run_id"]
    repository = app_module.app.state.task_repository

    async def complete():
        grant = await repository.acquire_run_lease(
            run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
        )
        return await repository.finalize_run_with_result(
            run_id,
            _result(run_id),
            lease_owner="worker",
            execution_epoch=grant.execution_epoch,
        )

    client.portal.call(complete)
    monkeypatch.setattr(app_module, "load_snapshot", lambda _task_id: None)

    snapshot = client.get(f"/api/v1/tasks/{task_id}/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["confidence"] == "high"
    assert "manifest" not in snapshot.text
    report = client.get(f"/api/v1/tasks/{task_id}/report")
    assert report.status_code == 200
    assert report.json()["run_id"] == run_id
    assert report.json()["report"] == "# Durable report"
    assert client.get(f"/api/v1/tasks/{task_id}/annotated").status_code == 200
    export = client.get(f"/api/v1/tasks/{task_id}/export?format=md")
    assert export.status_code == 200
    assert export.text == "# Durable report"

    legacy = client.get(f"/research/{task_id}/report")
    assert legacy.status_code == 200
    assert legacy.headers["deprecation"] == "true"
    assert legacy.json()["report"]
    legacy_snapshot = client.get(f"/research/{task_id}/snapshot")
    assert legacy_snapshot.status_code == 200
    assert legacy_snapshot.headers["warning"].startswith("299 DeepChoice")


def test_result_api_distinguishes_not_ready_and_terminal_unavailable(durable_client):
    client = durable_client
    created = client.post("/api/v1/tasks", json={"query": "queued"}).json()
    task_id = created["task"]["task_id"]
    not_ready = client.get(f"/api/v1/tasks/{task_id}/report")
    assert not_ready.status_code == 409
    assert not_ready.json()["error"]["code"] == "TASK_RESULT_NOT_READY"
    assert not_ready.json()["error"]["retryable"] is True

    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    unavailable = client.get(f"/api/v1/tasks/{task_id}/snapshot")
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "TASK_RESULT_UNAVAILABLE"
    assert unavailable.json()["error"]["retryable"] is False


def test_lost_runtime_lease_blocks_mutations_but_keeps_reads(durable_client):
    client = durable_client
    created = client.post("/api/v1/tasks", json={"query": "existing"}).json()
    task_id = created["task"]["task_id"]
    version = created["task"]["version"]
    app_module.app.state.runtime_instance_status = "lost"
    try:
        health = client.get("/health")
        assert health.status_code == 503
        assert client.get(f"/api/v1/tasks/{task_id}").status_code == 200
        for response in (
            client.post("/api/v1/tasks", json={"query": "blocked"}),
            client.post(f"/api/v1/tasks/{task_id}/cancel"),
            client.post(
                f"/api/v1/tasks/{task_id}/resume",
                headers={"If-Match": str(version)},
            ),
        ):
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "RUNTIME_INSTANCE_LEASE_LOST"
    finally:
        app_module.app.state.runtime_instance_status = "active"
