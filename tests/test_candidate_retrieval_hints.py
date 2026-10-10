"""Choice modifiers affect source relevance without changing candidate identity."""
from copy import deepcopy

import pytest

from deepchoice.agents.source_evaluator import (
    SourceEvaluatorAgent, _candidate_patterns, _candidate_retrieval_patterns,
    _candidate_rejection, _mentions_candidate,
)
from deepchoice.utils.evidence import candidate_name_pattern
from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY


@pytest.mark.parametrize("label,title", [
    ("Managed Acme 7", "Acme reference"),
    ("Ephemeral self-hosted Acme runners", "Acme runners guide"),
    ("GitHub-hosted GitHub Actions runners", "GitHub Actions reference"),
    ("Buildkite with ephemeral agents", "Buildkite configuration"),
    ("PostgreSQL 16 with pgvector", "PostgreSQL reference"),
    ("PostgreSQL 16 with pgvector", "pgvector reference"),
    ("continue using Node.js 22", "Node.js API reference"),
    ("Self-hosted MinIO", "MinIO reference"),
    ("托管 Acme", "Acme reference"),
])
def test_modified_choice_can_offer_product_sources(label, title):
    task = {"candidate_techs": [label]}
    assert _mentions_candidate({"title": title}, _candidate_retrieval_patterns(task))
    assert not candidate_name_pattern(label).search(title.casefold())
    assert task["candidate_techs"] == [label]


@pytest.mark.parametrize("label,title", [
    ("GitHub Actions", "GitHub generic repository guide"),
    ("Alpha Pro", "Alpha reference"),
    ("Managed Alpha Pro", "Alpha-Pro reference"),
    ("Managed Alpha", "Alpha-Pro reference"),
    ("Managed Alpha", "Alpha.Core reference"),
    ("Managed Go", "MongoDB reference"),
    ("Managed Redis", "red is available"),
    ("Acme with ephemeral agents", "Ephemeral agents reference"),
    ("continue using", "Continue using deployment patterns"),
    ("continue using switch to Acme", "Acme reference"),
    ("Unknown Action Atlas", "Atlas reference"),
    ("Managed C++", "C++++ reference"),
])
def test_hints_do_not_guess_unknown_compounds_or_generic_words(label, title):
    assert not _mentions_candidate({"title": title}, _candidate_retrieval_patterns({"candidate_techs": [label]}))


def test_existing_seed_and_local_comparison_veto_precede_hints():
    task = {"candidate_techs": ["Managed Redis", "Acme"]}
    strict, hints = _candidate_patterns(task), _candidate_retrieval_patterns(task)
    source = {"title": "Redis guide", "snippet": "Redis stores values.", "url": "https://redis.io/guide",
              "_seed_target_id": "p01-sqlite-wal", "_seed_source_type": "official",
              "_seed_verified_chunk": True, "_seed_seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY}
    assert _candidate_rejection(source, "chroma", task["candidate_techs"], strict, hints) == "seed_scope"
    source = {"title": "Redis vs Other", "snippet": "Redis stores values.", "url": "file:///kb/redis-vs-other.md"}
    assert _candidate_rejection(source, "chroma", task["candidate_techs"], strict, hints) == "comparison_scope"


@pytest.mark.asyncio
async def test_source_admission_preserves_version_and_deployment_conditions(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    task = {"query": "Evaluate the stated choice", "candidate_techs": ["Managed Acme 7"],
            "constraints": ["Tenant data must remain in the selected region"], "sub_questions": ["What remains our responsibility?"]}
    original = deepcopy(task)
    state = await SourceEvaluatorAgent().run({"task":task,"search_results":[{"source":"tavily","results":[
        {"title":"Acme 6 reference", "url":"https://example.org/acme/6/guide", "snippet":"Acme stores values using the configured service."},
        {"title":"Other guide", "url":"https://example.org/other", "snippet":"Other stores values."}]}]})
    assert len(state["source_scores"]) == 2
    assert all(row["evidence_type"] == "unassessed" for row in state["source_scores"])
    row = state["source_scores"][0]
    assert row["title"] == "Acme 6 reference"  # Discovery does not assert requested v7 applicability.
    assert row["evidence_type"] == "unassessed"
    assert "citation_verification" not in state and "final_recommendation" not in state
    assert task == original
    assert not candidate_name_pattern(task["candidate_techs"][0]).search(row["snippet"].casefold())
