"""Diagnostics observer hook tests: content-free LLM metadata capture."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deepchoice.utils.llm import call_model, set_current_case, set_record_callback
from deepchoice.utils.call_diagnostics import observe_output


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
        assert "prompt" not in e
        assert "raw_content" not in e
        assert "parsed" not in e
        assert e["prompt_chars"] > 0
        assert len(e["prompt_sha256"]) == 64
        assert e["response_chars"] == len('{"a": 1}')
        assert len(e["response_sha256"]) == 64
        assert e["parsed_type"] == "dict"
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
        assert records[0]["error"] == "Exception"
        assert records[0]["error_type"] == "Exception"
        assert records[0]["response_sha256"] is None
        assert "boom" not in str(records[0])

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
        assert records[0]["tag"] == "deepseek-flash"
        assert records[0]["tier"] == "deepseek-flash"


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
                model="deepseek-flash", response_format="json",
                extra_body={"thinking": {"type": "enabled"}},
            )
        assert c.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}

    @pytest.mark.asyncio
    async def test_no_extra_body_uses_tier_default(self):
        c = _CaptureClient(_resp('{"a": 1}'))
        with patch("deepchoice.utils.llm._get_client", return_value=c):
            await call_model(
                [{"role": "user", "content": "json please"}],
                model="qwen-flash", response_format="json",
            )
        assert c.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}

    @pytest.mark.asyncio
    async def test_deepseek_flash_explicitly_disables_thinking(self):
        c = _CaptureClient(_resp('{"a": 1}'))
        with patch("deepchoice.utils.llm._get_client", return_value=c):
            await call_model(
                [{"role": "user", "content": "json please"}],
                model="deepseek-flash", response_format="json",
            )
        assert c.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [False, True])
    async def test_retired_qwen_selector_and_thinking_keyword_use_deepseek(self, enabled):
        c = _CaptureClient(_resp('{"a": 1}'))
        legacy_options = {"enable_thinking": enabled}
        with patch("deepchoice.utils.llm._get_client", return_value=c) as factory:
            await call_model(
                [{"role": "user", "content": "return an object"}],
                model="qwen-flash", response_format="json", extra_body=legacy_options,
            )
        assert factory.call_args.kwargs["tier"] == "deepseek-flash"
        from deepchoice.utils.llm import TIERS
        assert c.kwargs["model"] == TIERS["deepseek-flash"]["model"]
        assert c.kwargs["extra_body"] == {"thinking": {"type": "enabled" if enabled else "disabled"}}
        assert "JSON" in c.kwargs["messages"][-1]["content"]
        assert legacy_options == {"enable_thinking": enabled}


def _constraint_aware_synthesis():
    return {
        "winner": "context_dependent",
        "winner_rationale": "PRIVATE decision explanation",
        "recommendation": "Pilot after the missing constraint is known.",
        "decision_basis_version": "constraint-aware-v1",
        "requirement_assessments": [{
            "id": "constraint-1", "requirement": "Recovery requirement",
            "status": "unknown", "decision_critical": True,
            "explanation": "PRIVATE unresolved recovery details", "evidence_ids": [],
        }],
        "decision_branches": [{"option": "A", "condition": "If the pilot meets the SLO"}],
        "action_plan": [{
            "step": "Run a pilot", "verification": "Record recovery time",
            "change_trigger": "Recovery exceeds SLO", "rollback": "Restore the prior service",
        }],
        "ranked_options": [],
        "trade_offs": [],
        "evidence_summary": "",
        "confidence": "low",
        "confidence_rationale": "Constraints need confirmation",
        "unresolved_questions": ["Recovery requirement"],
        "scene_fit_note": "",
    }


def _synthesis_diagnostics(payload):
    return observe_output(
        SimpleNamespace(finish_reason="stop"),
        json_requested=True, content=json.dumps(payload), parsed=payload,
        parse_ok=True, tag="conclusion_synthesizer",
    )


def test_constraint_aware_synthesis_shape_is_observed_without_recording_content():
    diagnostics = _synthesis_diagnostics(_constraint_aware_synthesis())

    assert diagnostics["schema_status"] == "valid"
    assert diagnostics["json_status"] == "strict"
    encoded = json.dumps(diagnostics)
    assert "PRIVATE" not in encoded
    assert "Recovery" not in encoded
    assert "decision_branches" not in encoded


@pytest.mark.parametrize("field", [
    "decision_basis_version", "requirement_assessments", "decision_branches", "action_plan",
])
def test_synthesis_diagnostics_reject_missing_constraint_aware_contract(field):
    payload = _constraint_aware_synthesis()
    payload.pop(field)

    assert _synthesis_diagnostics(payload)["schema_status"] == "invalid"


@pytest.mark.parametrize(("field", "invalid_value"), [
    ("decision_basis_version", "arbitrary-policy"),
    ("requirement_assessments", [{
        "id": "c1", "requirement": "Recovery", "status": "verified",
        "decision_critical": True, "explanation": "x", "evidence_ids": [1],
    }]),
    ("requirement_assessments", [{
        "id": "c1", "requirement": "Recovery", "status": "unknown",
        "decision_critical": True, "explanation": "x", "evidence_ids": ["1"],
    }]),
    ("decision_branches", [{"option": "A"}]),
    ("action_plan", [{"step": "Pilot", "verification": "Measure", "change_trigger": "Failure"}]),
])
def test_synthesis_diagnostics_reject_malformed_decision_structures(field, invalid_value):
    payload = _constraint_aware_synthesis()
    payload[field] = invalid_value

    assert _synthesis_diagnostics(payload)["schema_status"] == "invalid"


@pytest.mark.parametrize(("profile", "tag", "payload", "bad"), [
    ("fact-selection-v1", "conclusion_synthesizer",
     {"source_facts": [{"id": "F1", "evidence_id": 1}]},
     {"source_facts": [{"id": "F1", "evidence_id": True}]}),
    ("fact-selection-v2", "conclusion_synthesizer",
     {"source_facts": [{"id": "F1", "evidence_id": 1, "source_ranges": [[0, 2]]}]},
     {"source_facts": [{"id": "F1", "evidence_id": 1, "source_ranges": [[True, 2]]}]}),
    ("fact-view-selection-v1", "conclusion_synthesizer",
     {"source_view_ids": ["S1", "S2W1"]}, {"source_view_ids": [True]}),
    ("question-judgment-v1", "conclusion_synthesizer",
     {"decision_analysis": []}, {"decision_analysis": [{}]}),
    ("question-judgment-v2", "conclusion_synthesizer",
     {"decision_analysis": [{"kind": "answer", "option": "", "question_id": "R0",
       "basis_refs": ["B1"], "reasoning": "PRIVATE REASON", "assumptions": [], "change_condition": "PRIVATE"}]},
     {"decision_analysis": [{"kind": "answer", "option": "", "question_id": "R0",
       "basis_refs": [True], "reasoning": "PRIVATE REASON", "assumptions": [], "change_condition": "PRIVATE"}]}),
    ("self-review-targeted-v1", "self_reviewer",
     {"analysis_reviews": [{"analysis_id": "A1", "action": "withdraw"}]}, {}),
    ("self-review-v2", "self_reviewer",
     {"checks": [{"item": 1, "passed": True}], "confidence": "low",
      "knowledge_gaps": [], "critical_gaps": [], "analysis_reviews": [], "provisional_reviews": []},
     {"checks": [], "confidence": "low", "knowledge_gaps": [], "critical_gaps": []}),
])
async def test_current_profiles_observe_valid_and_malformed_without_changing_return(profile, tag, payload, bad):
    from deepchoice.utils.call_diagnostics import public_call_result
    from deepchoice.utils.llm import max_output_tokens_for

    for value, expected in ((payload, "valid"), (bad, "invalid")):
        diagnostics, usage = [], []
        client = _CaptureClient(_resp(json.dumps(value)))
        with patch("deepchoice.utils.llm._get_client", return_value=client):
            result = await call_model(
                [{"role": "user", "content": "PRIVATE JSON"}], tag=tag,
                response_format="json", diagnostic_profile=profile,
                diagnostics=diagnostics, usage=usage,
            )
        assert result == value
        assert client.kwargs["max_tokens"] == max_output_tokens_for(tag)
        assert "diagnostic_profile" not in client.kwargs
        assert usage[0]["total_tokens"] == 15
        record = diagnostics[0]
        assert record["tag"] == tag
        assert record["diagnostics"]["policy"] == "node-shape-v2"
        assert record["diagnostics"]["profile"] == profile
        assert record["diagnostics"]["schema_status"] == expected
        assert record["failure_category"] == (None if expected == "valid" else "json_schema_error")
        public = public_call_result(json.dumps({"diagnostics": record["diagnostics"], "raw": "PRIVATE"}))
        assert public["diagnostics"] == record["diagnostics"]
        assert "PRIVATE" not in json.dumps(record)
    historical = public_call_result('{"diagnostics":{"policy":"node-shape-v1","schema_status":"invalid"}}')
    assert historical["diagnostics"]["policy"] == "node-shape-v1"
    assert historical["diagnostics"]["schema_status"] == "invalid"


async def test_diagnostic_profile_cannot_change_call_identity():
    with patch("deepchoice.utils.llm._get_client") as factory:
        with pytest.raises(ValueError, match="Unknown diagnostic profile"):
            await call_model([], tag="query_analyzer", diagnostic_profile="fact-selection-v1")
    factory.assert_not_called()
