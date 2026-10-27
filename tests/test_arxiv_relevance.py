"""D2: arXiv domain gating and candidate-relevance filter."""
import asyncio

import pytest

from deepchoice.retrievers import arxiv_api
from deepchoice.retrievers.arxiv_api import (
    ArxivSearch,
    is_academic_question,
    _result_is_relevant,
)


def test_non_academic_selection_questions_skip_arxiv():
    assert is_academic_question(
        "我们正在 Svelte 和 Vue 之间做技术选型",
        ["Svelte 构建速度与 Vue 生态对比", "Svelte 与 Vue 的长期维护成本"],
        ["Svelte", "Vue"],
    ) is False
    assert is_academic_question(
        "Elasticsearch vs OpenSearch for regulated audit logging",
        [], ["Elasticsearch", "OpenSearch"],
    ) is False
    assert is_academic_question(
        "MySQL vs MariaDB migration compatibility", [], ["MySQL", "MariaDB"],
    ) is False


def test_ml_selection_questions_keep_arxiv():
    assert is_academic_question(
        "LangGraph vs AutoGen for agent orchestration", [], ["LangGraph", "AutoGen"],
    ) is True
    assert is_academic_question(
        "vLLM vs TGI inference latency", [], ["vLLM", "Text Generation Inference"],
    ) is True
    assert is_academic_question(
        "pgvector vs Qdrant for RAG", [], ["pgvector", "Qdrant"],
    ) is True
    assert is_academic_question(
        "Which embedding model should we use for retrieval?", [], [],
    ) is True


def test_candidate_relevance_filter_drops_unrelated_papers():
    keep = _result_is_relevant(
        "LangGraph: stateful agent orchestration", "We benchmark LangGraph...",
        "agent framework", ["LangGraph", "AutoGen"])
    drop = _result_is_relevant(
        "Chinese word segmentation with transformers", "A study of tokenizers...",
        "agent framework", ["LangGraph", "AutoGen"])
    assert keep is True
    assert drop is False


def test_open_question_requires_two_significant_words():
    keep = _result_is_relevant(
        "Retrieval augmented generation benchmarks", "RAG evaluation study",
        "retrieval augmented generation evaluation", [])
    drop = _result_is_relevant(
        "A note on tokenization", "This paper studies tokenization only",
        "retrieval augmented generation evaluation", [])
    assert keep is True
    assert drop is False


def test_relaxed_rule_keeps_topical_paper_without_candidate_name():
    keep = _result_is_relevant(
        "Multi-agent framework with stateful workflows",
        "We study orchestration and recovery in agent systems.",
        "agent orchestration LangGraph AutoGen", ["LangGraph", "AutoGen"])
    drop = _result_is_relevant(
        "Chinese word segmentation with transformers",
        "A study of tokenizers and segmentation accuracy.",
        "agent orchestration LangGraph AutoGen", ["LangGraph", "AutoGen"])
    assert keep is True
    assert drop is False


def test_relaxed_rule_requires_analysis_like_paper():
    drop = _result_is_relevant(
        "Multi-agent learning in social settings",
        "We study emergent behavior in simulated communities.",
        "MySQL MariaDB indexing", ["LangGraph", "AutoGen"])
    keep = _result_is_relevant(
        "A Survey of Retrieval-Augmented Generation Pipelines",
        "We review RAG architectures and evaluation methods.",
        "document indexing", ["LlamaIndex", "Haystack"])
    assert drop is False
    assert keep is True


@pytest.mark.asyncio
async def test_gated_arxiv_search_makes_no_http_call(monkeypatch):
    called = {"value": False}

    async def fail_if_called(*args, **kwargs):
        called["value"] = True
        raise AssertionError("outbound client must not be created")

    monkeypatch.setattr(arxiv_api._outbound, "make_client", fail_if_called)
    result = await ArxivSearch().search(
        "Svelte vs Vue for a solo founder", [], candidate_techs=["Svelte", "Vue"])
    assert result["status"] == "empty"
    assert result["empty_reason"] == "domain_not_academic"
    assert result["results"] == []
    assert called["value"] is False
