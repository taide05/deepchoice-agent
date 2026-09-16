"""Provider context-cache accounting is metadata, not retrieval/response caching."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai.types import CompletionUsage

from benchmarks.product_baseline import node_usage_projection, record_usage_projection, write_collection_summary
from deepchoice.utils import llm
from deepchoice.utils.token_usage import CACHE_FIELDS, cache_totals, provider_usage, public_usage, trace_usage


def _native(hit=80, miss=20):
    return {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
            "prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": miss}


def test_sdk_native_usage_and_alias_are_allowlisted():
    raw = CompletionUsage(**_native(), private_note="not public")
    assert provider_usage(raw) == _native()
    assert trace_usage(raw) == {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                                "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20}
    alias = {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 80}}
    assert provider_usage(alias)["prompt_cache_miss_tokens"] == 20
    assert "private_note" not in provider_usage(raw)


@pytest.mark.parametrize("fields", [
    {"prompt_cache_hit_tokens": True}, {"prompt_cache_miss_tokens": -1},
    {"prompt_cache_hit_tokens": "80"}, {"prompt_cache_miss_tokens": 21},
    {"prompt_cache_hit_tokens": None}, {"prompt_tokens": None},
    {"prompt_tokens_details": {"cached_tokens": True}},
    {"prompt_tokens_details": {"cached_tokens": 80.0}},
    {"prompt_tokens_details": {"cached_tokens": 79}},
    {"prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None,
     "prompt_tokens_details": {"cached_tokens": 80}},
])
def test_invalid_or_inconsistent_cache_pair_is_unknown(fields):
    usage = provider_usage({**_native(), **fields})
    assert not any(field in usage for field in CACHE_FIELDS)


def test_missing_zero_and_partial_aggregate_are_distinct():
    assert provider_usage(None) == {}
    assert cache_totals([{"input_tokens": 100}])["prompt_cache_hit_tokens"] is None
    zero = trace_usage(_native(0, 100))
    assert cache_totals([zero])["prompt_cache_hit_ratio"] == 0
    empty = trace_usage({**_native(0, 0), "prompt_tokens": 0})
    assert cache_totals([empty])["prompt_cache_hit_ratio"] is None
    partial = cache_totals([trace_usage(_native()), {}])
    assert partial["prompt_cache_hit_tokens"] == 80
    assert partial["cache_usage_known_calls"] == 1
    assert partial["cache_usage_complete"] is False
    assert partial["prompt_cache_hit_ratio"] is None
    assert public_usage({**trace_usage(_native()), "private": "body"}) == trace_usage(_native())


@pytest.mark.parametrize("alias", [True, 1.0])
@pytest.mark.parametrize("sdk", [False, True])
def test_alias_equal_to_native_integer_still_requires_strict_integer(alias, sdk):
    raw = {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1,
           "prompt_cache_hit_tokens": 1, "prompt_cache_miss_tokens": 0,
           "prompt_tokens_details": {"cached_tokens": alias}}
    # The real SDK may coerce details; use an object fixture to preserve malformed
    # provider values and cover our object and dict extraction paths explicitly.
    value = SimpleNamespace(**raw) if sdk else raw
    assert not any(field in provider_usage(value) for field in CACHE_FIELDS)


@pytest.mark.asyncio
async def test_shared_call_trace_list_and_diagnostics_agree_without_budget_discount(monkeypatch):
    response = SimpleNamespace(model="deepseek-flash", usage=CompletionUsage(**_native()),
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response))))
    monkeypatch.setattr(llm, "_get_client", lambda **_: client)
    import deepchoice.observability as obs
    import deepchoice.budget as budget
    trace = SimpleNamespace(start_external_call=AsyncMock(return_value=SimpleNamespace(call_id="call")),
                            finish_external_call=AsyncMock())
    monkeypatch.setattr(obs, "current_trace_recorder", lambda: (trace, "node"))
    settle = AsyncMock()
    monkeypatch.setattr(budget, "reserve_call", AsyncMock(return_value=()))
    monkeypatch.setattr(budget, "settle_call", settle)
    records, usage = [], []
    async def observer(record):
        records.append(record)
    monkeypatch.setattr(llm, "_record_callback", observer)
    assert await llm.call_model([{"role": "user", "content": "private JSON prompt"}],
                                response_format="json", usage=usage) == {"ok": True}
    assert trace.finish_external_call.call_args.kwargs["usage_summary"] == trace_usage(response.usage)
    assert usage[0]["prompt_cache_hit_tokens"] == records[0]["usage"]["prompt_cache_hit_tokens"] == 80
    assert settle.call_args.args[1][budget.BudgetResource.TOTAL_TOKENS] == 110
    assert "private JSON prompt" not in json.dumps(records)
    assert llm.summarize_usage("query_analyzer", usage)["cache_usage_complete"] is True


def test_node_export_keeps_attempts_retries_and_historical_unknown_separate(tmp_path):
    known = trace_usage(_native())
    calls = [{"kind": "llm", "node_name": "conflict_detector", "node_attempt_no": 1,
              "retry_no": 0, "usage": known},
             {"kind": "llm", "node_name": "conflict_detector", "node_attempt_no": 1,
              "retry_no": 1, "usage": None},
             {"kind": "llm", "node_name": "conflict_detector", "node_attempt_no": 2,
              "retry_no": 0, "usage": {"input_tokens": 10}},
             {"kind": "retrieval", "node_name": "multi_retriever", "node_attempt_no": 1}]
    record = {"case_id": "P01", "run_id": "run", "status": "completed", "observability": {
        "availability": "available", "calls": calls, "totals": {"total_tokens": 110}}}
    rows = node_usage_projection(record)
    assert len(rows) == 2
    assert rows[0]["llm_calls"] == 2 and rows[0]["llm_retries"] == 1
    assert rows[0]["cache_usage_known_calls"] == 1
    assert rows[0]["cache_usage_complete"] is False and rows[0]["prompt_cache_hit_ratio"] is None
    assert rows[1]["prompt_cache_miss_tokens"] is None
    write_collection_summary(tmp_path, [record])
    assert "prompt_cache_miss_tokens" in (tmp_path / "usage.csv").read_text(encoding="utf-8-sig")
    assert "conflict_detector" in (tmp_path / "usage-by-node.csv").read_text(encoding="utf-8-sig")
    assert record_usage_projection(record)["prompt_cache_hit_tokens"] is None
    record["observability_final"] = False
    record["observability"]["totals"].update(cache_totals([known]))
    assert record_usage_projection(record)["cache_usage_complete"] is False
    assert record_usage_projection(record)["prompt_cache_hit_ratio"] is None
    assert all(row["cache_usage_complete"] is False for row in node_usage_projection(record))
