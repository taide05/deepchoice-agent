"""Staged synthesis contracts; fixtures show routing, not semantic quality."""
from unittest.mock import AsyncMock, Mock

import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.budget_errors import BudgetPersistenceError
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.utils.question_packet import (
    bounded_fact_packet, candidate_mentions, has_multi_candidate_coverage, question_rows,
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


def test_packet_keeps_complete_sentence_addresses_and_title_tags():
    facts = [{"id": "F1", "source_title": "Alpha guide", "saved_text": CHAINS[0]["sources"][0]["snippet"]},
             {"id": "F2", "source_title": "Beta guide", "saved_text": CHAINS[1]["sources"][0]["snippet"]}]
    packet = bounded_fact_packet(facts, TASK["candidate_techs"])
    assert "F1 | title: Alpha guide | title mentions: ['Alpha']" in packet
    assert "s1: If writers can wait" in packet
    assert "s2: Alpha does not guarantee restart recovery" in packet
    assert "s2: If the service fails" in packet
    assert has_multi_candidate_coverage(facts, TASK["candidate_techs"])
    assert not has_multi_candidate_coverage(facts[1:], TASK["candidate_techs"])
    assert candidate_mentions("Alpha vs Beta", TASK["candidate_techs"]) == ["Alpha", "Beta"]
    assert has_multi_candidate_coverage([{"source_title": "Unclassified comparison"}], TASK["candidate_techs"])



def test_packet_marks_separate_passages_without_changing_sentence_addresses():
    first = "If writers cannot queue, a server database is appropriate."
    second = "A local database needs no configuration or maintenance."
    fact = {"id": "F1", "source_title": "Alpha guide",
            "saved_text": first + " " + second,
            "saved_passages": [first, second]}
    packet = bounded_fact_packet([fact], TASK["candidate_techs"])
    assert "Passage 1/2 (same source, separate location):" in packet
    assert "Passage 2/2 (same source, separate location):" in packet
    assert f"s1: {first}" in packet and f"s2: {second}" in packet
    assert packet.index(f"s1: {first}") < packet.index("Passage 2/2") < packet.index(f"s2: {second}")
    invalid = {**fact, "saved_passages": [first, first]}
    assert bounded_fact_packet([invalid], TASK["candidate_techs"]) == "No bound source facts."

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
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
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
    assert "R0:" in judgment.args[0][0]["content"] and "Q1:" in judgment.args[0][0]["content"]
    assert all(call.kwargs["seed"] == 0 for call in model.await_args_list)
    unused.assert_not_called()


async def test_one_sided_facts_withhold_r0_but_allow_bounded_specific_answer(monkeypatch):
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S2"]}, answer("Q1", "B1")])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]
    assert "R0:" not in model.await_args_list[1].args[0][0]["content"]


async def test_subquestion_cannot_create_a_second_choice(monkeypatch):
    choice = answer("Q1", "B3")
    choice["decision_analysis"][0].update(kind="choice", option="Beta")
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [answer("R0", "B1")["decision_analysis"][0],
                               choice["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["R0"]]
    stage = state["quality_signals"][0]["staged_generation"]
    assert stage["rows_received"] == 2 and stage["rows_selected"] == 1
    assert stage["judgment_calls"] == 1
    assert stage["facts_received"] == 2
    assert stage["rows_rejected_question"] == 1


async def test_malformed_question_id_cannot_crash_or_enter_output(monkeypatch):
    malformed = answer("R0", "B1")["decision_analysis"][0]
    malformed["question_id"] = {"not": "an ID"}
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [malformed, answer("Q1", "B3")["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]


async def test_invalid_question_output_isolated_and_budget_loss_propagates(monkeypatch):
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [
            answer("Q1", "B1")["decision_analysis"][0],
            {**answer("R0", "B1")["decision_analysis"][0],
             "question_id": ["R0", "Q1"]},

        ]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1", "S2"]},
        BudgetPersistenceError("private budget error")])
    monkeypatch.setattr(synth, "call_model", model)
    with pytest.raises(BudgetPersistenceError):
        await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
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
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(
        {"task": task, "evidence_chains": chains})
    rec = state["final_recommendation"]
    assert [row["requirement_ids"] for row in rec["decision_analysis"]] == [["R0"]]
    assert "R0:" in model.await_args_list[1].args[0][0]["content"]
    assert state["quality_signals"][0]["staged_generation"]["r0_withheld_one_sided"] == 0
    assert rec["winner"] == "context_dependent"
    assert rec["source_facts"][0]["status"] == "unknown"
    assert rec["decision_analysis"][0]["review_status"] == "not_checked"
    assert not has_multi_candidate_coverage([{"source_title": "Node.js guide"}], task["candidate_techs"])


async def test_known_conditions_with_empty_extra_assumptions_reach_reviewed_report(monkeypatch):
    import httpx
    from copy import deepcopy
    from deepchoice.agents import self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    task = {"query": "Can Alpha queue writes when writers can wait?", "candidate_techs": ["Alpha"],
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
    state.update(await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(state))
    assert state["final_recommendation"]["decision_analysis"][0]["assumptions"] == []
    assert state["final_recommendation"]["decision_analysis"][0]["requirement_ids"] == ["R0"]
    inventory = state["final_recommendation"]["answer_delivery"]["requirements"]
    assert [inventory[f"C{i}"] for i in range(1, 5)] == task["constraints"]
    assert state["task"] == task and state["evidence_chains"] == original
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
    monkeypatch.setattr(synth, "basis_reference_packet", lambda *_: ("No bound source facts.", {}))
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
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
        await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
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
    state.update(await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(state))
    assert model.await_count == 2
    for call in model.await_args_list:
        prompt = call.args[0][0]["content"]
        assert all(f"Q{i}: {question}" in prompt for i, question in enumerate(questions, 1))
        assert "R0: Can Alpha queue writes?" in prompt
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [[key] for key in selected_ids]
    assert state["quality_signals"][0]["staged_generation"]["questions_planned"] == 21
    assert state["task"] == task
    assert state["evidence_chains"] == CHAINS[:1]

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


@pytest.mark.parametrize("count", [9, 21])
async def test_more_offered_questions_does_not_expand_answer_output_authority(monkeypatch, count):
    task = {**TASK, "sub_questions": [f"Original question {i}?" for i in range(1, 21)]}
    ids = ["R0"] + [f"Q{i}" for i in range(1, 21)]
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1", "S2"]},
        {"decision_analysis": [answer(key)["decision_analysis"][0] for key in ids[:count]]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(
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
    connection, _, manager, _, _ = await _running_budget(tmp_path, limits=BudgetHardLimits(total_tokens=60000))
    dispatch = AsyncMock()
    monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=dispatch))))
    state = {"task": task, "evidence_chains": chains}
    try:
        node = ChiefEditorAgent(task)._timed_node("conclusion_synthesizer",
            synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run)
        with bind_run_context(_context(manager)), pytest.raises(BudgetExceededError) as caught:
            await node(state)
        assert caught.value.resource == BudgetResource.TOTAL_TOKENS
        assert caught.value.requested > 60000
        assert caught.value.partial_state["task"] == task
        dispatch.assert_not_awaited()
        assert await _count(connection) == 0
    finally:
        await connection.close()
