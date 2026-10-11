"""A verified addressed sentence can enter review while its full source stays unknown."""
from copy import deepcopy
import json

import pytest

from deepchoice.citations.contracts import CitationVerification
from deepchoice.citations.verifier import _split_sentences, _strip_citations
from deepchoice.formats.decision import render_decision_details
from deepchoice.utils.analysis_review import analysis_review_input, apply_analysis_review, prepare_analysis_review
from deepchoice.utils.decision_analysis import bind_analysis_basis, calibrate_decision_analysis
from deepchoice.utils.evidence_choices import calibrate_evidence_choices
from tests.test_self_review import make_state, reviewed, revision


def partial_state(*, reason="qualifier_unverified", status="unknown", addressed=2):
    state = make_state()
    recommendation = deepcopy(state["final_recommendation"])
    sentences = _split_sentences(recommendation["source_facts"][0]["saved_text"])
    for analysis in recommendation["decision_analysis"]:
        analysis["basis"] = [{"fact_id": "F1", "sentence_ids": [addressed],
                              "source_sentences": [sentences[addressed - 1]]}]
    verification = deepcopy(state["citation_verification"])
    verification["checks"][0].update(status=status, reason=reason)
    verification["status_counts"] = {"verified": 1, status: 1} if status != "verified" else {"verified": 2}
    bound = CitationVerification.model_validate_json(json.dumps(verification))
    recommendation = calibrate_decision_analysis(calibrate_evidence_choices(recommendation, bound))
    state.update(final_recommendation=recommendation, citation_verification=verification)
    return state


@pytest.mark.parametrize("reason", ["qualifier_unverified", "content_insufficient"])
def test_only_addressed_verified_sentence_enters_full_source_review(reason):
    state = partial_state(reason=reason)
    recommendation = state["final_recommendation"]
    fact = recommendation["source_facts"][0]
    assert fact["status"] == "unknown"
    assert fact["review_availability"] == "sentence_scoped"
    assert fact["reviewable_sentence_ids"] == [2]
    assert [x["review_status"] for x in recommendation["decision_analysis"]] == [
        "sentence_scoped_pending_review", "sentence_scoped_pending_review"]
    assert "Model judgment" not in "\n".join(render_decision_details(recommendation, "en"))
    context = prepare_analysis_review(state)
    assert list(context.slots) == ["A1", "A2"]
    payload = analysis_review_input(context)
    assert payload["complete_saved_sources"][0]["saved_text"] == fact["saved_text"]
    assert payload["complete_saved_sources"][0]["reviewable_sentence_ids"] == [2]
    answer = revision()
    answer["source_checks"] = [["F1", "qualifies", [1]]]
    result, summary = apply_analysis_review(context, reviewed([
        answer, {"analysis_id": "A2", "action": "withdraw"},
    ]))
    assert summary == {"status": "complete", "submitted": 2, "reviewed": 2,
                       "retained": 1, "revised": 1, "withdrawn": 1}
    assert result["source_facts"][0]["status"] == "unknown"
    assert result["winner"] == recommendation["winner"]
    assert result["decision_analysis"][0]["review_status"] == "sentence_scoped_human_review_required"
    report = "\n".join(render_decision_details(result, "en"))
    assert "Model judgment" in report
    assert "text in the same source remains unlocated or unverified" in report
    assert "Source check: unknown (some source text remains unlocated or unverified)" in report
    assert "Other requirements can also justify" in report


def test_an_analysis_addressing_the_unverified_sentence_is_withheld():
    state = partial_state(addressed=1)
    # The unverified sentence is dropped; with no reviewable basis left the
    # analysis is withheld, and the removal stays observable.
    assert state["final_recommendation"]["decision_analysis"] == []
    assert state["final_recommendation"]["analysis_calibration"] == {
        "basis_sentences_dropped": 2, "analyses_dropped": 2, "retained": 0}
    assert prepare_analysis_review(state).slots == {}


