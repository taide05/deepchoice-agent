"""Observability panel verification (Task 3) — AppTest integration with a faked backend.

Runs the real frontend script (frontend/app.py) inside Streamlit's AppTest run
context. The backend API is faked entirely (no live server): httpx.get/post/stream
are replaced with in-memory doubles.

Requires Streamlit — the whole module skips where it cannot be imported
(e.g. the main Python 3.13 env). Run on the Anaconda env:

    python -m pytest tests/test_frontend_obs.py -q
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import httpx
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[1] / "frontend" / "app.py")

SNAP = {
    "task": {"query": "FastAPI vs Flask"},
    "evidence_chains": [{"conclusion": "c1", "evidence_strength": "strong", "sources": [{"x": 1}]}],
    "conflicts": [
        {
            "claim_a": "FastAPI is faster",
            "claim_b": "Flask is simpler",
            "source_a": {"url": "https://a", "score": 8.2},
            "source_b": {"url": "https://b", "score": 6.5},
            "resolution": "A_correct", "confidence": "high",
            "reasoning": "Score diff >= 2.5 with benchmark evidence.",
            "key_factor": "benchmark evidence",
        }
    ],
    "confidence": "high",
    "agent_timing": {
        "query_analyzer": 3.21, "multi_retriever": 42.5, "source_evaluator": 12.34,
        "conflict_detector": 18.9, "evidence_chain": 5.55,
        "conclusion_synthesizer": 22.1, "report_generator": 15.02, "self_reviewer": 9.87,
    },
    "search_results": [
        {"source": "tavily", "status": "success", "results": [{"title": "t1"}], "error": None, "latency_ms": 14169},
        {"source": "arxiv", "status": "failed", "results": [], "error": "401 Unauthorized", "latency_ms": 821},
    ],
    "partial_failures": ["arxiv"],
    "source_scores": [{"title": "s1", "total_score": 8, "scores": {"authority": 8, "timeliness": 7, "verifiability": 9}}],
    "token_usage": [
        {"agent": "query_analyzer", "model": "deepseek-v4-flash", "calls": 2, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        {"agent": "self_reviewer", "model": "deepseek-v4-flash", "calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        {"agent": "self_reviewer", "model": "deepseek-v4-flash", "calls": 2, "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    ],
    "report": "<h1>Fake report</h1><p>body</p>",
}


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        def ev(node, phase, ts):
            return f"data: {json.dumps({'node': node, 'update': {}, 'phase': phase, 'ts': ts})}"
        return iter([ev(*e) for e in self._events])


class _FakeBackend:
    """httpx double. stream_events = [(node, phase, ts), ...]; status_complete
    controls the /status answer used by the EOF fallback path."""

    def __init__(self, stream_events, status_complete):
        self.stream_events = stream_events
        self.status_complete = status_complete

    def get(self, url, **kw):
        if url.endswith("/snapshot"):
            return _FakeResp(SNAP)
        if url.endswith("/report"):
            return _FakeResp({"report": SNAP["report"]})
        if url.endswith("/status"):
            return _FakeResp({"status": "complete"} if self.status_complete else {"status": "started"})
        return _FakeResp({"status": "started"})

    def post(self, url, **kw):
        return _FakeResp({"task_id": "t1", "status": "started"})

    def stream(self, method, url, **kw):
        return _FakeStream(self.stream_events)


def _enter_research_phase(at):
    at.session_state["phase"] = "research"
    at.session_state["clarified_data"] = {"clarified_task": {"query": "FastAPI vs Flask"}, "sub_questions": []}
    at.session_state["research_started"] = True
    at.session_state["research_running"] = True
    at.session_state["research_complete"] = False
    at.session_state["research_task_id"] = "t1"


def _md_text(at):
    return "\n".join(str(m.value) for m in at.markdown)


def test_live_waterfall_shows_running_row_for_successor(monkeypatch):
    """Regression (Task 3 review, Finding 1): on a normal forward run the
    pulsing "运行中" row must render for the workflow-order successor node,
    even though that node has not emitted a completion event yet.

    /status answers "started", so after EOF the script ends without rerun and
    the live waterfall markdown is the final rendered output."""
    backend = _FakeBackend(
        stream_events=[
            ("query_analyzer", "query_analysis", 1000.0),
            ("multi_retriever", "retrieval", 1030.0),
        ],
        status_complete=False,
    )
    monkeypatch.setattr(httpx, "get", backend.get)
    monkeypatch.setattr(httpx, "post", backend.post)
    monkeypatch.setattr(httpx, "stream", backend.stream)

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception, f"initial run: {at.exception}"

    _enter_research_phase(at)
    at.run()
    assert not at.exception, f"live run: {at.exception}"

    md = _md_text(at)
    # Completed bars for the two finished nodes.
    assert "查询分析" in md
    assert "多源检索" in md and "30.0s" in md
    # The running row: successor of multi_retriever is source_evaluator, which
    # has NOT emitted a completion event — the row must still be appended.
    assert "tl-bar-running" in md, "running row missing from live waterfall"
    assert "运行中" in md, "running label missing from live waterfall"
    assert "来源评估" in md, "running row must be the successor node (source_evaluator)"


def test_results_phase_renders_observability_panels(monkeypatch):
    """Full flow: live stream → EOF → /status complete → rerun → results phase
    with the 观测 tab rendering all four panels."""
    backend = _FakeBackend(
        stream_events=[
            ("query_analyzer", "query_analysis", 1000.0),
            ("multi_retriever", "retrieval", 1030.0),
            ("self_reviewer", "self_review", 1040.0),
        ],
        status_complete=True,
    )
    monkeypatch.setattr(httpx, "get", backend.get)
    monkeypatch.setattr(httpx, "post", backend.post)
    monkeypatch.setattr(httpx, "stream", backend.stream)

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception, f"initial run: {at.exception}"

    _enter_research_phase(at)
    at.run()
    assert not at.exception, f"results run: {at.exception}"

    # EOF → /status complete → _complete() → st.rerun() → results phase.
    assert at.session_state["research_running"] is False
    assert at.session_state["research_complete"] is True

    md = _md_text(at)
    cap = "\n".join(str(c.value) for c in at.caption)
    assert len(at.tabs) == 4, f"expected 4 tabs, got {len(at.tabs)}"
    for needle in ("运行轨迹时间轴", "tl-bar", "检索明细", "tavily", "冲突仲裁",
                   "A 正确", "得分 8.2", "Token 统计", "deepseek-v4-flash", "195"):
        assert needle in md, f"missing {needle!r} in rendered markdown"
    assert "129.5s" in cap, f"total elapsed caption missing: {cap!r}"
