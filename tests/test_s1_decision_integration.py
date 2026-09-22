"""Offline contracts for decision evidence, restricted output and graph state."""

from copy import deepcopy

import httpx
import pytest
from langgraph.graph import END, StateGraph

from deepchoice.agents.evidence_decision_gate import _build_limited_report
from deepchoice.agents.evidence_decision_gate import should_request_evidence_decision
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.query_analyzer import QueryAnalyzerAgent
from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY, BudgetExceededError, BudgetResource
from deepchoice.budget.limited import build_budget_limited_state
from deepchoice.citations.verifier import _extract_claims, verify_citations
from deepchoice.state import ResearchState


@pytest.mark.asyncio
async def test_analyzed_constraints_survive_real_graph_state(monkeypatch):
    async def fake_model(*args, **kwargs):
        return {"constraints": ["Recover interrupted jobs safely"],
                "sub_questions": ["Who prevents duplicate job side effects?"]}

    monkeypatch.setattr("deepchoice.agents.query_analyzer.call_model", fake_model)
    graph = StateGraph(ResearchState)
    graph.add_node("analyze", QueryAnalyzerAgent().run)
    seen = {}

    def consume(state):
        seen.update(state)
        return {}

    graph.add_node("consume", consume)
    graph.set_entry_point("analyze")
    graph.add_edge("analyze", "consume")
    graph.add_edge("consume", END)
    await graph.compile().ainvoke({
        "task": {"query": "Compare background job queues", "constraints": ["Use Python"]},
    })
    assert seen["constraints"] == ["Recover interrupted jobs safely"]
    assert seen["task"]["constraints"] == ["Use Python"]
    assert seen["sub_questions"] == ["Who prevents duplicate job side effects?"]


def _state(fmt):
    return {
        "task": {"query": "Compare package tools", "report_format": fmt},
        "conflicts": [],
        "evidence_chains": [
            {"conclusion": "A saved finding", "disputed": False,
             "sources": [{"title": f"Docs {i}", "url": url, "score": 7,
                          "snippet": "A saved finding"}]}
            for i, url in enumerate(("https://a.example/1", "https://a.example/2",
                                     "https://b.example/3"))
        ],
        "final_recommendation": {
            "decision_basis_version": "constraint-aware-v1",
            "winner": "uv",
            "recommendation": "100% adopt uv immediately.",
            "winner_rationale": "uv is guaranteed best.",
            "scene_fit_note": "Always use uv.",
            "ranked_options": [{"name": "uv", "rank": 1}],
            "requirement_assessments": [{
                "id": "C1", "requirement": "Private index compatibility",
                "status": "satisfied", "decision_critical": True,
                "explanation": "100% guaranteed compatibility without testing.",
                "provisional_explanation": "Unchecked analysis must not survive a limited report.",
                "evidence_ids": [1],
            }],
            "decision_branches": [{"option": "uv", "condition": "Only if the pilot passes."}],
            "action_plan": [{"step": "Pilot one project",
                            "verification": "Compare lockfile and CI results",
                            "change_trigger": "Proceed only after compatibility checks",
                            "rollback": "Keep the Poetry lockfile for rollback"}],
            "unresolved_questions": ["Is the private index compatible?"],
        },
    }


@pytest.mark.parametrize("fmt", ["what_why_how", "evidence_first", "comparison_matrix"])
@pytest.mark.parametrize("limited_kind", ["hitl", "budget"])
def test_restricted_result_and_all_formats_drop_winner_preserve_plan(fmt, limited_kind):
    state = _state(fmt)
    before = deepcopy(state)
    if limited_kind == "hitl":
        result = _build_limited_report(state)
    else:
        result = build_budget_limited_state(
            state, request=state["task"], policy=DEFAULT_RUN_BUDGET_POLICY,
            error=BudgetExceededError(BudgetResource.LLM_CALLS, limit=96,
                                      consumed=96, requested=1),
        )
    assert state == before  # No mutation of accepted checkpoint input.
    rec = result["final_recommendation"]
    assert rec["winner"] == "context_dependent"
    assert rec["ranked_options"] == []
    assert rec["requirement_assessments"][0]["status"] == "unknown"
    assert rec["requirement_assessments"][0]["evidence_ids"] == []
    assert "provisional_explanation" not in rec["requirement_assessments"][0]
    assert "Unchecked analysis" not in result["report"]
    assert "100%" not in result["report"]
    assert "guaranteed best" not in result["report"]
    assert "Always use" not in result["report"]
    assert "#1 " not in result["report"]
    assert "Pilot one project" in result["report"]
    assert "Compare lockfile and CI results" in result["report"]
    assert "Poetry" in result["report"]


