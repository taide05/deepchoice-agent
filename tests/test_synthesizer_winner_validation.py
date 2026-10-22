"""Unified decision contract: recommended / conditional / insufficient / invalid."""
import asyncio
import copy

from deepchoice.agents import self_reviewer
from deepchoice.agents.conclusion_synthesizer import normalize_decision
from deepchoice.formats import comparison_matrix, evidence_first, what_why_how
from deepchoice.utils.decision import (
    CONDITIONAL, INSUFFICIENT, INVALID, RECOMMENDED,
    decision_view,
)

SOURCE = "https://source.example/doc"
CHAINS = [{"sources": [{"title": "Source", "url": SOURCE,
                        "snippet": "bounded source body", "has_body": True}]}]


def _state(rec):
    return {"task": {"query": "choose a tool", "report_format": "what_why_how"},
            "evidence_chains": CHAINS, "conflicts": [], "quality_signals": [],
            "knowledge_gaps": [], "final_recommendation": rec,
            "confidence": rec.get("confidence", "medium")}


def _render_all(rec):
    state = _state(rec)
    return {
        "what_why_how": what_why_how.render(state),
        "evidence_first": evidence_first.render(state),
        "comparison_matrix": comparison_matrix.render(state),
    }


def test_supported_explicit_recommendation_is_unchanged():
    rec = normalize_decision({
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "The source states Alpha fits the constraint.",
        "recommendation": "Adopt Alpha after the stated prerequisite.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "confidence": "high", "unresolved_questions": [],
    })
    assert rec["decision_status"] == RECOMMENDED
    assert rec["winner"] == "Alpha"
    assert decision_view(rec)["status"] == RECOMMENDED


def test_genuine_conditional_is_not_forced_to_a_winner():
    rec = normalize_decision({
        "decision_status": "conditional", "winner": "context_dependent",
        "winner_rationale": "Evidence branches on deployment mode.",
        "recommendation": "Choose Alpha for cloud; choose Beta for offline.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "unresolved_questions": [],
    })
    assert rec["decision_status"] == CONDITIONAL
    assert rec["winner"] == ""
    outputs = _render_all(rec)
    assert all("Winner:" not in output for output in outputs.values())


def test_explicit_hold_is_not_filled_by_ranking_or_rendering():
    rec = normalize_decision({
        "decision_status": "insufficient_evidence", "winner": "",
        "winner_rationale": "No versioned official evidence for the decisive item.",
        "recommendation": "Hold until versioned official evidence is obtained.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "unresolved_questions": ["Need versioned official audit evidence."],
    })
    assert rec["decision_status"] == INSUFFICIENT
    assert rec["winner"] == ""
    outputs = _render_all(rec)
    for output in outputs.values():
        assert "Winner:" not in output
        assert "hold" in output.lower() or "暂缓" in output


def test_invalid_model_output_is_not_a_valid_hold():
    rec = normalize_decision({
        "decision_status": "insufficient_evidence", "winner": "",
        "recommendation": "hold", "unresolved_questions": [],
        "ranked_options": [{"name": "Alpha", "rank": 1}],
    })
    assert rec["decision_status"] == INVALID
    outputs = _render_all(rec)
    assert all("Decision unavailable" in output or "决策未生成" in output
               for output in outputs.values())
    assert not any("Winner:" in output for output in outputs.values())


def test_self_review_withdrawal_enters_final_report(monkeypatch):
    rec = {
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "Unsupported decisive basis.",
        "recommendation": "Adopt Alpha.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "unresolved_questions": [],
        "confidence": "medium",
    }
    state = _state(rec)
    state["task"]["language"] = "zh"

    async def fake_call_model(prompt, **kwargs):
        return {
            "checks": [{"item": i, "passed": i != 1} for i in range(1, 7)],
            "passed_count": 5, "confidence": "low", "knowledge_gaps": [],
            "critical_gaps": ["versioned official evidence is missing"],
            "corrections": [{
                "option": "", "field": "decision_status",
                "action": "withdraw_decision",
                "reason": "No cited source supports the recommendation.",
            }],
        }
    monkeypatch.setattr(self_reviewer, "call_model", fake_call_model)
    out = asyncio.run(self_reviewer.SelfReviewerAgent().run(state))
    final = out["final_recommendation"]
    assert final["decision_status"] == INSUFFICIENT
    assert final["winner"] == ""
    assert "推荐已撤回" in final["winner_rationale"]
    assert "暂缓选型" in final["recommendation"]
    assert "Winner:" not in out["report"]
    assert "暂缓" in out["report"]


def test_failed_review_does_not_apply_withdrawal(monkeypatch):
    rec = {
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "basis", "recommendation": "Adopt Alpha.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "unresolved_questions": [], "confidence": "medium",
    }
    state = _state(rec)

    async def failing_call_model(prompt, **kwargs):
        raise RuntimeError("reviewer unavailable")
    monkeypatch.setattr(self_reviewer, "call_model", failing_call_model)
    out = asyncio.run(self_reviewer.SelfReviewerAgent().run(state))
    assert out["final_recommendation"]["decision_status"] == RECOMMENDED
    assert out["final_recommendation"]["winner"] == "Alpha"


