"""Bounded structural correction through synthesis and the existing citation gate."""
import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.budget_errors import BudgetPersistenceError, StaleBudgetAuthorityError
from deepchoice.persistence.repository import RunLeaseLostError
from deepchoice.runtime.instance_guard import RuntimeInstanceLeaseLostError
from deepchoice.utils.decision_analysis import inspect_synthesis_bindings
from deepchoice.utils.decision_contract import restrict_recommendation


TASK = {"query": "How does recovery work?", "candidate_techs": ["ExampleQueue"],
        "constraints": ["No silent task loss"], "sub_questions": ["What happens after restart?"]}
SNIPPET = "Recovery replays tasks from a durable journal after restart."
CHAINS = [{"sources": [{"title": "Recovery", "url": "https://example.org/recovery", "snippet": SNIPPET}]}]
REQS = [{"id": "Q1", "kind": "frozen_sub_question", "requirement": TASK["sub_questions"][0]}]


def response():
    return {"winner": "context_dependent", "winner_rationale": "", "recommendation": "",
            "decision_basis_version": "constraint-aware-v1", "requirement_assessments": [],
            "decision_branches": [], "action_plan": [], "ranked_options": [], "trade_offs": [],
            "evidence_summary": "", "confidence": "low", "confidence_rationale": "",
            "unresolved_questions": [], "scene_fit_note": "",
            "source_facts": [{"id": "F1", "evidence_id": 1}],
            "decision_analysis": [{"kind": "answer", "option": "ExampleQueue",
                "basis": [{"fact_id": "F1", "sentence_ids": [1]}], "requirement_ids": ["Q1"], "reasoning": "FIRST_PRIVATE_REASON",
                "assumptions": ["A durable journal is available."],
                "change_condition": "Reconsider if the journal cannot be read."}]}


def overflowing():
    value = response()
    value["source_facts"] = [{"id": f"F{i}", "evidence_id": 1} for i in range(1, 7)]
    return value


@pytest.mark.parametrize("source_ok", [True, False])
async def test_corrected_response_still_requires_citations_and_cannot_gain_authority(monkeypatch, source_ok):
    first, revised = overflowing(), response()
    revised["decision_analysis"][0]["reasoning"] = "SECOND_REVIEWABLE_REASON"
    model = AsyncMock(side_effect=[first, revised])
    monkeypatch.setattr(synth, "call_model", model)
    fetch = AsyncMock(return_value=httpx.Response(200 if source_ok else 503, text=SNIPPET,
        headers={"content-type": "text/plain"}, request=httpx.Request("GET", "https://example.org/recovery")))
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    first["answer_contract"] = "question-analysis-v1"
    revised["answer_contract"] = "question-analysis-v1"
    # The compatibility path retains its one structural correction. Durable
    # runs use the staged source/question path covered separately.
    state = {"task": deepcopy(TASK), "evidence_chains": deepcopy(CHAINS)}
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    assert model.await_count == 2
    initial_call, corrective_call = model.await_args_list
    assert initial_call.kwargs == corrective_call.kwargs
    assert corrective_call.kwargs["seed"] == initial_call.kwargs["seed"] == 0
    assert corrective_call.kwargs["timeout"] == initial_call.kwargs["timeout"]
    assert corrective_call.args[0][0] == initial_call.args[0][0]
    assert "FIRST_PRIVATE_REASON" not in json.dumps(corrective_call.args)
    feedback = corrective_call.args[0][-1]["content"]
    assert '"facts_item_limit": 1' in feedback
    assert '"eligible_source_numbers": [1]' in feedback
    assert '"original_requirement_ids": ["C1", "Q1", "R0"]' in feedback
    signal = state["quality_signals"][0]["structure_correction"]
    assert signal["initial"]["source_facts_received"] == 6
    assert signal["initial"]["errors"] == {"facts_item_limit": 1}
    assert signal["attempted"] == 1 and signal["outcome"] == "corrected"
    assert "PRIVATE" not in json.dumps(signal) and "REVIEWABLE" not in json.dumps(signal)
    assert first == {**overflowing(), "answer_contract": "question-analysis-v1"}  # no mutation
    assert state["final_recommendation"]["source_facts"][0]["status"] == "unknown"
    state.update(await CitationValidatorAgent().run(state))
    rec = state["final_recommendation"]
    # A row whose only source could not be verified is retained as advisory
    # instead of being deleted; it is still excluded from the rendered report.
    assert len(rec["decision_analysis"]) == 1
    if source_ok:
        assert rec["decision_analysis"][0]["review_status"] == "human_review_required"
    else:
        assert rec["decision_analysis"][0]["review_status"] == "advisory_unreviewed"
    assert rec["winner"] == "context_dependent"
    assert rec["deployment_readiness"] == "unverified" and rec["action_plan_mode"] == "validation_only"
    assert "decision_analysis" not in restrict_recommendation(rec, TASK["query"])


