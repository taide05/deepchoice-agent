"""Tests for the research progress SSE stream and /status endpoints.

Follows the TestClient + module-level _active_tasks injection pattern from
tests/clarify/test_clarify_routes.py (injection into the shared app module's
dict, which is the right fit here — no app rebuild needed).
"""
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


class FakeOrchestrator:
    """Minimal stand-in for ChiefEditorAgent, streamed from app_module._active_tasks."""

    def __init__(self, events=None, exc=None, live_phase=None):
        self.thread_id = "fake-thread"
        self.events = events or []
        self.exc = exc
        self.live_phase = live_phase

    async def astream_research_task(self):
        if self.exc is not None:
            raise self.exc
        for event in self.events:
            yield event

    async def get_state(self):
        raise RuntimeError("get_state should not be reached when live_phase is set")


def _register(orchestrator):
    app_module._active_tasks[TASK_ID] = {
        "thread_id": orchestrator.thread_id,
        "orchestrator": orchestrator,
    }


def _parse_stream(text):
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


class TestStreamEventFormat:
    def test_stream_events_carry_node_phase_ts_update(self):
        _register(FakeOrchestrator(events=[
            {"query_analyzer": {"sub_questions": ["q1"]}},
            {"query_adapter": {"adapted_queries": {}}},
            {"multi_retriever": {"search_results": []}},
            {"source_evaluator": {"source_scores": []}},
            {"conflict_detector": {"conflicts": []}},
            {"evidence_chain": {"evidence_chains": []}},
            {"conclusion_synthesizer": {"final_recommendation": {}}},
            {"report_generator": {"report": "# R"}},
            {"self_reviewer": {"confidence": "high"}},
        ]))

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
        _register(FakeOrchestrator(exc=RuntimeError("boom")))

        resp = client.get(f"/research/{TASK_ID}/stream")
        assert resp.status_code == 200
        events = _parse_stream(resp.text)

        assert len(events) == 1
        assert events[0]["node"] == "__error__"
        assert "boom" in events[0]["detail"]
        assert all(e["node"] != "__done__" for e in events)


class TestStatusLivePhase:
    def test_status_prefers_orchestrator_live_phase(self):
        _register(FakeOrchestrator(live_phase="multi_retriever"))

        resp = client.get(f"/research/{TASK_ID}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["phase"] == "multi_retriever"
