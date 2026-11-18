"""Resume endpoint policy (M2): feature flag, guards, attempt cap, lock, run wiring.

All offline: the checkpoint store, the orchestrator class and the background
runner are stubbed. The policy function is also covered directly (pure, no I/O).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import run_limits
from deepchoice.server import app as app_module
from deepchoice.server import resume as resume_module
from deepchoice.server import snapshot_store

client = TestClient(app_module.app)

TASK_ID = "resume_task_1"
SCHEMA = run_limits.GRAPH_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Policy (pure function)
# ---------------------------------------------------------------------------

def _policy(**overrides):
    kwargs = {
        "complete_snapshot": None,
        "failed_snapshot": {"_resume": {"next_nodes": ["evidence_chain"],
                                        "checkpoint_step": 4}},
        "run_state": {"attempt": 1, "graph_schema_version": SCHEMA},
        "current_schema_version": SCHEMA,
    }
    kwargs.update(overrides)
    return resume_module.build_resume_info(**kwargs)


def test_policy_resumable_after_one_failed_attempt(monkeypatch):
    monkeypatch.setenv("RESUME_ENABLED", "1")
    info = _policy()
    assert info["resumable"] is True
    assert info["attempt"] == 1
    assert info["next_node"] == "evidence_chain"
    assert info["checkpoint_step"] == 4


def test_policy_reasons(monkeypatch):
    monkeypatch.setenv("RESUME_ENABLED", "1")
    assert _policy(complete_snapshot={"task": {}})["reason"] == "already_complete"
    monkeypatch.setenv("RESUME_ENABLED", "0")
    assert _policy()["reason"] == "feature_disabled"
    # The capability flag wins even for a completed task in the pure function.
    assert _policy(complete_snapshot={"task": {}})["reason"] == "feature_disabled"
    monkeypatch.setenv("RESUME_ENABLED", "1")
    assert _policy(run_state={})["reason"] == "no_run_record"
    assert _policy(run_state={"attempt": 1,
                              "graph_schema_version": SCHEMA - 1})["reason"] == "schema_mismatch"
    assert _policy(run_state={"attempt": 2,
                              "graph_schema_version": SCHEMA})["reason"] == "attempts_exhausted"
    assert _policy(failed_snapshot={"task": {}})["reason"] == "no_checkpoint"
    assert _policy(complete_snapshot=None, failed_snapshot={"task": {},
                                                            "_resume": {"next_nodes": []}})["reason"] == "no_checkpoint"


def test_policy_max_attempts_env(monkeypatch):
    monkeypatch.setenv("RESUME_ENABLED", "1")
    monkeypatch.setenv("RESUME_MAX_ATTEMPTS", "3")
    assert _policy()["max_attempts"] == 3
    assert _policy(run_state={"attempt": 3,
                              "graph_schema_version": SCHEMA})["reason"] == "attempts_exhausted"


# ---------------------------------------------------------------------------
# Endpoint fixtures
# ---------------------------------------------------------------------------

class FakeState:
    def __init__(self, values=None, metadata=None, next_=()):
        self.values = values or {}
        self.metadata = metadata
        self.next = tuple(next_)


class StubOrchestrator:
    """Stand-in for ChiefEditorAgent; the probe and the run both use it."""

    created: list["StubOrchestrator"] = []
    probe_state = FakeState(values={"task": {"query": "Kafka vs Redis"}},
                            metadata={"step": 4}, next_=("evidence_chain",))

    def __init__(self, task, checkpointer=None, thread_id=None):
        self.task = task
        self.checkpointer = checkpointer
        self.thread_id = thread_id
        self.task_id = thread_id
        self.live_phase = None
        self.resume_calls = 0
        self.astream_calls = 0
        StubOrchestrator.created.append(self)

    async def get_state(self):
        return StubOrchestrator.probe_state

    async def resume_research_task(self):
        self.resume_calls += 1
        if False:  # pragma: no cover - empty async generator
            yield {}

    async def astream_research_task(self):
        self.astream_calls += 1
        if False:  # pragma: no cover - empty async generator
            yield {}


class FakeSaver:
    conn = None


def _write_run_state(task_dir: Path, **overrides) -> None:
    record = {"task_id": task_dir.name, "state": "failed", "attempt": 1,
              "graph_schema_version": SCHEMA}
    record.update(overrides)
    (task_dir / "run_state.json").write_text(json.dumps(record), encoding="utf-8")


def _write_failed_snapshot(task_id: str, next_nodes=("evidence_chain",),
                           step: int = 4) -> None:
    snapshot_store.save_failed_snapshot(
        task_id, {"task": {"query": "Kafka vs Redis"}, "confidence": "low"},
        "boom")
    path = snapshot_store.failed_snapshot_path(task_id, 1)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_resume"] = {
        "attempt": 1,
        "max_attempts": resume_module.max_attempts(),
        "next_nodes": list(next_nodes),
        "checkpoint_step": step,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _reset_module_state() -> None:
    app_module._active_tasks.pop(TASK_ID, None)
    lock = app_module._resume_locks.pop(TASK_ID, None)
    if lock is not None and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass


@pytest.fixture
def resume_env(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    task_dir = outputs / TASK_ID
    task_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", outputs)
    monkeypatch.setattr(snapshot_store, "OUTPUT_DIR", outputs)
    monkeypatch.setenv("RESUME_ENABLED", "1")
    monkeypatch.delenv("RESUME_MAX_ATTEMPTS", raising=False)
    monkeypatch.setattr(app_module, "_get_sqlite_saver",
                        AsyncMock(return_value=FakeSaver()))
    monkeypatch.setattr(app_module, "ChiefEditorAgent", StubOrchestrator)
    monkeypatch.setattr(StubOrchestrator, "created", [])
    _reset_module_state()
    _write_run_state(task_dir)
    _write_failed_snapshot(TASK_ID)
    yield outputs, task_dir
    _reset_module_state()


# ---------------------------------------------------------------------------
# Endpoint guards
# ---------------------------------------------------------------------------

def test_resume_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("RESUME_ENABLED", raising=False)
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 404
    assert "RESUME_DISABLED" in response.json()["detail"]


def test_resume_requires_explicit_confirm(resume_env):
    response = client.post(f"/research/{TASK_ID}/resume", json={})
    assert response.status_code == 400
    assert "RESUME_CONFIRM_REQUIRED" in response.json()["detail"]
    assert not app_module._resume_locks.get(TASK_ID, asyncio.Lock()).locked()


def test_unknown_task_is_404(resume_env):
    response = client.post("/research/no_such_task/resume",
                           json={"confirm": True})
    assert response.status_code == 404


def test_complete_task_is_not_resumable(resume_env):
    snapshot_store.save_snapshot(TASK_ID, {"task": {"query": "q"}})
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 409
    assert "ALREADY_COMPLETE" in response.json()["detail"]


def test_attempt_cap_refuses_further_resume(resume_env):
    outputs, task_dir = resume_env
    _write_run_state(task_dir, attempt=2)
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 409
    assert "RESUME_EXHAUSTED" in response.json()["detail"]


def test_schema_mismatch_refuses_resume(resume_env):
    outputs, task_dir = resume_env
    _write_run_state(task_dir, graph_schema_version=SCHEMA - 1)
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 409
    assert "SCHEMA_MISMATCH" in response.json()["detail"]


def test_missing_run_record_is_not_resumable(resume_env):
    outputs, task_dir = resume_env
    (task_dir / "run_state.json").unlink()
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 409
    assert "NOT_RESUMABLE" in response.json()["detail"]


def test_no_pending_nodes_releases_the_lock(resume_env, monkeypatch):
    monkeypatch.setattr(StubOrchestrator, "probe_state",
                        FakeState(values={"task": {}}, metadata={"step": 4},
                                  next_=()))
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 409
    assert "no pending checkpoint nodes" in response.json()["detail"]
    assert not app_module._resume_locks[TASK_ID].locked()


def test_running_task_conflict(resume_env):
    app_module._active_tasks[TASK_ID] = {"status": "running",
                                         "orchestrator": StubOrchestrator({})}
    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})
    assert response.status_code == 409
    assert "RESUME_IN_PROGRESS" in response.json()["detail"]


def test_resume_lock_conflict(resume_env):
    lock = app_module._resume_locks.setdefault(TASK_ID, asyncio.Lock())
    asyncio.run(lock.acquire())
    try:
        response = client.post(f"/research/{TASK_ID}/resume",
                               json={"confirm": True})
    finally:
        lock.release()
    assert response.status_code == 409
    assert "RESUME_IN_PROGRESS" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_resume_spawns_the_resumed_run(resume_env, monkeypatch):
    spawned = []

    def fake_run(task_id, orchestrator, resume=False):
        spawned.append({"task_id": task_id, "orchestrator": orchestrator,
                        "resume": resume})

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(app_module, "_run_research", fake_run)

    response = client.post(f"/research/{TASK_ID}/resume",
                           json={"confirm": True})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "resuming"
    assert body["attempt"] == 2
    assert body["next_node"] == "evidence_chain"
    assert spawned and spawned[0]["resume"] is True
    assert spawned[0]["task_id"] == TASK_ID
    entry = app_module._active_tasks[TASK_ID]
    assert entry["status"] == "resuming"
    assert entry["resume_attempt"] == 2
    assert entry["resume_lock"].locked()


# ---------------------------------------------------------------------------
# Status extension
# ---------------------------------------------------------------------------

def test_status_reports_resumable_failed_task(resume_env):
    response = client.get(f"/research/{TASK_ID}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["resumable"] is True
    assert body["attempt"] == 1
    assert body["max_attempts"] == 2
    assert body["next_node"] == "evidence_chain"
    assert body["checkpoint_step"] == 4


def test_status_explains_feature_disabled(resume_env, monkeypatch):
    monkeypatch.setenv("RESUME_ENABLED", "0")
    body = client.get(f"/research/{TASK_ID}/status").json()
    assert body["resumable"] is False
    assert body["reason"] == "feature_disabled"


# ---------------------------------------------------------------------------
# Background run wiring: a resumed attempt writes attempt=2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_research_resume_records_the_second_attempt(resume_env,
                                                              monkeypatch):
    outputs, task_dir = resume_env
    state_before = dict(run_limits._state)
    run_dir_before, task_before = run_limits._run_dir, run_limits._task_id

    class RunStub(StubOrchestrator):
        async def get_state(self):
            return FakeState(values={"report": "# R", "confidence": "high",
                                     "task": {"query": "Kafka vs Redis"}},
                             metadata={"step": 9},
                             next_=("self_reviewer",))

    stub = RunStub({"query": "Kafka vs Redis"}, checkpointer=FakeSaver(),
                   thread_id=TASK_ID)
    lock = asyncio.Lock()
    await lock.acquire()
    app_module._active_tasks[TASK_ID] = {
        "thread_id": TASK_ID,
        "orchestrator": stub,
        "queue": asyncio.Queue(),
        "events": [],
        "status": "resuming",
        "resume_attempt": 2,
        "resume_lock": lock,
    }
    try:
        await app_module._run_research(TASK_ID, stub, resume=True)
    finally:
        run_limits._state.clear()
        run_limits._state.update(state_before)
        run_limits._run_dir, run_limits._task_id = run_dir_before, task_before

    record = json.loads((task_dir / "run_state.json").read_text(encoding="utf-8"))
    assert record["attempt"] == 2
    assert record["resumed"] is True
    assert record["graph_schema_version"] == SCHEMA
    assert stub.resume_calls == 1
    assert stub.astream_calls == 0
    assert not lock.locked()
    entry = app_module._active_tasks[TASK_ID]
    assert entry["status"] == "complete"
    assert (task_dir / "research_snapshot.json").exists()
