"""Offline conflict-coordinate regressions through the real scan and binding path."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import numpy as np
import pytest

from deepchoice.agents import conflict_detector as cd
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.conclusion_synthesizer import _usable_evidence_ids
from deepchoice.budget.limited import usable_evidence_chains
from deepchoice.utils.evidence_choices import bind_evidence_choices
from deepchoice.utils.fact_selection import selection_packet

SENTENCES = [
    "Atlas permits one writer at a time.",
    "Writer contention must be measured for the target workload.",
    "Administrators configure document retention and storage capacity before scheduling regular maintenance windows.",
    "Operators review the documented capacity policy and retain configuration history for changes to the workload.",
    "Documentation lists maintenance responsibilities and requires an explicit owner for recovery validation.",
    "Atlas can create encrypted snapshots of retained records.",
    "Restoring encrypted snapshots requires the original encryption key.",
    "Snapshot restoration must be validated in an isolated environment before production use.",
]


def scores(passages=False):
    result = []
    for idx in range(2):
        sentences = list(SENTENCES)
        if idx:
            sentences[0] = "Atlas permits multiple writers at a time."
        text = " ".join(sentences)
        row = {"title": f"Atlas capacity guide {idx}", "url": f"https://source{idx}.example/docs",
               "snippet": text, "total_score": 7, "scores": {"authority": 6}}
        if passages:
            row["passages"] = [text]
        result.append(row)
    return result


async def scanned(monkeypatch, *, ranges_a=None, ranges_b=None, passages=False):
    items = scores(passages)
    monkeypatch.setattr(cd, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda titles: np.ones((len(titles), 3))))
    call = AsyncMock(return_value={"has_difference": True, "type": "tradeoff_disagreement",
        "explanation": "Incompatible writer counts", "ranges_a": [[0, 1]] if ranges_a is None else ranges_a,
        "ranges_b": [[0, 1]] if ranges_b is None else ranges_b})
    monkeypatch.setattr(cd, "call_model", call)
    result = await cd.ConflictDetectorAgent().run({"task": {"query": "Choose Atlas configuration"},
                                               "source_scores": items})
    return items, result["conflicts"], build_evidence_chain(items, result["conflicts"]), call


@pytest.mark.asyncio
@pytest.mark.parametrize("passages", [False, True])
async def test_local_dispute_preserves_far_fact_and_full_conditions(monkeypatch, passages):
    items, conflicts, chains, call = await scanned(monkeypatch, passages=passages)
    original = deepcopy(chains)
    assert all(c["disputed"] for c in chains)
    packet, offered = selection_packet(chains)
    assert offered == {1, 2}
    assert '"whole_allowed":false' in packet
    assert '"conflict_ranges":[[0,1]]' in packet
    raw = {"source_facts": [{"id": "F1", "evidence_id": 1, "source_ranges": [[6, 7]]}]}
    facts = bind_evidence_choices(raw, chains, ["Atlas"], [])["source_facts"]
    assert len(facts) == 1
    assert facts[0]["saved_text"] == " ".join(SENTENCES[5:8])
    assert facts[0]["source_ranges"] == [[6, 7]] and facts[0]["status"] == "unknown"
    assert chains == original and chains[0]["sources"][0]["snippet"] == items[0]["snippet"]
    assert "original encryption key" in str(call.await_args.args[0])
    assert call.await_count == 1 and len(conflicts) == 1
    assert _usable_evidence_ids(chains) == set()
    assert usable_evidence_chains({"evidence_chains": chains, "conflicts": conflicts}) == []
    assert bind_evidence_choices(json.loads(json.dumps({"source_facts": facts})), chains, ["Atlas"], [])["source_facts"] == facts


@pytest.mark.asyncio
@pytest.mark.parametrize("ranges", [None, [[0, 1]], [[1, 2]]])
async def test_whole_conflicting_and_adjacent_facts_stay_excluded(monkeypatch, ranges):
    _, _, chains, _ = await scanned(monkeypatch)
    row = {"id": "F1", "evidence_id": 1}
    if ranges is not None:
        row["source_ranges"] = ranges
    assert not bind_evidence_choices({"source_facts": [row]}, chains, [], [])["source_facts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[], [[False, 1]], [[0, 99]], [[1, 0]], [[0, 1], [0, 2]], "0:1"])
async def test_invalid_either_side_scope_keeps_whole_pair_excluded(monkeypatch, bad):
    _, conflicts, chains, _ = await scanned(monkeypatch, ranges_b=bad)
    assert conflicts[0]["scan_status"] == "confirmed"
    assert selection_packet(chains)[1] == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("second", ["known", "unknown", "legacy", "missing", "changed_text"])
async def test_every_conflict_for_canonical_url_must_be_bound(monkeypatch, second):
    from deepchoice.utils.conflict_scope import make_conflict_scope
    items, conflicts, _, _ = await scanned(monkeypatch)
    later = deepcopy(conflicts[0])
    later["source_a"]["url"] += "#another-section"
    later["source_a"]["conflict_scope"] = make_conflict_scope(items[0], [[6, 7]])
    if second == "unknown":
        later["scan_status"] = "unknown"
    elif second == "legacy":
        later.pop("scan_status")
    elif second == "missing":
        later["source_a"].pop("conflict_scope")
    elif second == "changed_text":
        changed = dict(items[0], snippet=items[0]["snippet"].replace("one writer", "two writers"))
        later["source_a"]["conflict_scope"] = make_conflict_scope(changed, [[6, 7]])
    chains = build_evidence_chain(items, conflicts + [later])
    assert not bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1,
        "source_ranges": [[6, 7]]}]}, chains, [], [])["source_facts"]
    source = chains[0]["sources"][0]
    assert source["conflict_scope"] is None if second != "known" else source["conflict_scope"]["ranges"] == [[0, 1], [6, 7]]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["url", "text", "structure", "policy", "hash", "missing"])
async def test_scope_identity_mismatch_closes_selection_and_binding(monkeypatch, change):
    _, _, chains, _ = await scanned(monkeypatch)
    source = chains[0]["sources"][0]
    if change == "url":
        source["url"] = "https://changed.example/docs"
    elif change == "text":
        source["snippet"] += " Another complete condition applies."
    elif change == "structure":
        source["passages"] = [source["snippet"]]
    elif change == "missing":
        source.pop("conflict_scope")
    else:
        source["conflict_scope"]["policy" if change == "policy" else "identity_sha256"] = "forged"
    assert 1 not in selection_packet(chains)[1]
    assert not bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1,
        "source_ranges": [[6, 7]]}]}, chains, [], [])["source_facts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["omission", "fragment", "large", "ambiguous", "multiple", "mismatched_passage"])
async def test_incomplete_or_ambiguous_excerpts_never_authorize_partial_use(monkeypatch, change):
    items = scores()
    if change == "omission":
        items[0]["snippet"] += " [...] Additional conditions apply."
    elif change == "fragment":
        items[0]["snippet"] += " Additional conditions require"
    elif change == "large":
        items[0]["snippet"] += " More documentation applies." * 90
    elif change == "ambiguous":
        items[0]["snippet"] += " " + SENTENCES[0]
    elif change == "multiple":
        items[0]["passages"] = [" ".join(SENTENCES[:4]), " ".join(SENTENCES[4:])]
    else:
        items[0]["passages"] = ["A different saved excerpt applies."]
    call = AsyncMock(return_value={"has_difference": True, "type": "tradeoff_disagreement",
        "explanation": "Writer counts conflict", "ranges_a": [[0, 1]], "ranges_b": [[0, 1]]})
    monkeypatch.setattr(cd, "call_model", call)
    info = await cd._scan_pair_contradiction(*items, "fixture")
    assert info["scan_status"] == "confirmed" and "scope_a" not in info
    assert call.await_count == 1
    if change != "ambiguous":
        assert "without complete coordinates" in str(call.await_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("ranges", [[[0, 1]], None, "0:1", [[False, 1]]])
async def test_negative_with_conflicting_or_malformed_ranges_is_unknown(monkeypatch, ranges):
    monkeypatch.setattr(cd, "call_model", AsyncMock(return_value={"has_difference": False,
        "type": "none", "explanation": "No difference", "ranges_a": ranges, "ranges_b": []}))
    finding = await cd._scan_pair_contradiction(*scores(), "fixture")
    assert finding == {"scan_status": "unknown", "scan_reason": "invalid_output"}


def test_retriever_scope_cannot_supply_runtime_authority():
    from deepchoice.utils.conflict_scope import make_conflict_scope
    items = scores()
    items[0]["conflict_scope"] = make_conflict_scope(items[0], [[0, 1]])
    unknown = {"scan_status": "unknown", "source_a": {"url": items[0]["url"]},
               "source_b": {"url": items[1]["url"]}}
    chains = build_evidence_chain(items, [unknown])
    assert chains[0]["sources"][0]["conflict_scope"] is None
    assert selection_packet(chains)[1] == set()


@pytest.mark.asyncio
async def test_conditional_choice_survives_citation_and_actual_self_review_without_winner_authority(monkeypatch):
    import httpx
    from deepchoice.agents import conclusion_synthesizer as synth, self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.utils.analysis_review import prepare_analysis_review
    items, conflicts, chains, _ = await scanned(monkeypatch)
    original = deepcopy(chains)
    task = {"query": "Choose Atlas when encrypted snapshots are required.", "candidate_techs": ["Atlas"]}
    selection = {"source_facts": [{"id": "F1", "evidence_id": 1, "source_ranges": [[6, 7]]}]}
    analysis = {"decision_analysis": [{"kind": "choice", "option": "Atlas", "requirement_ids": ["R0"],
        "basis": [{"fact_id": "F1", "sentence_ids": [1, 2, 3]}],
        "reasoning": "Consider Atlas for encrypted snapshots if the original encryption key is retained and isolated restoration validation is satisfactory.",
        "assumptions": ["The original encryption key is available."],
        "change_condition": "Reassess if the encryption key is unavailable."}]}
    model = AsyncMock(side_effect=[selection, analysis])
    monkeypatch.setattr(synth, "call_model", model)
    state = {"task": task, "evidence_chains": chains, "conflicts": conflicts}
    state.update(await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(state))
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=f"<p>{items[0]['snippet']}</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await CitationValidatorAgent().run(state))
    assert state["final_recommendation"]["source_facts"][0]["status"] == "verified"
    assert len(prepare_analysis_review(state).slots) == 1
    reviewer = AsyncMock(return_value={"analysis_reviews": [{"analysis_id": "A1", "action": "keep",
        "source_checks": [["F1", "supports", [1, 2, 3]]]}]})
    monkeypatch.setattr(review, "call_model", reviewer)
    state.update(await review.SelfReviewerAgent().run(state))
    final = state["final_recommendation"]
    assert len(final["decision_analysis"]) == 1 and final["decision_analysis"][0]["option"] == "Atlas"
    assert final["winner"] != "Atlas" and final["deployment_readiness"] != "ready"
    assert "original encryption key" in final["source_facts"][0]["saved_text"]
    assert chains == original and _usable_evidence_ids(chains) == set()
    assert usable_evidence_chains(state) == []
    assert model.await_count == 2 and reviewer.await_count == 1
    forged = deepcopy(state)
    forged["final_recommendation"]["source_facts"][0]["source_ranges"] = [[0, 1]]
    assert not prepare_analysis_review(forged).slots


@pytest.mark.asyncio
@pytest.mark.parametrize("forge", ["whole_fact", "missing_scope", "wrong_page"])
async def test_citation_rechecks_conflict_binding_and_live_page(monkeypatch, forge):
    import httpx
    from deepchoice.citations.verifier import verify_citations
    _, _, chains, _ = await scanned(monkeypatch)
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1,
        "source_ranges": [[6, 7]]}]}, chains, [], [])
    if forge == "whole_fact":
        fact = bound["source_facts"][0]
        fact.pop("source_ranges")
        fact.pop("saved_passages")
        source = chains[0]["sources"][0]
        fact["saved_text"] = source["snippet"]
        fact["text"] = " ".join(f"{sentence} [Source: {source['title']}]" for sentence in SENTENCES)
    elif forge == "missing_scope":
        chains[0]["sources"][0].pop("conflict_scope")
    async def fetch(*args, **kwargs):
        text = "Atlas describes an unrelated language." if forge == "wrong_page" else chains[0]["sources"][0]["snippet"]
        return httpx.Response(200, text=f"<p>{text}</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    verification, _ = await verify_citations(bound, chains)
    assert verification.checks and {check.status.value for check in verification.checks} == {"unknown"}


@pytest.mark.asyncio
async def test_union_is_not_limited_to_one_scans_three_ranges(monkeypatch):
    from deepchoice.utils.conflict_scope import make_conflict_scope
    items, conflicts, _, _ = await scanned(monkeypatch)
    rows = []
    for index in [0, 2, 4, 6]:
        row = deepcopy(conflicts[0])
        row["source_a"]["conflict_scope"] = make_conflict_scope(items[0], [[index, index + 1]])
        rows.append(row)
    chains = build_evidence_chain(items, rows)
    assert chains[0]["sources"][0]["conflict_scope"]["ranges"] == [[0, 1], [2, 3], [4, 5], [6, 7]]
    assert chains[0]["disputed"]
    assert not bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1,
        "source_ranges": [[6, 7]]}]}, chains, [], [])["source_facts"]
