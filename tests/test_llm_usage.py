"""Token usage capture tests (Task 2: LLM token instrumentation).

Covers call_model's `usage` param, summarize_usage helper, and per-agent
read-accumulate-write wiring into ResearchState["token_usage"].
"""
import types
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from deepchoice.utils.llm import call_model, summarize_usage
from deepchoice.agents.query_analyzer import QueryAnalyzerAgent
from deepchoice.agents.query_adapter import QueryAdapterAgent
from deepchoice.agents.self_reviewer import SelfReviewerAgent
from deepchoice.agents import conflict_detector as cd_module


def _fake_response(content, model="flash",
                   prompt_tokens=120, completion_tokens=80):
    return types.SimpleNamespace(
        model=model,
        usage=types.SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
    )


def _fake_client(response):
    create = AsyncMock(return_value=response)
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)),
    )


def _gather_fake_response(content="evidence found", model="flash",
                          prompt_tokens=150, completion_tokens=60):
    """Fake OpenAI response for _gather_evidence: assistant message with
    model_dump() and no tool_calls, plus a usage block."""
    message = types.SimpleNamespace(
        content=content,
        tool_calls=[],
        model_dump=lambda exclude_none=None: {"role": "assistant", "content": content},
    )
    return types.SimpleNamespace(
        model=model,
        usage=types.SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        choices=[types.SimpleNamespace(message=message)],
    )


class _APIError(Exception):
    def __init__(self, status_code):
        super().__init__(f"API error {status_code}")
        self.status_code = status_code


class TestCallModelRetry:
    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        create = AsyncMock(side_effect=[_APIError(429), _APIError(429), _fake_response("ok")])
        client = _fake_client(_fake_response("ok"))
        client.chat.completions.create = create
        with patch("deepchoice.utils.llm._get_client", return_value=client), \
             patch("deepchoice.utils.llm._retry_sleep", new=AsyncMock()):
            result = await call_model([{"role": "user", "content": "hi"}])
        assert result == "ok"
        assert create.await_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        create = AsyncMock(side_effect=[_APIError(429), _APIError(429), _APIError(429)])
        client = _fake_client(_fake_response("ok"))
        client.chat.completions.create = create
        with patch("deepchoice.utils.llm._get_client", return_value=client), \
             patch("deepchoice.utils.llm._retry_sleep", new=AsyncMock()):
            with pytest.raises(Exception):
                await call_model([{"role": "user", "content": "hi"}])
        assert create.await_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_status(self):
        create = AsyncMock(side_effect=_APIError(400))
        client = _fake_client(_fake_response("ok"))
        client.chat.completions.create = create
        with patch("deepchoice.utils.llm._get_client", return_value=client), \
             patch("deepchoice.utils.llm._retry_sleep", new=AsyncMock()):
            with pytest.raises(Exception):
                await call_model([{"role": "user", "content": "hi"}])
        assert create.await_count == 1


class TestCallModelUsageCapture:
    @pytest.mark.asyncio
    async def test_appends_usage_record_after_successful_call(self):
        usage = []
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(_fake_response("plain text answer"))):
            result = await call_model([{"role": "user", "content": "hi"}], usage=usage)

        assert result == "plain text answer"
        assert usage == [{
            "model": "flash",
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
        }]

    @pytest.mark.asyncio
    async def test_without_usage_param_keeps_old_behavior(self):
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(_fake_response('{"ok": true}'))):
            result = await call_model(
                [{"role": "user", "content": "hi"}],
                model="flash",
                response_format="json",
            )

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_captures_usage_even_when_json_parse_fails(self):
        usage = []
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(_fake_response("not json at all {{{"))):
            result = await call_model(
                [{"role": "user", "content": "hi"}],
                response_format="json",
                usage=usage,
            )

        assert result == {}
        assert len(usage) == 1, "failed parses must still count the LLM call"
        assert usage[0]["total_tokens"] == 200

    @pytest.mark.asyncio
    async def test_falls_back_to_requested_model_when_response_model_missing(self):
        usage = []
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(_fake_response("answer", model=None))):
            await call_model(
                [{"role": "user", "content": "hi"}],
                model="pro",
                usage=usage,
            )

        assert usage[0]["model"] == "qwen3.8-flash"  # alias resolved to the real model name

    @pytest.mark.asyncio
    async def test_skips_capture_when_response_usage_is_none(self):
        usage = []
        response = _fake_response("answer")
        response.usage = None
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(response)):
            result = await call_model([{"role": "user", "content": "hi"}], usage=usage)

        assert result == "answer"
        assert usage == []


class TestSummarizeUsage:
    def test_single_model_aggregates_sums(self):
        records = [
            {"model": "flash", "prompt_tokens": 100,
             "completion_tokens": 50, "total_tokens": 150},
            {"model": "flash", "prompt_tokens": 200,
             "completion_tokens": 75, "total_tokens": 275},
        ]

        summary = summarize_usage("query_analyzer", records)

        assert summary == {
            "agent": "query_analyzer",
            "model": "flash",
            "calls": 2,
            "prompt_tokens": 300,
            "completion_tokens": 125,
            "total_tokens": 425,
        }

    def test_mixed_models_joins_unique_names(self):
        records = [
            {"model": "flash", "prompt_tokens": 10,
             "completion_tokens": 5, "total_tokens": 15},
            {"model": "pro", "prompt_tokens": 30,
             "completion_tokens": 20, "total_tokens": 50},
            {"model": "flash", "prompt_tokens": 10,
             "completion_tokens": 5, "total_tokens": 15},
        ]

        summary = summarize_usage("conflict_detector", records)

        assert summary["model"] == "flash,pro"
        assert summary["calls"] == 3
        assert summary["total_tokens"] == 80

    def test_empty_usage_returns_zero_row(self):
        summary = summarize_usage("query_adapter", [])

        assert summary == {
            "agent": "query_adapter",
            "model": "",
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }


