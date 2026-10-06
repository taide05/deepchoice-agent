"""Candidate action labels keep their choices while routing literal products."""
import pytest

from deepchoice.agents.source_evaluator import (
    SourceEvaluatorAgent, _audited_seed_scope_covers_candidate, _candidate_patterns, _mentions_candidate,
)
from deepchoice.utils.evidence import candidate_name_pattern
from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY
from deepchoice.utils.question_packet import candidate_mentions, has_multi_candidate_coverage


@pytest.mark.parametrize("label,title", [
    ("继续使用 Atlas", "Atlas documentation"),
    ("迁移到 C++", "C++ reference"),
    ("切换到 Qt", "Qt deployment guide"),
    ("continue using Bun", "Bun runtime guide"),
    ("migrate to C#", "C# language reference"),
    ("keep using Node.js", "Node.js manual"),
    ("stay with Apache Kafka", "Apache Kafka documentation"),
    ("  CONTINUE   USING Atlas  ", "Atlas documentation"),
    ("继续使用甲乙", "甲乙文档"),
])
def test_action_label_uses_literal_identity_at_source_and_packet_boundaries(label, title):
    pattern = candidate_name_pattern(label)
    assert pattern is not None and pattern.search(title.casefold())
    assert _mentions_candidate({"title": title}, _candidate_patterns({"candidate_techs": [label]}))
    assert candidate_mentions(title, [label]) == [label]
    assert candidate_mentions("Unrelated product documentation", [label]) == []


@pytest.mark.parametrize("label", ["continue using", "keep using ", "迁移到", "继续使用",
    "continue using switch to Atlas", "继续使用 迁移到 uv"])
def test_action_without_product_cannot_disable_candidate_gate_or_claim_coverage(label):
    patterns = _candidate_patterns({"candidate_techs": [label]})
    assert patterns
    assert not _mentions_candidate({"title": "Continue using deployment patterns and documentation"}, patterns)
    assert not _mentions_candidate({"title": label + " general advice"}, patterns)
    assert candidate_mentions("Continue using deployment patterns and documentation", [label]) == []
    assert candidate_mentions("Switch implementation details for Atlas and uv", [label]) == []


@pytest.mark.parametrize("label,title,bad", [
    ("migrate to C++", "C++", "C++++"),
    ("继续使用 uv", "uv", "uvicorn"),
    ("keep using Node.js 22", "Node.js 22", "Node.js 20"),
    ("switch to Atlas + Vector", "Atlas + Vector", "Atlas"),
    ("Unknown Action Atlas", "Unknown Action Atlas", "Atlas"),
    ("Use Case", "Use Case", "Case"),
])
def test_identity_keeps_identifier_version_compound_and_unknown_label_bounds(label, title, bad):
    pattern = candidate_name_pattern(label)
    assert pattern is not None and pattern.search(title.casefold())
    assert not pattern.search(bad.casefold())


@pytest.mark.asyncio
async def test_evaluator_admits_product_prose_for_action_label_without_changing_task(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    task = {"query": "Choose how to use Atlas", "candidate_techs": ["继续使用 Atlas", "迁移到 Beta"]}
    results = [{"title": name + " documentation", "url": "https://example.org/" + name,
                "snippet": name + " stores records in a bounded local journal."} for name in ["Atlas", "Other"]]
    state = await SourceEvaluatorAgent().run({"task": task,
        "search_results": [{"source": "tavily", "results": results}]})
    assert [row["title"] for row in state["source_scores"]] == ["Atlas documentation"]
    assert task["candidate_techs"] == ["继续使用 Atlas", "迁移到 Beta"]


def test_audited_seed_scope_uses_same_identity_without_granting_other_product_scope():
    source = {"_seed_target_id": "p01-sqlite-wal", "_seed_source_type": "official",
              "_seed_seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY}
    assert _audited_seed_scope_covers_candidate(source, "chroma", ["continue using SQLite"]) is True
    assert _audited_seed_scope_covers_candidate(source, "chroma", ["迁移到 Redis"]) is False
    assert _audited_seed_scope_covers_candidate({**source, "_seed_seed_identity_sha256": "forged"},
                                              "chroma", ["继续使用 SQLite"]) is None


def test_multi_candidate_packet_preserves_original_choice_labels_and_missing_side():
    labels = ["continue using Atlas", "migrate to Beta"]
    assert not has_multi_candidate_coverage([{"source_title": "Atlas documentation"}], labels)
    assert has_multi_candidate_coverage([{"source_title": "Atlas documentation"},
                                        {"source_title": "Beta documentation"}], labels)
