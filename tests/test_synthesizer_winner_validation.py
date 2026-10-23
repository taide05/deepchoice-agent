"""Unified decision contract: recommended / conditional / insufficient / invalid."""
import asyncio
import copy

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import self_reviewer
from deepchoice.agents.conclusion_synthesizer import normalize_decision
from deepchoice.formats import comparison_matrix, evidence_first, what_why_how
from deepchoice.formats.basis import used_sources
from deepchoice.formats.citations import inject_citations, number_sources
from deepchoice.utils.decision import (
    CONDITIONAL, INSUFFICIENT, INVALID, RECOMMENDED,
    decision_view,
)

SOURCE = "https://source.example/doc"
CHAINS = [{"sources": [{"title": "Source", "url": SOURCE,
                        "snippet": "bounded source body", "has_body": True}]}]


def _state(rec, chains=None, candidates=None):
    return {"task": {"query": "choose a tool", "report_format": "what_why_how",
                      "candidate_techs": candidates or []},
            "evidence_chains": chains or CHAINS, "conflicts": [],
            "quality_signals": [], "knowledge_gaps": [],
            "final_recommendation": rec,
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


def test_malformed_ranked_options_are_invalid_and_render_safely():
    malformed = [
        None,
        1,
        "Alpha",
        [None],
        [{}],
        [{"name": ""}],
        ["Alpha"],
        [{"name": "Alpha"}, {"name": "alpha"}],
    ]
    for raw in malformed:
        rec = normalize_decision({
            "decision_status": "recommended", "winner": "Alpha",
            "winner_rationale": "basis", "recommendation": "Adopt Alpha.",
            "ranked_options": raw, "unresolved_questions": [],
        }, declared_candidates=["Alpha", "Beta"])
        assert rec["decision_status"] == INVALID, raw
        assert rec["winner"] == "", raw
        assert rec["ranked_options"] == [], raw
        outputs = _render_all(rec)
        assert all("Winner:" not in output for output in outputs.values()), raw


def test_declared_candidate_identity_is_exact_not_substring():
    good = normalize_decision({
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "basis", "recommendation": "Adopt Alpha.",
        "ranked_options": [{"name": "Alpha"}, {"name": "Beta"}],
        "unresolved_questions": [],
    }, declared_candidates=["Alpha", "Beta"])
    assert good["decision_status"] == RECOMMENDED
    assert good["winner"] == "Alpha"

    for winner in ("Al", "Alpha Cloud", "AlphaBeta", "Gamma"):
        bad = normalize_decision({
            "decision_status": "recommended", "winner": winner,
            "winner_rationale": "basis", "recommendation": "Adopt it.",
            "ranked_options": [{"name": "Alpha"}, {"name": "Beta"}],
            "unresolved_questions": [],
        }, declared_candidates=["Alpha", "Beta"])
        assert bad["decision_status"] == INVALID, winner
        assert bad["winner"] == "", winner


def test_real_synthesis_agent_rejects_winner_outside_declared_candidates(monkeypatch):
    state = {
        "task": {"query": "choose a tool", "candidate_techs": ["Alpha", "Beta"],
                 "scene_context": "team", "constraints": []},
        "sub_questions": [], "evidence_chains": CHAINS, "source_scores": [],
        "conflicts": [], "conflict_check": {}, "token_usage": [],
    }

    async def fake_call_model(prompt, **kwargs):
        return {
            "decision_status": "recommended", "winner": "Alpha Cloud",
            "winner_rationale": "basis", "recommendation": "Adopt Alpha Cloud.",
            "ranked_options": [{"name": "Alpha"}, {"name": "Beta"}],
            "unresolved_questions": [],
        }
    monkeypatch.setattr(cs, "call_model", fake_call_model)
    out = asyncio.run(cs.ConclusionSynthesizerAgent().run(state))
    rec = out["final_recommendation"]
    assert rec["decision_status"] == INVALID
    assert rec["winner"] == ""


def test_declared_candidate_identity_preserves_symbol_names():
    base = {
        "decision_status": "recommended", "winner_rationale": "basis",
        "recommendation": "Adopt it.",
        "ranked_options": [{"name": "C++"}, {"name": "C#"}],
        "unresolved_questions": [],
    }
    for name in ("C++", "C#", "c++"):
        rec = normalize_decision({**base, "winner": name},
                                 declared_candidates=["C++", "C#"])
        assert rec["decision_status"] == RECOMMENDED, name
        assert rec["winner"] == name
    for name in ("C", "C+", "C Sharp"):
        rec = normalize_decision({**base, "winner": name},
                                 declared_candidates=["C++", "C#"])
        assert rec["decision_status"] == INVALID, name
    duplicate = normalize_decision({
        "decision_status": "conditional", "winner": "",
        "winner_rationale": "branches", "recommendation": "branch",
        "ranked_options": [{"name": "C++"}, {"name": "c++"}],
        "unresolved_questions": [],
    }, declared_candidates=["C++", "C#"])
    assert duplicate["decision_status"] == INVALID


def test_conditional_requires_two_distinct_declared_candidates():
    good = normalize_decision({
        "decision_status": "conditional", "winner": "",
        "winner_rationale": "branches",
        "recommendation": "Alpha for cloud; Beta for offline.",
        "ranked_options": [{"name": "Alpha"}, {"name": "Beta"}],
        "unresolved_questions": [],
    }, declared_candidates=["Alpha", "Beta"])
    assert good["decision_status"] == CONDITIONAL

    for options in (
        [{"name": "Alpha"}],
        [{"name": "Alpha"}, {"name": "Alpha"}],
        [{"name": "Alpha"}, {"name": "Gamma"}],
    ):
        bad = normalize_decision({
            "decision_status": "conditional", "winner": "",
            "winner_rationale": "branches",
            "recommendation": "Alpha for cloud; Gamma for offline.",
            "ranked_options": options, "unresolved_questions": [],
        }, declared_candidates=["Alpha", "Beta"])
        assert bad["decision_status"] == INVALID, options

    open_contract = normalize_decision({
        "decision_status": "conditional", "winner": "",
        "winner_rationale": "branches",
        "recommendation": "Any for cloud; Other for offline.",
        "ranked_options": [{"name": "Any"}, {"name": "Other"}],
        "unresolved_questions": [],
    })
    assert open_contract["decision_status"] == CONDITIONAL


def test_real_synthesis_agent_returns_invalid_for_malformed_structure(monkeypatch):
    state = {
        "task": {"query": "choose a tool", "candidate_techs": ["Alpha", "Beta"],
                 "scene_context": "team", "constraints": []},
        "sub_questions": [], "evidence_chains": CHAINS, "source_scores": [],
        "conflicts": [], "conflict_check": {}, "token_usage": [],
    }

    async def fake_call_model(prompt, **kwargs):
        return {
            "decision_status": "recommended", "winner": "Alpha",
            "winner_rationale": "basis", "recommendation": "Adopt Alpha.",
            "ranked_options": None, "unresolved_questions": [],
        }
    monkeypatch.setattr(cs, "call_model", fake_call_model)
    out = asyncio.run(cs.ConclusionSynthesizerAgent().run(state))
    rec = out["final_recommendation"]
    assert rec["decision_status"] == INVALID
    assert rec["winner"] == ""
    assert rec["ranked_options"] == []
    for renderer in (what_why_how.render, evidence_first.render,
                     comparison_matrix.render):
        rendered = renderer(_state(rec))
        assert "Winner:" not in rendered
        assert "Decision unavailable" in rendered or "决策未生成" in rendered


def test_withdrawal_clears_only_replaced_field_bindings(monkeypatch):
    url_a = "https://a.example/doc"
    url_b = "https://b.example/doc"
    chains = [{"sources": [
        {"title": "Alpha docs", "url": url_a, "snippet": "Alpha body",
         "has_body": True},
        {"title": "Beta docs", "url": url_b, "snippet": "Beta body",
         "has_body": True},
    ]}]
    rec = {
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "Alpha is supported [[1]]",
        "recommendation": "Adopt Alpha [[1]]",
        "ranked_options": [
            {"name": "Alpha", "rank": 1, "rationale": "Alpha fits [[2]]"},
            {"name": "Beta", "rank": 2, "rationale": "Beta fits [[2]]"},
        ],
        "unresolved_questions": [], "confidence": "medium",
    }
    cs.apply_citation_rules(rec, chains)
    assert set(rec[cs.CITATION_SOURCES_KEY]) >= {
        "recommendation", "winner_rationale", "option=Alpha/rationale"}
    state = _state(rec, chains=chains)

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
    assert "recommendation" not in final[cs.CITATION_SOURCES_KEY]
    assert "winner_rationale" not in final[cs.CITATION_SOURCES_KEY]
    assert "option=Alpha/rationale" in final[cs.CITATION_SOURCES_KEY]
    used = used_sources(final, chains)
    assert [src["url"] for src in used] == [url_b]
    for renderer in (what_why_how.render, evidence_first.render,
                     comparison_matrix.render):
        rendered = renderer(_state(final, chains=chains))
        assert url_a not in rendered
        assert url_b in rendered
    annotated = inject_citations(out["report"], number_sources(chains))
    assert url_a not in annotated
    assert "Alpha docs" not in annotated
    assert "Beta docs" in annotated


def test_withdrawal_new_text_reuses_the_binding_entry(monkeypatch):
    url_a = "https://a.example/doc"
    chains = [{"sources": [{"title": "Alpha docs", "url": url_a,
                             "snippet": "Alpha body", "has_body": True}]}]
    rec = {
        "decision_status": "recommended", "winner": "Alpha",
        "winner_rationale": "Alpha is supported [[1]]",
        "recommendation": "Adopt Alpha [[1]]",
        "ranked_options": [{"name": "Alpha", "rank": 1,
                            "rationale": "Alpha fits [[1]]"}],
        "unresolved_questions": [], "confidence": "medium",
    }
    cs.apply_citation_rules(rec, chains)

    async def fake_call_model(prompt, **kwargs):
        return {
            "checks": [{"item": i, "passed": True} for i in range(1, 7)],
            "passed_count": 6, "confidence": "low", "knowledge_gaps": [],
            "corrections": [{
                "option": "", "field": "decision_status",
                "action": "withdraw_decision",
                "reason": "Reviewer cites [[1]] as the unsupported basis.",
            }],
        }
    monkeypatch.setattr(self_reviewer, "call_model", fake_call_model)
    out = asyncio.run(self_reviewer.SelfReviewerAgent().run(
        _state(rec, chains=chains)))
    final = out["final_recommendation"]
    assert final[cs.CITATION_SOURCES_KEY]["winner_rationale"]
    assert final[cs.CITATION_SOURCES_KEY]["winner_rationale"][0]["url"] == url_a
    assert "recommendation" not in final[cs.CITATION_SOURCES_KEY]


def test_prompt_has_no_forced_winner_or_constraint_fit_override():
    from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
    assert "decision_status" in SYNTHESIS_PROMPT
    assert "winner MUST be the highest constraint-fit" not in SYNTHESIS_PROMPT
    assert "context_dependent" not in SYNTHESIS_PROMPT
