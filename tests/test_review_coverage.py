"""Executable coverage and attribution boundaries; no real model quality claim."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import self_reviewer as review
from deepchoice.agents.conclusion_synthesizer import _decision_requirements
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.citations.verifier import _extract_claims
from deepchoice.utils.analysis_review import prepare_analysis_review, analysis_review_input
from tests.test_self_review import make_state, reviewed


def requirement_state(count=1):
    state = make_state()
    state["task"]["constraints"] = [f"Constraint {i}" for i in range(count)]
    requirements, _ = _decision_requirements(state["task"]["query"], state["task"]["constraints"], [], [], [], state["task"]["scene_context"])
    requirements = [row for row in requirements if row["kind"] == "frozen_constraint"]
    rec = state["final_recommendation"]
    rec["decision_analysis"] = []
    rec["requirement_assessments"] = []
    for index, requirement in enumerate(requirements):
        text = "Local storage may be evaluated if other requirements allow it. [Source: Source 0]"
        rec["requirement_assessments"].append({"id": requirement["id"], "requirement": requirement["requirement"],
            "status": "unknown", "explanation": "Unknown", "evidence_ids": [], "provisional_explanation": text})
        claims, _ = _extract_claims({"requirement_assessments": [{"explanation": text}]})
        for claim in claims:
            state["citation_verification"]["checks"].append({"claim_id": f"r-{index}-{claim.claim_id}",
                "claim_path": f"final_recommendation.requirement_assessments[{index}].explanation", "claim_text": claim.text,
                "source_title": "Source 0", "canonical_url": "https://source0.example/docs", "status": "unknown", "reason": "network_uncertain"})
    return state


def response_for(state):
    context = prepare_analysis_review(state)
    checks = [[fact["id"], "supports", [1]] for fact in context.facts]
    return {**reviewed([]), "analysis_reviews": [{"analysis_id": key, "action": "keep", "source_checks": deepcopy(checks)} for key in context.slots],
            "provisional_reviews": [{"analysis_id": key, "action": "keep", "source_checks": deepcopy(checks)} for key in context.provisional_slots]}


@pytest.mark.asyncio
async def test_requirement_explanations_are_reviewed_once_with_exact_sources_and_literal_output(monkeypatch):
    state = requirement_state(6)
    before = deepcopy(state)
    answer = response_for(state)
    assert len(answer["provisional_reviews"]) == 6
    answer["provisional_reviews"][0].update(action="revise", text="If other requirements allow it, evaluate Local storage; suitability remains unconfirmed.")
    async def model(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        assert len(payload["requirement_explanations"]) == 6
        assert payload["challenge_fact_ids"] == ["F1"]
        assert len(payload["complete_saved_sources"][0]["sentences"]) == 2
        return answer
    called = AsyncMock(side_effect=model)
    monkeypatch.setattr(review, "call_model", called)
    update = await review.SelfReviewerAgent().run(state)
    called.assert_awaited_once()
    assert state == before
    state.update(update)
    rec = state["final_recommendation"]
    assert rec["provisional_review"]["retained"] == 6
    assert rec["provisional_review"]["revised"] == 1
    for original, row in zip(before["final_recommendation"]["requirement_assessments"], rec["requirement_assessments"]):
        for key in ("id", "requirement", "status", "evidence_ids", "explanation"):
            assert row[key] == original[key]
    for key in ("winner", "source_facts", "action_plan_mode", "deployment_readiness"):
        assert rec[key] == before["final_recommendation"][key]
    for render in FORMAT_RENDERERS.values():
        text = render(state)
        assert "suitability remains unconfirmed" in text and "not semantic verification" in text
        assert "Other requirements can also justify" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["content", "missing", "duplicate", "path", "text", "title", "url", "requirement", "row_id", "fact", "overflow"])
async def test_provisional_binding_cannot_be_forged_or_laundered_by_keep(monkeypatch, bad):
    state = requirement_state()
    checks = state["citation_verification"]["checks"]
    target = checks[-1]
    if bad == "content": target["reason"] = "content_insufficient"
    elif bad == "missing": checks.pop()
    elif bad == "duplicate": checks.append(deepcopy(target))
    elif bad == "path": target["claim_path"] = "final_recommendation.requirement_assessments[1].explanation"
    elif bad == "text": target["claim_text"] = "Another claim"
    elif bad == "title": target["source_title"] = "Forged source"
    elif bad == "url": target["canonical_url"] = "https://other.example/"
    elif bad == "requirement": state["final_recommendation"]["requirement_assessments"][0]["requirement"] = "Different question"
    elif bad == "row_id": state["final_recommendation"]["requirement_assessments"][0]["id"] = "FORGED"
    elif bad == "fact": state["final_recommendation"]["source_facts"][0]["saved_text"] = "Forged full text"
    else: checks.append({**target, "claim_id": "overflow", "claim_path": "final_recommendation"})
    assert prepare_analysis_review(state).provisional_slots == {}
    answer = {**reviewed([]), "provisional_reviews": [{"analysis_id": "R1", "action": "keep", "source_checks": [["F1", "supports", [1]]]}]}
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    state.update(await review.SelfReviewerAgent().run(state))
    assert "provisional_explanation" not in state["final_recommendation"]["requirement_assessments"][0]
    assert state["confidence"] == "low"
    for render in FORMAT_RENDERERS.values():
        assert "Local storage may be evaluated" not in render(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing", "duplicate", "foreign", "invalid_sentence", "qualifies", "conflicts", "truncated", "failure", "oversized_revision", "authority"])
async def test_incomplete_review_withholds_only_invalid_requirement(monkeypatch, bad):
    state = requirement_state(2)
    answer = response_for(state)
    row = answer["provisional_reviews"][0]
    if bad == "missing": answer["provisional_reviews"].pop(0)
    elif bad == "duplicate": answer["provisional_reviews"].append(deepcopy(row))
    elif bad == "foreign": row["source_checks"][0][0] = "F9"
    elif bad == "invalid_sentence": row["source_checks"][0][2] = [999]
    elif bad in {"qualifies", "conflicts"}: row["source_checks"][0][1] = bad
    elif bad == "oversized_revision": row.update(action="revise", text="x" * 201)
    elif bad == "authority": row["status"] = "satisfied"
    elif bad == "truncated": answer = '{"provisional_reviews":'
    monkeypatch.setattr(review, "call_model", AsyncMock(side_effect=OSError("PRIVATE") if bad == "failure" else None, return_value=answer))
    state.update(await review.SelfReviewerAgent().run(state))
    rows = state["final_recommendation"]["requirement_assessments"]
    assert "provisional_explanation" not in rows[0]
    assert ("provisional_explanation" in rows[1]) is (bad not in {"failure", "truncated"})
    assert "PRIVATE" not in json.dumps(state)


@pytest.mark.asyncio
async def test_shared_eight_slot_bound_never_silently_displays_overflow(monkeypatch):
    state = requirement_state(8)
    state["final_recommendation"]["decision_analysis"] = make_state()["final_recommendation"]["decision_analysis"]
    context = prepare_analysis_review(state)
    assert len(context.slots) == 2 and len(context.provisional_slots) == 6
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=response_for(state)))
    state.update(await review.SelfReviewerAgent().run(state))
    rows = state["final_recommendation"]["requirement_assessments"]
    assert all("provisional_explanation" not in row for row in rows[6:])
    assert state["final_recommendation"]["provisional_review"]["withdrawn"] == 2


@pytest.mark.asyncio
async def test_alternative_claim_fails_even_when_model_reports_all_sources_support_it(monkeypatch):
    state = make_state(maximum=True)
    # Every source is bound/checked, but only F1 belongs to A1's basis. F2 may
    # mention the alternative without granting that attribution to A1.
    own_name = "Document 0"
    other_name = "Document 1"
    state["task"]["candidate_techs"] = [own_name, other_name]
    rec = state["final_recommendation"]
    item = rec["decision_analysis"][0]
    item.update(option=own_name, reasoning=f"{own_name} persists data, but {other_name} always loses everything on restart.",
                assumptions=["Persistence settings are unconfirmed."], change_condition="Reassess after verifying the required failure scope.")
    rec["decision_analysis"] = [item]
    assert len(prepare_analysis_review(state).facts) == 4
    payload = analysis_review_input(prepare_analysis_review(state))
    assert payload["challenge_fact_ids"] == ["F1", "F2", "F3", "F4"]
    answer = response_for(state)
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    update = await review.SelfReviewerAgent().run(state)
    assert update["final_recommendation"]["decision_analysis"] == []
    answer["analysis_reviews"][0].update(action="revise", reasoning=f"Evaluate {own_name} only after its persistence settings and required failure scope are confirmed.",
        assumptions=item["assumptions"], change_condition=item["change_condition"])
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    update = await review.SelfReviewerAgent().run(state)
    assert len(update["final_recommendation"]["decision_analysis"]) == 1
    assert other_name not in update["final_recommendation"]["decision_analysis"][0]["reasoning"]
    assert update["final_recommendation"]["decision_analysis"][0]["basis"] == item["basis"]


def test_unreviewed_provisional_and_forged_source_status_do_not_render():
    state = requirement_state()
    for render in FORMAT_RENDERERS.values():
        assert "Local storage may be evaluated" not in render(state)
    row = state["final_recommendation"]["requirement_assessments"][0]
    row.update(provisional_review_status="human_review_required", provisional_fact_ids=["F1"])
    state["final_recommendation"]["provisional_review"] = {"retained": 1}
    state["final_recommendation"]["source_facts"][0]["status"] = "unsupported"
    for render in FORMAT_RENDERERS.values():
        assert "Local storage may be evaluated" not in render(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["assumptions", "change_condition"])
async def test_revision_cannot_move_unbound_alternative_claim_to_another_visible_field(monkeypatch, field):
    state = make_state()
    state["task"]["candidate_techs"].append("OtherProduct")
    answer = response_for(state)
    original = state["final_recommendation"]["decision_analysis"][0]
    answer["analysis_reviews"][0].update(action="revise", **{key: original[key] for key in ("reasoning", "assumptions", "change_condition")})
    claim = "OtherProduct loses all data on restart."
    answer["analysis_reviews"][0][field] = [claim] if field == "assumptions" else claim
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    update = await review.SelfReviewerAgent().run(state)
    assert len(update["final_recommendation"]["decision_analysis"]) == 1
    assert claim not in json.dumps(update)


@pytest.mark.asyncio
async def test_option_heading_cannot_attribute_unnamed_claim_to_an_unbound_candidate(monkeypatch):
    state = make_state()
    state["task"]["candidate_techs"].append("OtherProduct")
    original = state["final_recommendation"]["decision_analysis"][0]
    original.update(option="OtherProduct", reasoning="This option loses everything on restart.")
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=response_for(state)))
    update = await review.SelfReviewerAgent().run(state)
    assert len(update["final_recommendation"]["decision_analysis"]) == 1
    assert "This option loses everything" not in json.dumps(update)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "keep", "unchanged", "irrelevant", "wrong_sentence", "missing_fact", "replace"])
async def test_repair_can_only_append_bound_challenge_sentences_without_authority_gain(monkeypatch, mode):
    state = make_state(maximum=True)
    state["task"]["candidate_techs"] = ["Document 0", "Document 1"]
    rec = state["final_recommendation"]
    rec["decision_analysis"] = rec["decision_analysis"][:1]
    original = rec["decision_analysis"][0]
    original.update(option="Document 0", reasoning="Document 1 always loses everything.", assumptions=["Settings remain unknown."], change_condition="Reassess the required failure scope.")
    answer = response_for(state)
    row = answer["analysis_reviews"][0]
    row.update(action="revise", reasoning="Document 1 has a qualified exception; compare it with Document 0 after checking the applicable settings.",
               assumptions=original["assumptions"], change_condition=original["change_condition"],
               additional_basis=[{"fact_id": "F2", "sentence_ids": [2]}])
    row["source_checks"][1] = ["F2", "qualifies", [2]]
    if mode == "keep": row["action"] = "keep"
    elif mode == "unchanged": row["reasoning"] = original["reasoning"]
    elif mode == "irrelevant": row["source_checks"][1] = ["F2", "irrelevant", []]
    elif mode == "wrong_sentence": row["additional_basis"][0]["sentence_ids"] = [1]
    elif mode == "missing_fact": row["additional_basis"][0]["fact_id"] = "F9"
    elif mode == "replace": row["basis"] = row.pop("additional_basis")
    before = deepcopy(rec)
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    update = await review.SelfReviewerAgent().run(state)
    rec = update["final_recommendation"]
    assert len(rec["decision_analysis"]) == (1 if mode == "valid" else 0)
    if mode == "valid":
        new = rec["decision_analysis"][0]
        assert new["basis"][:1] == original["basis"]
        assert new["basis"][1]["fact_id"] == "F2" and new["basis"][1]["sentence_ids"] == [2]
    for key in ("winner", "source_facts", "deployment_readiness", "action_plan_mode"):
        assert rec[key] == before[key]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["option", "reasoning", "assumptions", "change_condition"])
@pytest.mark.parametrize("action", ["keep", "revise"])
async def test_action_candidate_cannot_borrow_other_slots_product_basis(monkeypatch, field, action):
    state = make_state(maximum=True)
    state["task"]["candidate_techs"] = ["continue using Document 0", "switch to Document 1"]
    rec = state["final_recommendation"]
    original = rec["decision_analysis"][0]
    original.update(kind="choice", option=state["task"]["candidate_techs"][0],
                    reasoning="Evaluate Document 0 within the stated limits.", assumptions=[],
                    change_condition="Reconsider after measuring the workload.")
    rec["decision_analysis"] = [original]
    claim = "Document 1 guarantees durable recovery."
    if field == "option":
        original["option"] = state["task"]["candidate_techs"][1]
    else:
        # Isolate bare-product leakage from the old guard's separate option-label rejection.
        original.update(kind="answer", option="")
        if action == "keep":
            original[field] = [claim] if field == "assumptions" else claim
    answer = response_for(state)
    row = answer["analysis_reviews"][0]
    row["action"] = action
    if action == "revise":
        row.update({key: original[key] for key in ("reasoning", "assumptions", "change_condition")})
        if field != "option":
            row[field] = [claim] if field == "assumptions" else claim
    # All four facts are reviewable; the competing product in F2 is not in A1's basis.
    assert len(prepare_analysis_review(state).facts) == 4
    assert original["fact_ids"] == ["F1"]
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    update = await review.SelfReviewerAgent().run(state)
    assert update["final_recommendation"]["decision_analysis"] == []


@pytest.mark.asyncio
async def test_provisional_review_checks_bare_product_of_action_candidate(monkeypatch):
    state = requirement_state()
    state["task"]["candidate_techs"] = ["continue using Local", "switch to OtherProduct"]
    answer = response_for(state)
    claim = "OtherProduct guarantees recovery."
    answer["provisional_reviews"][0].update(action="revise", text=claim)
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=answer))
    update = await review.SelfReviewerAgent().run(state)
    assert "provisional_explanation" not in update["final_recommendation"]["requirement_assessments"][0]
    assert claim not in json.dumps(update)
