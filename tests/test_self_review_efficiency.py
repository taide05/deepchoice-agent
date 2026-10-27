"""Opt-in self-review cost experiments: trigger skip and self-review-only budget.

Default behaviour (mode=full, shared evidence budget) is unchanged; these tests
cover the experiment switches used by the off-peak A/B validation.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deepchoice.agents import self_reviewer as sr
from deepchoice.utils.candidate_identity import shared_evidence_package


def _state(**overrides):
    rec = {
        "decision_status": "conditional",
        "winner": "",
        "winner_rationale": "differs by deployment",
        "recommendation": "分支A选A，分支B选B。",
        "confidence": "low",
        "confidence_rationale": "证据有限",
        "ranked_options": [{"name": "A", "rank": 1}, {"name": "B", "rank": 2}],
        "trade_offs": [],
        "unresolved_questions": [],
    }
    state = {
        "task": {"query": "A vs B", "scene_context": "team",
                 "constraints": [], "candidate_techs": ["A", "B"]},
        "evidence_chains": [],
        "final_recommendation": rec,
        "confidence": "low",
        "knowledge_gaps": [],
        "quality_signals": [],
        "token_usage": [],
        "conflicts": [],
        "retry_count": 0,
        "report": "# A vs B\n" + "[Source: x] " * 25,
    }
    state.update(overrides)
    return state


def _review_json():
    return {
        "checks": [{"item": i, "passed": True, "note": "ok"} for i in range(1, 7)],
        "passed_count": 6,
        "confidence": "medium",
        "knowledge_gaps": [],
        "critical_gaps": [],
        "corrections": [],
    }


def test_default_mode_still_reviews(monkeypatch):
    monkeypatch.delenv("SELF_REVIEW_MODE", raising=False)
    with patch.object(sr, "call_model", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _review_json()
        out = asyncio.run(sr.SelfReviewerAgent().run(_state()))
    assert mock_llm.await_count == 1
    signal = out["quality_signals"][0]
    assert signal["review_status"] == "completed"
    assert signal["review_mode"] == "full"


def test_triggered_mode_skips_low_risk_case_without_calling_model(monkeypatch):
    monkeypatch.setenv("SELF_REVIEW_MODE", "triggered")
    with patch.object(sr, "call_model", new_callable=AsyncMock) as mock_llm:
        out = asyncio.run(sr.SelfReviewerAgent().run(_state()))
    assert mock_llm.await_count == 0
    signal = out["quality_signals"][0]
    assert signal["review_status"] == "skipped_by_trigger"
    assert signal["review_mode"] == "triggered"
    assert signal["skip_reason"] == "skip:low_risk"
    assert out["retry_count"] == 0
    assert out["final_recommendation"]["recommendation"] == "分支A选A，分支B选B。"


def test_triggered_mode_reviews_invalid_decision(monkeypatch):
    monkeypatch.setenv("SELF_REVIEW_MODE", "triggered")
    state = _state()
    state["final_recommendation"]["decision_status"] = "invalid"
    with patch.object(sr, "call_model", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _review_json()
        out = asyncio.run(sr.SelfReviewerAgent().run(state))
    assert mock_llm.await_count == 1
    assert out["quality_signals"][0]["review_status"] == "completed"


def test_triggered_mode_reviews_when_conflicts_recorded(monkeypatch):
    monkeypatch.setenv("SELF_REVIEW_MODE", "triggered")
    state = _state(conflicts=[{"claim_a": "x", "claim_b": "y"}])
    with patch.object(sr, "call_model", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _review_json()
        out = asyncio.run(sr.SelfReviewerAgent().run(state))
    assert mock_llm.await_count == 1
    assert out["quality_signals"][0]["review_status"] == "completed"


def test_self_review_only_budget_is_passed_to_package(monkeypatch):
    monkeypatch.setenv("SELF_REVIEW_MODE", "full")
    monkeypatch.setenv("SELF_REVIEW_EVIDENCE_BUDGET_CHARS", "8000")
    captured = {}
    real = shared_evidence_package

    def spy(entries, focus_terms=None, budget_chars=None):
        captured["budget_chars"] = budget_chars
        return real(entries, focus_terms=focus_terms, budget_chars=budget_chars)

    monkeypatch.setattr(
        "deepchoice.utils.candidate_identity.shared_evidence_package", spy)
    with patch.object(sr, "call_model", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _review_json()
        out = asyncio.run(sr.SelfReviewerAgent().run(_state(evidence_chains=[{
            "sources": [{"title": "S", "url": "https://s.example/doc",
                         "snippet": "bounded body", "has_body": True}],
        }])))
    assert captured.get("budget_chars") == 8000
    assert out["quality_signals"][0]["evidence_input_budget_chars"] == 8000


def test_output_constraint_is_opt_in_and_appears_in_prompt(monkeypatch):
    monkeypatch.delenv("SELF_REVIEW_OUTPUT_CONSTRAINT", raising=False)
    captured = {}

    async def fake_call(prompt, **kwargs):
        captured.setdefault("prompts", []).append(str(prompt))
        return _review_json()

    with patch.object(sr, "call_model", fake_call):
        asyncio.run(sr.SelfReviewerAgent().run(_state()))
    assert "Cost Experiment Output Constraint" not in captured["prompts"][0]

    monkeypatch.setenv("SELF_REVIEW_OUTPUT_CONSTRAINT", "1")
    captured.clear()
    with patch.object(sr, "call_model", fake_call):
        asyncio.run(sr.SelfReviewerAgent().run(_state()))
    assert "Cost Experiment Output Constraint" in captured["prompts"][0]
    assert "at most 20 words" in captured["prompts"][0]
