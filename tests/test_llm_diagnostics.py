"""Diagnostics observer hook tests (task 0.2): raw LLM response capture."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deepchoice.utils.llm import call_model, set_current_case, set_record_callback


def _resp(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="deepseek-v4-flash",
    )


class _Client:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._resp


@pytest.fixture(autouse=True)
def _clear_callback():
    yield
    set_record_callback(None)
    set_current_case("")


class TestRecordCallback:
    @pytest.mark.asyncio
    async def test_emits_on_success_json(self):
        records = []

        async def cb(e):
            records.append(e)

        set_record_callback(cb)
        set_current_case("TC-X")
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_Client(_resp('{"a": 1}'))):
            result = await call_model(
                [{"role": "user", "content": "please answer in json"}],
                model="deepseek-flash", response_format="json", tag="node1",
            )
        assert result == {"a": 1}
        assert len(records) == 1
        e = records[0]
        assert e["tag"] == "node1"
        assert e["case_id"] == "TC-X"
        assert e["tier"] == "deepseek-flash"
        assert e["raw_content"] == '{"a": 1}'
        assert e["parsed"] == {"a": 1}
        assert e["error"] is None
        assert e["elapsed_ms"] >= 0
        assert e["usage"]["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_emits_error_entry(self):
        records = []

        async def cb(e):
            records.append(e)

        set_record_callback(cb)
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_Client(exc=Exception("boom"))):
            with pytest.raises(Exception):
                await call_model([{"role": "user", "content": "hi"}], tag="node2")
        assert len(records) == 1
        assert records[0]["error"] and "boom" in records[0]["error"]
        assert records[0]["raw_content"] is None

    @pytest.mark.asyncio
    async def test_no_callback_is_noop(self):
        # default: _record_callback is None — production path must not break
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_Client(_resp("plain"))):
            result = await call_model([{"role": "user", "content": "hi"}])
        assert result == "plain"

    @pytest.mark.asyncio
    async def test_default_tag_falls_back_to_tier(self):
        records = []

        async def cb(e):
            records.append(e)

        set_record_callback(cb)
        with patch("deepchoice.utils.llm._get_client",
                   return_value=_Client(_resp("plain"))):
            await call_model([{"role": "user", "content": "hi"}], model="qwen-flash")
        assert records[0]["tag"] == "qwen-flash"


class _CaptureClient:
    def __init__(self, resp):
        self._resp = resp
        self.kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return self._resp


class TestExtraBody:
    @pytest.mark.asyncio
    async def test_per_call_extra_body_overrides_tier_default(self):
        c = _CaptureClient(_resp('{"a": 1}'))
        with patch("deepchoice.utils.llm._get_client", return_value=c):
            await call_model(
                [{"role": "user", "content": "json please"}],
                model="qwen-flash", response_format="json",
                extra_body={"enable_thinking": True},
            )
        assert c.kwargs["extra_body"] == {"enable_thinking": True}

    @pytest.mark.asyncio
    async def test_no_extra_body_uses_tier_default(self):
        c = _CaptureClient(_resp('{"a": 1}'))
        with patch("deepchoice.utils.llm._get_client", return_value=c):
            await call_model(
                [{"role": "user", "content": "json please"}],
                model="qwen-flash", response_format="json",
            )
        assert c.kwargs["extra_body"] == {"enable_thinking": False}

    @pytest.mark.asyncio
    async def test_deepseek_flash_has_no_extra_body(self):
        c = _CaptureClient(_resp('{"a": 1}'))
        with patch("deepchoice.utils.llm._get_client", return_value=c):
            await call_model(
                [{"role": "user", "content": "json please"}],
                model="deepseek-flash", response_format="json",
            )
        assert "extra_body" not in c.kwargs
