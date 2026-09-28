"""Offline P01 retrieval counterexamples; no embedding model or network."""

import hashlib
from types import SimpleNamespace

import pytest

from deepchoice.agents.conclusion_synthesizer import _summarize_chains
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.multi_retriever import (
    MultiRetrieverAgent, _chroma_local_scene_needs, _chroma_scene_focus_query,
)
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.retrievers import chroma_kb
from deepchoice.retrievers.contracts import RetrievalResult
from deepchoice.retrievers.chroma_kb import _audited_fts5_overview
from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY


FTS5_URL = "https://sqlite.org/fts5.html"
FTS5_META = {
    "url": FTS5_URL,
    "title": "p01-sqlite-fts5",
    "source_type": "official",
    "target_id": "p01-sqlite-fts5",
    "seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY,
}
OVERVIEW = (
    "6.10. The 'pgsz' Configuration Option\n"
    "Summary of Technical Differences\n1. Overview of FTS5\n"
    "FTS5 is an SQLite virtual table module that provides\nfull-text search\n"
    "functionality to database applications. In their most elementary form,\n"
    "full-text search engines allow the user to efficiently search a large\n"
    "collection of documents for the subset that contain one or more instances\n"
    "of a search term.\nTo use FTS5, the user creates an FTS5 virtual table."
)
DEEP_COMMAND = "the merge command. The application should stop invoking merge when the result drops."


def _index(document=OVERVIEW):
    return {
        doc_id: ("p01-sqlite-fts5", FTS5_URL, hashlib.sha256(body.encode()).hexdigest())
        for doc_id, body in (
            ("fts5-overview", document),
            ("fts5-deep", DEEP_COMMAND),
            ("fts5-nav", "SQLite FTS5 Extension\nHome\nTable Of Contents"),
        )
    }


def test_original_request_only_projects_local_capability_flags():
    task = {
        "query": "SQLite or PostgreSQL?",
        "scene_context": "不需要备份，但需要基本全文检索。",
        "constraints": ["必须说明迁移触发"],
    }
    assert _chroma_local_scene_needs(task) == ("full_text_search",)
    task["scene_context"] = "需要备份与基本全文检索。"
    assert _chroma_local_scene_needs(task) == ("backup", "full_text_search")
    task["scene_context"] = "任务结果不能因服务重启静默丢失。"
    task["constraints"] = ["必须讨论重启恢复和至少一次执行语义"]
    assert _chroma_local_scene_needs(task) == ("task_recovery",)


@pytest.mark.asyncio
async def test_model_generated_subquestion_cannot_override_original_negation():
    captured = {}

    class Fake:
        async def retrieve(self, request):
            captured["request"] = request
            return RetrievalResult(source="chroma", status="success", results=[], latency_ms=0)

    await MultiRetrieverAgent(retriever_registry={"chroma": Fake}).run({
        "task": {
            "query": "SQLite or PostgreSQL?", "candidate_techs": ["SQLite", "PostgreSQL"],
            "scene_context": "不需要备份和全文检索。",
        },
        "sub_questions": ["需要备份和全文检索吗？"],
        "adapted_queries": {"chroma": ["backup full text search"]},
    })
    assert captured["request"].local_scene_needs == ()


def test_positive_scene_requirement_is_a_short_candidate_bound_dimension():
    task = {
        "candidate_techs": ["SQLite", "PostgreSQL"],
        "scene_context": "单人开发和运维，预计12个月内日活低于5000，读多写少，需要备份与基本全文检索。",
    }
    assert _chroma_scene_focus_query(task) == "SQLite PostgreSQL 需要备份与基本全文检索"


def test_mixed_negation_retains_only_the_positive_need():
    assert _chroma_scene_focus_query({
        "candidate_techs": ["SQLite", "PostgreSQL"],
        "scene_context": "不需要备份但需要基本全文检索。",
    }) == "SQLite PostgreSQL 需要基本全文检索"
    assert _chroma_scene_focus_query({
        "candidate_techs": ["SQLite", "PostgreSQL"],
        "scene_context": "任务不能丢失且需要基本全文检索。",
    }) == "SQLite PostgreSQL 需要基本全文检索"


