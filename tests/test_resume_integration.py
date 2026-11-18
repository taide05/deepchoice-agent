"""End-to-end resume against a real sqlite checkpoint (no stubs for the graph).

The endpoint tests stub the orchestrator; this test covers the actual pairing the
server relies on: a real LangGraph graph, a real AsyncSqliteSaver file, and a
fresh graph/connection resuming from the checkpoint the first attempt left.

Both graph entry shapes are covered:
  * a plain task started at query_analyzer;
  * a task with sub_questions (clarify flow) started at query_adapter, whose
    graph does not contain query_analyzer at all.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deepchoice.agents.orchestrator import ChiefEditorAgent

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

PLAIN_TASK = {"query": "Kafka vs Redis", "scene_context": "solo",
              "constraints": [], "report_format": "what_why_how"}
CLARIFY_TASK = {**PLAIN_TASK, "sub_questions": ["q1", "q2"]}


def _patch_agents(calls: dict[str, int], fail_once: dict[str, Exception]):
    stack = ExitStack()
    for name, class_name in CLASSES.items():
        async def _run(state, _name=name, _payload=PAYLOADS[name]):
            calls[_name] = calls.get(_name, 0) + 1
            if _name in fail_once:
                raise fail_once.pop(_name)
            return dict(_payload)

        stack.enter_context(patch(
            f"deepchoice.agents.orchestrator.{class_name}.run",
            new=AsyncMock(side_effect=_run)))
    return stack


async def _run_interrupted_then_resume(task: dict, thread_id: str,
                                       db_path) -> tuple[dict, dict]:
    """Fail the first attempt, then resume it with a fresh saver and graph."""
    conn = await aiosqlite.connect(str(db_path))
    saver = AsyncSqliteSaver(conn)
    calls: dict[str, int] = {}
    orchestrator = ChiefEditorAgent(task, checkpointer=saver, thread_id=thread_id)
    with _patch_agents(calls, {"evidence_chain": RuntimeError("provider down")}):
        with pytest.raises(RuntimeError, match="provider down"):
            await orchestrator.run_research_task()
    await conn.close()
    before = dict(calls)

    # What the server does: a new connection, a probe graph to read the
    # checkpoint, then a fresh orchestrator for the resumed stream.
    conn2 = await aiosqlite.connect(str(db_path))
    saver2 = AsyncSqliteSaver(conn2)
    probe = ChiefEditorAgent(task, checkpointer=saver2, thread_id=thread_id)
    state = await probe.get_state()
    assert tuple(state.next) == ("evidence_chain",)
    expected_sub_questions = list(task.get("sub_questions") or ["q1"])
    assert state.values.get("sub_questions") == expected_sub_questions

    calls.clear()
    resumed = ChiefEditorAgent(task, checkpointer=saver2, thread_id=thread_id)
    with _patch_agents(calls, {}):
        events = [event async for event in resumed.astream_research_task(resume=True)]
    final = await resumed.get_state()
    await conn2.close()
    return {"before": before, "after": dict(calls), "events": events,
            "final_next": tuple(final.next),
            "final_confidence": final.values.get("confidence")}


def test_resume_from_real_checkpoint_plain_task(tmp_path):
    result = asyncio.run(_run_interrupted_then_resume(
        PLAIN_TASK, "plain-thread", tmp_path / "plain.db"))

    assert result["before"].get("evidence_chain") == 1
    # Completed nodes are not re-run; only the failed node and successors run.
    assert result["after"].get("query_analyzer", 0) == 0
    assert result["after"].get("query_adapter", 0) == 0
    assert result["after"].get("multi_retriever", 0) == 0
    assert result["after"].get("source_evaluator", 0) == 0
    assert result["after"].get("conflict_detector", 0) == 0
    assert result["after"].get("evidence_chain") == 1
    assert result["after"].get("self_reviewer") == 1
    assert result["final_next"] == ()
    assert result["final_confidence"] == "high"
    assert result["events"]


def test_resume_from_real_checkpoint_clarify_task(tmp_path):
    """A run whose graph starts at query_adapter (no query_analyzer node)."""
    result = asyncio.run(_run_interrupted_then_resume(
        CLARIFY_TASK, "clarify-thread", tmp_path / "clarify.db"))

    assert result["before"].get("query_analyzer") is None
    assert result["before"].get("query_adapter") == 1
    assert result["after"].get("query_adapter", 0) == 0
    assert result["after"].get("multi_retriever", 0) == 0
    assert result["after"].get("evidence_chain") == 1
    assert result["after"].get("self_reviewer") == 1
    assert result["final_next"] == ()
