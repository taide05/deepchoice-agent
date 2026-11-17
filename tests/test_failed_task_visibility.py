"""A failed research run must stay inspectable after the process restarts.

The server persists a failed run's partial state to
`outputs/{task_id}/research_snapshot_failed.json` (save_failed_snapshot), but no
endpoint read that file: after a restart the failed task answered 404 while its
partial evidence sat on disk. These tests pin the read paths for the snapshot,
status and history endpoints.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import deepchoice.server.app as app_module
from deepchoice.server import snapshot_store

client = TestClient(app_module.app)

PARTIAL_STATE = {
    "task": {"query": "Kafka vs Redis"},
    "confidence": "low",
    "evidence_chains": [],
}


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """Point the snapshot store at a temp directory (the app module imports the
    functions directly; their module global is what the fixture replaces)."""
    monkeypatch.setattr(snapshot_store, "OUTPUT_DIR", tmp_path)
    return tmp_path


def _save_failed(task_id: str, error: str = "provider down") -> str:
    snapshot_store.save_failed_snapshot(task_id, dict(PARTIAL_STATE), error)
    app_module._active_tasks.pop(task_id, None)
    return task_id


def test_failed_snapshot_is_served_after_restart(store_dir):
    task_id = _save_failed("failed_task_1")

    resp = client.get(f"/research/{task_id}/snapshot")

    assert resp.status_code == 200
    data = resp.json()
    assert data["_status"] == "failed"
    assert data["_error"] == "provider down"
    assert data["task"]["query"] == "Kafka vs Redis"
    assert data["confidence"] == "low"


def test_failed_status_is_reported_instead_of_404(store_dir):
    task_id = _save_failed("failed_task_2", error="boom")

    resp = client.get(f"/research/{task_id}/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "boom" in data["error"]


def test_a_complete_snapshot_wins_over_a_stale_failed_fragment(store_dir):
    task_id = "complete_task_1"
    snapshot_store.save_snapshot(
        task_id, {"task": {"query": "Kafka vs Redis"}, "confidence": "high"})
    snapshot_store.save_failed_snapshot(
        task_id, dict(PARTIAL_STATE), "from an earlier attempt")
    app_module._active_tasks.pop(task_id, None)

    snapshot = client.get(f"/research/{task_id}/snapshot").json()
    assert "_error" not in snapshot
    assert snapshot["confidence"] == "high"
    status = client.get(f"/research/{task_id}/status").json()
    assert status["status"] == "complete"


def test_history_lists_completed_and_failed_tasks(store_dir):
    complete_id = "history_ok_1"
    failed_id = _save_failed("history_fail_1", error="provider down")
    snapshot_store.save_snapshot(
        complete_id, {"task": {"query": "Redis vs Memcached"},
                      "confidence": "medium"})
    app_module._active_tasks.pop(complete_id, None)

    rows = client.get("/history").json()["tasks"]
    by_id = {row["task_id"]: row for row in rows}

    assert by_id[complete_id]["status"] == "complete"
    assert by_id[failed_id]["status"] == "failed"
    assert "provider down" in by_id[failed_id]["error"]
    assert by_id[failed_id]["query"] == "Kafka vs Redis"


def test_unknown_task_still_answers_404(store_dir):
    assert client.get("/research/no_such_task_9/snapshot").status_code == 404
    assert client.get("/research/no_such_task_9/status").status_code == 404
