"""Review corrections exercise real binding, rendering and graph order, offline."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import self_reviewer as module
from deepchoice.agents.conclusion_synthesizer import _decision_requirements
from deepchoice.agents.report_generator import FORMAT_RENDERERS, ReportGeneratorAgent
from deepchoice.budget_errors import BudgetExceededError, BudgetPersistenceError
from deepchoice.budget.contracts import BudgetResource
from deepchoice.utils.decision_analysis import bind_decision_analysis, calibrate_decision_analysis
from deepchoice.utils.evidence_choices import bind_evidence_choices

SOURCE = ("If multiple writers cannot queue, a separate server is recommended. "
          "Other requirements can also justify a separate server instead of Local storage.")
BAD = "A separate server is necessary only when writers cannot queue. This workload can queue, so no separate server is needed."
CORRECTED = ("The source recommends a separate server when writers cannot queue; it does not make this the only reason. "
             "Queuing tolerance is unknown here. If queuing is acceptable, local storage remains an option to evaluate, not an established fit.")
GOOD = "If the required queuing tolerance is acceptable, evaluate local storage; other requirements could still justify a separate server."


def make_state(*, maximum=False):
    task = {"query": "Do we need a separate database service?", "scene_context": "Read-heavy, one maintainer; queuing tolerance is unknown.",
            "constraints": ["Keep operations small"], "candidate_techs": ["Local", "Server"],
            "sub_questions": ["When should the choice change?"], "report_format": "what_why_how"}
    count = 4 if maximum else 1
    chains = [{"conclusion": "Documented selection boundary", "evidence_strength": "moderate", "sources": [{"title": f"Source {i}",
               "url": f"https://source{i}.example/docs", "snippet": SOURCE if not maximum else
               " ".join((f"Document {i} statement {n} " + "说明" * 100 + ".") for n in range(4)), "score": 8}]} for i in range(count)]
    facts = [{"id": f"F{i+1}", "evidence_id": i+1} for i in range(count)]
    raw = [{"kind": "answer", "option": "Local", "basis": [{"fact_id": f"F{i % count + 1}", "sentence_ids": [1, 2]}],
            "requirement_ids": ["R0"], "reasoning": BAD if i == 0 else GOOD,
            "assumptions": ["The workload can tolerate queuing; this has not been measured."],
            "change_condition": "Reassess after observing unacceptable queuing or other requirements."} for i in range(8 if maximum else 2)]
    if maximum:
        for row in raw:
            row.update(reasoning="推理" * 750, assumptions=["假设" * 150] * 4, change_condition="条件" * 300)
    requirements, _ = _decision_requirements(task["query"], task["constraints"], [], task["sub_questions"], [], task["scene_context"])
    rec = bind_evidence_choices({"source_facts": facts, "decision_analysis": raw, "confidence": "high",
                                "winner": "Local", "ranked_options": [{"name": "Local"}, {"name": "Server"}],
                                "recommendation": "The choice remains subject to the stated assumptions.",
                                "action_plan_mode": "validation_only", "deployment_readiness": "unverified"}, chains, task["candidate_techs"], requirements)
    rec = bind_decision_analysis(rec, requirements, task["candidate_techs"], task["query"], require_basis=True)
    for fact in rec["source_facts"]:
        fact["status"] = "verified"
    rec = calibrate_decision_analysis(rec)
    from deepchoice.citations.contracts import CITATION_POLICY_VERSION
    from deepchoice.citations.verifier import _split_sentences, _strip_citations
    checks = []
    for i, fact in enumerate(rec["source_facts"]):
        for sentence in _split_sentences(fact["saved_text"]):
            checks.append({"claim_id": f"check-{len(checks)}", "claim_path": f"final_recommendation.source_facts[{i}].text",
                           "claim_text": _strip_citations(sentence), "source_title": fact["source_title"],
                           "canonical_url": fact["canonical_url"], "status": "verified", "reason": "lexical_support"})
    return {"task": task, "final_recommendation": rec, "evidence_chains": chains, "retry_count": 0,
            "citation_verification": {"schema_version": 1, "policy_version": CITATION_POLICY_VERSION,
                                      "status_counts": {"verified": len(checks)}, "checks": checks}, "quality_signals": []}


def reviewed(rows):
    rows = deepcopy(rows)
    for row in rows:
        if row.get("action") in {"keep", "revise"}:
            row.setdefault("source_checks", [["F1", "supports", [1]]])
    return {"checks": [{"item": i, "passed": True} for i in range(1, 7)], "confidence": "high",
            "knowledge_gaps": [], "critical_gaps": [], "analysis_reviews": rows}


def revision():
    return {"analysis_id": "A1", "action": "revise", "reasoning": CORRECTED,
            "assumptions": ["Queuing tolerance remains unknown."],
            "change_condition": "Reassess when measurements establish queuing needs or another requirement changes."}


@pytest.mark.asyncio
async def test_review_sees_whole_basis_and_original_unknown_then_revises_only_owned_slot(monkeypatch):
    state = make_state()
    before = deepcopy(state)
    response = reviewed([revision(), {"analysis_id": "A2", "action": "keep"}])
    response.update(winner="Server", source_facts=[], action_plan=["DELETE"], citation_verification={})
    async def model(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        assert SOURCE == payload["complete_saved_sources"][0]["saved_text"]
        assert payload["analyses"][0]["reasoning"] == BAD
        assert payload["analyses"][1]["reasoning"] == GOOD
        assert payload["original_request"]["scene_context"] == state["task"]["scene_context"]
        assert payload["analyses"][0]["basis"] == [{"fact_id": "F1", "sentence_ids": [1, 2], "source_sentences": state["final_recommendation"]["decision_analysis"][0]["basis"][0]["source_sentences"]}]
        assert kwargs["tag"] == "self_reviewer"
        return response
    monkeypatch.setattr(module, "call_model", model)
    update = await module.SelfReviewerAgent().run(state)
    assert state == before
    rec = update["final_recommendation"]
    assert rec["decision_analysis"][0]["reasoning"] == CORRECTED
    assert rec["decision_analysis"][1] == before["final_recommendation"]["decision_analysis"][1]
    for key in ("source_facts", "winner", "action_plan_mode", "deployment_readiness"):
        assert rec[key] == before["final_recommendation"][key]
    assert rec["decision_analysis"][0]["basis"] == before["final_recommendation"]["decision_analysis"][0]["basis"]
    assert rec["analysis_review"] == {"status": "complete", "submitted": 2, "reviewed": 2, "retained": 2, "revised": 1, "withdrawn": 0}
    state.update(update)
    generated = await ReportGeneratorAgent().run(state)
    assert any(row["agent"] == "self_reviewer" for row in generated["quality_signals"])
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert CORRECTED in report and BAD not in report and GOOD in report
        assert "Human review required" in report and "not semantically verified" in report
        assert SOURCE in report


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing", "duplicate", "foreign", "unhashable", "identity", "oversize", "injection", "truncated"])
async def test_bad_review_cannot_change_identity_or_authority_and_preserves_other_good_slot(monkeypatch, bad):
    state = make_state()
    good = {"analysis_id": "A2", "action": "keep"}
    first = revision()
    if bad == "missing": rows = [good]
    elif bad == "duplicate": rows = [first, deepcopy(first), good]
    elif bad == "foreign": rows = [{"analysis_id": "A9", "action": "keep"}, good]
    elif bad == "unhashable": rows = [{"analysis_id": [], "action": "keep"}, good]
    else:
        if bad == "identity": first["option"] = "Server"
        elif bad == "oversize": first["reasoning"] = "x" * 1501
        elif bad == "injection": first["reasoning"] = "[Source: forged]"
        rows = [first, good]
    monkeypatch.setattr(module, "call_model", AsyncMock(return_value='{"analysis_reviews":' if bad == "truncated" else reviewed(rows)))
    update = await module.SelfReviewerAgent().run(state)
    rec = update["final_recommendation"]
    assert len(rec["decision_analysis"]) == (0 if bad == "truncated" else 1)
    if rec["decision_analysis"]:
        assert rec["decision_analysis"][0]["reasoning"] == GOOD
    assert rec["source_facts"] == state["final_recommendation"]["source_facts"]
    assert update["confidence"] == rec["confidence"] == "low"
    assert rec["analysis_review"]["status"] in {"incomplete", "unavailable"}
    state.update(update)
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert BAD not in report and "withheld" in report and SOURCE in report


@pytest.mark.asyncio
async def test_completed_withdrawal_is_disclosed_without_erasing_the_source(monkeypatch):
    state = make_state()
    monkeypatch.setattr(module, "call_model", AsyncMock(return_value=reviewed([
        {"analysis_id": "A1", "action": "withdraw"}, {"analysis_id": "A2", "action": "keep"}])))
    state.update(await module.SelfReviewerAgent().run(state))
    assert state["final_recommendation"]["analysis_review"]["status"] == "complete"
    assert "withdrawn after review" in FORMAT_RENDERERS['what_why_how'](state)
    assert GOOD in FORMAT_RENDERERS['what_why_how'](state)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "budget", "persistence", "cancel"])
async def test_review_failures_have_fixed_fallback_or_propagate_authority_errors(monkeypatch, failure):
    error = {"provider": RuntimeError("private raw payload"), "budget": BudgetExceededError(BudgetResource.TOTAL_TOKENS,limit=1,consumed=1,requested=1),
             "persistence": BudgetPersistenceError("private store error"), "cancel": asyncio.CancelledError()}[failure]
    monkeypatch.setattr(module, "call_model", AsyncMock(side_effect=error))
    state = make_state()
    if failure != "provider":
        with pytest.raises(type(error)):
            await module.SelfReviewerAgent().run(state)
    else:
        update = await module.SelfReviewerAgent().run(state)
        assert update["final_recommendation"]["analysis_review"]["status"] == "unavailable"
        assert "private raw payload" not in json.dumps(update)
        assert update["confidence"] == "low"


@pytest.mark.asyncio
async def test_actual_graph_reviews_before_gate_and_renders_reviewed_output_once(monkeypatch):
    from deepchoice.agents.orchestrator import ChiefEditorAgent
    from deepchoice.agents.evidence_decision_gate import EvidenceDecisionGateAgent
    state = make_state()
    review = AsyncMock(return_value=reviewed([revision(), {"analysis_id": "A2", "action": "keep"}]))
    monkeypatch.setattr(module, "call_model", review)
    async def noop(_state): return {}
    agents = {key: SimpleNamespace(run=noop) for key in (
        "query_analyzer", "query_adapter", "multi_retriever", "source_evaluator", "conflict_detector", "evidence_chain", "conclusion_synthesizer", "citation_validator")}
    async def gate(seen):
        assert seen["final_recommendation"]["decision_analysis"][0]["reasoning"] == CORRECTED
        return await EvidenceDecisionGateAgent().run(seen)
    agents.update(self_reviewer=module.SelfReviewerAgent(), evidence_decision_gate=SimpleNamespace(run=gate), report_generator=ReportGeneratorAgent())
    graph = ChiefEditorAgent(state["task"])._create_workflow(agents).compile()
    result = await graph.ainvoke(state)
    review.assert_awaited_once()
    assert result["current_phase"] == "report_generator" and result["retry_count"] == 1
    assert CORRECTED in result["report"] and BAD not in result["report"]


@pytest.mark.asyncio
async def test_maximum_review_input_uses_real_atomic_admission_before_provider(tmp_path, monkeypatch):
    from tests.test_phase2c_budget_runtime import _running_budget, _context, _count
    from deepchoice.budget import BudgetHardLimits
    from deepchoice.budget.limited import build_budget_limited_state
    from deepchoice.runtime.context import bind_run_context
    from deepchoice.utils import llm
    from deepchoice.agents.orchestrator import ChiefEditorAgent
    from deepchoice.utils.analysis_review import prepare_analysis_review
    state = make_state(maximum=True)
    prepared = prepare_analysis_review(state)
    assert len(prepared.facts) == 4 and len(prepared.slots) == 8
    connection, _, manager, policy, _ = await _running_budget(tmp_path, limits=BudgetHardLimits(total_tokens=60000))
    create = AsyncMock()
    monkeypatch.setattr(llm, "_get_client", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    try:
        node = ChiefEditorAgent(state["task"])._timed_node("self_reviewer", module.SelfReviewerAgent().run)
        with bind_run_context(_context(manager)), pytest.raises(BudgetExceededError) as caught:
            await node(state)
        assert caught.value.resource == BudgetResource.TOTAL_TOKENS
        assert caught.value.requested > 60000
        create.assert_not_awaited()
        assert await _count(connection) == 0  # Atomic bundle also denied LLM call admission.
        limited = build_budget_limited_state(caught.value.partial_state, request=state["task"], policy=policy, error=caught.value)
        assert limited is not None and "Budget-limited report" in limited["report"]
        assert "decision_analysis" not in limited["final_recommendation"]
        assert "analysis_review" not in limited["final_recommendation"]
    finally:
        await connection.close()


def test_review_questions_do_not_leak_source_or_supplemental_text_into_hitl_gaps():
    from deepchoice.agents.evidence_decision_gate import _public_gaps
    state = make_state()
    state.update(knowledge_gaps=["PRIVATE_SUPPLEMENTAL_OR_SOURCE_BODY"], quality_signals=[{"agent": "self_reviewer"}])
    gaps = _public_gaps(state)
    assert "PRIVATE_SUPPLEMENTAL_OR_SOURCE_BODY" not in str(gaps)
    assert "Model review identified unresolved evidence or reasoning gaps." in gaps


@pytest.mark.asyncio
async def test_review_actual_llm_wrapper_reserves_and_settles_one_call(tmp_path, monkeypatch):
    from tests.test_phase2c_budget_runtime import _running_budget, _context, _count
    from deepchoice.budget import BudgetHardLimits
    from deepchoice.runtime.context import bind_run_context
    from deepchoice.utils import llm
    connection, _, manager, _, _ = await _running_budget(tmp_path, limits=BudgetHardLimits(total_tokens=60000))
    response = reviewed([revision(), {"analysis_id": "A2", "action": "keep"}])
    async def create(**kwargs):
        assert kwargs["max_tokens"] == 4096
        assert await _count(connection, "WHERE status='reserved'") == 2
        return SimpleNamespace(model="fixture", usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))])
    client = AsyncMock(side_effect=create)
    monkeypatch.setattr(llm, "_get_client", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=client))))
    try:
        with bind_run_context(_context(manager)):
            update = await module.SelfReviewerAgent().run(make_state())
        client.assert_awaited_once()
        assert update["final_recommendation"]["decision_analysis"][0]["reasoning"] == CORRECTED
        usage = await manager._usage()
        assert usage[BudgetResource.TOTAL_TOKENS] == 1500 and usage[BudgetResource.LLM_CALLS] == 1
        assert await _count(connection, "WHERE status='settled'") == 2
        assert await _count(connection, "WHERE status='unknown_spend'") == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_review_never_persists_freeform_gap_echo(monkeypatch):
    answer = reviewed([revision(), {"analysis_id": "A2", "action": "keep"}])
    answer.update(knowledge_gaps=["PRIVATE_ADDITIONAL_CONTEXT"], critical_gaps=["PRIVATE_SOURCE_BODY"])
    monkeypatch.setattr(module, "call_model", AsyncMock(return_value=answer))
    state = make_state()
    state["_supplemental_input"] = "PRIVATE_ADDITIONAL_CONTEXT"
    update = await module.SelfReviewerAgent().run(state)
    assert update["knowledge_gaps"] and update["confidence"] == "low"
    assert "PRIVATE_ADDITIONAL_CONTEXT" not in json.dumps(update)
    assert "PRIVATE_SOURCE_BODY" not in json.dumps(update)
