"""Navigation metadata must not establish a technical evidence base."""

from copy import deepcopy

import pytest

from deepchoice.agents.conclusion_synthesizer import _usable_evidence_ids
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.evidence_decision_gate import should_request_evidence_decision
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.budget.limited import minimum_evidence_is_met, usable_evidence_chains
from deepchoice.contracts.errors import DeepChoiceError
from deepchoice.contracts.manifest import (
    RunManifest,
    _expected_manifest_id,
    build_run_manifest,
    ensure_run_manifest_compatible,
)
from deepchoice.retrievers.official import TECH_DOCS


def _source(snippet="Official documentation site for alpha", *, url="https://alpha.example/docs"):
    return {"url": url, "title": "Alpha documentation", "snippet": snippet, "date": ""}


def _scored(source):
    return {**source, "total_score": 6.8, "supporting_sources": []}


def _chain(source):
    return {
        "conclusion": source["title"],
        "sources": [{**source, "score": 6.8}],
        "evidence_strength": "moderate",
        "disputed": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["official", "tavily", "chroma"])
async def test_navigation_is_not_scored_but_raw_retrieval_remains_visible(channel):
    state = {"search_results": [{
        "source": channel, "status": "success", "error": None,
        "results": [_source()],
    }], "partial_failures": ["community"]}
    original = deepcopy(state)
    output = await SourceEvaluatorAgent().run(state)
    assert output["source_scores"] == []
    assert output["quality_signals"][0]["navigation_excluded_count"] == 1
    assert build_evidence_chain(output["source_scores"], []) == []
    assert state == original


@pytest.mark.asyncio
async def test_all_curated_navigation_terms_are_excluded_without_title_guessing():
    results = [_source(f"Official documentation site for {term}") for term in TECH_DOCS]
    results.extend([
        _source(" \nOFFICIAL documentation\t site for unknown-package.v2 \n"),
        _source("Official documentation site for c++"),
    ])
    output = await SourceEvaluatorAgent().run({"search_results": [{
        "source": "official", "results": results,
    }]})
    assert output["source_scores"] == []
    assert output["quality_signals"][0]["navigation_excluded_count"] == len(results)


@pytest.mark.asyncio
async def test_actual_content_and_short_package_summary_keep_existing_scores():
    snippets = [
        "Official documentation site for Alpha describes feature A and its limits.",
        "Alpha supports feature A.",
        "Version: 1.0, Summary: Alpha client",
    ]
    output = await SourceEvaluatorAgent().run({"search_results": [{
        "source": "official", "results": [_source(snippet) for snippet in snippets],
    }]})
    assert [row["snippet"] for row in output["source_scores"]] == snippets
    assert all(row["total_score"] == 6.8 for row in output["source_scores"])
    assert output["quality_signals"][0]["navigation_excluded_count"] == 0


def test_chain_builder_rejects_placeholder_even_if_score_is_already_present():
    scores = [_scored(_source()), _scored(_source("Alpha supports feature A."))]
    original = deepcopy(scores)
    chains = build_evidence_chain(scores, [])
    assert len(chains) == 1
    assert chains[0]["sources"][0]["snippet"] == "Alpha supports feature A."
    assert scores == original


@pytest.mark.parametrize("prebuilt", [True, False])
def test_budget_and_hitl_do_not_count_navigation_toward_minimum(prebuilt):
    sources = [
        _source(url="https://alpha.example/docs"),
        _source("Alpha supports feature A.", url="https://alpha.example/feature"),
        _source("Beta supports feature B.", url="https://beta.example/feature"),
    ]
    state = {
        "conflicts": [],
        "source_scores": [_scored(source) for source in sources],
        "evidence_chains": [_chain(source) for source in sources] if prebuilt else [],
        "final_recommendation": {
            "decision_basis_version": "constraint-aware-v1", "winner": "context_dependent",
        },
    }
    original = deepcopy(state)
    assert len(usable_evidence_chains(state)) == 2
    assert not minimum_evidence_is_met(state)
    assert should_request_evidence_decision(state)
    assert state == original
    replacement = _source("Alpha documents feature C.")
    state["source_scores"][0] = _scored(replacement)
    if prebuilt:
        state["evidence_chains"][0] = _chain(replacement)
    assert minimum_evidence_is_met(state)
    assert not should_request_evidence_decision(state)


def test_synthesis_binding_rejects_navigation_without_renumbering_other_sources():
    chains = [_chain(_source()), _chain(_source("Alpha supports feature A."))]
    assert _usable_evidence_ids(chains) == {2}


def test_old_scoring_identity_is_readable_but_cannot_resume():
    current = build_run_manifest({})
    assert current.scoring_policy_version == "source-score-v4"
    old = current.model_copy(update={"scoring_policy_version": "source-score-v3"})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    restored = RunManifest.model_validate_json(old.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"
    ensure_run_manifest_compatible(current, {})