@pytest.mark.parametrize("kind", ["valid", "empty", "legacy"])
async def test_valid_empty_or_legacy_output_does_not_trigger_correction(monkeypatch, kind):
    payload = response()
    if kind == "empty":
        payload.update(source_facts=[], decision_analysis=[])
    elif kind == "legacy":
        payload.pop("source_facts")
        payload.pop("decision_analysis")
    model = AsyncMock(return_value=payload)
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": CHAINS})
    model.assert_awaited_once()
    assert state["quality_signals"][0]["structure_correction"]["outcome"] == "not_needed"


@pytest.mark.parametrize("second", ["invalid", "incomplete", "service_error"])
async def test_failed_correction_preserves_original_bound_answer_without_merging(monkeypatch, second):
    first = response()
    first["source_facts"].append({"id": "F2", "evidence_id": 99})
    revised = response()
    revised["decision_analysis"][0]["reasoning"] = "SECOND_UNUSABLE_REASON"
    if second == "invalid":
        revised["decision_analysis"][0]["requirement_ids"] = ["A1"]
    elif second == "incomplete":
        revised.pop("winner")
    else:
        revised = OSError("PRIVATE_ERROR")
    model = AsyncMock(side_effect=[first, revised])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2
    assert state["final_recommendation"]["decision_analysis"][0]["reasoning"] == "FIRST_PRIVATE_REASON"
    assert "SECOND_UNUSABLE_REASON" not in json.dumps(state)
    signal = state["quality_signals"][0]["structure_correction"]
    assert signal["outcome"] == ("provider_error" if second == "service_error" else "invalid")
    assert "PRIVATE_ERROR" not in json.dumps(signal)


@pytest.mark.parametrize("error", [BudgetPersistenceError("private"), StaleBudgetAuthorityError("private"),
    RunLeaseLostError("private"), RuntimeInstanceLeaseLostError("private"), asyncio.CancelledError()])
@pytest.mark.parametrize("call_index", [1, 2])
async def test_authority_loss_and_cancellation_propagate_without_further_generation(monkeypatch, error, call_index):
    model = AsyncMock(side_effect=([overflowing()] if call_index == 2 else []) + [error])
    monkeypatch.setattr(synth, "call_model", model)
    with pytest.raises(type(error)):
        await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == call_index


@pytest.mark.parametrize("bad", ["duplicate", "bool_id", "null_facts", "null_analysis", "missing_fact", "overflow_analysis"])
def test_binding_inspection_reuses_existing_contract(bad):
    rec = response()
    if bad == "duplicate": rec["source_facts"] *= 2
    elif bad == "bool_id": rec["source_facts"][0]["evidence_id"] = True
    elif bad == "null_facts": rec["source_facts"] = None
    elif bad == "null_analysis": rec["decision_analysis"] = None
    elif bad == "missing_fact": rec["decision_analysis"][0]["basis"][0]["fact_id"] = "F99"
    else: rec["decision_analysis"] *= 9
    _, diagnostic = inspect_synthesis_bindings(rec, CHAINS, REQS, TASK["candidate_techs"], TASK["query"])
    assert diagnostic["errors"]
    assert "FIRST_PRIVATE_REASON" not in json.dumps(diagnostic)


async def test_correction_feedback_excludes_derived_questions(monkeypatch):
    model = AsyncMock(side_effect=[overflowing(), response()])
    monkeypatch.setattr(synth, "call_model", model)
    await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": CHAINS,
        "sub_questions": [TASK["sub_questions"][0], "A derived question from the analyzer"]})
    assert model.await_count == 2
    feedback = model.await_args_list[1].args[0][-1]["content"]
    assert '"original_requirement_ids": ["C1", "Q1", "R0"]' in feedback
    assert "Q2" not in feedback


async def test_two_synthesis_attempts_keep_full_evidence_within_observed_reservation_margin(monkeypatch):
    # Representative 14-source input; this is a byte-reservation regression, not a
    # guarantee for all workloads or a model-quality assertion. No source is clipped.
    chains = []
    for number in range(14):
        snippet = ("The documented mechanism has explicit prerequisites and bounded failure conditions. " * 9
                   + f"Final prerequisite for source {number}: validate the actual operating conditions.")
        chains.append({"evidence_strength": "moderate", "sources": [{
            "title": f"Mechanism {number}", "url": f"https://example.org/source-{number}", "snippet": snippet}]})
    model = AsyncMock(side_effect=[overflowing(), response()])
    monkeypatch.setattr(synth, "call_model", model)
    await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": chains})
    assert model.await_count == 2
    for call in model.await_args_list:
        messages = call.args[0]
        for chain in chains:
            # Numbering may add sentence labels, but every original sentence must remain.
            from deepchoice.citations.verifier import _split_sentences
            for sentence in _split_sentences(chain["sources"][0]["snippet"]):
                assert sentence in messages[0]["content"]
        reserved = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode()) + 4096
        assert reserved < 40267  # Remaining capacity at the recorded correction refusal.
    assert model.await_args_list[1].args[0][0] == model.await_args_list[0].args[0][0]
