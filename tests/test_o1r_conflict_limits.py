"""Offline reliability checks; no model, embedding weights, or network."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
@pytest.mark.parametrize("scores", [[], [7], [3, 4], [7, 4]])
async def test_unpairable_sources_do_not_require_embedding_weights(monkeypatch, scores):
    from copy import deepcopy

    loader = Mock(side_effect=AssertionError("Unpairable sources must not load weights"))
    call = AsyncMock(side_effect=AssertionError("Unpairable sources must not call the model"))
    monkeypatch.setattr(cd, "get_embedding_model", loader)
    monkeypatch.setattr(cd, "call_model", call)
    items = [{"title": f"Source {index}", "snippet": "Complete fixture description.",
              "url": f"https://source{index}.example/docs", "total_score": score}
             for index, score in enumerate(scores)]
    original = deepcopy(items)
    previous_usage = {"agent": "previous", "total_tokens": 17}
    result = await cd.ConflictDetectorAgent().run({
        "task": {"query": "Select a store"}, "source_scores": items,
        "token_usage": [previous_usage],
    })
    assert result["conflicts"] == [] and items == original
    assert result["token_usage"][0] == previous_usage
    assert result["quality_signals"] == [{
        "agent": "conflict_detector", "conflicts_found": 0,
        "resolved_count": 0, "unresolved_count": 0, "scan_unknown_count": 0,
        "conflict_policy": "scan-only-v2",
        "gather_evidence_requested": True, "gather_evidence_effective": False,
    }]
    loader.assert_not_called()
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairable_sources_keep_embedding_load_failure_visible(monkeypatch):
    loader = Mock(side_effect=RuntimeError("Embedding unavailable"))
    call = AsyncMock()
    monkeypatch.setattr(cd, "get_embedding_model", loader)
    monkeypatch.setattr(cd, "call_model", call)
    items = [{"title": f"Source {index}", "total_score": 5}
             for index in range(2)]
    with pytest.raises(RuntimeError, match="Embedding unavailable"):
        await cd.find_contradictions(items)
    loader.assert_called_once_with()
    call.assert_not_awaited()
