"""Knowledge gaps never become search targets: the graph has no retry edge.

`self_reviewer` is terminal, so a low-confidence review serves the result as-is
and `knowledge_gaps` stay in the state/snapshot. There is no retry routing, and
the deprecated `retry_count` field was removed (2026-11-17 Step B). These tests
pin the observable result: a run that still carries knowledge_gaps adapts and
searches the original sub-questions, not the gaps.
"""
from __future__ import annotations

import asyncio

from deepchoice.agents import multi_retriever as mr
from deepchoice.agents import query_adapter as qa


def test_query_adapter_ignores_retry_targets(monkeypatch):
    captured = {}

    async def fake_call_model(prompt, **kwargs):
        captured["prompt"] = "\n".join(
            str(message.get("content", "")) for message in prompt)
        return {"adapted": []}

    monkeypatch.setattr(qa, "call_model", fake_call_model)
    out = asyncio.run(qa.QueryAdapterAgent().run({
        "task": {"query": "Kafka vs Redis", "constraints": []},
        "sub_questions": ["throughput comparison question"],
        "knowledge_gaps": ["a gap query"],
    }))

    assert "throughput comparison question" in captured["prompt"]
    assert "a gap query" not in captured["prompt"]
    # The fallback still fills every retriever from the original sub-questions.
    assert out["adapted_queries"]["tavily"] == ["throughput comparison question"]


def test_multi_retriever_ignores_retry_targets(monkeypatch):
    searches = []

    class FakeRetriever:
        async def search(self, query, sub_questions, adapted_queries=None,
                         candidate_techs=None):
            searches.append(list(sub_questions))
            return {"source": "fake", "status": "success", "results": [],
                    "latency_ms": 0}

    monkeypatch.setattr(mr, "RETRIEVER_REGISTRY", {"fake": FakeRetriever})
    monkeypatch.setattr(mr, "extract_terms", lambda text: [])
    monkeypatch.setattr(mr, "harvest", lambda terms, results, existing=None: [])
    out = asyncio.run(mr.MultiRetrieverAgent().run({
        "task": {"query": "Kafka vs Redis", "candidate_techs": [],
                 "constraints": []},
        "sub_questions": ["throughput comparison question"],
        "adapted_queries": {},
        "knowledge_gaps": ["a gap query"],
        "token_usage": [],
    }))

    assert searches, "no retriever was called"
    assert searches[0] == ["throughput comparison question"], searches[0]
    assert out["search_results"][0]["status"] == "success"
