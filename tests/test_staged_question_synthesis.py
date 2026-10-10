"""Staged synthesis contracts; fixtures show routing, not semantic quality."""
from tests.staged_synthesis_helpers import run_staged
from unittest.mock import AsyncMock, Mock

import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.budget_errors import BudgetPersistenceError
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.utils.question_packet import (
    candidate_mentions, has_multi_candidate_coverage, question_rows,
)

TASK = {"query": "Choose Alpha or Beta under restart constraints?",
        "candidate_techs": ["Alpha", "Beta"],
        "constraints": ["Do not invent durability"],
        "sub_questions": ["What changes after restart?"]}
CHAINS = [
    {"evidence_strength": "moderate", "sources": [{"title": "Alpha guide",
      "url": "https://alpha.example/guide", "snippet": "If writers can wait, Alpha can queue writes. Alpha does not guarantee restart recovery."}]},
    {"evidence_strength": "moderate", "sources": [{"title": "Beta guide",
      "url": "https://beta.example/guide", "snippet": "Beta requires a separate service. If the service fails, results need a durable store."}]},
]


def answer(question_id, ref="B1"):
    return {"decision_analysis": [{"kind": "answer", "option": "", "question_id": question_id,
        "basis_refs": [ref],
        "reasoning": "Conditional judgment based on the stated prerequisite.",
        "assumptions": ["The relevant prerequisite is confirmed."],
        "change_condition": "Reconsider when the prerequisite changes."}]}


def test_only_original_question_rows_are_planned():
    rows = question_rows(TASK["query"], [
        {"id": "C1", "kind": "frozen_constraint", "requirement": "Hard"},
        {"id": "Q1", "kind": "frozen_sub_question", "requirement": "Original"},
        {"id": "Q2", "kind": "analysis_sub_question", "requirement": "Derived"},
    ])
    assert rows == [("R0", TASK["query"]), ("Q1", "Original")]