def test_historical_record_is_displayed_without_deriving_a_winner():
    old_with_winner = {"winner": "Alpha", "recommendation": "Legacy recommendation."}
    before = copy.deepcopy(old_with_winner)
    outputs = _render_all(old_with_winner)
    assert any("Winner: Alpha" in output for output in outputs.values())
    assert old_with_winner == before

    old_without_winner = {"recommendation": "No winner was saved.",
                          "ranked_options": [{"name": "Alpha", "rank": 1}]}
    before = copy.deepcopy(old_without_winner)
    outputs = _render_all(old_without_winner)
    assert all("Winner:" not in output for output in outputs.values())
    assert old_without_winner == before


def test_constraint_fit_never_overrides_evidence_winner():
    rec = normalize_decision({
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "The cited source supports Alpha for this constraint.",
        "recommendation": "Adopt Alpha with the stated prerequisite.",
        "ranked_options": [
            {"name": "Alpha", "rank": 1, "constraint_fit": "low"},
            {"name": "Beta", "rank": 2, "constraint_fit": "high"},
        ],
        "confidence": "medium", "unresolved_questions": [],
    })
    assert rec["winner"] == "Alpha"
    assert rec["decision_status"] == RECOMMENDED


def test_self_review_withdrawal_is_consistent_in_all_three_renderers(monkeypatch):
    rec = {
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "Unsupported basis.", "recommendation": "Adopt Alpha.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "unresolved_questions": [], "confidence": "medium",
    }
    state = _state(rec)
    state["task"]["language"] = "zh"

    async def fake_call_model(prompt, **kwargs):
        return {
            "checks": [{"item": i, "passed": True} for i in range(1, 7)],
            "passed_count": 6, "confidence": "low", "knowledge_gaps": [],
            "corrections": [{
                "option": "", "field": "decision_status",
                "action": "withdraw_decision",
                "reason": "No cited source supports the recommendation.",
            }],
        }
    monkeypatch.setattr(self_reviewer, "call_model", fake_call_model)
    out = asyncio.run(self_reviewer.SelfReviewerAgent().run(state))
    final = out["final_recommendation"]
    assert final["decision_status"] == INSUFFICIENT
    outputs = _render_all(final)
    for output in outputs.values():
        assert "Winner:" not in output
        assert "暂缓" in output or "hold" in output.lower()


def test_self_review_cannot_replace_a_winner_with_another_product(monkeypatch):
    rec = {
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "basis", "recommendation": "Adopt Alpha.",
        "ranked_options": [{"name": "Alpha", "rank": 1},
                           {"name": "Beta", "rank": 2}],
        "unresolved_questions": [], "confidence": "medium",
    }
    applied, rejected = self_reviewer._apply_corrections(
        rec,
        [{"option": "", "field": "winner", "action": "revise",
          "corrected": "Beta", "reason": "unsupported"}],
        language="zh",
    )
    assert applied == []
    assert rejected
    assert rec["winner"] == "Alpha"


def test_parse_failure_is_invalid_not_a_hold():
    rec = normalize_decision(["not", "an", "object"])
    assert rec["decision_status"] == INVALID
    assert rec["winner"] == ""
    outputs = _render_all(rec)
    assert all("Decision unavailable" in output or "决策未生成" in output
               for output in outputs.values())


def test_self_review_cannot_turn_invalid_output_into_a_hold(monkeypatch):
    rec = normalize_decision({
        "decision_status": "insufficient_evidence", "winner": "",
        "recommendation": "hold", "unresolved_questions": [],
    })
    assert rec["decision_status"] == INVALID
    state = _state(rec)

    async def fake_call_model(prompt, **kwargs):
        return {
            "checks": [{"item": i, "passed": True} for i in range(1, 7)],
            "passed_count": 6, "confidence": "low", "knowledge_gaps": [],
            "corrections": [{
                "option": "", "field": "decision_status",
                "action": "withdraw_decision",
                "reason": "try to turn invalid into hold",
            }],
        }
    monkeypatch.setattr(self_reviewer, "call_model", fake_call_model)
    out = asyncio.run(self_reviewer.SelfReviewerAgent().run(state))
    assert out["final_recommendation"]["decision_status"] == INVALID
    assert out["final_recommendation"]["winner"] == ""


def test_prompt_has_no_forced_winner_or_constraint_fit_override():
    from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
    assert "decision_status" in SYNTHESIS_PROMPT
    assert "winner MUST be the highest constraint-fit" not in SYNTHESIS_PROMPT
    assert "context_dependent" not in SYNTHESIS_PROMPT