@pytest.mark.asyncio
async def test_new_decision_claims_share_one_bounded_fetch(monkeypatch):
    calls = []

    async def fetch(*args, **kwargs):
        calls.append(args)
        return httpx.Response(200, text="SQLite allows only one writer.",
                              headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", "https://example.org/sqlite"))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    claim = "SQLite allows only one writer. [Source: SQLite Docs]"
    rec = {
        "requirement_assessments": [{"explanation": claim}],
        "decision_branches": [{"condition": claim}],
        "action_plan": [{"step": claim, "verification": claim,
                         "change_trigger": claim, "rollback": claim}],
    }
    verification, _ = await verify_citations(rec, [{
        "sources": [{"title": "SQLite Docs", "url": "https://example.org/sqlite"}],
    }])
    assert len(calls) == 1
    assert verification.status_counts.verified == 6
    assert {check.claim_path for check in verification.checks} == {
        "final_recommendation.requirement_assessments[0].explanation",
        "final_recommendation.decision_branches[0].condition",
        *(f"final_recommendation.action_plan[0].{field}"
          for field in ("step", "verification", "change_trigger", "rollback")),
    }


def test_new_decision_claim_overflow_is_explicit_and_bounded():
    claims, truncated = _extract_claims({
        "requirement_assessments": [{"explanation": "Unknown premise."}] * 41,
        "action_plan": [{"step": "Validate compatibility."}] * 21,
    })
    assert truncated
    assert len(claims) == 60
    assert all("assessments[40]" not in claim.path for claim in claims)


def test_self_review_counts_new_factual_fields():
    from deepchoice.agents.self_reviewer import _citation_coverage

    assert _citation_coverage({
        "requirement_assessments": [{"explanation": "One writer [Source: SQLite Docs]"}],
        "decision_branches": [{"condition": "Compatibility is unknown"}],
        "action_plan": [{"verification": "Run a recovery check"}],
    }) == {"total_fields": 3, "cited_fields": 1, "uncited_fields": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 503, 404])
async def test_citation_outcome_calibrates_critical_premise_without_falsifying_it(monkeypatch, status):
    async def fetch(*args, **kwargs):
        return httpx.Response(status, text="SQLite allows only one writer.",
                              headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", "https://example.org/sqlite"))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    rec = {
        "decision_basis_version": "constraint-aware-v1",
        "winner": "SQLite", "winner_rationale": "SQLite allows only one writer. [Source: SQLite Docs]",
        "recommendation": "SQLite allows only one writer. [Source: SQLite Docs]",
        "ranked_options": [{"name": "SQLite", "rank": 1}],
        "requirement_assessments": [{
            "id": "C1", "requirement": "A single writer is enough", "status": "satisfied",
            "decision_critical": True, "explanation": "SQLite allows only one writer. [Source: SQLite Docs]",
            "evidence_ids": [1],
        }],
    }
    before = deepcopy(rec)
    out = await CitationValidatorAgent().run({
        "task": {"query": "SQLite or PostgreSQL?"},
        "final_recommendation": rec,
        "evidence_chains": [{"sources": [{
            "title": "SQLite Docs", "url": "https://example.org/sqlite",
        }]}],
    })
    assert rec == before
    calibrated = out["final_recommendation"]
    if status == 200:
        assert calibrated["winner"] == "SQLite"
        assert calibrated["requirement_assessments"][0]["status"] == "satisfied"
    else:
        assert calibrated["winner"] == "context_dependent"
        assert calibrated["ranked_options"] == []
        assert calibrated["requirement_assessments"][0]["status"] == "unknown"
        assert "Unknown:" in calibrated["requirement_assessments"][0]["explanation"]