async def test_durable_stage_answers_each_original_question_with_bound_facts(monkeypatch):
    # The default path must not build an unused legacy prompt or its full bindings.
    unused = Mock(side_effect=AssertionError("legacy preparation on durable path"))
    monkeypatch.setattr(synth, "_summarize_chains", unused)
    monkeypatch.setattr(synth, "_summarize_conflicts", unused)
    monkeypatch.setattr(synth, "SYNTHESIS_PROMPT", Mock(format=unused))
    for helper in ("_normalize_decision_contract", "_usable_evidence_ids", "_validate_winner",
                   "_validate_constraint_fit", "abstain_recommendation"):
        monkeypatch.setattr(synth, helper, unused)
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"],
         "winner": "FORGED"},
        {"decision_analysis": [answer("R0", "B1")["decision_analysis"][0],
                               answer("Q1", "B4")["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
        {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2
    rec = state["final_recommendation"]
    assert rec["winner"] == "context_dependent"
    assert len(rec["source_facts"]) == 2
    assert [row["requirement_ids"] for row in rec["decision_analysis"]] == [["R0"], ["Q1"]]
    assert rec["decision_analysis"][1]["basis"][0]["source_sentences"] == [
        "If the service fails, results need a durable store."]
    assert state["quality_signals"][0]["structure_correction"]["attempted"] == 0
    assert "FORGED" not in str(state)
    selection, judgment = model.await_args_list
    assert selection.kwargs["diagnostic_profile"] == "fact-view-selection-v1"
    assert judgment.kwargs["diagnostic_profile"] == "question-judgment-v2"
    assert '"id":"S1"' in selection.args[0][0]["content"]
    assert "B4: If the service fails" in judgment.args[0][0]["content"]
    assert "User inputs:" in judgment.args[0][0]["content"]
    assert "Sources need not prescribe that measurement" in judgment.args[0][0]["content"]
    assert "Technical facts:" in judgment.args[0][0]["content"]
    assert "R0:" in judgment.args[0][0]["content"] and "Q1:" in judgment.args[0][0]["content"]
    assert all(call.kwargs["seed"] == 0 for call in model.await_args_list)
    unused.assert_not_called()


@pytest.mark.parametrize("kind,option,retained", [("answer", "", True), ("choice", "Beta", False),
    ("answer", "Beta", False), ("design", "", False)])
async def test_one_sided_overall_answer_preserved_without_granting_choice(monkeypatch, kind, option, retained):
    row = answer("R0", "B1")["decision_analysis"][0]
    row.update(kind=kind, option=option)
    model = AsyncMock(side_effect=[{"source_view_ids": ["S2"]}, {"decision_analysis": [row]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
        {"task": TASK, "evidence_chains": CHAINS})
    rec = state["final_recommendation"]
    analyses = rec["decision_analysis"]
    assert bool(analyses) is retained
    if retained:
        assert analyses[0]["requirement_ids"] == ["R0"]
        assert analyses[0]["kind"] == "answer" and analyses[0]["option"] == ""
    assert rec["winner"] == "context_dependent"
    stage = state["quality_signals"][0]["staged_generation"]
    assert stage["r0_withheld_one_sided"] is not retained
    assert stage["rows_selected"] == int(retained)
    assert model.await_count == 2


async def test_subquestion_cannot_create_a_second_choice(monkeypatch):
    choice = answer("Q1", "B3")
    choice["decision_analysis"][0].update(kind="choice", option="Beta")
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [answer("R0", "B1")["decision_analysis"][0],
                               choice["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["R0"]]
    stage = state["quality_signals"][0]["staged_generation"]
    assert stage["rows_received"] == 2 and stage["rows_selected"] == 1
    assert stage["judgment_calls"] == 1
    assert stage["facts_bound"] == 2
    assert stage["rows_rejected_question"] == 1


async def test_invalid_question_output_isolated_and_budget_loss_propagates(monkeypatch):
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [
            answer("Q1", "B1")["decision_analysis"][0],
            {**answer("R0", "B1")["decision_analysis"][0],
             "question_id": ["R0", "Q1"]},

        ]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        BudgetPersistenceError("private budget error")])
    monkeypatch.setattr(synth, "call_model", model)
    with pytest.raises(BudgetPersistenceError):
        await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
            {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2


@pytest.mark.parametrize("title,candidates,expected", [
    ("Bun vs Node.js", ["Bun", "Node.js"], ["Bun", "Node.js"]),
    ("比较Go和Rust", ["Go", "Rust"], ["Go", "Rust"]),
    ("R / C++ / C# / Qt", ["R", "C++", "C#", "Qt"], ["R", "C++", "C#", "Qt"]),
    ("BUN / node.js", ["Bun", "Node.js"], ["Bun", "Node.js"]),
    ("Bunny Golang CR C++++ C## QtWidgets _Bun Bun_", ["Bun", "Go", "R", "C++", "C#", "Qt"], []),
    ("Kafka versus RabbitMQ", ["Apache Kafka", "RabbitMQ"], ["Apache Kafka", "RabbitMQ"]),
    ("甲乙对比丙丁", ["甲乙", "丙丁"], ["甲乙", "丙丁"]),
])
def test_title_mentions_preserve_short_names_and_identifier_boundaries(title, candidates, expected):
    assert candidate_mentions(title, candidates) == expected


async def test_explicit_short_candidate_in_comparison_title_keeps_original_question(monkeypatch):
    task = {**TASK, "query": "Choose Bun or Node.js?", "candidate_techs": ["Bun", "Node.js"]}
    chains = [{"evidence_strength": "moderate", "sources": [{
        "title": "Node.js Compatibility | Bun Docs", "url": "https://bun.example/compat",
        "snippet": "Bun has compatibility limits when using Node.js packages.",
    }]}]
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1"]}, answer("R0", "B1")])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)),
        {"task": task, "evidence_chains": chains})
    rec = state["final_recommendation"]
    assert [row["requirement_ids"] for row in rec["decision_analysis"]] == [["R0"]]
    assert "R0:" in model.await_args_list[1].args[0][0]["content"]
    assert state["quality_signals"][0]["staged_generation"]["r0_withheld_one_sided"] == 0
    assert rec["winner"] == "context_dependent"
    assert rec["source_facts"][0]["status"] == "verified"
    assert rec["decision_analysis"][0]["review_status"] == "human_review_required"
    assert not has_multi_candidate_coverage([{"source_title": "Node.js guide"}], task["candidate_techs"])


async def test_known_conditions_with_empty_extra_assumptions_reach_reviewed_report(monkeypatch):
    import httpx
    from copy import deepcopy
    from deepchoice.agents import self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    task = {"query": "Can Alpha queue writes when writers can wait?", "candidate_techs": ["Alpha", "Beta"],
        "scene_context": "The user confirms queued writes are acceptable; one maintainer.",
        "constraints": ["Queued writes are acceptable", "One maintainer", "Do not invent throughput",
                        "Recovery remains unconfirmed"]}
    original = deepcopy(CHAINS[:1])
    row = answer("R0", "B1")["decision_analysis"][0]
    row.update(assumptions=[], basis_refs=["B1", "B2"], requirement_ids=["R0", "C1", "C2", "C3", "C4"],
        basis=[{"fact_id": "FORGED", "sentence_ids": [99]}],
        reasoning="With the stated tolerance for queued writes, Alpha can be evaluated for queuing. This does not establish restart recovery.")
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1"]},
                                  {"decision_analysis": [row]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = {"task": deepcopy(task), "evidence_chains": deepcopy(original)}
    state.update(await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)), state))
    assert state["final_recommendation"]["decision_analysis"][0]["assumptions"] == []
    assert state["final_recommendation"]["decision_analysis"][0]["requirement_ids"] == ["R0"]
    inventory = state["final_recommendation"]["answer_delivery"]["requirements"]
    assert [inventory[f"C{i}"] for i in range(1, 5)] == task["constraints"]
    assert state["task"] == task and original == CHAINS[:1]
    judgment = model.await_args_list[1].args[0][0]["content"]
    assert task["scene_context"] in judgment and "0-4" in judgment
    assert all(constraint in judgment for constraint in task["constraints"])
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=f"<p>{original[0]['sources'][0]['snippet']}</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await CitationValidatorAgent().run(state))
    reviewer = AsyncMock(return_value={"analysis_reviews": [{"analysis_id": "A1", "action": "keep",
        "source_checks": [["F1", "supports", [1, 2]]]}]})
    monkeypatch.setattr(review, "call_model", reviewer)
    state.update(await review.SelfReviewerAgent().run(state))
    assert all(constraint in str(reviewer.await_args.args[0]) for constraint in task["constraints"])
    final = state["final_recommendation"]
    assert final["source_facts"][0]["status"] == "verified" and final["decision_analysis"][0]["assumptions"] == []
    assert final["winner"] == "context_dependent" and final["action_plan_mode"] == "validation_only"
    assert final["deployment_readiness"] == "unverified"
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert row["reasoning"] in report and "Unconfirmed assumption:" not in report
        assert "semantically" in report or "Lexical" in report
    assert model.await_count == 2 and reviewer.await_count == 1


async def test_no_advertised_basis_skips_judgment_and_keeps_visible_gaps(monkeypatch):
    from copy import deepcopy
    model = AsyncMock(return_value={"source_view_ids": ["S1", "S2"]})
    original = deepcopy(CHAINS)
    monkeypatch.setattr(synth, "call_model", model)
    monkeypatch.setattr(synth, "basis_reference_packet", lambda *_, **__: ("No bound source facts.", {}))
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
        {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 1 and CHAINS == original
    rec = state["final_recommendation"]
    assert len(rec["source_facts"]) == 2 and rec["decision_analysis"] == []
    assert rec["winner"] == "context_dependent"
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    report = FORMAT_RENDERERS["what_why_how"]({"task": TASK, **state})
    assert TASK["query"] in report and TASK["sub_questions"][0] in report
    assert state["quality_signals"][0]["staged_generation"]["judgment_calls"] == 0


@pytest.mark.parametrize("code", ["RUN_LEASE_LOST", "RUNTIME_INSTANCE_LEASE_LOST", "RUN_BUDGET_AUTHORITY_STALE"])
async def test_judgment_authority_loss_never_becomes_empty_success(monkeypatch, code):
    error = RuntimeError("PRIVATE AUTHORITY")
    error.code = code
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1", "S2"]}, error])
    monkeypatch.setattr(synth, "call_model", model)
    with pytest.raises(RuntimeError) as caught:
        await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
            {"task": TASK, "evidence_chains": CHAINS})
    assert caught.value is error and model.await_count == 2


@pytest.mark.parametrize("retained_count", [1, 8])
async def test_late_questions_get_selection_judgment_and_reviewed_report_opportunity(monkeypatch, retained_count):
    """All accepted questions are offered; a stub choosing Q20 is not live coverage proof."""
    import httpx
    from copy import deepcopy
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.agents import self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.agents.report_generator import FORMAT_RENDERERS

    questions = [f"Question {i}: " + "适用条件" * 115 + "?" for i in range(1, 21)]
    task = ResearchRequest(query="Can Alpha queue writes?", candidate_techs=["Alpha"],
                           sub_questions=questions).model_dump(mode="json")
    selected_ids = [f"Q{i}" for i in range(21-retained_count, 21)]
    rows = [answer(key)["decision_analysis"][0] for key in selected_ids]
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1"]}, {"decision_analysis": rows}])
    monkeypatch.setattr(synth, "call_model", model)
    state = {"task": deepcopy(task), "evidence_chains": deepcopy(CHAINS[:1])}
    state.update(await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)), state))
    assert model.await_count == 2
    for call in model.await_args_list:
        prompt = call.args[0][0]["content"]
        assert all(f"Q{i}: {question}" in prompt for i, question in enumerate(questions, 1))
        assert "R0: Can Alpha queue writes?" in prompt
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [[key] for key in selected_ids]
    assert state["quality_signals"][0]["staged_generation"]["questions_planned"] == 21
    assert state["task"] == task
    assert state["evidence_chains"][0]["sources"][0]["snippet"] == CHAINS[0]["sources"][0]["snippet"]

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", AsyncMock(return_value=httpx.Response(
        200, text=CHAINS[0]["sources"][0]["snippet"], headers={"content-type": "text/plain"})))
    state.update(await CitationValidatorAgent().run(state))
    reviewer = AsyncMock(return_value={"analysis_reviews": [
        {"analysis_id": f"A{i}", "action": "keep", "source_checks": [["F1", "supports", [1]]]}
        for i in range(1, retained_count+1)]})
    monkeypatch.setattr(review, "call_model", reviewer)
    state.update(await review.SelfReviewerAgent().run(state))
    assert reviewer.await_count == 1
    rec = state["final_recommendation"]
    assert [row["requirement_ids"] for row in rec["decision_analysis"]] == [[key] for key in selected_ids]
    assert rec["analysis_review"]["retained"] == retained_count
    assert rec["winner"] == "context_dependent" and rec["deployment_readiness"] == "unverified"
    for format_name, render in FORMAT_RENDERERS.items():
        report = render(state)
        assert rows[-1]["reasoning"] in report
        assert questions[-1] in report and questions[0] in report
        assert "Human review required" in report
        if format_name == "comparison_matrix":
            assert f"| {questions[0]} | Unanswered |" in report
            assert f"| {questions[-1]} | Conditional analysis for human review |" in report
        else:
            missing = report.split("Questions without retained analysis", 1)[1]
            assert questions[0] in missing and questions[-1] not in missing


