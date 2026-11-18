"""Recovery of tasks whose process died mid-run (review finding R1).

A forced stop leaves `run_state.json` with state=running and a checkpoint that may
still have pending nodes. Startup recovery turns such a task into an
`interrupted` partial attempt so it becomes inspectable and resumable.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import run_limits
from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.server import app as app_module
from deepchoice.server import recovery, snapshot_store

client = TestClient(app_module.app)

TASK_ID = "recovered_task_1"
SCHEMA = run_limits.GRAPH_SCHEMA_VERSION

PAYLOADS = {
    "query_analyzer": {"sub_questions": ["q1"], "scene_context": "solo",
                       "constraints": []},
    "query_adapter": {"adapted_queries": {}},
    "multi_retriever": {"search_results": [], "partial_failures": []},
    "source_evaluator": {"source_scores": []},
    "conflict_detector": {"conflicts": [], "conflict_check": {}},
    "evidence_chain": {"evidence_chains": []},
    "conclusion_synthesizer": {"final_recommendation": {},
                               "confidence": "medium"},
    "report_generator": {"report": "# R"},
    "self_reviewer": {"report": "# R", "confidence": "high",
                      "knowledge_gaps": [], "final_recommendation": {}},
}
CLASSES = {
    "query_analyzer": "QueryAnalyzerAgent",
    "query_adapter": "QueryAdapterAgent",
    "multi_retriever": "MultiRetrieverAgent",
    "source_evaluator": "SourceEvaluatorAgent",
    "conflict_detector": "ConflictDetectorAgent",
    "evidence_chain": "EvidenceChainAgent",
    "conclusion_synthesizer": "ConclusionSynthesizerAgent",
    "report_generator": "ReportGeneratorAgent",
    "self_reviewer": "SelfReviewerAgent",
}


def _patch_agents():
    stack = ExitStack()
    for name, class_name in CLASSES.items():
        async def _run(state, _name=name, _payload=PAYLOADS[name]):
            if _name == "evidence_chain":
                raise RuntimeError("provider down")
            return dict(_payload)

        stack.enter_context(patch(
            f"deepchoice.agents.orchestrator.{class_name}.run",
            new=AsyncMock(side_effect=_run)))
    return stack


def _write_stale_run_state(task_dir: Path, **overrides) -> dict:
    now = time.time()
    record = {
        "task_id": task_dir.name,
        "state": "running",
        "attempt": 1,
        "graph_schema_version": SCHEMA,
        "started_at_epoch": now - 7200,
        "wall_clock_max_s": 900,
    }
    record.update(overrides)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "run_state.json").write_text(json.dumps(record), encoding="utf-8")
    return record


async def _make_interrupted_run(outputs: Path, task_id: str) -> None:
    """Create a real sqlite checkpoint of a run that failed at evidence_chain."""
    outputs.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(outputs / "checkpoints.db"))
    saver = AsyncSqliteSaver(conn)
    orchestrator = ChiefEditorAgent(
        {"query": "Kafka vs Redis", "scene_context": "solo",
         "constraints": [], "report_format": "what_why_how"},
        checkpointer=saver, thread_id=task_id)
    try:
        with _patch_agents():
            with pytest.raises(RuntimeError, match="provider down"):
                await orchestrator.run_research_task()
    finally:
        await conn.close()


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    root.mkdir()
    monkeypatch.setattr(app_module, "OUTPUT_DIR", root)
    monkeypatch.setattr(snapshot_store, "OUTPUT_DIR", root)
    monkeypatch.setenv("RESUME_ENABLED", "1")
    monkeypatch.delenv("RESUME_MAX_ATTEMPTS", raising=False)
    app_module._active_tasks.pop(TASK_ID, None)
    app_module._resume_locks.pop(TASK_ID, None)
    yield root
    app_module._active_tasks.pop(TASK_ID, None)
    lock = app_module._resume_locks.pop(TASK_ID, None)
    if lock is not None and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass


def test_recovery_persists_an_interrupted_partial_snapshot(outputs):
    asyncio.run(_make_interrupted_run(outputs, TASK_ID))
    _write_stale_run_state(outputs / TASK_ID)

    recovered = asyncio.run(recovery.recover_interrupted_tasks(outputs, grace_s=0))

    assert recovered == [TASK_ID]
    partial = snapshot_store.load_failed_snapshot(TASK_ID)
    assert partial["_status"] == recovery.INTERRUPTED_STATUS
    assert partial["_attempt"] == 1
    assert partial["_resume"]["next_nodes"] == ["evidence_chain"]
    assert partial["_resume"]["checkpoint_step"] == 5
    record = json.loads((outputs / TASK_ID / "run_state.json").read_text(
        encoding="utf-8"))
    assert record["state"] == "interrupted"

    # Idempotent: a second sweep has nothing left to recover.
    assert asyncio.run(recovery.recover_interrupted_tasks(outputs, grace_s=0)) == []


def test_recovered_task_is_inspectable_and_resumable(outputs, monkeypatch):
    asyncio.run(_make_interrupted_run(outputs, TASK_ID))
    _write_stale_run_state(outputs / TASK_ID)
    asyncio.run(recovery.recover_interrupted_tasks(outputs, grace_s=0))

    status = client.get(f"/research/{TASK_ID}/status").json()
    assert status["status"] == "interrupted"
    assert status["resumable"] is True
    assert status["next_node"] == "evidence_chain"

    rows = {row["task_id"]: row for row in client.get("/history").json()["tasks"]}
    assert rows[TASK_ID]["status"] == "interrupted"
    assert rows[TASK_ID]["attempts"] == 1

    # The recovered task follows the normal resume path.
    class FakeSaver:
        conn = None

    class StubOrchestrator:
        probe_state = type("S", (), {
            "next": ("evidence_chain",), "metadata": {"step": 5},
            "values": {"task": {"query": "Kafka vs Redis"}}})()

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
        spawned.append(resume)

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
    assert spawned == [True]


def test_fresh_running_record_is_not_recovered(outputs):
    task_dir = outputs / "live_task_1"
    _write_stale_run_state(task_dir, started_at_epoch=time.time())

    assert asyncio.run(recovery.recover_interrupted_tasks(
        outputs, grace_s=30)) == []
    record = json.loads((task_dir / "run_state.json").read_text(encoding="utf-8"))
    assert record["state"] == "running"


def test_stale_record_without_checkpoint_is_marked_and_status_visible(outputs,
                                                                     monkeypatch):
    task_dir = outputs / "dead_task_1"
    _write_stale_run_state(task_dir)

    recovered = asyncio.run(recovery.recover_interrupted_tasks(outputs, grace_s=0))

    assert recovered == ["dead_task_1"]
    assert not list(task_dir.glob("research_snapshot_failed_attempt*.json"))
    record = json.loads((task_dir / "run_state.json").read_text(encoding="utf-8"))
    assert record["state"] == "interrupted"
    status = client.get("/research/dead_task_1/status").json()
    assert status["status"] == "interrupted"
    assert status["resumable"] is False
    rows = {row["task_id"]: row for row in client.get("/history").json()["tasks"]}
    assert rows["dead_task_1"]["status"] == "interrupted"


def test_lifespan_skips_recovery_when_disabled(monkeypatch, tmp_path):
    calls = []

    async def fake_recover(outputs_dir):
        calls.append(outputs_dir)
        return []

    monkeypatch.setattr(recovery, "recover_interrupted_tasks", fake_recover)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.delenv("RESUME_ENABLED", raising=False)

    async def run_lifespan():
        async with app_module._app_lifespan(app_module.app):
            pass

    asyncio.run(run_lifespan())
    assert calls == []


def test_lifespan_runs_recovery_when_enabled(monkeypatch, tmp_path):
    calls = []

    async def fake_recover(outputs_dir):
        calls.append(outputs_dir)
        return [TASK_ID]

    monkeypatch.setattr(recovery, "recover_interrupted_tasks", fake_recover)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setenv("RESUME_ENABLED", "1")

    async def run_lifespan():
        async with app_module._app_lifespan(app_module.app):
            pass

    asyncio.run(run_lifespan())
    assert calls == [tmp_path]