def test_abstention_without_ranks_still_uses_the_single_structural_hitl_gate():
    state = {"final_recommendation": {
        "decision_basis_version": "constraint-aware-v1",
        "winner": "context_dependent", "ranked_options": [],
    }}
    assert should_request_evidence_decision(state)
    assert not should_request_evidence_decision({**state, "_evidence_decision_gate_seen": True})
    sufficient = _state("what_why_how")
    sufficient["final_recommendation"] = state["final_recommendation"]
    assert not should_request_evidence_decision(sufficient)


@pytest.mark.asyncio
async def test_supported_single_writer_choice_keeps_backup_and_migration_plan(monkeypatch):
    from deepchoice.agents.conclusion_synthesizer import ConclusionSynthesizerAgent
    from deepchoice.formats.what_why_how import render

    async def model(*args, **kwargs):
        return {
            "winner": "SQLite",
            "winner_rationale": "SQLite allows only one writer [[1]].",
            "recommendation": "SQLite allows only one writer [[1]].",
            "ranked_options": [{"name": "SQLite", "rank": 1, "constraint_fit": "high",
                                "rationale": "SQLite allows only one writer [[1]]."}],
            "requirement_assessments": [{
                "id": "C1", "status": "satisfied", "evidence_ids": [1],
                "explanation": "SQLite allows only one writer [[1]].",
            }],
            "decision_branches": [{"option": "SQLite", "condition": "One writer is sufficient"}],
            "action_plan": [{
                "step": "Rehearse a consistent backup",
                "verification": "Check restored data against the source database",
                "change_trigger": "Consider PostgreSQL after measured lock waits exceed the agreed target",
                "rollback": "Keep a verified database restore point",
            }],
        }

    async def fetch(*args, **kwargs):
        return httpx.Response(200, text="SQLite allows only one writer.",
                              headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", "https://example.org/sqlite"))

    monkeypatch.setattr("deepchoice.agents.conclusion_synthesizer.call_model", model)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = {
        "task": {"query": "SQLite or PostgreSQL for a small read-heavy application?",
                 "constraints": ["Only one writer required"]},
        "evidence_chains": [{"sources": [{
            "title": "SQLite Docs", "url": "https://example.org/sqlite",
            "snippet": "SQLite allows only one writer.",
        }]}],
    }
    state.update(await ConclusionSynthesizerAgent().run(state))
    state.update(await CitationValidatorAgent().run(state))
    report = render(state)
    assert state["final_recommendation"]["winner"] == "SQLite"
    assert "**Winner: SQLite**" in report
    assert "only one writer" in report
    assert "consistent backup" in report
    assert "measured lock waits" in report
    assert "verified database restore point" in report
    assert "Proposed validation plan" in report


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["recommendation", "confidence_rationale", "rationale", "finding", "overflow"])
async def test_verified_headline_cannot_mask_unsupported_decisive_prose(monkeypatch, location):
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text="SQLite allows only one writer.",
                              headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", "https://example.org/sqlite"))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    supported = "SQLite allows only one writer. [Source: SQLite Docs]"
    unsupported = "SQLite supports 100 concurrent writers. [Source: SQLite Docs]"
    rec = {
        "decision_basis_version": "constraint-aware-v1",
        "winner": "SQLite", "winner_rationale": supported, "recommendation": supported,
        "requirement_assessments": [],
        "ranked_options": [{"name": "SQLite", "rank": 1, "rationale": supported}],
        "trade_offs": [{"dimension": "Concurrency", "finding": supported}],
    }
    if location in ("recommendation", "confidence_rationale"):
        rec[location] = unsupported
    elif location == "rationale":
        rec["ranked_options"][0][location] = unsupported
    elif location == "finding":
        rec["trade_offs"][0][location] = unsupported
    else:
        rec["recommendation"] = " ".join([supported] * 17)
    out = await CitationValidatorAgent().run({
        "task": {"query": "SQLite or PostgreSQL?"},
        "final_recommendation": rec,
        "evidence_chains": [{"sources": [{"title": "SQLite Docs",
                                         "url": "https://example.org/sqlite"}]}],
    })
    calibrated = out["final_recommendation"]
    assert calibrated["winner"] == "context_dependent"
    assert calibrated["ranked_options"] == []
    assert calibrated["trade_offs"] == []
    assert "100 concurrent" not in calibrated["recommendation"]