@pytest.mark.parametrize("count", [9])
async def test_more_offered_questions_does_not_expand_answer_output_authority(monkeypatch, count):
    task = {**TASK, "constraints": [f"Maintain boundary {i}" for i in range(50)],
            "sub_questions": [f"Original question {i}?" for i in range(1, 21)]}
    ids = ["R0"] + [f"Q{i}" for i in range(1, 21)]
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [answer(key)["decision_analysis"][0] for key in ids[:count]]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)),
        {"task": task, "evidence_chains": CHAINS})
    assert model.await_count == 2
    assert state["final_recommendation"]["decision_analysis"] == []
    assert state["quality_signals"][0]["staged_generation"]["rows_rejected_limit"] == count
    assert state["final_recommendation"]["answer_delivery"]["requirements"]["Q20"] == task["sub_questions"][-1]


async def test_all_question_context_still_obeys_real_budget_before_model_dispatch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from deepchoice.budget import BudgetHardLimits, BudgetExceededError, BudgetResource
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.runtime.context import bind_run_context
    from deepchoice.agents.orchestrator import ChiefEditorAgent
    from deepchoice.utils import llm
    from tests.test_phase2c_budget_runtime import _running_budget, _context, _count

    task = ResearchRequest(query="技术条件" * 1000, candidate_techs=["Alpha"],
        sub_questions=[f"{i:02d}" + "问题" * 249 for i in range(20)]).model_dump(mode="json")
    chains = [{"evidence_strength": "moderate", "sources": [{
        "title": f"Alpha guide {i}", "url": f"https://source{i}.example/guide",
        "snippet": "Alpha queues writes when writers can wait. " + "Documented condition " * 45 + "."}]} for i in range(24)]
    connection, _, manager, _, _ = await _running_budget(tmp_path, limits=BudgetHardLimits(total_tokens=50000))
    dispatch = AsyncMock()
    monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=dispatch))))
    state = {"task": task, "evidence_chains": chains}
    try:
        node = ChiefEditorAgent(task)._timed_node("source_selection",
            synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).select_sources)
        with bind_run_context(_context(manager)), pytest.raises(BudgetExceededError) as caught:
            await node(state)
        assert caught.value.resource == BudgetResource.TOTAL_TOKENS
        assert caught.value.requested > 50000
        assert caught.value.partial_state["task"] == task
        dispatch.assert_not_awaited()
        assert await _count(connection) == 0
    finally:
        await connection.close()


