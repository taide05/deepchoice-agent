"""Synthetic offline regressions for evidence admission and honest binding."""

from copy import deepcopy

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synthesis
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.citations.verifier import verify_citations
from deepchoice.contracts.errors import DeepChoiceError
from deepchoice.contracts.manifest import (
    RunManifest, _expected_manifest_id, build_run_manifest, ensure_run_manifest_compatible,
)
from deepchoice.formats.citations import cited_source_links
from deepchoice.formats.what_why_how import render
from deepchoice.utils.evidence import source_title


def _result(title, snippet="", url="https://example.com/docs"):
    return {"title": title, "snippet": snippet, "url": url}


def _state(results, candidates=None):
    return {
        "task": {"query": "A technology choice", "candidate_techs": candidates or []},
        "search_results": [{"source": "tavily", "status": "success", "results": results}],
    }


@pytest.mark.asyncio
async def test_candidate_gate_preserves_raw_results_and_rejects_offtopic_popularity():
    state = _state([
        _result("React release", "A popular serverless web framework"),
        _result("On quantum steps", "Serverless task scheduling"),
        _result("SQLite notes", "SQLite WAL backup boundaries"),
        _result("Migration guide", "PostgreSQL migration from embedded storage"),
    ], ["SQLite", "PostgreSQL"])
    original = deepcopy(state)
    output = await SourceEvaluatorAgent().run(state)
    assert state == original
    assert {item["title"] for item in output["source_scores"]} == {"SQLite notes", "Migration guide"}
    assert output["quality_signals"][0]["candidate_excluded_count"] == 2
    assert output["quality_signals"][0]["candidate_gate"] == "lexical"


@pytest.mark.asyncio
@pytest.mark.parametrize(("candidate", "positive", "negative"), [
    ("React", "React中文文档", "reactor experiments"),
    ("C++", "C++ compiler", "C++++ code"),
    ("C#", "C# runtime", "C## runtime"),
    ("RabbitMQ Streams", "RABBITMQ   Streams replay", "RabbitMQ classic queues"),
    ("向量数据库", "选择向量数据库的边界", "关系数据库"),
])
async def test_candidate_gate_identifier_boundaries_and_mixed_language(candidate, positive, negative):
    output = await SourceEvaluatorAgent().run(_state([
        _result(positive), _result(negative, url="https://example.com/other"),
    ], [candidate]))
    assert [item["title"] for item in output["source_scores"]] == [" ".join(positive.split())]


