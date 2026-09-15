from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepchoice.hitl import DecisionPause
from deepchoice.persistence.records import CheckpointReference
from deepchoice.server import app as app_module


@pytest.fixture(autouse=True)
def isolate_durable_app_state(tmp_path: Path):
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
        yield
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


def _decode_sse(body: str) -> list[dict[str, object]]:
    decoded: list[dict[str, object]] = []
    for block in body.strip().split("\n\n") if body.strip() else []:
        item: dict[str, object] = {}
        for line in block.splitlines():
            field, value = line.split(":", 1)
            value = value.lstrip()
            item[field] = json.loads(value) if field == "data" else value
        decoded.append(item)
    return decoded


def _create_cancelled(client: TestClient, query: str = "compare A and B") -> tuple[str, int]:
    created = client.post("/api/v1/tasks", json={"query": query})
    assert created.status_code == 202
    task_id = created.json()["task"]["task_id"]
    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    return task_id, cancelled.json()["task"]["version"]


def test_durable_sse_replay_and_last_event_id_reconnect() -> None:
    with TestClient(app_module.app) as client:
        task_id, _ = _create_cancelled(client)
        response = client.get(f"/api/v1/tasks/{task_id}/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        events = _decode_sse(response.text)
        assert [item["event"] for item in events] == ["task.queued", "task.cancelled"]
        ids = [int(item["id"]) for item in events]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        assert all(
            set(item["data"]) <= {"seq", "run_id", "created_at", "status", "node", "reason"}
            for item in events
        )

        resumed = client.get(
            f"/api/v1/tasks/{task_id}/events",
            headers={"Last-Event-ID": str(ids[0])},
        )
        replay = _decode_sse(resumed.text)
        assert [item["event"] for item in replay] == ["task.cancelled"]
        assert int(replay[0]["id"]) == ids[1]


def test_durable_sse_foreign_cursor_requests_public_resync() -> None:
    with TestClient(app_module.app) as client:
        task_id, _ = _create_cancelled(client, "first")
        other_id, _ = _create_cancelled(client, "second")
        foreign = _decode_sse(client.get(f"/api/v1/tasks/{other_id}/events").text)[0]["id"]

        response = client.get(
            f"/api/v1/tasks/{task_id}/events",
            headers={"Last-Event-ID": str(foreign)},
        )
        events = _decode_sse(response.text)
        assert [item["event"] for item in events] == ["resync_required"]
        snapshot = events[0]["data"]["snapshot"]
        assert snapshot["task"]["task_id"] == task_id
        assert snapshot["task"]["status"] == "cancelled"
        assert "lease_owner" not in json.dumps(snapshot)
        assert "execution_epoch" not in json.dumps(snapshot)
        assert "checkpoint_ns" not in json.dumps(snapshot)


def test_durable_sse_waiting_task_delivers_decision_then_closes() -> None:
    with TestClient(app_module.app) as client:
        created = client.post(
            "/api/v1/tasks", json={"query": "compare FastAPI and Flask"}
        ).json()
        task_id = created["task"]["task_id"]
        run_id = created["latest_run"]["run_id"]
        repository = app_module.app.state.task_repository

        async def pause():
            now = datetime.now(UTC)
            run = await repository.get_run(run_id)
            grant = await repository.acquire_run_lease(
                run_id,
                lease_owner="worker",
                lease_ttl=timedelta(minutes=1),
                run_timeout=timedelta(minutes=30),
                now=now,
            )
            reference = CheckpointReference(
                run_id=run_id,
                storage_checkpoint_ns="deepchoice-execution-1",
                checkpoint_id="decision-checkpoint",
                state_schema_version=run.manifest.state_schema_version,
                execution_epoch=grant.execution_epoch,
                created_at=now + timedelta(seconds=1),
            )
            await repository.add_checkpoint_reference(
                reference,
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
                now=now + timedelta(seconds=1),
            )
            await repository.pause_for_decision(
                DecisionPause(
                    decision_id="decision-api-sse",
                    reason="Evidence is structurally insufficient.",
                    gaps=("Missing independent evidence.",),
                ),
                reference,
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
                now=now + timedelta(seconds=2),
            )

        client.portal.call(pause)
        response = client.get(f"/api/v1/tasks/{task_id}/events")
        assert response.status_code == 200
        events = _decode_sse(response.text)
        assert events[-1]["event"] == "decision.required"
        assert events[-1]["data"]["status"] == "waiting_for_input"

        caught_up = client.get(
            f"/api/v1/tasks/{task_id}/events",
            headers={"Last-Event-ID": events[-1]["id"]},
        )
        assert caught_up.status_code == 200
        assert caught_up.text == ""


def test_durable_sse_rejects_invalid_cursor_and_missing_task() -> None:
    with TestClient(app_module.app) as client:
        task_id, _ = _create_cancelled(client)
        invalid = client.get(
            f"/api/v1/tasks/{task_id}/events",
            headers={"Last-Event-ID": "-1"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INVALID_LAST_EVENT_ID"
        missing = client.get("/api/v1/tasks/missing/events")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_legacy_status_aliases_read_durable_tasks() -> None:
    with TestClient(app_module.app) as client:
        task_id, _ = _create_cancelled(client)
        for path in (f"/research/{task_id}/status", f"/tasks/{task_id}"):
            response = client.get(path)
            assert response.status_code == 200
            payload = response.json()
            assert payload["task_id"] == task_id
            assert payload["status"] == "failed"
            assert payload["error_detail"]["code"] == "TASK_CANCELLED"


def test_lifespan_imports_legacy_snapshot_once(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    snapshot_dir = legacy_root / "legacy-task"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "research_snapshot.json").write_text(
        json.dumps({"task": {"query": "legacy query"}, "report": "# Legacy report"}),
        encoding="utf-8",
    )
    app_module.app.state.legacy_snapshot_root = legacy_root

    with TestClient(app_module.app) as client:
        imported = client.get("/api/v1/tasks/legacy-task")
        for _ in range(100):
            if imported.status_code == 200:
                break
            time.sleep(0.01)
            imported = client.get("/api/v1/tasks/legacy-task")
        assert imported.status_code == 200
        assert imported.json()["task"]["status"] == "completed"
        report = client.get("/api/v1/tasks/legacy-task/report")
        assert report.status_code == 200
        assert report.json()["report"] == "# Legacy report"
        summary = app_module.app.state.legacy_import_summary
        assert summary.imported == 1

    with TestClient(app_module.app) as client:
        for _ in range(100):
            if app_module.app.state.legacy_import_summary is not None:
                break
            time.sleep(0.01)
        assert client.get("/api/v1/tasks/legacy-task").status_code == 200
        assert app_module.app.state.legacy_import_summary.skipped == 1


def test_legacy_import_does_not_block_readiness(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import threading

    started = threading.Event()
    release = threading.Event()

    async def slow_import(*_args, **_kwargs):
        started.set()
        await asyncio.to_thread(release.wait)
        return app_module.LegacyImportSummary()

    monkeypatch.setattr(app_module, "import_legacy_snapshots", slow_import)
    try:
        with TestClient(app_module.app) as client:
            assert started.wait(timeout=1)
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["legacy_import"]["status"] == "running"
            release.set()
    finally:
        release.set()