@pytest.mark.parametrize("constraint_count,outcome", [
    (39, "keep"), (40, "keep"), (50, "keep"),
    (50, "unreachable"), (50, "unsupported"), (50, "withdraw"), (50, "invalid_basis"),
])
async def test_many_requirements_preserve_only_bound_cited_reviewed_analysis(monkeypatch, constraint_count, outcome):
    """Real code + model/fetch stubs exercise delivery, not semantic acceptance."""
    import httpx
    from copy import deepcopy
    from deepchoice.contracts.api import ResearchRequest
    from deepchoice.agents import self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.agents.report_generator import FORMAT_RENDERERS

    task = ResearchRequest(query="Which Alpha option fits?", candidate_techs=["Alpha"],
        constraints=[f"Maintain boundary {i}" for i in range(constraint_count)],
        sub_questions=["What conditions affect the choice?"]).model_dump(mode="json")
    requirements, overflow = synth._decision_requirements(
        task["query"], task["constraints"], [], task["sub_questions"], [])
    assert len(requirements) == constraint_count + 1
    assert overflow is (constraint_count >= 40)
    row = answer("Q1", "B999" if outcome == "invalid_basis" else "B1")["decision_analysis"][0]
    row["reasoning"] = "Evaluate Alpha only when the documented queuing condition is acceptable. Other requirements still need assessment."
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1"]}, {"decision_analysis": [row]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = {"task": deepcopy(task), "evidence_chains": deepcopy(CHAINS[:1])}
    state.update(await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)), state))
    rec = state["final_recommendation"]
    assert model.await_count == 2
    for call in model.await_args_list:
        prompt = call.args[0][0]["content"]
        assert all(f": {text}\n" in prompt for text in task["constraints"])
    assert state["task"] == task and state["evidence_chains"][0]["sources"][0]["snippet"] == CHAINS[0]["sources"][0]["snippet"]
    expected_bound = 0 if outcome == "invalid_basis" else 1
    assert state["quality_signals"][0]["staged_generation"]["rows_selected"] == expected_bound
    assert len(rec["decision_analysis"]) == expected_bound
    inventory = deepcopy(rec["answer_delivery"]["requirements"])
    assert len(inventory) == constraint_count + 2
    assert [inventory[f"C{i}"] for i in range(1, constraint_count + 1)] == task["constraints"]
    assert inventory["R0"] == task["query"] and inventory["Q1"] == task["sub_questions"][0]
    if overflow:
        assert rec["action_plan"] == []
    assert rec["requirement_assessments"] == rec["ranked_options"] == rec["decision_branches"] == []
    for render in FORMAT_RENDERERS.values():
        assert row["reasoning"] not in render(state)  # Binding has no publication authority.

    fetch = AsyncMock(return_value=httpx.Response(200,
        text="An unrelated document about geometry." if outcome == "unsupported" else CHAINS[0]["sources"][0]["snippet"],
        headers={"content-type": "text/plain"}))
    if outcome == "unreachable":
        fetch.side_effect = httpx.ConnectError("PRIVATE_NETWORK_FAILURE")
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await CitationValidatorAgent().run(state))
    for render in FORMAT_RENDERERS.values():
        assert row["reasoning"] not in render(state)  # Citations alone do not approve inference.
    review_row = {"analysis_id": "A1", "action": "withdraw" if outcome == "withdraw" else "keep"}
    if outcome != "withdraw":
        review_row["source_checks"] = [["F1", "supports", [1]]]
    reviewer = AsyncMock(return_value={"analysis_reviews": [review_row]})
    monkeypatch.setattr(review, "call_model", reviewer)
    state.update(await review.SelfReviewerAgent().run(state))
    rec = state["final_recommendation"]
    retained = outcome in {"keep", "unreachable"}
    assert len(rec["decision_analysis"]) == int(retained)
    assert rec["answer_delivery"]["requirements"] == inventory
    assert rec["winner"] == "context_dependent" and rec["confidence"] == "low"
    assert rec["deployment_readiness"] == "unverified"
    assert rec["requirement_assessments"] == rec["ranked_options"] == rec["decision_branches"] == []
    if overflow:
        assert rec["action_plan"] == []
    if outcome in {"keep", "unreachable", "withdraw"}:
        reviewer.assert_awaited_once()
        assert all(text in str(reviewer.await_args.args[0]) for text in task["constraints"])
    for name, render in FORMAT_RENDERERS.items():
        report = render(state)
        assert (row["reasoning"] in report) is retained
        if outcome == "unreachable":
            assert rec["source_facts"][0]["status"] == "unknown"
            assert rec["decision_analysis"][0]["review_status"] == "network_unconfirmed_human_review_required"
            assert "Live source verification was unavailable (unknown)" in report
        assert task["query"] in report and task["sub_questions"][0] in report
        assert "PRIVATE_NETWORK_FAILURE" not in report
        if name == "comparison_matrix":
            label = "Conditional analysis for human review" if retained else "Unanswered"
            assert f'| {task["sub_questions"][0]} | {label} |' in report
        else:
            missing = report.split("Questions without retained analysis", 1)[1]
            assert (task["sub_questions"][0] in missing) is (not retained)


async def test_one_sided_overall_answer_still_rejects_unbound_alternative_after_review(monkeypatch):
    from deepchoice.agents import self_reviewer as review
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    row = answer("R0", "B1")["decision_analysis"][0]
    row.update(reasoning="Beta guarantees restart recovery, so select Beta.", assumptions=[])
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1"]}, {"decision_analysis": [row]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await run_staged(synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)),
        {"task": TASK, "evidence_chains": CHAINS})
    assert len(state["final_recommendation"]["decision_analysis"]) == 1
    reviewer = AsyncMock(return_value={"analysis_reviews": [{"analysis_id": "A1", "action": "keep",
        "source_checks": [["F1", "supports", [1, 2]]]}]})
    monkeypatch.setattr(review, "call_model", reviewer)
    state.update(await review.SelfReviewerAgent().run(state))
    assert reviewer.await_count >= 1
    assert state["final_recommendation"]["decision_analysis"] == []
    assert state["final_recommendation"]["winner"] == "context_dependent"
    for render in FORMAT_RENDERERS.values():
        assert row["reasoning"] not in render(state)
