import json

import pytest

from deepchoice.agents import conclusion_synthesizer as cs_mod
from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.contracts.errors import DeepChoiceError
from deepchoice.contracts.manifest import (
    WORKFLOW_NODES,
    build_run_manifest,
    ensure_run_manifest_compatible,
)
from deepchoice.utils.llm import MAX_OUTPUT_TOKENS, TIERS


def test_manifest_id_is_deterministic_and_created_at_is_not_identity():
    first = build_run_manifest({"query": "A vs B", "report_format": "evidence_first"})
    second = build_run_manifest({"query": "different", "report_format": "evidence_first"})

    assert first.manifest_id == second.manifest_id
    assert first.manifest_schema_version == 1
    assert first.app_version
    assert first.workflow_version == "research-v2"
    assert first.workflow_nodes == WORKFLOW_NODES
    assert first.state_schema_version == 2
    assert len(first.prompts) == 7
    assert len(first.llm_calls) == 8
    assert all(
        call.max_output_tokens == MAX_OUTPUT_TOKENS for call in first.llm_calls
    )
    assert len(first.retrievers) == 6
    assert first.report.template_version == "evidence-first-v1"
    assert first.scoring_policy_version == "source-score-v1"
    assert first.security_policy_version == "outbound-url-v1"
    assert first.citation_policy_version == "deterministic-citation-v1"


def test_pre_citation_manifest_identity_is_valid_but_runtime_incompatible():
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    old = current.model_copy(update={
        "workflow_version": "research-v1",
        "workflow_nodes": tuple(
            node for node in current.workflow_nodes if node != "citation_validator"
        ),
        "state_schema_version": 1,
        "citation_policy_version": None,
    })
    from deepchoice.contracts.manifest import _expected_manifest_id

    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    assert old.manifest_id == _expected_manifest_id(old)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(old, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_manifest_changes_when_effective_model_configuration_changes(monkeypatch):
    before = build_run_manifest({"query": "A vs B"})
    changed_tiers = {name: dict(config) for name, config in TIERS.items()}
    changed_tiers["deepseek-flash"]["model"] = "another-model"
    monkeypatch.setattr("deepchoice.contracts.manifest.TIERS", changed_tiers)

    after = build_run_manifest({"query": "A vs B"})

    assert after.manifest_id != before.manifest_id
    assert after.models[0].model == "another-model"


def test_manifest_contains_effective_models_but_no_endpoint_or_api_key(monkeypatch):
    secret = "super-secret-api-key"
    credential_url = "https://user:password@example.test/v1?token=hidden"
    changed_tiers = {name: dict(config) for name, config in TIERS.items()}
    changed_tiers["deepseek-flash"].update({"key": secret, "base": credential_url})
    monkeypatch.setattr("deepchoice.contracts.manifest.TIERS", changed_tiers)

    manifest = build_run_manifest({"query": "A vs B"})
    serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False)

    assert secret not in serialized
    assert credential_url not in serialized
    assert "password" not in serialized
    assert "hidden" not in serialized
    assert changed_tiers["deepseek-flash"]["model"] in serialized
    assert manifest.models[0].endpoint_sha256

    safe_tiers = {name: dict(config) for name, config in changed_tiers.items()}
    safe_tiers["deepseek-flash"]["base"] = "https://example.test/v1"
    monkeypatch.setattr("deepchoice.contracts.manifest.TIERS", safe_tiers)
    safe_manifest = build_run_manifest({"query": "A vs B"})
    assert safe_manifest.models[0].endpoint_sha256 == manifest.models[0].endpoint_sha256


def test_manifest_model_parameters_are_deeply_immutable():
    manifest = build_run_manifest({"query": "A vs B"})
    qwen = next(model for model in manifest.models if model.tier == "qwen-flash")

    assert qwen.extra_body_json == '{"enable_thinking":false}'
    assert isinstance(qwen.extra_body_json, str)


def test_manifest_freezes_dynamic_synthesis_parameters(monkeypatch):
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "1")
    manifest = build_run_manifest({"query": "A vs B"})
    synthesis = next(
        call for call in manifest.llm_calls if call.call_id == "conclusion_synthesizer"
    )

    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")

    assert synthesis.tier == "qwen-flash"
    assert synthesis.timeout_s == 900.0
    assert synthesis.seed == 0
    assert synthesis.extra_body_json == '{"enable_thinking":true}'


