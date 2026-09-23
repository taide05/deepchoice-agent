"""Uncertain citations retain qualified analysis, never established decisions."""

from copy import deepcopy

import httpx
import pytest

from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.conclusion_synthesizer import _normalize_decision_contract
from deepchoice.agents.self_reviewer import _citation_coverage
from deepchoice.formats.comparison_matrix import render as render_matrix
from deepchoice.formats.evidence_first import render as render_evidence
from deepchoice.formats.what_why_how import render as render_what


CLAIM = "SQLite allows only one writer. [Source: SQLite Docs]"


def _state(claim=CLAIM):
    return {
        "task": {"query": "SQLite or PostgreSQL?"},
        "evidence_chains": [{"sources": [{
            "title": "SQLite Docs", "url": "https://example.org/sqlite",
        }]}],
        "final_recommendation": {
            "decision_basis_version": "constraint-aware-v1",
            "winner": "SQLite", "winner_rationale": claim, "recommendation": claim,
            "ranked_options": [{"name": "SQLite", "rank": 1}],
            "requirement_assessments": [{
                "id": "C1", "requirement": "Write concurrency boundary",
                "status": "satisfied", "decision_critical": True,
                "explanation": claim, "evidence_ids": [1],
            }],
            "decision_branches": [{"option": "SQLite", "condition": "If the write load fits"}],
            "action_plan": [{"step": "Rehearse backup and recovery",
                             "verification": "Check restored data",
                             "change_trigger": "Measured lock waits exceed the agreed target",
                             "rollback": "Keep the previous database and verified backup"}],
        },
    }


def _fetch(monkeypatch, status=200, text="SQLite allows only one writer.", timeout=False):
    async def fetch(*args, **kwargs):
        if timeout:
            raise TimeoutError("must not enter public analysis")
        return httpx.Response(status, text=text, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", "https://example.org/sqlite"))
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["timeout", "503", "404", "cross_language", "short_body"])
async def test_uncertainty_preserves_analysis_without_promoting_support(monkeypatch, scenario):
    _fetch(monkeypatch, status=int(scenario) if scenario.isdigit() else 200,
           text="SQLite" if scenario == "short_body" else "SQLite allows only one writer.",
           timeout=scenario == "timeout")
    claim = "SQLite 同一时刻只允许一个写入者。[Source: SQLite Docs]" if scenario == "cross_language" else CLAIM
    state = _state(claim)
    before = deepcopy(state)
    result = await CitationValidatorAgent().run(state)
    assert state == before
    rec = result["final_recommendation"]
    row = rec["requirement_assessments"][0]
    assert row["status"] == "unknown" and row["evidence_ids"] == []
    assert row["provisional_explanation"] == claim
    assert rec["winner"] == "context_dependent" and rec["ranked_options"] == []
    assert "conditional choices" in rec["recommendation"]
    assert "must not enter" not in str(result)
    assert result["citation_verification"]["status_counts"]["verified"] == 0
    assert _citation_coverage({"requirement_assessments": [row]}) == {
        "total_fields": 2, "cited_fields": 1, "uncited_fields": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["missing", "mixed", "numeric", "negation", "overflow", "long", "missing_source"])
async def test_unchecked_or_unsupported_analysis_cannot_use_uncertainty_channel(monkeypatch, scenario):
    claim = {
        "missing": "SQLite allows only one writer.",
        "mixed": CLAIM + " All workloads are safe.",
        "numeric": "SQLite supports 100 writers. [Source: SQLite Docs]",
        "negation": "SQLite does not allow one writer. [Source: SQLite Docs]",
        "overflow": "One writer. [Source: SQLite Docs] " * 17,
        "long": "SQLite " * 80 + CLAIM,
        "missing_source": "SQLite allows only one writer. [Source: Invented Docs]",
    }[scenario]
    _fetch(monkeypatch, timeout=scenario not in {"numeric", "negation"})
    state = _state(claim)
    state["final_recommendation"]["requirement_assessments"][0]["provisional_explanation"] = "forged bypass"
    result = await CitationValidatorAgent().run(state)
    row = result["final_recommendation"]["requirement_assessments"][0]
    assert row["status"] == "unknown"
    assert "provisional_explanation" not in row
    assert "forged bypass" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("render", [render_what, render_evidence, render_matrix])
