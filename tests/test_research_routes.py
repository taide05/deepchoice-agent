"""Tests for the research progress SSE stream and /status endpoints.

Follows the TestClient + module-level _active_tasks injection pattern from
tests/clarify/test_clarify_routes.py (injection into the shared app module's
dict, which is the right fit here — no app rebuild needed).

Post-S-fix semantics (2026-08-27): the background task (_run_research) is the
single execution of the pipeline; it appends events to entry["events"] and
wakes stream subscribers via queue sentinels. The stream endpoint only replays
entry["events"] and never executes the pipeline itself.
"""
import asyncio
import json

from fastapi.testclient import TestClient

import deepchoice.server.app as app_module

client = TestClient(app_module.app)

TASK_ID = "fake_task_1"

# node -> phase pairs matching NODE_TO_PHASE in src/deepchoice/server/app.py
EXPECTED_EVENTS = [
    ("query_analyzer", "query_analysis"),
    ("query_adapter", "query_analysis"),
    ("multi_retriever", "retrieval"),
    ("source_evaluator", "source_evaluation"),
    ("conflict_detector", "conflict_detection"),
    ("evidence_chain", "evidence_chain"),
    ("conclusion_synthesizer", "evidence_chain"),
    ("report_generator", "report_generation"),
    ("self_reviewer", "self_review"),
]

NODE_EVENTS = [
    {"query_analyzer": {"sub_questions": ["q1"]}},
    {"query_adapter": {"adapted_queries": {}}},
    {"multi_retriever": {"search_results": []}},
    {"source_evaluator": {"source_scores": []}},
    {"conflict_detector": {"conflicts": []}},
    {"evidence_chain": {"evidence_chains": []}},
    {"conclusion_synthesizer": {"final_recommendation": {}}},
    {"report_generator": {"report": "# R"}},
    {"self_reviewer": {"confidence": "high"}},
]


class FakeState:
    def __init__(self, values=None, metadata=None):
        self.values = values or {}
        self.metadata = metadata


class FakeOrchestrator:
    """Minimal stand-in for ChiefEditorAgent, streamed from app_module._active_tasks."""

    def __init__(self, events=None, exc=None, live_phase=None, state=None, checkpointer=None):
        self.thread_id = "fake-thread"
        self.events = events or []
        self.exc = exc
        self.live_phase = live_phase
        self.state = state
        self.checkpointer = checkpointer
        self.astream_calls = 0

    async def astream_research_task(self):
        self.astream_calls += 1
        if self.exc is not None:
            raise self.exc
        for event in self.events:
            yield event

    async def get_state(self):
        if self.state is not None:
            return self.state
        raise RuntimeError("get_state should not be reached when live_phase is set")


def _register(orchestrator, *, status="running", events=None):
    app_module._active_tasks[TASK_ID] = {
        "thread_id": orchestrator.thread_id,
        "orchestrator": orchestrator,
        "queue": asyncio.Queue(),
        "events": list(events or []),
        "status": status,
    }


def _parse_stream(text):
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


class TestStreamEventFormat:
    def test_stream_events_carry_node_phase_ts_update(self):
        _register(FakeOrchestrator(), status="complete", events=NODE_EVENTS)

        resp = client.get(f"/research/{TASK_ID}/stream")
        assert resp.status_code == 200
        events = _parse_stream(resp.text)

        assert len(events) == len(EXPECTED_EVENTS) + 1  # node events + __done__
        for event, (node, phase) in zip(events, EXPECTED_EVENTS):
            assert event["node"] == node
            assert event["phase"] == phase
            assert "update" in event
            assert isinstance(event["ts"], float)

        assert events[-1] == {"node": "__done__", "update": {}}

    def test_stream_error_event_and_no_done_after_error(self):
        _register(FakeOrchestrator(), status="failed",
                  events=[{"__error__": {"detail": "boom"}}])

        resp = client.get(f"/research/{TASK_ID}/stream")
        assert resp.status_code == 200
        events = _parse_stream(resp.text)

        assert len(events) == 1
        assert events[0]["node"] == "__error__"
        assert "boom" in events[0]["detail"]
        assert all(e["node"] != "__done__" for e in events)

    def test_stream_replays_only_events_never_executes(self):
        orch = FakeOrchestrator(events=NODE_EVENTS)
        _register(orch, status="complete", events=NODE_EVENTS)

        client.get(f"/research/{TASK_ID}/stream")

        assert orch.astream_calls == 0


class TestBackgroundRun:
    def test_run_streams_once_and_saves_snapshot(self, monkeypatch):
        saved = {}
        monkeypatch.setattr(app_module, "save_snapshot",
                            lambda task_id, state: saved.setdefault("snapshot", state) or None)
        monkeypatch.setattr(app_module, "save_report",
                            lambda task_id, report: saved.setdefault("report", report) or None)

        orch = FakeOrchestrator(events=NODE_EVENTS,
                                state=FakeState(values={"report": "# R", "confidence": "high"}))
        _register(orch)

        asyncio.run(app_module._run_research(TASK_ID, orch))

        assert orch.astream_calls == 1  # single execution — B1 fix
        entry = app_module._active_tasks[TASK_ID]
        assert entry["status"] == "complete"
        assert len(entry["events"]) == len(NODE_EVENTS)
        assert saved["snapshot"]["confidence"] == "high"
        assert saved["report"] == "# R"

    def test_run_failure_saves_partial_and_records_error(self, monkeypatch):
        saved = {}
        monkeypatch.setattr(app_module, "save_failed_snapshot",
                            lambda task_id, state, error: saved.setdefault("partial", (state, error)) or None)

        orch = FakeOrchestrator(
            events=NODE_EVENTS[:2], exc=RuntimeError("boom"),
            state=FakeState(values={"task": {"query": "x"}}),
        )
        _register(orch)

        asyncio.run(app_module._run_research(TASK_ID, orch))

        entry = app_module._active_tasks[TASK_ID]
        assert entry["status"] == "failed"
        assert entry["error"] == "boom"
        assert entry["events"][-1] == {"__error__": {"detail": "boom"}}
        partial_state, error = saved["partial"]
        assert partial_state["task"] == {"query": "x"}
        assert error == "boom"

    def test_run_closes_checkpointer_connection(self, monkeypatch):
        closed = []

        class FakeConn:
            async def close(self):
                closed.append(True)

        checkpointer = type("FakeCP", (), {"conn": FakeConn()})()
        orch = FakeOrchestrator(events=NODE_EVENTS,
                                state=FakeState(values={"report": "# R"}), checkpointer=checkpointer)
        _register(orch)
        monkeypatch.setattr(app_module, "save_snapshot", lambda *a, **k: None)
        monkeypatch.setattr(app_module, "save_report", lambda *a, **k: None)

        asyncio.run(app_module._run_research(TASK_ID, orch))

        assert closed == [True]


class TestStatusLivePhase:
    def test_status_prefers_orchestrator_live_phase(self):
        _register(FakeOrchestrator(live_phase="multi_retriever"))

        resp = client.get(f"/research/{TASK_ID}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["phase"] == "multi_retriever"
