"""Analysis delivery under source outage and per-item correction, without live calls."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth, self_reviewer as review
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.citations.contracts import CitationVerification
from deepchoice.utils.analysis_review import prepare_analysis_review
from deepchoice.utils.decision_analysis import bind_decision_analysis, calibrate_decision_analysis
from deepchoice.utils.decision_contract import restrict_recommendation
from deepchoice.utils.evidence_choices import calibrate_evidence_choices
from tests.test_synthesis_structure import response, TASK, CHAINS, REQS
from tests.test_self_review import reviewed


async def unavailable_state(monkeypatch):
    monkeypatch.setattr(synth, "call_model", AsyncMock(return_value=response()))
    async def fail(*args, **kwargs):
        raise httpx.ConnectError("PRIVATE_NETWORK_MESSAGE")
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fail)
    state = {"task": deepcopy(TASK), "evidence_chains": deepcopy(CHAINS)}
    # Name the fixture product so this test isolates network eligibility rather than missing attribution.
    state["evidence_chains"][0]["sources"][0]["title"] = "ExampleQueue documentation"
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    state.update(await CitationValidatorAgent().run(state))
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["keep", "revise", "withdraw", "missing", "failure"])
async def test_network_unknown_requires_slot_review_and_never_upgrades_authority(monkeypatch, action):
    state = await unavailable_state(monkeypatch)
    rec = state["final_recommendation"]
    assert len(rec["decision_analysis"]) == 1
    assert rec["source_facts"][0]["status"] == "unknown"
    assert rec["source_facts"][0]["review_availability"] == "network_unconfirmed"
    for render in FORMAT_RENDERERS.values():
        assert "FIRST_PRIVATE_REASON" not in render(state)  # Pending is not publishable.
    row = {"analysis_id": "A1", "action": action}
    if action == "revise":
        row.update(reasoning="If a durable journal exists, evaluate replay with application idempotency.",
                   assumptions=["Journal durability is unconfirmed."],
                   change_condition="Reassess if the journal is unavailable.")
    async def model(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        assert payload["complete_saved_sources"][0]["status"] == "unknown"
        assert payload["complete_saved_sources"][0]["saved_text"] == CHAINS[0]["sources"][0]["snippet"]
        if action == "failure":
            raise OSError("PRIVATE_REVIEW_ERROR")
        result = reviewed([] if action == "missing" else [row])
        result.update(winner="FORGED", source_facts=[], action_plan=["DANGEROUS"])
        return result
    monkeypatch.setattr(review, "call_model", model)
    original = deepcopy(rec)
    state.update(await review.SelfReviewerAgent().run(state))
    rec = state["final_recommendation"]
    keep = action in {"keep", "revise"}
    assert len(rec["decision_analysis"]) == int(keep)
    assert rec["confidence"] == "low" and state["knowledge_gaps"]
    for key in ("winner", "requirement_assessments", "action_plan", "source_facts"):
        assert rec[key] == original[key]
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert ("Live source verification was unavailable (unknown)" in report) is keep
        assert "Source lexical check: verified" not in report
        assert "FORGED" not in report and "DANGEROUS" not in report and "PRIVATE_REVIEW_ERROR" not in report
    assert "decision_analysis" not in restrict_recommendation(rec, TASK["query"])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing", "duplicate", "title", "url", "overflow", "content", "language", "unsupported", "unreachable", "forged_marker"])
async def test_unknown_review_gate_rejects_incomplete_or_non_network_evidence(monkeypatch, bad):
    state = await unavailable_state(monkeypatch)
    v = state["citation_verification"]
    checks = v["checks"]
    fact_path = "final_recommendation.source_facts[0].text"
    target = next(c for c in checks if c["claim_path"] == fact_path)
    if bad == "missing": checks.remove(target)
    elif bad == "duplicate": checks.append(deepcopy(target))
    elif bad == "title": target["source_title"] = "Forged title"
    elif bad == "url": target["canonical_url"] = "https://other.example/"
    elif bad == "overflow": checks.append({**target, "claim_id": "overflow", "claim_path": "final_recommendation"})
    elif bad == "content": target["reason"] = "content_insufficient"
    elif bad == "language": target["reason"] = "cross_language"
    elif bad == "unsupported": target.update(status="unsupported", reason="lexical_mismatch")
    elif bad == "unreachable": target.update(status="unreachable", reason="not_publicly_accessible")
    else: state["citation_verification"] = {}  # A forged marker alone is not eligibility.
    rec = deepcopy(state["final_recommendation"])
    if bad != "forged_marker":
        recalibrated = calibrate_decision_analysis(calibrate_evidence_choices(rec, CitationVerification.model_validate_json(json.dumps(v))))
        assert recalibrated["decision_analysis"] == []
    assert prepare_analysis_review(state).slots == {}


@pytest.mark.asyncio
async def test_partial_correction_selects_whole_bound_response_without_promoting_operations(monkeypatch):
    first = response()
    first["source_facts"].append({"id": "F2", "evidence_id": 99})
    second = deepcopy(first)
    new = deepcopy(second["decision_analysis"][0])
    new.update(requirement_ids=["R0"], reasoning="SECOND_NEW_DIMENSION")
    second["decision_analysis"].append(new)
    second["decision_analysis"][0]["reasoning"] = "SECOND_EXISTING_DIMENSION"
    second["action_plan"] = [{"step": "UNSAFE_PROCEDURE", "verification": "", "rollback": "", "change_trigger": ""}]
    second["confidence"] = "high"
    model = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(synth, "call_model", model)
    result = await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": CHAINS})
    feedback = model.await_args_list[1].args[0][-1]["content"]
    coordinates = json.loads(feedback.split("Runtime-computed error counts and eligible identifiers: ", 1)[1])
    assert coordinates["accepted_source_facts"] == [{"id": "F1", "evidence_id": 1}]
    assert coordinates["accepted_analyses"] == [{"kind": "answer", "option": "ExampleQueue",
        "requirement_ids": ["Q1"], "basis": [{"fact_id": "F1", "sentence_ids": [1]}]}]
    assert "FIRST_PRIVATE_REASON" not in feedback and "F2" not in feedback
    rec = result["final_recommendation"]
    assert len(rec["decision_analysis"]) == 2
    assert rec["confidence"] == "low" and rec["winner"] == "context_dependent"
    assert rec["action_plan_mode"] == "validation_only"
    assert "FIRST_PRIVATE_REASON" not in json.dumps(rec) and "UNSAFE_PROCEDURE" not in json.dumps(rec)
    assert result["quality_signals"][0]["structure_correction"]["outcome"] == "partial_corrected"
    assert len(rec["source_facts"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["lost_question", "lost_basis", "winner", "satisfaction", "same_coverage", "incomplete"])
async def test_partial_correction_cannot_trade_away_old_coverage_or_strengthen_authority(monkeypatch, bad):
    first = response(); first["source_facts"].append({"id": "F2", "evidence_id": 99})
    second = deepcopy(first)
    new = deepcopy(second["decision_analysis"][0]); new["requirement_ids"] = ["R0"]
    second["decision_analysis"].append(new)
    second["decision_analysis"][0]["reasoning"] = "SECOND_REASON"
    if bad == "lost_question": second["decision_analysis"][0]["requirement_ids"] = ["R0"]
    elif bad == "lost_basis": second["decision_analysis"][0]["basis"][0]["sentence_ids"] = [99]
    elif bad == "winner": second["winner"] = "ExampleQueue"
    elif bad == "satisfaction": second["requirement_assessments"] = [{"id":"C1","requirement":"No silent task loss","status":"satisfied","decision_critical":True,"explanation":"CLAIM", "evidence_ids":[1]}]
    elif bad == "same_coverage": new["requirement_ids"] = ["Q1"]
    else: second.pop("confidence")
    monkeypatch.setattr(synth, "call_model", AsyncMock(side_effect=[first, second]))
    result = await synth.ConclusionSynthesizerAgent().run({"task": TASK, "evidence_chains": CHAINS})
    assert result["final_recommendation"]["decision_analysis"][0]["reasoning"] == "FIRST_PRIVATE_REASON"
    assert result["quality_signals"][0]["structure_correction"]["outcome"] == "invalid"


@pytest.mark.parametrize("value,expected", [(None,"prose_type"),("", "prose_empty"),("x"*1501,"prose_length"),("[[1]]", "prose_reference")], ids=["type","empty","length","reference"])
def test_prose_feedback_has_fixed_specific_reason_without_text(value, expected):
    rec = response()
    rec["source_facts"] = [{"id":"F1", "saved_text": CHAINS[0]["sources"][0]["snippet"]}]
    rec["decision_analysis"][0]["reasoning"] = value
    counts = {}
    bound = bind_decision_analysis(rec, REQS, TASK["candidate_techs"], diagnostics=counts, require_basis=True)
    assert bound["decision_analysis"] == [] and counts["rejected"] == {expected:1}
    assert "PRIVATE" not in json.dumps(counts)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["empty", "winner", "requirement", "basis"])
async def test_fully_valid_correction_also_preserves_existing_coverage_and_authority(monkeypatch, bad):
    first = response(); first["source_facts"].append({"id":"F2", "evidence_id":99})
    second = response()
    if bad == "empty": second.update(source_facts=[], decision_analysis=[])
    elif bad == "winner": second["winner"] = "ExampleQueue"
    elif bad == "requirement": second["requirement_assessments"] = [{"id":"C1","requirement":"No silent task loss","status":"satisfied","decision_critical":True,"explanation":"claim","evidence_ids":[1]}]
    else: second["decision_analysis"][0]["requirement_ids"] = ["R0"]
    monkeypatch.setattr(synth,"call_model",AsyncMock(side_effect=[first,second]))
    result = await synth.ConclusionSynthesizerAgent().run({"task":TASK,"evidence_chains":CHAINS})
    assert result["quality_signals"][0]["structure_correction"]["outcome"] == "invalid"
    assert result["final_recommendation"]["decision_analysis"][0]["requirement_ids"] == ["Q1"]


@pytest.mark.asyncio
async def test_ordinary_selection_partial_correction_keeps_validation_only_after_normalization(monkeypatch):
    task={"query":"Which small library should I choose?","candidate_techs":["ExampleQueue"],"sub_questions":["What are the tradeoffs?"]}
    first=response();first["source_facts"].append({"id":"F2","evidence_id":99})
    second=deepcopy(first);new=deepcopy(second["decision_analysis"][0]);new["requirement_ids"]=["R0"]
    second["decision_analysis"].append(new)
    monkeypatch.setattr(synth,"call_model",AsyncMock(side_effect=[first,second]))
    result=await synth.ConclusionSynthesizerAgent().run({"task":task,"evidence_chains":CHAINS})
    assert result["quality_signals"][0]["structure_correction"]["outcome"] == "partial_corrected"
    assert result["final_recommendation"]["action_plan_mode"] == "validation_only"
    assert result["final_recommendation"]["confidence"] == "low"


@pytest.mark.asyncio
async def test_forged_verified_status_cannot_override_current_network_unknown_checks(monkeypatch):
    state=await unavailable_state(monkeypatch)
    state["final_recommendation"]["source_facts"][0]["status"]="verified"
    assert prepare_analysis_review(state).slots == {}
    monkeypatch.setattr(review,"call_model",AsyncMock(return_value=reviewed([{"analysis_id":"A1","action":"keep"}])))
    state.update(await review.SelfReviewerAgent().run(state))
    assert state["final_recommendation"]["decision_analysis"] == []
    for render in FORMAT_RENDERERS.values():
        assert "FIRST_PRIVATE_REASON" not in render(state)
