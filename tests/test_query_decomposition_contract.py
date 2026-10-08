"""Default decomposition owns research hints; caller requirements stay authoritative."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import query_analyzer, query_adapter
from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.agents.conclusion_synthesizer import _decision_requirements
from deepchoice.clarify import clarification_agent
from deepchoice.clarify.session_manager import SessionManager
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import WORKFLOW_NODES
from deepchoice.budget_errors import BudgetPersistenceError

QUERY = "Compare Cedar and Maple only for offline import compatibility; do not evaluate throughput or popularity."


async def test_finalize_does_not_invent_frozen_questions_or_call_model(monkeypatch):
    manager = SessionManager()
    sid = manager.create(QUERY)["session_id"]
    model = AsyncMock(side_effect=AssertionError("Finalization must be local"))
    monkeypatch.setattr(clarification_agent, "call_model", model)
    result = await clarification_agent.ClarificationAgent().finalize(manager.get(sid))
    model.assert_not_awaited()
    assert result["payload"]["sub_questions"] == []
    assert result["payload"]["clarified_task"]["query"] == QUERY


@pytest.mark.parametrize("bad", [
    None, [], "not an object", {"sub_questions": "characters"},
    {"sub_questions": ["valid", 3]}, {"sub_questions": ["valid", ""]},
    {"sub_questions": ["q"] * 21}, {"sub_questions": ["q" * 501]},
    {"sub_questions": ["unsafe\u202equestion"]},
    {"sub_questions": ["q" * 500] * 20},
], ids=["null", "array", "string", "question-string", "mixed", "empty", "count", "length", "control", "aggregate"])
async def test_invalid_decomposition_falls_back_atomically_without_new_requirements(monkeypatch, bad):
    model = AsyncMock(return_value=bad)
    monkeypatch.setattr(query_analyzer, "call_model", model)
    state = {"task": {"query": QUERY, "constraints": ["Offline import is required"]}}
    if isinstance(bad, dict) and bad.get("sub_questions") == ["q" * 500] * 20:
        state["task"]["constraints"] = ["c" * 500] * 50
    before = deepcopy(state)
    result = await query_analyzer.QueryAnalyzerAgent().run(state)
    assert state == before
    assert result["sub_questions"] == []
    assert result["constraints"] == state["task"]["constraints"]
    signal = result["quality_signals"][0]
    assert signal["decomposition_status"] == "raw_query_fallback"
    assert signal["fallback_reason"] == "invalid_response"
    assert "dimensions_covered" not in signal and "scene_context" not in result
    model.assert_awaited_once()


async def test_analyzer_keeps_only_relevant_generated_questions_and_actual_scene(monkeypatch):
    model = AsyncMock(return_value={"sub_questions": ["Does Cedar import this format offline?"], "constraints": []})
    monkeypatch.setattr(query_analyzer, "call_model", model)
    task = ResearchRequest(query=QUERY, scene_context="Only offline import is in scope", constraints=["No network"] ).model_dump()
    result = await query_analyzer.QueryAnalyzerAgent().run({"task": task})
    prompt = model.await_args.args[0]
    payload = json.loads(prompt[1]["content"])
    assert payload["request"]["query"] == QUERY
    assert payload["request"]["scene_context"] == task["scene_context"]
    assert "coarse_scene_classification" not in payload
    assert "5 analysis dimensions" not in prompt[0]["content"]
    assert "Minimum 15 Chinese characters" not in prompt[0]["content"]
    assert result["sub_questions"] == ["Does Cedar import this format offline?"]
    assert result["quality_signals"][0]["decomposition_status"] == "derived"
    assert "dimensions_covered" not in result["quality_signals"][0]


@pytest.mark.parametrize("failure", [RuntimeError("private failure"), BudgetPersistenceError("private failure"), asyncio.CancelledError()], ids=["provider", "budget", "cancel"])
async def test_analyzer_fallback_distinguishes_provider_errors_from_authority_and_cancellation(monkeypatch, failure):
    model = AsyncMock(side_effect=failure)
    monkeypatch.setattr(query_analyzer, "call_model", model)
    if isinstance(failure, (BudgetPersistenceError, asyncio.CancelledError)):
        with pytest.raises(type(failure)):
            await query_analyzer.QueryAnalyzerAgent().run({"task": {"query": QUERY}})
    else:
        result = await query_analyzer.QueryAnalyzerAgent().run({"task": {"query": QUERY}})
        assert result["sub_questions"] == []
        assert result["quality_signals"][0]["fallback_reason"] == "model_unavailable"
        assert "private failure" not in str(result)
    model.assert_awaited_once()


@pytest.mark.parametrize("preset", [False, True])
async def test_actual_orchestrator_graph_preserves_caller_questions_and_derived_provenance(monkeypatch, preset):
    manager = SessionManager()
    sid = manager.create(QUERY)["session_id"]
    monkeypatch.setattr(clarification_agent, "call_model", AsyncMock(side_effect=AssertionError("No pre-run model call")))
    final = await clarification_agent.ClarificationAgent().finalize(manager.get(sid))
    task = ResearchRequest(**final["payload"]["clarified_task"], sub_questions=final["payload"]["sub_questions"]).model_dump()
    if preset:
        task["sub_questions"] = ["Caller explicitly asks about compatibility"]
    task["constraints"] = ["Offline import is required"]
    derived = ["Can Cedar read the offline format?"]
    analyze = AsyncMock(return_value={"sub_questions": derived, "constraints": ["Must sustain 100k QPS"]})
    adapt = AsyncMock(return_value={})
    monkeypatch.setattr(query_analyzer, "call_model", analyze)
    monkeypatch.setattr(query_adapter, "call_model", adapt)
    agents = {name: SimpleNamespace(run=AsyncMock(return_value={})) for name in WORKFLOW_NODES}
    agents["query_analyzer"] = query_analyzer.QueryAnalyzerAgent()
    agents["query_adapter"] = query_adapter.QueryAdapterAgent()
    editor = ChiefEditorAgent(task)
    monkeypatch.setattr(editor, "_initialize_agents", lambda: agents)
    result = await editor.run_research_task()
    assert result["task"] == task
    assert result["sub_questions"] == (task["sub_questions"] if preset else derived)
    assert analyze.await_count == (0 if preset else 1)
    adapt.assert_awaited_once()
    requirements, _ = _decision_requirements(task["query"], task["constraints"], result.get("constraints", []), task["sub_questions"], result["sub_questions"])
    assert "Must sustain 100k QPS" not in str(requirements)
    assert any(item["kind"] == "frozen_constraint" for item in requirements)
    assert not any(item["kind"] == "analysis_constraint" for item in requirements)
    question = next(item for item in requirements if item["requirement"] == result["sub_questions"][0])
    assert question["kind"] == ("frozen_sub_question" if preset else "analysis_sub_question")


async def test_default_analyzer_reserves_budget_before_dispatch(tmp_path, monkeypatch):
    from deepchoice.budget import BudgetHardLimits, BudgetExceededError, BudgetResource
    from deepchoice.runtime.context import bind_run_context
    from deepchoice.utils import llm
    from tests.test_phase2c_budget_runtime import _running_budget, _context, _count
    connection, _, manager, _, _ = await _running_budget(tmp_path, limits=BudgetHardLimits(total_tokens=1))
    dispatch = AsyncMock()
    monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=dispatch))))
    try:
        with bind_run_context(_context(manager)), pytest.raises(BudgetExceededError) as caught:
            await query_analyzer.QueryAnalyzerAgent().run({"task": {"query": QUERY}})
        assert caught.value.resource == BudgetResource.TOTAL_TOKENS
        dispatch.assert_not_awaited()
        assert await _count(connection) == 0
    finally:
        await connection.close()


@pytest.mark.parametrize("model_constraints", [["Must sustain 100k QPS"], [], "invalid old field", ["c"] * 51])
async def test_model_constraints_never_add_or_withdraw_user_requirements(monkeypatch, model_constraints):
    questions = ["Can Cedar import the format offline?"]
    model = AsyncMock(return_value={"sub_questions": questions, "constraints": model_constraints})
    monkeypatch.setattr(query_analyzer, "call_model", model)
    state = {"task": {"query": QUERY, "constraints": ["No throughput evaluation"]}}
    result = await query_analyzer.QueryAnalyzerAgent().run(state)
    assert result["sub_questions"] == questions
    assert result["constraints"] == state["task"]["constraints"]
    assert result["constraints"] is not state["task"]["constraints"]


async def test_maximum_valid_question_packet_is_preserved_without_prefix_clipping(monkeypatch):
    questions = [f"{i:02d}" + "问" * 498 for i in range(20)]
    model = AsyncMock(return_value={"sub_questions": questions})
    monkeypatch.setattr(query_analyzer, "call_model", model)
    result = await query_analyzer.QueryAnalyzerAgent().run({"task": {"query": "原" * 4000, "constraints": ["Must preserve all questions"]}})
    assert result["sub_questions"] == questions
    assert result["quality_signals"][0]["sub_question_count"] == 20


async def test_budgeted_analyzer_records_one_call_under_its_real_node_attempt(tmp_path, monkeypatch):
    from deepchoice.budget import BudgetHardLimits, BudgetResource
    from deepchoice.observability import RuntimeTraceRecorder, SQLiteTraceStore
    from deepchoice.persistence import SQLiteTaskRunRepository
    from deepchoice.runtime.context import RunContext, bind_run_context
    from deepchoice.utils import llm
    from tests.test_phase2c_budget_runtime import _running_budget, _Cancellation, _count
    connection, lock, manager, _, clock = await _running_budget(tmp_path, limits=BudgetHardLimits(llm_calls=1))
    try:
        repository = SQLiteTaskRunRepository(connection, lock)
        run = await repository.get_run("run-1")
        stored_task = await repository.get_task("task-1")
        task = stored_task.task.request.model_dump(mode="json")
        trace = RuntimeTraceRecorder(SQLiteTraceStore(connection, lock, clock=clock).bind(
            run_id=run.run_id, execution_epoch=run.execution_epoch, lease_owner="worker"), task_id=run.task_id)
        context = RunContext.from_run_record(run, cancellation=_Cancellation(), trace=trace, budget=manager)
        async def dispatch(**kwargs):
            assert await _count(connection, "WHERE status='reserved'") == 2
            return SimpleNamespace(model="fixture", usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"sub_questions":["Does a support the required format?"],"constraints":["Invented constraint"]}'))])
        create = AsyncMock(side_effect=dispatch)
        monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        editor = ChiefEditorAgent(task, run_manifest=run.manifest)
        with bind_run_context(context):
            result = await editor._timed_node("query_analyzer", query_analyzer.QueryAnalyzerAgent().run)({"task": task})
        create.assert_awaited_once()
        assert result["constraints"] == task["constraints"]
        assert (await manager._usage())[BudgetResource.LLM_CALLS] == 1
        assert result["token_usage"][0]["total_tokens"] == 150
        rows = await (await connection.execute(
            "SELECT n.node_name,n.status,c.status FROM node_attempts n JOIN external_calls c ON c.node_attempt_id=n.node_attempt_id"
        )).fetchall()
        assert [tuple(row) for row in rows] == [("query_analyzer", "succeeded", "succeeded")]
        assert context.manifest_id == editor.run_manifest.manifest_id
    finally:
        await connection.close()