@pytest.mark.parametrize("scene", [
    "读多写少，不需要全文检索。",
    "No full-text search is required.",
    "We must not use full-text search.",
    "需要避免全文检索。",
    "全文检索不是必须。",
    "用户没有声明必须能力。",
    "需要" + "长" * 170,
])
def test_negated_missing_or_oversized_scene_requirement_is_not_promoted(scene):
    assert _chroma_scene_focus_query({
        "candidate_techs": ["SQLite", "PostgreSQL"], "scene_context": scene,
    }) is None


@pytest.mark.asyncio
async def test_scene_focus_reaches_only_chroma_and_precedes_model_adaptations():
    captured = {}

    def retriever(source):
        class Fake:
            async def retrieve(self, request):
                captured[source] = request
                return RetrievalResult(source=source, status="success", results=[], latency_ms=0)
        return Fake

    await MultiRetrieverAgent(retriever_registry={
        "chroma": retriever("chroma"), "official": retriever("official"),
    }).run({
        "task": {
            "query": "SQLite or PostgreSQL?", "candidate_techs": ["SQLite", "PostgreSQL"],
            "scene_context": "读多写少，需要备份与基本全文检索。",
        },
        "sub_questions": ["How does each option handle concurrent writes?"],
        "adapted_queries": {"chroma": ["model query"], "official": ["official query"]},
    })
    assert captured["chroma"].adapted_queries == (
        "SQLite PostgreSQL 需要备份与基本全文检索", "model query",
    )
    assert captured["official"].adapted_queries == ("official query",)
    assert captured["chroma"].local_scene_needs == ("backup", "full_text_search")
    assert captured["official"].local_scene_needs == ()

    await MultiRetrieverAgent(retriever_registry={
        "chroma": retriever("chroma"),
    }).run({
        "task": {
            "query": "SQLite or PostgreSQL?", "candidate_techs": ["SQLite", "PostgreSQL"],
            "scene_context": "需要基本全文检索。",
        },
        "sub_questions": ["How does each option handle concurrent writes?"],
    })
    assert captured["chroma"].adapted_queries == (
        "SQLite PostgreSQL 需要基本全文检索",
        "How does each option handle concurrent writes?",
    )
    assert captured["chroma"].local_scene_needs == ("full_text_search",)


def test_overview_must_match_frozen_seed_and_exact_official_page():
    result = {"ids": [["fts5-overview"]], "documents": [[OVERVIEW]], "metadatas": [[FTS5_META]]}
    chosen = _audited_fts5_overview(result, ("full_text_search",), _index())
    assert chosen is not None
    assert chosen[0] == FTS5_URL
    assert chosen[1].startswith("FTS5 is an SQLite virtual table module")
    assert "merge command" not in chosen[1]
    assert _audited_fts5_overview(result, (), _index()) is None
    assert _audited_fts5_overview(result, ("backup",), _index()) is None
    assert _audited_fts5_overview(result, ("full_text_search",), {}) is None
    for metadata in (
        {**FTS5_META, "seed_identity_sha256": "f" * 64},
        {**FTS5_META, "source_type": "blog"},
        {**FTS5_META, "url": "https://example.com/fts5.html"},
        {**FTS5_META, "url": "http://sqlite.org/fts5.html"},
    ):
        assert _audited_fts5_overview({
            "ids": [["fts5-overview"]], "documents": [[OVERVIEW]], "metadatas": [[metadata]],
        }, ("full_text_search",), _index()) is None


