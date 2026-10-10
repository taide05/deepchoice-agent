"""Offline regressions for default conflict preservation; no network or weights."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from deepchoice.agents import conflict_detector as cd
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.budget import BudgetExceededError, BudgetResource
from deepchoice.contracts.manifest import build_run_manifest


def sources():
    return [{"title": "Comparable capacity", "snippet": text,
             "url": f"https://source{idx}.example/docs", "total_score": 7,
             "scores": {"authority": 6}}
            for idx, text in enumerate(["Alpha accepts one writer.", "Alpha accepts multiple writers."])]


def embeddings(monkeypatch):
    monkeypatch.setattr(cd, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda titles: np.ones((len(titles), 3))))


@pytest.mark.asyncio
@pytest.mark.parametrize("gather_requested", [True, False])
async def test_default_preserves_confirmed_pair_without_arbitration(monkeypatch, gather_requested):
    embeddings(monkeypatch)
    call = AsyncMock(side_effect=[{"has_difference": True, "type": "tradeoff_disagreement",
                                  "explanation": "Incompatible writer counts"},
                                 RuntimeError("arbitration provider private detail")])
    monkeypatch.setattr(cd, "call_model", call)
    result = await cd.ConflictDetectorAgent(gather_evidence=gather_requested).run(
        {"task": {"query": "Select a store"}, "source_scores": sources()})
    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["scan_status"] == "confirmed"
    assert conflict["resolution"] == "insufficient_data"
    assert conflict["confidence"] == "low"
    assert [c.kwargs["tag"] for c in call.await_args_list] == ["conflict_scan"]
    assert all(chain["disputed"] for chain in build_evidence_chain(sources(), result["conflicts"]))
    signal = result["quality_signals"][0]
    assert signal["resolved_count"] == 0 and signal["scan_unknown_count"] == 0
    assert signal["gather_evidence_requested"] is gather_requested
    assert signal["gather_evidence_effective"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [RuntimeError("secret PRIVATE_PROVIDER_PAYLOAD"), None,
    {"has_difference": "false", "type": "none", "explanation": "bad"},
    {"has_difference": True, "type": "none", "explanation": "bad"},
    {"has_difference": False, "type": "tradeoff_disagreement", "explanation": "bad"},
    {"has_difference": True, "type": "tradeoff_disagreement", "explanation": 42}])
async def test_failed_or_malformed_scan_is_unknown_and_excludes_pair(monkeypatch, value):
    embeddings(monkeypatch)
    call = AsyncMock(side_effect=value) if isinstance(value, Exception) else AsyncMock(return_value=value)
    monkeypatch.setattr(cd, "call_model", call)
    result = await cd.ConflictDetectorAgent(gather_evidence=False).run(
        {"task": {"query": "Select a store"}, "source_scores": sources()})
    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["scan_status"] == "unknown" and conflict["difference_type"] == "unknown"
    assert result["quality_signals"][0]["conflicts_found"] == 0
    assert result["quality_signals"][0]["scan_unknown_count"] == 1
    assert all(chain["disputed"] for chain in build_evidence_chain(sources(), result["conflicts"]))
    assert "PRIVATE_PROVIDER_PAYLOAD" not in json.dumps(result)
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_explicit_negative_is_not_unknown(monkeypatch):
    embeddings(monkeypatch)
    monkeypatch.setattr(cd, "call_model", AsyncMock(return_value={
        "has_difference": False, "type": "none", "explanation": "Different conditions"}))
    result = await cd.ConflictDetectorAgent().run(
        {"task": {"query": "Select a store"}, "source_scores": sources()})
    assert result["conflicts"] == []
    assert result["quality_signals"][0]["scan_unknown_count"] == 0


@pytest.mark.asyncio
async def test_missing_text_is_unknown_without_dispatch(monkeypatch):
    items = sources()
    items[0]["snippet"] = ""
    call = AsyncMock()
    monkeypatch.setattr(cd, "call_model", call)
    info = await cd._scan_pair_contradiction(*items, "fixture")
    assert info["scan_status"] == "unknown" and info["scan_reason"] == "missing_description"
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_budget_denial_propagates(monkeypatch):
    embeddings(monkeypatch)
    denial = BudgetExceededError(BudgetResource.LLM_CALLS, limit=96, consumed=96, requested=1)
    monkeypatch.setattr(cd, "call_model", AsyncMock(side_effect=denial))
    with pytest.raises(BudgetExceededError) as caught:
        await cd.ConflictDetectorAgent().run({"task": {"query": "fixture"}, "source_scores": sources()})
    assert caught.value is denial


@pytest.mark.parametrize("requested", [True, False])
def test_default_manifest_and_graph_exclude_legacy_calls(requested):
    task = {"query": "Select a store", "gather_evidence": requested}
    manifest = build_run_manifest(task)
    assert manifest.conflict_policy_version == "scan-only-v2"
    assert manifest.gather_evidence is requested
    assert {c.call_id for c in manifest.llm_calls}.isdisjoint({
        "conflict_arbitration", "conflict_evidence_gather", "conflict_rearbitration"})
    assert isinstance(ChiefEditorAgent(task)._initialize_agents()["conflict_detector"], cd.ConflictDetectorAgent)


@pytest.mark.asyncio
@pytest.mark.parametrize("scan_status", ["confirmed", "unknown"])
async def test_unresolved_scan_excludes_even_stale_undisputed_chains(monkeypatch, scan_status):
    from deepchoice.budget.limited import usable_evidence_chains
    items = sources()
    pair = {"source_a": items[0], "source_b": items[1], "similarity": 1,
            "scan_status": scan_status, "difference_type": "tradeoff_disagreement"}
    monkeypatch.setattr(cd, "find_contradictions", AsyncMock(return_value=[pair]))
    call = AsyncMock(side_effect=AssertionError("Scan findings must not trigger arbitration"))
    monkeypatch.setattr(cd, "call_model", call)
    result = await cd.ConflictDetectorAgent(gather_evidence=False).run(
        {"task": {"query": "fixture"}, "source_scores": items})
    chains = build_evidence_chain(items, result["conflicts"])
    assert all(c["disputed"] for c in chains)
    stale_chains = [dict(c, disputed=False) for c in chains]
    assert usable_evidence_chains({"evidence_chains": stale_chains, "conflicts": result["conflicts"]}) == []
    call.assert_not_awaited()


@pytest.mark.parametrize("renderer_name", ["what_why_how", "evidence_first", "comparison_matrix"])
def test_unknown_scan_is_explained_in_every_report(renderer_name):
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    items = sources()
    pair = {"source_a": items[0], "source_b": items[1], "similarity": 1,
            "scan_status": "unknown", "scan_reason": "scan_unavailable"}
    conflict = cd._unresolved_conflict(pair)
    report = FORMAT_RENDERERS[renderer_name]({"task": {"query": "Select a store"}, "conflicts": [conflict]})
    assert "Conflict scan unknown" in report and "no contradiction has been established" in report


def test_public_evidence_switch_is_deprecated_and_bounded():
    from deepchoice.contracts.api import ResearchRequest
    schema = ResearchRequest.model_json_schema()
    field = schema["properties"]["gather_evidence"]
    assert field["deprecated"] is True and "scan-only" in field["description"]
    assert ResearchRequest(query="fixture", gather_evidence=False).gather_evidence is False


@pytest.mark.parametrize("status,expected", [
    ("unknown", "scan unknown; contradiction not established"),
    ("confirmed", "scan flagged incompatible claims; unresolved"),
])
def test_synthesis_summary_preserves_scan_status(status, expected):
    from deepchoice.agents.conclusion_synthesizer import _summarize_conflicts
    items = sources()
    pair = {"source_a": items[0], "source_b": items[1], "similarity": 1, "scan_status": status}
    summary = _summarize_conflicts([cd._unresolved_conflict(pair)])
    assert expected in summary
    assert ("contradiction not established" in summary) == (status == "unknown")


@pytest.mark.asyncio
async def test_cancellation_propagates_from_scan(monkeypatch):
    import asyncio
    embeddings(monkeypatch)
    monkeypatch.setattr(cd, "call_model", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await cd.ConflictDetectorAgent().run(
            {"task": {"query": "fixture"}, "source_scores": sources()})


def test_retired_direct_agent_arbitration_is_rejected():
    with pytest.raises(TypeError, match="legacy_arbitration"):
        cd.ConflictDetectorAgent(legacy_arbitration=True)
