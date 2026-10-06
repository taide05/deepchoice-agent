"""DeepSeek-only configuration without touching local credentials or the network."""
import runpy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deepchoice.utils import llm


@pytest.mark.parametrize("credential", ["DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY", None])
def test_only_deepseek_credentials_are_resolved(monkeypatch, credential):
    for name in ("DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY",
                 "DS_FLASH_MODEL", "FLASH_MODEL", "DS_FLASH_BASE_URL", "FLASH_BASE_URL", "DEEPSEEK_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for prefix in ("QW_FLASH", "PRO", "LLM"):
        monkeypatch.setenv(f"{prefix}_API_KEY", "wrong-provider-canary")
        monkeypatch.setenv(f"{prefix}_BASE_URL", "https://wrong-provider.test/v1")
        monkeypatch.setenv(f"{prefix}_MODEL", "wrong-provider-model")
    if credential:
        monkeypatch.setenv(credential, "deepseek-test-key")
    namespace = runpy.run_path(str(Path(llm.__file__)))
    tiers = namespace["TIERS"]
    assert set(tiers) == {"deepseek-flash"}
    assert tiers["deepseek-flash"] == {
        "model": "deepseek-v4-flash", "base": "https://api.deepseek.com/v1",
        "key": "deepseek-test-key" if credential else "",
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_legacy_client_selector_cannot_open_a_qwen_client(monkeypatch):
    captured = {}

    def client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm, "AsyncOpenAI", client)
    monkeypatch.setattr(llm, "TIERS", {"deepseek-flash": {
        "key": "deepseek-test-key", "base": "https://deepseek.test/v1", "model": "flash-test",
    }})
    llm._get_client(tier="qwen-flash", max_retries=0)
    assert captured["base_url"] == "https://deepseek.test/v1"
    assert captured["api_key"] == "deepseek-test-key"
    assert captured["max_retries"] == 0


def test_native_thinking_option_wins_over_legacy_option_without_mutation():
    options = {"enable_thinking": True, "thinking": {"type": "disabled"}}
    assert llm.deepseek_extra_body(options) == {"thinking": {"type": "disabled"}}
    assert options == {"enable_thinking": True, "thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_evidence_rearbitration_uses_deepseek_and_same_conflict_gate(monkeypatch):
    from deepchoice.agents import conflict_detector as detector

    source = {"url": "https://a.test", "title": "Claim A", "total_score": 7, "scores": {"authority": 7}}
    pair = {"source_a": source, "source_b": {**source, "url": "https://b.test", "title": "Claim B"}, "similarity": 0.9}
    monkeypatch.setattr(detector, "find_contradictions", AsyncMock(return_value=[pair]))
    monkeypatch.setattr(detector, "_deterministic_arbitration", lambda *_: None)
    monkeypatch.setattr(detector, "_gather_evidence", AsyncMock(return_value="Additional evidence"))
    gate = AsyncMock()
    monkeypatch.setattr(detector, "FLASH_SEM", gate)
    call = AsyncMock(side_effect=[
        {"confidence": "low", "resolution": "insufficient_data"},
        {"confidence": "high", "resolution": "A_correct"},
    ])
    monkeypatch.setattr(detector, "call_model", call)
    result = await detector.ConflictDetectorAgent(legacy_arbitration=True).run({"task": {"query": "A vs B"}, "source_scores": []})
    assert [entry.kwargs["model"] for entry in call.await_args_list] == ["deepseek-flash", "deepseek-flash"]
    assert call.await_args_list[-1].kwargs["tag"] == "conflict_rearbitration"
    assert gate.__aenter__.await_count == 2
    assert result["conflicts"][0]["arbiter_model"] == "deepseek-flash+evidence"
    assert result["conflicts"][0]["resolution"] == "A_correct"


@pytest.mark.asyncio
async def test_synthesis_without_manifest_uses_deepseek_native_option(monkeypatch):
    from deepchoice.agents import conclusion_synthesizer as synthesis

    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "1")
    call = AsyncMock(return_value={"winner": "A", "ranked_options": [], "confidence": "low"})
    monkeypatch.setattr(synthesis, "call_model", call)
    await synthesis.ConclusionSynthesizerAgent().run({"task": {"query": "A vs B"}})
    assert call.await_args.kwargs["model"] == "deepseek-flash"
    assert call.await_args.kwargs["extra_body"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