def _embedding_fake(dim=8):
    def encode(titles):
        return np.ones((len(titles), dim))
    return types.SimpleNamespace(encode=encode)


class TestAgentTokenUsageWiring:
    @pytest.mark.asyncio
    async def test_query_analyzer_writes_token_usage_row(self):
        state = {
            "task": {"query": "FastAPI vs Flask", "scene_context": "solo", "constraints": []},
            "token_usage": [{
                "agent": "prior_agent", "model": "", "calls": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            }],
        }
        content = '{"sub_questions": ["q1", "q2"], "scene_context": "solo", "constraints": []}'
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(_fake_response(content))):
            result = await QueryAnalyzerAgent().run(state)

        assert len(result["token_usage"]) == 2
        assert result["token_usage"][0]["agent"] == "prior_agent"
        assert result["token_usage"][1] == {
            "agent": "query_analyzer",
            "model": "flash",
            "calls": 1,
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
        }

    @pytest.mark.asyncio
    async def test_query_adapter_early_return_writes_zero_row(self):
        state = {
            "task": {"query": "x", "scene_context": "solo", "constraints": []},
            "sub_questions": [],
        }
        result = await QueryAdapterAgent().run(state)

        rows = result.get("token_usage", [])
        assert len(rows) == 1
        assert rows[0]["agent"] == "query_adapter"
        assert rows[0]["calls"] == 0

    @pytest.mark.asyncio
    async def test_self_reviewer_accumulates_across_invocations(self):
        state = {
            "task": {"query": "x", "scene_context": "solo", "constraints": []},
            "report": "# report",
            "evidence_chains": [],
            "sub_questions": [],
            "quality_signals": [],
            "retry_count": 0,
        }
        content = ('{"checks": [], "passed_count": 5, '
                   '"confidence": "high", "knowledge_gaps": []}')
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_fake_client(_fake_response(content))):
            first = await SelfReviewerAgent().run(state)
            second_state = {**state, "token_usage": first["token_usage"],
                            "retry_count": first["retry_count"]}
            second = await SelfReviewerAgent().run(second_state)

        rows = second["token_usage"]
        assert [r["agent"] for r in rows] == ["self_reviewer", "self_reviewer"]
        assert [r["calls"] for r in rows] == [1, 1]
        assert rows[1]["total_tokens"] == 200

    @pytest.mark.asyncio
    async def test_conflict_scan_captures_usage_with_wellformed_messages(self, monkeypatch):
        monkeypatch.setattr(cd_module, "get_embedding_model", lambda: _embedding_fake())
        usage = []
        content = ('{"has_difference": false, "type": "none", "explanation": ""}')
        client = _fake_client(_fake_response(content))
        create = client.chat.completions.create

        with patch("deepchoice.utils.llm._get_client", return_value=client):
            pairs = await cd_module.find_contradictions(
                [
                    {"url": "https://a", "title": "A vs B", "snippet": "s",
                     "total_score": 7.5, "scores": {"authority": 7}},
                    {"url": "https://b", "title": "B vs A", "snippet": "s",
                     "total_score": 8.0, "scores": {"authority": 8}},
                ],
                query_topic="A vs B",
                usage=usage,
            )

        assert pairs == []
        assert len(usage) == 1, "scan-phase LLM calls must be captured"
        sent_messages = create.await_args.kwargs["messages"]
        assert len(sent_messages) == 2, "scan prompt must be system+user messages, not a polluted content list"
        for msg in sent_messages:
            assert isinstance(msg, dict)
            assert msg["role"] in ("system", "user")
            assert isinstance(msg["content"], str)

    @pytest.mark.asyncio
    async def test_conflict_detector_no_pairs_writes_zero_row(self, monkeypatch):
        monkeypatch.setattr(cd_module, "get_embedding_model", lambda: _embedding_fake())
        state = {
            "task": {"query": "x"},
            "source_scores": [{"title": "low", "total_score": 3.0, "url": "https://c"}],
        }
        result = await cd_module.ConflictDetectorAgent(gather_evidence=False).run(state)

        assert result["conflicts"] == []
        rows = result.get("token_usage", [])
        assert len(rows) == 1
        assert rows[0]["agent"] == "conflict_detector"
        assert rows[0]["calls"] == 0


class TestGatherEvidenceUsageCapture:
    @pytest.mark.asyncio
    async def test_gather_evidence_appends_usage_row(self):
        """_gather_evidence builds AsyncOpenAI directly (not via call_model),
        so its client is mocked by patching openai.AsyncOpenAI — the local
        `from openai import AsyncOpenAI` inside the function picks it up."""
        usage = []
        client = _fake_client(
            _gather_fake_response("Benchmarks favor async under concurrent load"))
        with patch("openai.AsyncOpenAI", return_value=client):
            evidence = await cd_module._gather_evidence(
                topic="FastAPI async performance",
                claim_a="Async endpoints are slower than sync",
                claim_b="Async endpoints are faster under concurrency",
                usage=usage,
            )

        assert evidence == "Benchmarks favor async under concurrent load"
        assert usage == [{
            "model": "flash",
            "prompt_tokens": 150,
            "completion_tokens": 60,
            "total_tokens": 210,
        }]
