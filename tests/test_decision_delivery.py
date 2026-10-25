"""Decision-delivery guards: validation salvage and honest report headlines.

These tests pin the round-2 behaviour: a bound inference that fails review or
calibration is retained (not deleted), while the report distinguishes a
deliverable conditional choice from a report that retained no judgment. They do
not claim model quality and make no live call.
"""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import self_reviewer as review
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.formats.decision import render_answer_report
from deepchoice.utils.answer_delivery import finalize_answer_delivery
from deepchoice.utils.question_packet import bind_question_rows
from tests.test_self_review import BAD, GOOD, SOURCE, make_state, reviewed


def answer_state(rows, *, review_summary=None, query="Do we need a separate database service?"):
    rec = {
        "winner": "context_dependent",
        "ranked_options": [],
        "source_facts": [{
            "id": "F1", "evidence_id": 1, "source_title": "Source 0",
            "canonical_url": "https://source0.example/docs",
            "text": SOURCE, "saved_text": SOURCE, "status": "verified",
        }],
        "decision_analysis": rows,
        "answer_delivery": {
            "version": "question-analysis-v1",
            "requirements": {"R0": query},
            "questions": ["R0"],
        },
    }
    if review_summary is not None:
        rec["analysis_review"] = review_summary
    rec = finalize_answer_delivery(rec, query)
    return {"task": {"query": query, "report_format": "what_why_how"},
            "final_recommendation": rec, "citation_verification": {}}


def choice_row(**overrides):
    row = {
        "kind": "choice", "option": "Server",
        "fact_ids": ["F1"], "requirement_ids": ["R0"],
        "requirements": ["Do we need a separate database service?"],
        "reasoning": "If queuing tolerance cannot be established, a separate server is the conditional preference.",
        "assumptions": ["Queuing tolerance is unmeasured."],
        "change_condition": "Reassess once queuing measurements exist.",
        "review_status": "human_review_required",
        "basis": [{"fact_id": "F1", "sentence_ids": [1],
                   "source_sentences": [SOURCE.split(". ")[0] + "."]}],
    }
    row.update(overrides)
    return row


def complete_review(retained=1):
    return {"status": "complete", "submitted": retained, "reviewed": retained,
            "retained": retained, "revised": 0, "withdrawn": 0,
            "unaddressed": 0, "unreviewed_retained": 0}


@pytest.mark.asyncio
async def test_unreviewed_analysis_is_retained_and_rendered_as_advisory(monkeypatch):
    state = make_state()
    # The reviewer's only row for A1 is structurally invalid, so A1 was never
    # adjudicated. It must stay in state and appear in the report as advisory.
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=reviewed([
        {"analysis_id": "A1", "action": "keep", "source_checks": []},
        {"analysis_id": "A2", "action": "keep"},
    ])))
    update = await review.SelfReviewerAgent().run(state)
    rec = update["final_recommendation"]
    assert len(rec["decision_analysis"]) == 2
    advisory = [row for row in rec["decision_analysis"]
                if row["review_status"] == "advisory_unreviewed"]
    assert len(advisory) == 1 and advisory[0]["reasoning"] == BAD
    assert rec["analysis_review"]["unreviewed_retained"] == 1
    state.update(update)
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert "(unreviewed)" in report and "unreviewed inferences" in report
        assert BAD in report and GOOD in report


def test_answer_report_without_displayable_analysis_never_claims_a_judgment():
    state = answer_state([])
    report = render_answer_report(state, "en")
    assert "No displayable source-bound analysis was retained" in report
    assert "no deliverable judgment or choice" in report


def test_answer_report_with_choice_gets_summary_and_conditional_headline():
    state = answer_state([choice_row()], review_summary=complete_review())
    report = render_answer_report(state, "en")
    assert "Conditional choices or preferences are summarized below" in report
    assert "### Conditional choice summary" in report
    assert "**Server**" in report and "verified 1 / unknown 0" in report
    assert "What would change this judgment" in report


def test_answer_report_without_choice_does_not_overclaim_a_selection():
    row = choice_row(kind="answer", option="", review_status="human_review_required")
    state = answer_state([row], review_summary=complete_review())
    report = render_answer_report(state, "en")
    assert "without forming a single choice" in report
    assert "### Conditional choice summary" not in report
    assert "Conditional analyses cover some original questions" in report


def test_question_binding_records_split_shape_rejection_reasons():
    offered = {"S1B1": {"fact_id": "F1", "sentence_ids": [1], "source_sentences": ["x"]}}
    diagnostics = {}
    rows = [
        {"kind": "answer", "reasoning": "no question id", "basis_refs": ["S1B1"]},
        {"question_id": "R0", "kind": "answer", "reasoning": "bad refs", "basis_refs": []},
        {"question_id": "R0", "kind": "answer", "reasoning": "unknown view",
         "basis_refs": ["S9B1"]},
    ]
    selected = bind_question_rows(rows, {"R0", "Q1", "Q2"}, offered, diagnostics=diagnostics)
    assert selected == []
    assert diagnostics["rows_rejected_missing_id"] == 1
    assert diagnostics["rows_rejected_basis_refs"] == 1
    assert diagnostics["rows_rejected_unknown_refs"] == 1
    assert diagnostics["rows_rejected_shape"] == 3


def test_normalized_duplicate_question_rows_are_still_counted():
    offered = {"S1B1": {"fact_id": "F1", "sentence_ids": [1], "source_sentences": ["x"]}}
    diagnostics = {}
    row = {"question_id": "R0", "kind": "answer", "reasoning": "answer",
           "basis_refs": ["S1B1"]}
    selected = bind_question_rows([row, deepcopy(row)], {"R0", "Q1"}, offered,
                                  diagnostics=diagnostics)
    assert len(selected) == 1
    assert diagnostics["rows_rejected_question"] == 1
    assert diagnostics["rows_selected"] == 1