@pytest.mark.asyncio
async def test_same_url_overview_replaces_deep_chroma_snippet_without_extra_source(monkeypatch):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    calls = 0

    def query(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "ids": [["other-0", "fts5-deep"]],
                "documents": [["Other source", DEEP_COMMAND]],
                "metadatas": [[{"url": "https://other.example/docs", "title": "Other"}, FTS5_META]],
            }
        return {
            "ids": [["fts5-nav", "fts5-overview"]],
            "documents": [["SQLite FTS5 Extension\nHome\nTable Of Contents", OVERVIEW]],
            "metadatas": [[FTS5_META, FTS5_META]],
        }

    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever._audited_index = _index()
    retriever.collection = SimpleNamespace(query=query)
    results = await retriever._do_search(
        "SQLite versus PostgreSQL", [], 7,
        adapted_queries=["SQLite PostgreSQL 需要备份与基本全文检索"],
        local_scene_needs=("full_text_search",),
    )
    assert calls == 2
    assert [item["url"] for item in results] == ["https://other.example/docs", FTS5_URL]
    assert results[1]["snippet"].startswith("FTS5 is an SQLite virtual table module")
    assert "full-text search" in results[1]["snippet"]
    assert "merge command" not in results[1]["snippet"]

    scored = (await SourceEvaluatorAgent().run({
        "task": {"candidate_techs": ["SQLite", "PostgreSQL"]},
        "search_results": [{"source": "chroma", "results": [results[1]]}],
    }))["source_scores"]
    prompt, _ = _summarize_chains(build_evidence_chain(scored, []))
    assert "FTS5 is an SQLite virtual table module" in prompt
    assert "merge command" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_meta", [
    {**FTS5_META, "target_id": "p01-sqlite-wal", "title": "Different target"},
    {"url": FTS5_URL, "title": "Unreviewed provider"},
])
async def test_same_url_cannot_promote_body_into_different_source_identity(
    monkeypatch, selected_meta,
):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    calls = 0

    def query(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "ids": [["wrong-target"]], "documents": [[DEEP_COMMAND]],
                "metadatas": [[selected_meta]],
            }
        return {
            "ids": [["fts5-overview"]], "documents": [[OVERVIEW]],
            "metadatas": [[FTS5_META]],
        }

    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever._audited_index = _index()
    retriever.collection = SimpleNamespace(query=query)
    results = await retriever._do_search(
        "SQLite versus PostgreSQL", [], 7,
        adapted_queries=["SQLite PostgreSQL 需要基本全文检索"],
        local_scene_needs=("full_text_search",),
    )
    assert len(results) == 1
    assert results[0]["snippet"] == DEEP_COMMAND


@pytest.mark.asyncio
async def test_focus_dimension_reserves_source_capacity_without_erasing_primary(monkeypatch):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    responses = [
        {
            "ids": [[f"primary-{i}" for i in range(4)]],
            "documents": [[f"Primary evidence {i}" for i in range(4)]],
            "metadatas": [[{"url": f"https://primary-{i}.example/docs", "title": f"P{i}"}
                           for i in range(4)]],
        },
        {
            "ids": [["fts5-nav", "fts5-overview"]],
            "documents": [["SQLite FTS5 Extension\nHome\nTable Of Contents", OVERVIEW]],
            "metadatas": [[FTS5_META, FTS5_META]],
        },
        {
            "ids": [["subquestion"]], "documents": [["Existing subquestion evidence"]],
            "metadatas": [[{"url": "https://subquestion.example/docs", "title": "S"}]],
        },
    ]
    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever._audited_index = _index()
    retriever.collection = SimpleNamespace(query=lambda **_kwargs: responses.pop(0))
    results = await retriever._do_search(
        "SQLite versus PostgreSQL", [], 4,
        adapted_queries=["SQLite PostgreSQL 需要基本全文检索", "Existing subquestion"],
        local_scene_needs=("full_text_search",),
    )
    assert [item["title"] for item in results] == ["P0", "P1", "p01-sqlite-fts5", "S"]
    assert results[2]["snippet"].startswith("FTS5 is an SQLite virtual table module")
    assert not responses