def test_analysis_keeps_reviewable_basis_when_one_premise_is_unverified():
    """One unverifiable premise must not delete the whole useful analysis.

    Mirrors the measured 2026-10-10 loss: six analyses were generated and two
    were deleted whole because one of two cited sentences fell outside the
    narrower verified range.
    """
    state = make_state()
    recommendation = deepcopy(state["final_recommendation"])
    recommendation["decision_analysis"] = recommendation["decision_analysis"][:1]
    recommendation["decision_analysis"][0]["basis"] = [
        {"fact_id": "F1", "sentence_ids": [1]},
        {"fact_id": "F2", "sentence_ids": [2]},
    ]
    recommendation["source_facts"].append({
        **deepcopy(recommendation["source_facts"][0]), "id": "F2", "evidence_id": 2,
        "source_title": "Source 1", "canonical_url": "https://source1.example/docs"})
    verification = deepcopy(state["citation_verification"])
    # F1 keeps only sentence 2 reviewed; the analysis addressed sentence 1.
    verification["checks"][0].update(status="unknown", reason="qualifier_unverified")
    # F2 is fully verified: availability alone is uncertain for that source.
    fact_two = recommendation["source_facts"][1]
    for offset, sentence in enumerate(_split_sentences(fact_two["saved_text"])):
        verification["checks"].append({
            "claim_id": f"check-f2-{offset}",
            "claim_path": "final_recommendation.source_facts[1].text",
            "claim_text": _strip_citations(sentence),
            "source_title": fact_two["source_title"],
            "canonical_url": fact_two["canonical_url"],
            "status": "verified", "reason": "lexical_support"})
    verification["status_counts"] = {"verified": 3, "unknown": 1}
    bound = CitationVerification.model_validate_json(json.dumps(verification))
    result = calibrate_decision_analysis(calibrate_evidence_choices(recommendation, bound))

    assert result["source_facts"][0]["review_availability"] == "sentence_scoped"
    assert result["source_facts"][0]["reviewable_sentence_ids"] == [2]
    assert result["analysis_calibration"] == {
        "basis_sentences_dropped": 1, "analyses_dropped": 0, "retained": 1}
    assert len(result["decision_analysis"]) == 1
    row = result["decision_analysis"][0]
    assert row["fact_ids"] == ["F2"]
    assert [part["sentence_ids"] for part in row["basis"]] == [[2]]


def test_trimming_reindexes_addressed_quotations_to_the_surviving_sentences():
    """A partially reviewable fact keeps only the quotations it can vouch for."""
    state = make_state()
    recommendation = deepcopy(state["final_recommendation"])
    recommendation["decision_analysis"] = recommendation["decision_analysis"][:1]
    sentences = _split_sentences(recommendation["source_facts"][0]["saved_text"])
    recommendation["decision_analysis"][0]["basis"] = [
        {"fact_id": "F1", "sentence_ids": [1, 2],
         "source_sentences": [sentences[0], sentences[1]]},
    ]
    verification = deepcopy(state["citation_verification"])
    # Only sentence 2 of F1 is uniquely verified; sentence 1 stays unverified.
    verification["checks"][0].update(status="unknown", reason="qualifier_unverified")
    verification["status_counts"] = {"verified": 1, "unknown": 1}
    bound = CitationVerification.model_validate_json(json.dumps(verification))
    result = calibrate_decision_analysis(calibrate_evidence_choices(recommendation, bound))

    row = result["decision_analysis"][0]
    assert row["fact_ids"] == ["F1"]
    assert row["basis"][0]["sentence_ids"] == [2]
    # The surviving quotation must belong to sentence 2, not the dropped sentence 1.
    assert row["basis"][0]["source_sentences"] == [sentences[1]]
    assert result["analysis_calibration"] == {
        "basis_sentences_dropped": 1, "analyses_dropped": 0, "retained": 1}
    # The row stays review-pending here, so the renderer gate withholds it until
    # analysis_review completes; that gate is covered above and by the binder.
    basis, error = bind_analysis_basis(row["basis"], {
        row["fact_ids"][0]: recommendation["source_facts"][0]})
    assert error is None and basis[0]["source_sentences"] == [sentences[1]]