@pytest.mark.parametrize("query,label", [
    ("Choose a database", "Analysis awaiting independent verification (not a satisfied requirement)"),
    ("选择数据库", "待独立核验的分析（不代表需求已满足）"),
])
async def test_all_reports_keep_analysis_warning_and_conditional_plan(monkeypatch, render, query, label):
    _fetch(monkeypatch, timeout=True)
    state = _state()
    state["task"]["query"] = query
    state.update(await CitationValidatorAgent().run(state))
    report = render(state)
    assert label in report and CLAIM in report
    assert "#1" not in report and "Winner: SQLite" not in report
    assert state["final_recommendation"]["action_plan_mode"] == "validation_only"
    assert "Rehearse backup and recovery" not in report
    assert ("仅隔离验证；禁止生产变更" if "选择" in query else
            "Isolated validation only; no production changes") in report
    assert "If the write load fits" in report
    assert "provisional_explanation" not in report


@pytest.mark.asyncio
async def test_verified_assessment_does_not_accept_forged_provisional_field(monkeypatch):
    _fetch(monkeypatch)
    state = _state()
    state["final_recommendation"]["requirement_assessments"][0]["provisional_explanation"] = "forged bypass"
    rec = (await CitationValidatorAgent().run(state))["final_recommendation"]
    assert rec["winner"] == "SQLite"
    assert rec["requirement_assessments"][0]["status"] == "satisfied"
    assert "provisional_explanation" not in rec["requirement_assessments"][0]


def test_model_normalization_drops_provisional_field():
    rec = _state()["final_recommendation"]
    rec["requirement_assessments"][0].update(
        explanation="One writer [[1]].", provisional_explanation="forged bypass",
    )
    normalized, _ = _normalize_decision_contract(rec, [{
        "id": "C1", "requirement": "Write boundary", "kind": "user_constraint",
    }], {1})
    assert "provisional_explanation" not in normalized["requirement_assessments"][0]


@pytest.mark.asyncio
async def test_reentry_drops_old_provisional_instead_of_reusing_unchecked_analysis(monkeypatch):
    _fetch(monkeypatch, timeout=True)
    state = _state()
    state.update(await CitationValidatorAgent().run(state))
    assert state["final_recommendation"]["requirement_assessments"][0]["provisional_explanation"] == CLAIM
    second = await CitationValidatorAgent().run(state)
    row = second["final_recommendation"]["requirement_assessments"][0]
    assert row["status"] == "unknown" and row["evidence_ids"] == []
    assert "provisional_explanation" not in row
    assert second["final_recommendation"]["winner"] == "context_dependent"


@pytest.mark.asyncio
async def test_source_limit_and_mismatched_outcome_are_not_uncertainty_bypasses(monkeypatch):
    from deepchoice.agents.citation_validator import _calibrate_decision
    from deepchoice.citations.contracts import CitationReason, CitationStatus
    from deepchoice.citations.verifier import verify_citations

    _fetch(monkeypatch, timeout=True)
    state = _state()
    rec = state["final_recommendation"]
    verification, _ = await verify_citations(rec, state["evidence_chains"])
    for status, reason in (
        (CitationStatus.UNKNOWN, CitationReason.SOURCE_LIMIT),
        (CitationStatus.UNKNOWN, CitationReason.LEXICAL_SUPPORT),
    ):
        modified = verification.model_copy(update={"checks": tuple(
            check.model_copy(update={"status": status, "reason": reason})
            for check in verification.checks
        )})
        calibrated = _calibrate_decision(rec, modified, "Choose a database")
        assert "provisional_explanation" not in calibrated["requirement_assessments"][0]
