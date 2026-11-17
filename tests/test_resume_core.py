"""Checkpoint-resume core: streaming from a checkpoint, attempt budgets, inventory.

These tests are offline: the resume integration test uses LangGraph's in-memory
saver with mocked agent nodes, and the inventory test uses an in-memory sqlite
database, so no real run, model call or output directory is involved.
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import run_limits
from deepchoice.agents.orchestrator import ChiefEditorAgent

_REPO_ROOT = Path(__file__).resolve().parent.parent


async def _collect(agen) -> list:
    return [event async for event in agen]


# ---------------------------------------------------------------------------
# Streaming entry points
# ---------------------------------------------------------------------------

class _FakeChain:
    def __init__(self):
        self.calls: list[dict] = []

    async def astream(self, input, config=None, stream_mode="updates"):
        self.calls.append({"input": input, "config": config,
                           "stream_mode": stream_mode})
        yield {"query_analyzer": {"sub_questions": []}}


def _fake_orchestrator(monkeypatch, chain) -> ChiefEditorAgent:
    orch = ChiefEditorAgent({"query": "Kafka vs Redis"})
    monkeypatch.setattr(orch, "init_research_team",
                        lambda start_from="query_analyzer": chain)
    return orch


def test_resume_stream_continues_from_checkpoint(monkeypatch):
    chain = _FakeChain()
    orch = _fake_orchestrator(monkeypatch, chain)

    events = asyncio.run(_collect(orch.astream_research_task(resume=True)))

    assert events == [{"query_analyzer": {"sub_questions": []}}]
    call = chain.calls[0]
    # None input is what tells LangGraph to continue from the latest checkpoint.
    assert call["input"] is None
    assert call["config"] == {"configurable": {"thread_id": orch.thread_id}}
    assert call["stream_mode"] == "updates"


def test_resume_research_task_uses_the_same_resume_path(monkeypatch):
    chain = _FakeChain()
    orch = _fake_orchestrator(monkeypatch, chain)

    asyncio.run(_collect(orch.resume_research_task()))

    assert chain.calls[0]["input"] is None


def test_normal_stream_still_passes_the_initial_state(monkeypatch):
    chain = _FakeChain()
    orch = _fake_orchestrator(monkeypatch, chain)

    asyncio.run(_collect(orch.astream_research_task()))

    assert chain.calls[0]["input"] == {"task": {"query": "Kafka vs Redis"}}


# ---------------------------------------------------------------------------
# Real graph: resume must not re-run completed nodes
# ---------------------------------------------------------------------------

class _NodeCalls:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def record(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1


def _pipeline_patches(calls: _NodeCalls, fail_once: dict[str, Exception]):
    """Patch all nine nodes; `fail_once` nodes raise their exception once."""
    payloads = {
        "query_analyzer": {"sub_questions": ["q1"],
                           "scene_context": "solo", "constraints": []},
        "query_adapter": {"adapted_queries": {}},
        "multi_retriever": {"search_results": [], "partial_failures": []},
        "source_evaluator": {"source_scores": []},
        "conflict_detector": {"conflicts": [], "conflict_check": {}},
        "evidence_chain": {"evidence_chains": []},
        "conclusion_synthesizer": {"final_recommendation": {},
                                   "confidence": "medium"},
        "report_generator": {"report": "# R"},
        "self_reviewer": {"report": "# R", "confidence": "high",
                          "knowledge_gaps": [],
                          "final_recommendation": {}},
    }
    class_names = {
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
    stack = ExitStack()
    for name, class_name in class_names.items():
        async def _run(state, _name=name, _payload=payloads[name]):
            calls.record(_name)
            if _name in fail_once:
                exc = fail_once.pop(_name)
                raise exc
            return dict(_payload)

        target = f"deepchoice.agents.orchestrator.{class_name}.run"
        stack.enter_context(patch(target, new=AsyncMock(side_effect=_run)))
    return stack


def test_completed_nodes_are_not_re_run_on_resume():
    calls = _NodeCalls()
    orch = ChiefEditorAgent({"query": "Kafka vs Redis", "scene_context": "solo",
                             "constraints": [], "report_format": "what_why_how"})
    fail_once = {"evidence_chain": RuntimeError("provider down")}

    with _pipeline_patches(calls, fail_once):
        # First attempt: the graph raises inside evidence_chain.
        with pytest.raises(RuntimeError, match="provider down"):
            asyncio.run(orch.run_research_task())
        before_resume = dict(calls.counts)

        # The checkpoint we would resume from points at the failed node.
        state = asyncio.run(orch.get_state())
        assert "evidence_chain" in tuple(state.next)
        assert state.values.get("sub_questions") == ["q1"]

        # Resume: only the failed node and its successors run again.
        events = asyncio.run(_collect(orch.astream_research_task(resume=True)))

    assert events, "the resumed run produced no graph events"
    after_resume = calls.counts
    completed_before = {"query_analyzer", "query_adapter", "multi_retriever",
                        "source_evaluator", "conflict_detector"}
    assert completed_before <= set(before_resume)
    for node in completed_before:
        assert after_resume[node] == 1, (
            f"{node} was re-run on resume: {after_resume[node]} calls")
    assert after_resume["evidence_chain"] == 2, "the failed node must be retried"
    for node in ("conclusion_synthesizer", "report_generator", "self_reviewer"):
        assert after_resume[node] == 1, (node, after_resume)


# ---------------------------------------------------------------------------
# Attempt-aware run record and per-attempt dispatch budget
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_run_limits(monkeypatch):
    """Give every test its own run_limits state dict; restore on teardown."""
    original = run_limits._state
    isolated = {
        "llm_requests": 0, "tavily_posts": 0,
        "llm_rejected": 0, "tavily_rejected": 0,
        "started_at": None, "run_started_at": None,
        "run_started_at_epoch": None, "stop_reason": None, "stop_at": None,
        "events": [], "counts_at_start": None, "attempt": 1,
    }
    monkeypatch.setattr(run_limits, "_state", isolated)
    monkeypatch.setattr(run_limits, "_run_dir", None)
    monkeypatch.setattr(run_limits, "_task_id", None)
    yield
    run_limits._state = original


def test_run_record_carries_attempt_and_schema_version(monkeypatch):
    run_limits._state["attempt"] = 2
    run_limits._task_id = "task-resume"

    record = run_limits._run_state()

    assert record["attempt"] == 2
    assert record["resumed"] is True
    assert record["graph_schema_version"] == run_limits.GRAPH_SCHEMA_VERSION
    # v3 removed retry_count from ResearchState; bump this deliberately whenever
    # the state contract changes, because resume refuses older checkpoints.
    assert run_limits.GRAPH_SCHEMA_VERSION == 3

    run_limits._state["attempt"] = 1
    first = run_limits._run_state()
    assert first["resumed"] is False
    assert run_limits.snapshot()["attempt"] == 1
    assert run_limits.snapshot()["graph_schema_version"] == (
        run_limits.GRAPH_SCHEMA_VERSION)


def _arm_dispatch_run(monkeypatch, counts_at_start: dict):
    monkeypatch.setattr(run_limits, "_state", {
        **run_limits._state,
        "counts_at_start": counts_at_start,
        "run_started_at": run_limits.time.monotonic(),
        "run_started_at_epoch": run_limits.time.time(),
        "started_at": run_limits.time.monotonic(),
        "stop_reason": None,
    })


def test_llm_budget_is_measured_from_the_attempt_start(monkeypatch):
    # 45 requests happened in the process, but a resumed attempt started at 40:
    # only 5 belong to this attempt, so the 40-request cap is not reached yet.
    run_limits._state["llm_requests"] = 45
    _arm_dispatch_run(monkeypatch, {"llm_requests": 40, "tavily_posts": 0})

    run_limits._check("llm")  # must not raise

    run_limits._state["llm_requests"] = 40 + run_limits.LLM_REQUESTS_MAX
    with pytest.raises(run_limits.DispatchLimitReached) as excinfo:
        run_limits._check("llm")
    assert "LLM request stop line" in str(excinfo.value)


def test_tavily_budget_is_measured_from_the_attempt_start(monkeypatch):
    run_limits._state["tavily_posts"] = 30
    _arm_dispatch_run(monkeypatch, {"llm_requests": 0, "tavily_posts": 24})

    run_limits._check("tavily")  # 6 posts this attempt, under the cap

    run_limits._state["tavily_posts"] = 24 + run_limits.TAVILY_POSTS_MAX
    with pytest.raises(run_limits.DispatchLimitReached) as excinfo:
        run_limits._check("tavily")
    assert "Tavily POST stop line" in str(excinfo.value)


def test_first_attempt_budget_still_counts_from_zero(monkeypatch):
    _arm_dispatch_run(monkeypatch, {"llm_requests": 0, "tavily_posts": 0})
    run_limits._state["llm_requests"] = run_limits.LLM_REQUESTS_MAX

    with pytest.raises(run_limits.DispatchLimitReached):
        run_limits._check("llm")


# ---------------------------------------------------------------------------
# Checkpoint inventory (M0)
# ---------------------------------------------------------------------------

def _load_checkpoint_stats_module():
    script = _REPO_ROOT / "scripts" / "checkpoint_stats.py"
    spec = spec_from_file_location("checkpoint_stats_under_test", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkpoint_stats_counts_tables_and_top_threads():
    stats_module = _load_checkpoint_stats_module()
    conn = sqlite3.connect(":memory:")
    try:
        # langgraph-checkpoint-sqlite 3.x on-disk schema (verified against the
        # installed saver): `checkpoints` + `writes`.
        conn.execute("create table checkpoints (thread_id text, checkpoint_id text)")
        conn.execute("create table writes (thread_id text)")
        conn.executemany(
            "insert into checkpoints values (?, ?)",
            [("t1", f"c{i}") for i in range(3)]
            + [("t2", f"c{i}") for i in range(2)]
            + [("t3", "c0")],
        )
        stats = stats_module.collect_stats(conn, top=2)
    finally:
        conn.close()

    assert stats["missing_expected_tables"] == []
    assert stats["unexpected_tables"] == []
    assert stats["tables"]["checkpoints"] == 6
    assert stats["thread_count"] == 3
    assert [row["thread_id"] for row in stats["top_threads"]] == ["t1", "t2"]
    assert stats["top_threads"][0]["checkpoints"] == 3
    assert stats["retention_policy"]["keep_days"] == stats_module.RETENTION_DAYS
    assert stats["retention_policy"]["keep_tasks"] == stats_module.RETENTION_TASKS


def test_checkpoint_stats_reports_missing_tables_without_failing():
    stats_module = _load_checkpoint_stats_module()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("create table unrelated (x integer)")
        stats = stats_module.collect_stats(conn)
    finally:
        conn.close()

    assert set(stats["missing_expected_tables"]) == {"checkpoints", "writes"}
    assert stats["unexpected_tables"] == ["unrelated"]
    assert stats["thread_count"] == 0
    assert stats["top_threads"] == []


def test_checkpoint_stats_is_read_only_by_construction():
    stats_module = _load_checkpoint_stats_module()
    # The inventory tool exposes no pruning path: row deletion needs the
    # version-specific checkpoint tables and stays an explicit admin action.
    assert not hasattr(stats_module, "prune")
    assert not hasattr(stats_module, "delete_threads")
    source = Path(stats_module.__file__).read_text(encoding="utf-8")
    assert "mode=ro" in source