def test_inconsistent_addressed_quotations_are_dropped_whole():
    """A basis part whose quotations cannot be re-indexed must not survive."""
    from deepchoice.utils.decision_analysis import _reviewable_basis

    fact = {"id": "F1", "status": "unknown", "review_availability": "sentence_scoped",
            "reviewable_sentence_ids": [2], "saved_text": "Alpha one. Bravo two."}
    kept, dropped = _reviewable_basis({"basis": [{
        "fact_id": "F1", "sentence_ids": [1, 2], "source_sentences": ["Alpha one."]}]},
        {"F1": fact})
    assert kept is None and dropped == [1, 2]


@pytest.mark.parametrize("mutation", ["cross_language", "unsupported", "unreachable",
                                       "missing", "duplicate", "wrong_title", "wrong_url", "overflow"])
def test_partial_review_requires_exact_complete_identity_and_eligible_uncertainty(mutation):
    state = make_state()
    verification = deepcopy(state["citation_verification"])
    checks = verification["checks"]
    if mutation == "cross_language":
        checks[0].update(status="unknown", reason="cross_language")
    elif mutation == "unsupported":
        checks[0].update(status="unsupported", reason="lexical_mismatch")
    elif mutation == "unreachable":
        checks[0].update(status="unreachable", reason="not_publicly_accessible")
    elif mutation == "missing":
        checks.pop(0)
    elif mutation == "duplicate":
        checks.append(deepcopy(checks[0]))
    elif mutation == "wrong_title":
        checks[0]["source_title"] = "forged"
    elif mutation == "wrong_url":
        checks[0]["canonical_url"] = "https://wrong.example/"
    else:
        checks.append({**checks[0], "claim_id": "overflow", "claim_path": "final_recommendation"})
    bound = CitationVerification.model_validate_json(json.dumps(verification))
    recommendation = calibrate_decision_analysis(calibrate_evidence_choices(
        deepcopy(state["final_recommendation"]), bound))
    assert recommendation["source_facts"][0].get("review_availability") != "sentence_scoped"
    assert "reviewable_sentence_ids" not in recommendation["source_facts"][0]


def test_forged_sentence_eligibility_is_recomputed_and_provisional_is_not_opened():
    state = partial_state()
    recommendation = deepcopy(state["final_recommendation"])
    recommendation["source_facts"][0]["reviewable_sentence_ids"] = [1, 2]
    state["final_recommendation"] = recommendation
    assert prepare_analysis_review(state).slots == {}
    state = partial_state()
    context = prepare_analysis_review(state)
    assert context.provisional_slots == {}


def test_partial_fact_cannot_authorize_unaddressed_requirement_explanation():
    state = partial_state()
    fact = state["final_recommendation"]["source_facts"][0]
    statement = "Local storage can be evaluated. [Source: Source 0]"
    state["final_recommendation"]["requirement_assessments"] = [{
        "id": "R0", "requirement": state["task"]["query"], "status": "unknown",
        "explanation": "Unknown", "evidence_ids": [], "provisional_explanation": statement,
    }]
    from deepchoice.citations.verifier import _extract_claims
    claims, overflow = _extract_claims({"requirement_assessments": [{"explanation": statement}]})
    assert not overflow and len(claims) == 1
    state["citation_verification"]["checks"].append({
        "claim_id": "provisional-1", "claim_path": "final_recommendation.requirement_assessments[0].explanation",
        "claim_text": claims[0].text, "source_title": fact["source_title"],
        "canonical_url": fact["canonical_url"], "status": "verified", "reason": "lexical_support",
    })
    context = prepare_analysis_review(state)
    assert len(context.slots) == 2
    assert context.provisional_slots == {}