@pytest.mark.asyncio
async def test_synthesizer_uses_frozen_call_parameters(monkeypatch):
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "1")
    manifest = build_run_manifest({"query": "A vs B"})
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")
    captured = {}

    async def fake_call_model(_prompt, **kwargs):
        captured.update(kwargs)
        return {"winner": "A", "ranked_options": [], "confidence": "low"}

    monkeypatch.setattr(cs_mod, "call_model", fake_call_model)
    state_manifest = manifest.model_dump(mode="json")
    synthesis = next(
        call
        for call in state_manifest["llm_calls"]
        if call["call_id"] == "conclusion_synthesizer"
    )
    synthesis["tier"] = "deepseek-flash"
    synthesis["timeout_s"] = 1.0
    await cs_mod.ConclusionSynthesizerAgent(run_manifest=manifest).run(
        {
            "task": {"query": "A vs B"},
            "run_manifest": state_manifest,
            "evidence_chains": [],
            "source_scores": [],
            "conflicts": [],
        },
    )

    assert captured["model"] == "qwen-flash"
    assert captured["response_format"] == "json"
    assert captured["timeout"] == 900.0
    assert captured["seed"] == 0
    assert captured["extra_body"] == {"enable_thinking": True}


def test_orchestrator_initial_state_carries_same_frozen_manifest():
    task = {"query": "A vs B", "report_format": "comparison_matrix"}
    manifest = build_run_manifest(task)
    orchestrator = ChiefEditorAgent(task, run_manifest=manifest)

    initial_state = orchestrator._make_initial_state(task)

    assert orchestrator.run_manifest is manifest
    assert initial_state["run_manifest"] == manifest.model_dump(mode="json")
    assert initial_state["run_manifest"]["manifest_id"] == manifest.manifest_id
    assert initial_state["task"] is task


def test_saved_manifest_rejects_changed_runtime_model(monkeypatch):
    task = {"query": "A vs B"}
    manifest = build_run_manifest(task)
    changed_tiers = {name: dict(config) for name, config in TIERS.items()}
    changed_tiers["deepseek-flash"]["model"] = "new-runtime-model"
    monkeypatch.setattr("deepchoice.contracts.manifest.TIERS", changed_tiers)

    with pytest.raises(DeepChoiceError, match="incompatible") as caught:
        ensure_run_manifest_compatible(manifest, task)

    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_pre_budget_manifest_is_identity_valid_but_runtime_incompatible():
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    old_calls = tuple(
        call.model_copy(update={"max_output_tokens": None})
        for call in current.llm_calls
    )
    old = current.model_copy(update={"llm_calls": old_calls})
    from deepchoice.contracts.manifest import _expected_manifest_id

    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(old, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_saved_manifest_keeps_its_resolved_synthesis_option(monkeypatch):
    task = {"query": "A vs B"}
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "1")
    manifest = build_run_manifest(task)
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")

    ensure_run_manifest_compatible(manifest, task)


def test_manifest_covers_direct_evidence_gathering_call():
    manifest = build_run_manifest({"query": "A vs B"})
    call = next(
        item for item in manifest.llm_calls if item.call_id == "conflict_evidence_gather"
    )

    assert call.response_format is None
    assert call.timeout_s == 30.0
    assert call.max_iterations == 2
    assert call.tool_timeout_s == 20.0
    assert call.tools_sha256


def test_manifest_identity_rejects_tampered_content():
    task = {"query": "A vs B"}
    manifest = build_run_manifest(task)
    tampered = manifest.model_copy(update={"gather_evidence": not manifest.gather_evidence})

    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(tampered, task)

    assert caught.value.error_detail.code == "RUN_MANIFEST_ID_MISMATCH"


def test_manifest_identity_includes_evidence_gathering_switch():
    enabled = build_run_manifest({"query": "A vs B", "gather_evidence": True})
    disabled = build_run_manifest({"query": "A vs B", "gather_evidence": False})

    assert enabled.manifest_id != disabled.manifest_id


def test_orchestrator_uses_normalized_manifest_evidence_switch():
    orchestrator = ChiefEditorAgent({"query": "A vs B", "gather_evidence": "false"})

    detector = orchestrator._initialize_agents()["conflict_detector"]

    assert orchestrator.run_manifest.gather_evidence is False
    assert detector.gather_evidence is False


@pytest.mark.asyncio
async def test_orchestrator_execution_guard_runs_before_and_after_node():
    calls = []
    orchestrator = ChiefEditorAgent({"query": "A vs B"}, execution_guard=lambda: _record(calls))

    async def node(state):
        calls.append("node")
        return {}

    wrapped = orchestrator._timed_node("fake", node)
    await wrapped({})
    assert calls == ["guard", "node", "guard"]


async def _record(calls):
    calls.append("guard")


@pytest.mark.asyncio
async def test_resume_passes_none_input_to_langgraph(monkeypatch):
    captured = {}

    class Chain:
        async def ainvoke(self, graph_input, *, config):
            captured["input"] = graph_input
            captured["config"] = config
            return {}

    orchestrator = ChiefEditorAgent({"query": "A vs B"}, thread_id="thread-1")
    monkeypatch.setattr(orchestrator, "init_research_team", lambda **_: Chain())
    await orchestrator.run_research_task(resume=True)
    assert captured["input"] is None
    assert captured["config"]["configurable"]["thread_id"] == "thread-1"
