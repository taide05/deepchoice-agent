"""Attempt-numbered partial snapshots and cancelled-run resume (M3).

A failed or cancelled run persists one partial snapshot per attempt
(`research_snapshot_failed_attempt{N}.json`); the latest attempt is the default
view and the resume source, and any attempt can be inspected by number. Cancelled
runs are resumable without being reported as failed.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import run_limits
from deepchoice.server import app as app_module
from deepchoice.server import resume as resume_module
from deepchoice.server import snapshot_store

client = TestClient(app_module.app)

TASK_ID = "attempts_task_1"
SCHEMA = run_limits.GRAPH_SCHEMA_VERSION


class FakeState:
    def __init__(self, values=None, metadata=None, next_=()):
        self.values = values or {}
        self.metadata = metadata
        self.next = tuple(next_)


def _write_run_state(task_dir, **overrides) -> None:
    record = {"task_id": task_dir.name, "state": "failed", "attempt": 1,
              "graph_schema_version": SCHEMA}
    record.update(overrides)
    (task_dir / "run_state.json").write_text(json.dumps(record), encoding="utf-8")


def _save_partial(task_id: str, attempt: int, *, status: str = "failed",
                  next_nodes=("evidence_chain",), error: str = "boom") -> None:
    snapshot_store.save_failed_snapshot(
        task_id,
        {"task": {"query": "Kafka vs Redis"}, "confidence": "low",
         "_resume": {"attempt": attempt,
                     "max_attempts": resume_module.max_attempts(),
                     "next_nodes": list(next_nodes),
                     "checkpoint_step": 4 + attempt}},
        error,
        attempt=attempt,
        status=status,
    )


def _reset_module_state() -> None:
    app_module._active_tasks.pop(TASK_ID, None)
    lock = app_module._resume_locks.pop(TASK_ID, None)
    if lock is not None and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass


@pytest.fixture
def store(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    task_dir = outputs / TASK_ID
    task_dir.mkdir(parents=True)
    monkeypatch.setattr(snapshot_store, "OUTPUT_DIR", outputs)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", outputs)
    monkeypatch.setenv("RESUME_ENABLED", "1")
    monkeypatch.delenv("RESUME_MAX_ATTEMPTS", raising=False)
    _reset_module_state()
    _write_run_state(task_dir)
    yield outputs, task_dir
    _reset_module_state()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def test_each_attempt_gets_its_own_file(store):
    _save_partial(TASK_ID, 1, error="first failure")
    _save_partial(TASK_ID, 2, error="second failure")

    path_1 = snapshot_store.failed_snapshot_path(TASK_ID, 1)
    path_2 = snapshot_store.failed_snapshot_path(TASK_ID, 2)
    assert path_1.name == "research_snapshot_failed_attempt1.json"
    assert path_2.exists()

    latest = snapshot_store.load_failed_snapshot(TASK_ID)
    assert latest["_attempt"] == 2
    assert latest["_error"] == "second failure"
    first = snapshot_store.load_failed_snapshot(TASK_ID, attempt=1)
    assert first["_attempt"] == 1
    assert first["_error"] == "first failure"

    attempts = snapshot_store.list_failed_attempts(TASK_ID)
    assert [row["attempt"] for row in attempts] == [1, 2]
    assert [row["error"] for row in attempts] == ["first failure", "second failure"]


def test_legacy_single_file_is_read_as_attempt_one(store):
    outputs, task_dir = store
    legacy = task_dir / "research_snapshot_failed.json"
    legacy.write_text(json.dumps({"task": {"query": "legacy"}, "_error": "old"}),
                      encoding="utf-8")

    snapshot = snapshot_store.load_failed_snapshot(TASK_ID)

    assert snapshot["_attempt"] == 1
    assert snapshot["_status"] == "failed"
    assert snapshot["_error"] == "old"
    assert snapshot_store.list_failed_attempts(TASK_ID) == [
        {"attempt": 1, "status": "failed", "error": "old"}]


def test_unknown_attempt_returns_none(store):
    _save_partial(TASK_ID, 1)
    assert snapshot_store.load_failed_snapshot(TASK_ID, attempt=7) is None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_snapshot_endpoint_defaults_to_latest_and_accepts_attempt(store):
    _save_partial(TASK_ID, 1, error="first failure")
    _save_partial(TASK_ID, 2, error="second failure")

    latest = client.get(f"/research/{TASK_ID}/snapshot").json()
    assert latest["_attempt"] == 2
    first = client.get(f"/research/{TASK_ID}/snapshot",
                       params={"attempt": 1}).json()
    assert first["_attempt"] == 1
    assert client.get(f"/research/{TASK_ID}/snapshot",
                      params={"attempt": 9}).status_code == 404


def test_snapshot_endpoint_prefers_the_complete_snapshot(store):
    _save_partial(TASK_ID, 1)
    snapshot_store.save_snapshot(TASK_ID, {"task": {"query": "done"},
                                           "confidence": "high"})

    snapshot = client.get(f"/research/{TASK_ID}/snapshot").json()

    assert "_error" not in snapshot
    assert snapshot["confidence"] == "high"
    # The partial attempt is still inspectable by number.
    assert client.get(f"/research/{TASK_ID}/snapshot",
                      params={"attempt": 1}).json()["_attempt"] == 1


def test_status_reports_cancelled_not_failed(store):
    _save_partial(TASK_ID, 1, status="cancelled", error="research cancelled")

    body = client.get(f"/research/{TASK_ID}/status").json()

    assert body["status"] == "cancelled"
    assert body["resumable"] is True
    assert body["next_node"] == "evidence_chain"


def test_history_reports_attempts_and_latest_status(store):
    outputs, task_dir = store
    _write_run_state(task_dir, attempt=2)
    _save_partial(TASK_ID, 1, error="first failure")
    _save_partial(TASK_ID, 2, status="cancelled", error="research cancelled")
    complete_id = "attempts_done_1"
    snapshot_store.save_snapshot(complete_id, {"task": {"query": "done"},
                                               "confidence": "high"})
    (outputs / complete_id).mkdir(exist_ok=True)
    _write_run_state(outputs / complete_id, state="complete", attempt=2)

    rows = {row["task_id"]: row for row in client.get("/history").json()["tasks"]}

    assert rows[TASK_ID]["status"] == "cancelled"
    assert rows[TASK_ID]["error"] == "research cancelled"
    assert rows[TASK_ID]["attempts"] == 2
    assert rows[complete_id]["status"] == "complete"
    assert rows[complete_id]["attempts"] == 2


def test_resume_accepts_a_cancelled_run(store, monkeypatch):
    _save_partial(TASK_ID, 1, status="cancelled", error="research cancelled")

    class FakeSaver:
        conn = None

    class StubOrchestrator:
        probe_state = FakeState(values={"task": {"query": "Kafka vs Redis"}},
                                metadata={"step": 5},
                                next_=("evidence_chain",))

        def __init__(self, task, checkpointer=None, thread_id=None):
            self.task = task
            self.checkpointer = checkpointer
            self.thread_id = thread_id
            self.task_id = thread_id
            self.live_phase = None

        async def get_state(self):
            return self.probe_state

    spawned = []

    def fake_run(task_id, orchestrator, resume=False):
        spawned.append({"task_id": task_id, "resume": resume})

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(app_module, "_get_sqlite_saver",
                        AsyncMock(return_value=FakeSaver()))
    monkeypatch.setattr(app_module, "ChiefEditorAgent", StubOrchestrator)
    monkeypatch.setattr(app_module, "_run_research", fake_run)

    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})

    assert response.status_code == 202
    assert response.json()["attempt"] == 2
    assert spawned and spawned[0]["resume"] is True


# ---------------------------------------------------------------------------
# Cancellation persists its own partial attempt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancellation_persists_a_resumable_partial_snapshot(store):
    outputs, task_dir = store
    state_before = dict(run_limits._state)
    run_dir_before, task_before = run_limits._run_dir, run_limits._task_id

    class CancellingOrchestrator:
        def __init__(self):
            self.checkpointer = None

        async def astream_research_task(self):
            raise asyncio.CancelledError()
            if False:  # pragma: no cover - empty async generator
                yield {}

        async def get_state(self):
            return FakeState(values={"task": {"query": "Kafka vs Redis"}},
                             metadata={"step": 5},
                             next_=("evidence_chain",))

    orchestrator = CancellingOrchestrator()
    app_module._active_tasks[TASK_ID] = {
        "orchestrator": orchestrator,
        "queue": asyncio.Queue(),
        "events": [],
        "status": "running",
    }
    try:
        with pytest.raises(asyncio.CancelledError):
            await app_module._run_research(TASK_ID, orchestrator)
    finally:
        run_limits._state.clear()
        run_limits._state.update(state_before)
        run_limits._run_dir, run_limits._task_id = run_dir_before, task_before

    entry = app_module._active_tasks[TASK_ID]
    assert entry["status"] == "cancelled"
    partial = snapshot_store.load_failed_snapshot(TASK_ID)
    assert partial["_attempt"] == 1
    assert partial["_status"] == "cancelled"
    assert partial["_resume"]["next_nodes"] == ["evidence_chain"]
    assert (task_dir / "research_snapshot_failed_attempt1.json").exists()
    # No complete snapshot was written for a cancelled task.
    assert not (task_dir / "research_snapshot.json").exists()
