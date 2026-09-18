"""Offline scope regressions; model outputs here are fixtures, not semantic proof."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import conflict_detector as detector
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.budget import BudgetExceededError, BudgetResource


def _source(title, snippet="Compared under one stated workload", score=7):
    return {"title": title, "snippet": snippet, "url": "https://example.com/docs",
            "total_score": score, "scores": {"authority": 7}, "evidence_type": "citation"}


@pytest.mark.asyncio
@pytest.mark.parametrize("pair_title", ["Alpha-Store-vs-BetaDB", "Alpha_Store_vs_BetaDB"])
async def test_local_pair_scope_uses_entire_requested_comparison_not_snippet_mentions(pair_title):
    state = {
        "task": {"candidate_techs": ["Alpha Store", "BetaDB"]},
        "search_results": [{"source": "chroma", "status": "success", "results": [
            {"title": "Alpha-Store-vs-GammaDB", "snippet": "Includes BetaDB search keywords",
             "url": "file:///knowledge/one.md"},
            {"title": pair_title, "snippet": "A bounded local comparison",
             "url": "file:///knowledge/two.md"},
            {"title": "BetaDB backup documentation", "snippet": "Capability documentation",
             "url": "https://docs.example.com/backup"},
        ]}, {"source": "community", "status": "failed", "results": [], "error": "failure"}],
    }
    original = deepcopy(state)
    result = await SourceEvaluatorAgent().run(state)
    assert state == original
    assert {item["title"] for item in result["source_scores"]} == {
        pair_title, "BetaDB backup documentation"}
    assert result["quality_signals"][0]["candidate_excluded_count"] == 1
    local = next(item for item in result["source_scores"] if item["url"].startswith("file:"))
    assert local["source_type"] == "tech_blog" and local["scores"]["authority"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("candidates", [[], ["Alpha"]])
async def test_local_pair_legacy_and_single_candidate_scope_is_preserved(candidates):
    state = {"task": {"candidate_techs": candidates}, "search_results": [{
        "source": "chroma", "results": [{"title": "Alpha-vs-Gamma", "snippet": "notes",
                                          "url": "file:///knowledge/pair.md"}]}]}
    assert len((await SourceEvaluatorAgent().run(state))["source_scores"]) == 1


@pytest.mark.asyncio
async def test_http_comparison_is_not_treated_as_a_local_pair_template():
    state = {"task": {"candidate_techs": ["Alpha", "Beta"]}, "search_results": [{
        "source": "chroma", "results": [{"title": "Alpha-vs-Gamma", "snippet": "Alpha capability",
                                          "url": "https://docs.example.com/comparison"}]}]}
    result = await SourceEvaluatorAgent().run(state)
    assert len(result["source_scores"]) == 1
    assert result["source_scores"][0]["source_type"] == "official_doc"


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["node-postgres-vs-pg_vector", "node-postgres_vs_pg_vector"])
async def test_local_pair_preserves_hyphens_and_underscores_inside_candidate_identifiers(title):
    state = {"task": {"candidate_techs": ["node-postgres", "pg_vector"]}, "search_results": [{
        "source": "chroma", "results": [{"title": title, "snippet": "Comparison notes",
                                          "url": "file:///knowledge/pair.md"}]}]}
    result = await SourceEvaluatorAgent().run(state)
    assert [item["title"] for item in result["source_scores"]] == [title]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_title", [None, "", "\\N", "null", "N/A"])
@pytest.mark.parametrize("path_prefix", ["file:///knowledge/", "file:///D:\\knowledge\\"])
async def test_missing_local_pair_title_cannot_bypass_known_filename_scope(missing_title, path_prefix):
    state = {"task": {"candidate_techs": ["Alpha Store", "BetaDB"]}, "search_results": [{
        "source": "chroma", "results": [
            {"title": missing_title, "snippet": "BetaDB keyword",
             "url": path_prefix + "Gamma-vs-BetaDB.md"},
            {"title": missing_title, "snippet": "BetaDB comparison",
             "url": path_prefix + "Alpha%20Store-vs-BetaDB.md"},
        ]}]}
    original = deepcopy(state)
    result = await SourceEvaluatorAgent().run(state)
    assert state == original
    assert len(result["source_scores"]) == 1
    scored = result["source_scores"][0]
    assert scored["url"].endswith("Alpha%20Store-vs-BetaDB.md")
    assert scored["title"].startswith("Untitled source (")
    assert result["quality_signals"][0]["candidate_excluded_count"] == 1


@pytest.mark.asyncio
async def test_real_local_title_remains_scope_authority_over_its_filename():
    state = {"task": {"candidate_techs": ["Alpha", "Beta"]}, "search_results": [{
        "source": "chroma", "results": [
            {"title": "Alpha-vs-Beta", "snippet": "Beta notes",
             "url": "file:///knowledge/Gamma-vs-Beta.md"},
            {"title": "Gamma-vs-Beta", "snippet": "Alpha and Beta keywords",
             "url": "file:///knowledge/Alpha-vs-Beta.md"},
        ]}]}
    result = await SourceEvaluatorAgent().run(state)
    assert [item["title"] for item in result["source_scores"]] == ["Alpha-vs-Beta"]


@pytest.mark.asyncio
async def test_malformed_missing_title_filename_is_excluded_without_hiding_valid_source():
    state = {"task": {"candidate_techs": ["Alpha", "Beta"]}, "search_results": [{
        "source": "chroma", "status": "success", "results": [
            {"title": None, "snippet": "Alpha and Beta comparison",
             "url": "file://[bad/Alpha-vs-Beta.md"},
            {"title": None, "snippet": "Alpha and Beta comparison",
             "url": "file:///knowledge/Alpha-vs-Beta.md"},
        ]}]}
    original = deepcopy(state)
    result = await SourceEvaluatorAgent().run(state)
    assert state == original
    assert len(result["source_scores"]) == 1
    assert result["source_scores"][0]["url"] == "file:///knowledge/Alpha-vs-Beta.md"
    assert result["quality_signals"][0]["candidate_excluded_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [
    {"has_difference": True, "type": "vendor_bias", "explanation": "Vendor identity"},
    {"has_difference": True, "type": "none", "explanation": "Different workloads"},
    {"has_difference": "true", "type": "tradeoff_disagreement", "explanation": "Invalid boolean"},
])
async def test_scan_rejects_noncontradictions_and_malformed_truth_flag(monkeypatch, result):
    monkeypatch.setattr(detector, "call_model", AsyncMock(return_value=result))
    assert await detector._scan_pair_contradiction(
        _source("Alpha bulk throughput", "Bulk load throughput is high"),
        _source("Beta low latency", "Interactive latency is low"), "Choose a store") is None


@pytest.mark.asyncio
async def test_scan_missing_descriptions_cannot_turn_titles_into_claims(monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(detector, "call_model", call)
    assert await detector._scan_pair_contradiction(
        _source("Pick Alpha", ""), _source("Pick Beta"), "Choose") is None
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_high_gap_remains_unresolved_without_new_calls_or_evidence_tools(monkeypatch):
    pair = {"source_a": _source("Alpha", score=10),
            "source_b": _source("Beta", score=5), "similarity": 0.9}
    monkeypatch.setattr(detector, "find_contradictions", AsyncMock(return_value=[pair]))
    call, gather = AsyncMock(), AsyncMock()
    monkeypatch.setattr(detector, "call_model", call)
    monkeypatch.setattr(detector, "_gather_evidence", gather)
    result = await detector.ConflictDetectorAgent().run({"task": {"query": "Choose"}})
    conflict = result["conflicts"][0]
    assert conflict["resolution"] == "insufficient_data" and conflict["confidence"] == "low"
    assert result["quality_signals"][0]["resolved_count"] == 0
    call.assert_not_awaited()
    gather.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("intervening_failure", [False, True])
async def test_rearbitration_updates_original_close_pair_not_preceding_rule(monkeypatch, intervening_failure):
    rule_pair = {"source_a": _source("Rule A", score=10),
                 "source_b": _source("Rule B", score=5), "similarity": 0.9}
    close_pair = {"source_a": _source("Close A"),
                  "source_b": _source("Close B"), "similarity": 0.8}
    pairs = [rule_pair]
    results = []
    if intervening_failure:
        pairs.append({"source_a": _source("Failed A"),
                      "source_b": _source("Failed B"), "similarity": 0.85})
        results.append(RuntimeError("fixture failed arbitration"))
    pairs.append(close_pair)
    results.extend([
        {"resolution": "insufficient_data", "confidence": "low"},
        {"resolution": "both_partial", "confidence": "high"},
    ])
    monkeypatch.setattr(detector, "find_contradictions", AsyncMock(return_value=pairs))
    call = AsyncMock(side_effect=results)
    gather = AsyncMock(return_value="Direct comparable fixture evidence")
    monkeypatch.setattr(detector, "call_model", call)
    monkeypatch.setattr(detector, "_gather_evidence", gather)
    result = await detector.ConflictDetectorAgent().run({"task": {"query": "Choose"}})
    rule, revised = result["conflicts"]
    assert rule["claim_a"] == "Rule A" and rule["claim_b"] == "Rule B"
    assert rule["resolution"] == "insufficient_data" and rule["evidence_collected"] == ""
    assert rule["arbiter_model"] == "deepseek-flash(rule)"
    assert revised["claim_a"] == "Close A" and revised["claim_b"] == "Close B"
    assert revised["resolution"] == "both_partial"
    assert revised["arbiter_model"] == "deepseek-flash+evidence"
    assert revised["evidence_collected"] == "Direct comparable fixture evidence"
    gather.assert_awaited_once()
    assert gather.await_args.kwargs["claim_a"] == "Close A"
    assert gather.await_args.kwargs["claim_b"] == "Close B"


@pytest.mark.asyncio
async def test_close_score_arbitration_receives_actual_text_and_retains_existing_budget_failure(monkeypatch):
    pair = {"source_a": _source("Alpha capability", "Alpha accepts one writer"),
            "source_b": _source("Beta capability", "Beta accepts multiple writers"), "similarity": 0.9}
    monkeypatch.setattr(detector, "find_contradictions", AsyncMock(return_value=[pair]))
    denial = BudgetExceededError(BudgetResource.LLM_CALLS, limit=96, consumed=96, requested=1)
    call = AsyncMock(side_effect=denial)
    monkeypatch.setattr(detector, "call_model", call)
    with pytest.raises(BudgetExceededError) as caught:
        await detector.ConflictDetectorAgent(gather_evidence=False).run({"task": {"query": "Choose"}})
    assert caught.value is denial
    messages = call.await_args.args[0]
    assert "Alpha accepts one writer" in messages[1]["content"]
    assert "Beta accepts multiple writers" in messages[1]["content"]
    assert call.await_args.kwargs["tag"] == "conflict_arbitration"