def test_renderer_rejects_forged_scoped_review_of_unknown_sentence():
    state = partial_state()
    recommendation = deepcopy(state["final_recommendation"])
    item = recommendation["decision_analysis"][0]
    item["review_status"] = "sentence_scoped_human_review_required"
    item["basis"][0]["sentence_ids"] = [1]
    item["basis"][0]["source_sentences"] = [_split_sentences(recommendation["source_facts"][0]["saved_text"])[0]]
    recommendation["analysis_review"] = {"status": "complete", "submitted": 1,
                                         "reviewed": 1, "retained": 1, "revised": 0, "withdrawn": 0}
    assert "Model judgment" not in "\n".join(render_decision_details(recommendation, "en"))

@pytest.mark.asyncio
async def test_real_verifier_mixed_sentence_status_reaches_review_and_report(monkeypatch):
    import httpx

    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.utils.evidence_choices import bind_evidence_choices

    state = make_state()
    source = ("Beat is required for all Celery tasks that execute on the production worker pool under the documented scheduler configuration. "
              "Celery workers execute queued tasks.")
    page = source + " " + source.split(". ")[0].replace("all Celery", "recurring Celery") + "."
    state["task"]["candidate_techs"] = ["Celery", "Server"]
    state["evidence_chains"][0]["sources"][0]["snippet"] = source
    recommendation = deepcopy(state["final_recommendation"])
    recommendation["decision_basis_version"] = "constraint-aware-v1"
    recommendation["winner"] = "context_dependent"
    recommendation["recommendation"] = ""
    recommendation["decision_analysis"] = recommendation["decision_analysis"][:1]
    recommendation["decision_analysis"][0]["option"] = "Celery"
    recommendation["decision_analysis"][0]["reasoning"] = "Celery workers execute queued tasks, and Beat is required for all Celery tasks."
    recommendation["decision_analysis"][0]["assumptions"] = ["The scheduler is configured."]
    recommendation["decision_analysis"][0]["change_condition"] = "Reassess when scheduling requirements are known."
    recommendation["decision_analysis"][0]["basis"] = [
        {"fact_id": "F1", "sentence_ids": [2]}]
    recommendation = bind_evidence_choices(
        recommendation, state["evidence_chains"], state["task"]["candidate_techs"], [])
    state["final_recommendation"] = recommendation
    calls = []

    async def fake_fetch(source_name, url, **kwargs):
        calls.append((source_name, url))
        return httpx.Response(200, text=page, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fake_fetch)
    update = await CitationValidatorAgent().run(state)
    assert calls == [("official", "https://source0.example/docs")]
    state.update(update)
    checks = [check for check in state["citation_verification"]["checks"]
              if check["claim_path"] == "final_recommendation.source_facts[0].text"]
    assert [(check["status"], check["reason"]) for check in checks] == [
        ("unknown", "qualifier_unverified"), ("verified", "lexical_support")]
    fact = state["final_recommendation"]["source_facts"][0]
    assert fact["status"] == "unknown"
    assert fact["reviewable_sentence_ids"] == [2]
    context = prepare_analysis_review(state)
    assert list(context.slots) == ["A1"]
    assert analysis_review_input(context)["complete_saved_sources"][0]["saved_text"] == source
    result, summary = apply_analysis_review(context, reviewed([{
        "analysis_id": "A1", "action": "revise",
        "reasoning": "Celery workers execute queued tasks; schedule requirements remain unresolved.",
        "assumptions": ["The scheduling requirement needs a separate check."],
        "change_condition": "Reassess after the schedule requirement is checked.",
        "source_checks": [["F1", "qualifies", [1]]],
    }]))
    assert summary["status"] == "complete"
    assert result["source_facts"][0]["status"] == "unknown"
    report = "\n".join(render_decision_details(result, "en"))
    assert "Model judgment" in report
    assert "text in the same source remains unlocated or unverified" in report
