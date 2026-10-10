"""Offline scope regressions; model outputs here are fixtures, not semantic proof."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import conflict_detector as detector
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent


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
    # HTTP admission survives; an unregistered docs.* hostname is not authority.
    assert result["source_scores"][0]["source_type"] == "tech_blog"


@pytest.mark.asyncio
async def test_audited_seed_target_rejects_incidental_candidate_mentions():
    seed = {
        "_seed_source_type": "official", "_seed_verified_chunk": True,
        "_seed_seed_identity_sha256": "9beba61dbeabf253fda953fa9a3dd6b3a8a8ff51e46d923c1cfdeb888a2391d6",
    }
    state = {"task": {"candidate_techs": ["Redis", "Memcached"]}, "search_results": [{
        "source": "chroma", "results": [
            {
                **seed,
                "_seed_target_id": "p04-celery-introduction",
                "title": "p04-celery-introduction",
                "snippet": "Celery result stores include Redis and Memcached.",
                "url": "https://docs.celeryq.dev/introduction",
            },
            {
                **seed,
                "_seed_target_id": "p08-memcached-overview",
                "title": "p08-memcached-overview",
                "snippet": "An audited product overview.",
                "url": "https://docs.memcached.org/",
            },
        ],
    }]}

    result = await SourceEvaluatorAgent().run(state)

    assert [item["title"] for item in result["source_scores"]] == [
        "p08-memcached-overview"
    ]
    signal = result["quality_signals"][0]
    assert signal["candidate_excluded_count"] == 1
    assert signal["audited_seed_scope_excluded_count"] == 1


@pytest.mark.asyncio
async def test_audited_seed_scope_never_bypasses_candidate_lexical_gate():
    state = {"task": {"candidate_techs": ["Redis"]}, "search_results": [{
        "source": "chroma", "results": [{
            "_seed_source_type": "official", "_seed_verified_chunk": True,
            "_seed_seed_identity_sha256": "9beba61dbeabf253fda953fa9a3dd6b3a8a8ff51e46d923c1cfdeb888a2391d6",
            "_seed_target_id": "p08-redis-persistence",
            "title": "Opaque approved page",
            "snippet": "Unrelated text cannot gain admission from provenance.",
            "url": "https://redis.io/docs/persistence",
        }],
    }]}

    result = await SourceEvaluatorAgent().run(state)

    assert result["source_scores"] == []
    assert result["quality_signals"][0]["candidate_excluded_count"] == 1


@pytest.mark.asyncio
async def test_audited_seed_title_matches_target_across_slug_and_camel_separators():
    state = {"task": {"candidate_techs": ["FastAPI BackgroundTasks", "Celery"]},
             "search_results": [{"source": "chroma", "results": [{
                 "_seed_source_type": "official", "_seed_verified_chunk": True,
                 "_seed_seed_identity_sha256": "9beba61dbeabf253fda953fa9a3dd6b3a8a8ff51e46d923c1cfdeb888a2391d6",
                 "_seed_target_id": "p04-fastapi-background-tasks",
                 "title": "p04-fastapi-background-tasks",
                 "snippet": "Run small work after returning a response.",
                 "url": "https://fastapi.tiangolo.com/tutorial/background-tasks/",
             }]}]}

    result = await SourceEvaluatorAgent().run(state)

    assert [item["title"] for item in result["source_scores"]] == [
        "p04-fastapi-background-tasks"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "snippet"),
    [
        ("Predis integration", "An unrelated client integration."),
        ("Opaque approved page", "The status light is red. Is the request complete?"),
    ],
)
async def test_audited_seed_compact_match_preserves_identifier_boundaries(
    title, snippet
):
    state = {"task": {"candidate_techs": ["Redis"]}, "search_results": [{
        "source": "chroma", "results": [{
            "_seed_source_type": "official", "_seed_verified_chunk": True,
            "_seed_seed_identity_sha256": "9beba61dbeabf253fda953fa9a3dd6b3a8a8ff51e46d923c1cfdeb888a2391d6",
            "_seed_target_id": "p08-redis-persistence",
            "title": title,
            "snippet": snippet,
            "url": "https://example.test/unrelated",
        }],
    }]}

    result = await SourceEvaluatorAgent().run(state)

    assert result["source_scores"] == []


@pytest.mark.asyncio
async def test_untrusted_or_unknown_seed_metadata_cannot_claim_audited_scope():
    base = {
        "_seed_source_type": "official", "_seed_verified_chunk": True,
        "title": "Redis incidental mention",
        "snippet": "Redis is mentioned incidentally.",
        "url": "https://example.test/page",
    }
    state = {"task": {"candidate_techs": ["Redis"]}, "search_results": [{
        "source": "chroma", "results": [
            {
                **base,
                "_seed_seed_identity_sha256": "0" * 64,
                "_seed_target_id": "p08-redis-forged",
            },
            {
                **base,
                "url": "https://example.test/other",
                "_seed_seed_identity_sha256": "9beba61dbeabf253fda953fa9a3dd6b3a8a8ff51e46d923c1cfdeb888a2391d6",
                "_seed_target_id": "p08-redis-unknown",
            },
        ],
    }]}

    result = await SourceEvaluatorAgent().run(state)

    # The forged identity receives no audited authority and falls back to the
    # pre-existing lexical gate; an impossible target under the exact frozen
    # identity fails closed.
    assert [item["url"] for item in result["source_scores"]] == [
        "https://example.test/page"
    ]
    assert result["quality_signals"][0]["audited_seed_scope_excluded_count"] == 1


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
        _source("Beta low latency", "Interactive latency is low"), "Choose a store") == {
            "scan_status": "unknown", "scan_reason": "invalid_output"}


@pytest.mark.asyncio
async def test_scan_missing_descriptions_cannot_turn_titles_into_claims(monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(detector, "call_model", call)
    assert await detector._scan_pair_contradiction(
        _source("Pick Alpha", ""), _source("Pick Beta"), "Choose") == {
            "scan_status": "unknown", "scan_reason": "missing_description"}
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_high_gap_remains_unresolved_without_new_calls_or_evidence_tools(monkeypatch):
    pair = {"source_a": _source("Alpha", score=10),
            "source_b": _source("Beta", score=5), "similarity": 0.9}
    monkeypatch.setattr(detector, "find_contradictions", AsyncMock(return_value=[pair]))
    call = AsyncMock()
    monkeypatch.setattr(detector, "call_model", call)
    result = await detector.ConflictDetectorAgent().run({"task": {"query": "Choose"}})
    conflict = result["conflicts"][0]
    assert conflict["resolution"] == "insufficient_data" and conflict["confidence"] == "low"
    assert result["quality_signals"][0]["resolved_count"] == 0
    call.assert_not_awaited()