@pytest.mark.asyncio
async def test_category_and_legacy_tasks_do_not_guess_candidates_or_hide_failures():
    state = _state([_result("A category survey")])
    state["search_results"].append({"source": "community", "status": "failed", "results": [], "error": "failure"})
    output = await SourceEvaluatorAgent().run(state)
    assert len(output["source_scores"]) == 1
    assert output["quality_signals"][0]["candidate_gate"] == "not_applied"
    assert state["search_results"][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_no_named_candidate_evidence_stays_empty_not_fallback_to_offtopic():
    output = await SourceEvaluatorAgent().run(_state([_result("General survey")], ["Qdrant"]))
    assert output["source_scores"] == []
    assert build_evidence_chain(output["source_scores"], []) == []


@pytest.mark.asyncio
async def test_high_scores_do_not_fabricate_corroboration_or_strong_chains():
    state = _state([
        _result("SQLite docs", "SQLite WAL concurrency", "https://docs.example.com/one"),
        _result("SQLite notes", "SQLite only supports one writer", "https://docs.example.com/two"),
        _result("SQLite discussion", "SQLite tradeoffs", "https://docs.example.com/three"),
    ], ["SQLite"])
    state["search_results"][0]["source"] = "official"
    output = await SourceEvaluatorAgent().run(state)
    assert all(item["supporting_sources"] == [] for item in output["source_scores"])
    assert all(item["scores"]["consistency"] is None for item in output["source_scores"])
    assert all(chain["evidence_strength"] != "strong" for chain in build_evidence_chain(output["source_scores"], []))


@pytest.mark.parametrize("title", [None, "", " \t", "\\N", "null", "N/A"])
def test_missing_titles_are_explicit_identifiers_not_invented_claims(title):
    identifier = source_title(title, "https://example.com/docs")
    assert identifier.startswith("Untitled source (")
    assert identifier == source_title(None, "https://example.com/docs")
    assert identifier != source_title(None, "https://example.com/other")
    assert "example.com" not in identifier
    assert source_title("Real title\n details", "") == "Real title details"


@pytest.mark.asyncio
async def test_null_title_is_cleaned_before_scores_chains_and_number_binding():
    state = _state([_result("\\N", "SQLite backup")], ["SQLite"])
    scores = (await SourceEvaluatorAgent().run(state))["source_scores"]
    chains = build_evidence_chain(scores, [])
    _, mapping = synthesis._summarize_chains(chains)
    result = {"recommendation": "SQLite backup [[1]]."}
    synthesis._bind_citations(result, mapping)
    assert "\\N" not in result["recommendation"]
    assert f"[Source: {scores[0]['title']}]" in result["recommendation"]


@pytest.mark.asyncio
async def test_punctuation_titles_roundtrip_without_dropping_or_rebinding(monkeypatch):
    title = "Release notes [2026], support; boundaries"
    chains = [{"sources": [_result(title)]}]
    recommendation = {"winner_rationale": f"SQLite supports WAL. [Source: {title}]"}
    synthesis._sanitize_citations(recommendation, chains)
    assert recommendation["winner_rationale"].endswith(f"[Source: {title}]")

    async def fetch(*args, **kwargs):
        return httpx.Response(200, text="SQLite supports WAL.", request=httpx.Request("GET", "https://example.com/docs"))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    verification, _ = await verify_citations(recommendation, chains)
    assert len(verification.checks) == 1
    assert verification.checks[0].status.value == "verified"
    assert cited_source_links(recommendation["winner_rationale"], chains) == [f"[{title}](https://example.com/docs)"]


@pytest.mark.parametrize("title", ["Docs, API; notes [v2]", "Docs [Index, Source: API]"])
def test_mixed_real_and_fabricated_punctuation_titles_preserve_only_real_marker(title):
    result = {"recommendation": f"Use A [Source: {title}, Source: Fake docs]."}
    synthesis._sanitize_citations(result, [{"sources": [_result(title)]}])
    assert result["recommendation"] == f"Use A [Source: {title}]."


@pytest.mark.parametrize(("real", "wrong"), [
    ("C++ deployment guide", "C# deployment guide"),
    ("node.js guide", "nodejs guide"),
])
def test_technology_punctuation_is_not_erased_by_sanitizer_or_renderer(real, wrong):
    chains = [{"sources": [_result(real)]}]
    text = f"Use A [Source: {wrong}]."
    result = {"recommendation": text}
    synthesis._sanitize_citations(result, chains)
    assert result["recommendation"] == "Use A ."
    assert cited_source_links(text, chains) == []
    assert cited_source_links(f"Use A [Source: {real}].", chains)


@pytest.mark.asyncio
async def test_nested_title_separator_roundtrips_through_shared_parsing(monkeypatch):
    title = "Docs [Index, Source: API]"
    chains = [{"sources": [_result(title)]}]

    async def fetch(*args, **kwargs):
        return httpx.Response(200, text="SQLite supports WAL.", request=httpx.Request("GET", "https://example.com/docs"))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    verification, _ = await verify_citations({"winner_rationale": f"SQLite supports WAL. [Source: {title}]"}, chains)
    assert len(verification.checks) == 1
    assert verification.checks[0].source_title == title
    assert verification.checks[0].status.value == "verified"


def test_renderer_only_links_explicit_sources_not_generic_word_matches():
    chains = [{"conclusion": "On quantum steps", "sources": [_result("On quantum steps")]}]
    state = {
        "task": {"query": "Choose a database"}, "evidence_chains": chains,
        "final_recommendation": {
            "ranked_options": [{"name": "PostgreSQL", "rationale": "PostgreSQL works on servers"}],
            "trade_offs": [{"dimension": "Deployment", "finding": "PostgreSQL works on servers"}],
        },
    }
    assert "*Sources:" not in render(state)
    assert cited_source_links("PostgreSQL works on servers", chains) == []
    assert cited_source_links("Use it [Source: On quantum steps].", chains) == ["[On quantum steps](https://example.com/docs)"]


def test_renderer_dedupes_urls_and_does_not_guess_ambiguous_or_unknown_titles():
    chains = [{"sources": [
        _result("Same title", url="https://example.com/a"),
        _result("Same title", url="https://example.com/b"),
        _result("Unique", url="https://example.com/c#first"),
        _result("Unique", url="https://example.com/c#second"),
    ]}]
    links = cited_source_links("Claim [Source: Same title, Source: Unique] [Source: Missing] [Source: Unique]", chains)
    assert len(links) == 1
    assert "Unique" in links[0]
    assert "Same title" not in links[0]


@pytest.mark.asyncio
async def test_missing_clause_citations_and_local_network_unknown_are_not_repaired(monkeypatch):
    async def fail(*args, **kwargs):
        raise OSError("private transport detail")

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fail)
    verification, _ = await verify_citations({
        "winner_rationale": "SQLite is simple; PostgreSQL scales [Source: Remote].",
        "recommendation": "SQLite has local evidence [Source: Local].",
    }, [{"sources": [
        _result("Remote"), _result("Local", url="file:///local/docs.md"),
    ]}])
    assert [(check.status.value, check.reason.value) for check in verification.checks] == [
        ("unsupported", "citation_missing"), ("unknown", "network_uncertain"), ("unsupported", "url_invalid"),
    ]
    assert verification.checks[0].source_title is None


@pytest.mark.parametrize("old_field", ["scoring", "template"])
def test_old_policy_identity_remains_readable_but_cannot_resume_after_cleanup(old_field):
    task = {"report_format": "what_why_how"}
    current = build_run_manifest(task)
    if old_field == "scoring":
        old = current.model_copy(update={"scoring_policy_version": "source-score-v1"})
    else:
        old = current.model_copy(update={"report": current.report.model_copy(update={"template_version": "what-why-how-v1"})})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    restored = RunManifest.model_validate_json(old.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"
