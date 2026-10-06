"""Offline reliability checks; no model, embedding weights, or network."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from deepchoice.agents import conflict_detector as cd
from deepchoice.budget import BudgetExceededError, BudgetResource
from deepchoice.utils import llm


def sources():
    return [{"title": f"source {index}", "snippet": "fixture", "url": f"https://example.com/{index}",
             "total_score": 6, "scores": {"authority": 6}} for index in range(7)]


@pytest.mark.asyncio
@pytest.mark.parametrize("tag,limit", [("conflict_scan", 512), ("conflict_arbitration", 4096)])
async def test_dispatch_and_reservation_use_same_frozen_output_limit(monkeypatch, tag, limit):
    response = SimpleNamespace(model="fixture", usage=SimpleNamespace(prompt_tokens=10,
        completion_tokens=5, total_tokens=15),
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])
    create = AsyncMock(return_value=response)
    monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    reserve = AsyncMock(return_value=())
    monkeypatch.setattr("deepchoice.budget.reserve_call", reserve)
    await llm.call_model([{"role": "user", "content": "JSON fixture"}], tag=tag, response_format="json")
    sent = create.call_args.kwargs
    assert sent["max_tokens"] == limit
    amounts = reserve.call_args.args[0]
    tokens = next(a.amount for a in amounts if a.resource == BudgetResource.TOTAL_TOKENS)
    assert tokens == len(json.dumps(sent["messages"], ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")) + limit


@pytest.mark.asyncio
@pytest.mark.parametrize("deny", [False, True])
async def test_scan_bounds_fanout_and_drains_before_failure(monkeypatch, deny):
    monkeypatch.setattr(cd, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda titles: np.ones((len(titles), 3))))
    active = peak = calls = settled = 0
    async def scan(*_args, **_kwargs):
        nonlocal active, peak, calls, settled
        ordinal = calls
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            if deny and ordinal == 0:
                raise BudgetExceededError(BudgetResource.TOTAL_TOKENS,
                    limit=60000, consumed=59000, requested=2000)
            await asyncio.sleep(0.01)
            settled += 1
            return None
        finally:
            active -= 1
    monkeypatch.setattr(cd, "_scan_pair_contradiction", scan)
    if deny:
        with pytest.raises(BudgetExceededError):
            await cd.find_contradictions(sources(), "fixture")
        assert settled == 14  # All admitted fake work is done before propagation.
    else:
        assert await cd.find_contradictions(sources(), "fixture") == []
        assert settled == 15
    assert calls == 15 and peak == 4 and active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_kb_evidence_tool_uses_default_collection_and_embeddings(monkeypatch, failed):
    from deepchoice.retrievers import chroma_kb

    captured = {}
    def query(**kwargs):
        captured["query"] = kwargs
        if failed:
            raise RuntimeError("private provider detail must not escape")
        return {"ids": [["fixture"]], "documents": [["x" * 500]],
                "metadatas": [[{"url": "https://example.com/kb", "title": "fixture", "date": "2026"}]]}
    def collection(name):
        captured["collection"] = name
        return SimpleNamespace(query=query)
    def client(**kwargs):
        captured["path"] = kwargs["path"]
        return SimpleNamespace(get_or_create_collection=collection)
    monkeypatch.setenv("CHROMA_PATH", "fixture-isolated-kb")
    monkeypatch.setattr(chroma_kb.chromadb, "PersistentClient", client)
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda query: np.ones(1024)))
    monkeypatch.setattr("deepchoice.retrievers.base._outbound.get_resolver", lambda: SimpleNamespace(
        invalidate=AsyncMock()))
    result = json.loads(await cd._execute_search("search_kb", {"query": "fixture", "max_results": 2}))
    assert captured["path"] == "fixture-isolated-kb" and captured["collection"] == "tech_kb"
    assert "query_texts" not in captured["query"]
    assert len(captured["query"]["query_embeddings"][0]) == 1024
    if failed:
        assert result == {"error": "KB collection unavailable", "results": []}
        assert cd._tool_failure_category(json.dumps(result)) == "knowledge_base_unavailable"
    else:
        assert result == [{"content": "x" * 300, "metadata": {
            "url": "https://example.com/kb", "title": "fixture", "date": "2026"}}]


@pytest.mark.asyncio
async def test_kb_evidence_tool_does_not_swallow_budget_error(monkeypatch):
    error = BudgetExceededError(BudgetResource.RETRIEVAL_CALLS,
        limit=72, consumed=72, requested=1)
    monkeypatch.setattr("deepchoice.retrievers.chroma_kb.ChromaKB.retrieve", AsyncMock(side_effect=error))
    monkeypatch.setattr("deepchoice.retrievers.chroma_kb.ChromaKB.__init__", lambda self: None)
    with pytest.raises(BudgetExceededError) as raised:
        await cd._execute_search("search_kb", {"query": "fixture"})
    assert raised.value is error


@pytest.mark.asyncio
async def test_arbitration_has_a_run_local_four_call_gate(monkeypatch):
    items = sources()
    pairs = [{"source_a": items[0], "source_b": items[1], "similarity": 1}
             for _ in range(15)]
    monkeypatch.setattr(cd, "find_contradictions", AsyncMock(return_value=pairs))
    active = peak = calls = 0
    async def arbitrate(*_args, **_kwargs):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return {"resolution": "both_partial", "confidence": "high"}
        finally:
            active -= 1
    monkeypatch.setattr(cd, "call_model", arbitrate)
    result = await cd.ConflictDetectorAgent(legacy_arbitration=True).run({"task": {"query": "fixture"}, "source_scores": items})
    assert len(result["conflicts"]) == 15
    assert calls == 15 and peak == 4 and active == 0
