import json
import re

import pytest

from deepchoice.agents import conclusion_synthesizer as cs_mod
from deepchoice.agents.conflict_detector import (
    ARBITRATION_SYSTEM,
    CONTRADICTION_SCAN_SYSTEM,
    EVIDENCE_GATHER_SYSTEM,
    EVIDENCE_GATHER_USER_TEMPLATE,
)
from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.agents.query_adapter import ADAPT_SYSTEM
from deepchoice.agents.query_analyzer import DECOMPOSITION_SYSTEM
from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
from deepchoice.contracts.errors import DeepChoiceError
from deepchoice.contracts.manifest import (
    REPORT_TEMPLATE_VERSIONS,
    WORKFLOW_NODES,
    _expected_core_asset_registry_id,
    build_core_asset_registry,
    build_run_manifest,
    ensure_run_manifest_compatible,
)
from deepchoice.utils.llm import TIERS, max_output_tokens_for


def test_manifest_id_is_deterministic_and_created_at_is_not_identity():
    first = build_run_manifest({"query": "A vs B", "report_format": "evidence_first"})
    second = build_run_manifest({"query": "different", "report_format": "evidence_first"})

    assert first.manifest_id == second.manifest_id
    assert first.manifest_schema_version == 1
    assert first.app_version
    assert first.workflow_version == "research-v3"
    assert first.workflow_nodes == WORKFLOW_NODES
    assert first.state_schema_version == 3
    assert len(first.prompts) == 7
    assert len(first.llm_calls) == 8
    assert all(
        call.max_output_tokens == max_output_tokens_for(call.call_id) for call in first.llm_calls
    )
    assert len(first.retrievers) == 6
    assert first.report.template_version == "evidence-first-v4"
    assert first.scoring_policy_version == "source-score-v6"
    assert {
        retriever.retriever_id: retriever.version
        for retriever in first.retrievers
    }["chroma"] == "v2"
    assert all(
        retriever.version == "v1"
        for retriever in first.retrievers
        if retriever.retriever_id != "chroma"
    )
    assert first.security_policy_version == "outbound-url-v3"
    assert first.citation_policy_version == "deterministic-citation-v1"
    assert first.hitl_policy_version == "evidence-insufficient-v1"


def test_historical_chroma_v1_is_readable_but_cannot_resume():
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    historical = current.model_copy(update={
        "retrievers": tuple(
            retriever.model_copy(update={"version": "v1"})
            if retriever.retriever_id == "chroma" else retriever
            for retriever in current.retrievers
        )
    })
    historical = historical.model_copy(update={
        "manifest_id": _expected_manifest_id(historical)
    })

    restored = RunManifest.model_validate_json(historical.model_dump_json())
    assert next(
        item.version for item in restored.retrievers
        if item.retriever_id == "chroma"
    ) == "v1"
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_core_asset_registry_locks_the_versioned_core_asset_inventory():
    registry = build_core_asset_registry()
    expected_prompt_ids = (
        "query_analyzer.decomposition_system",
        "query_adapter.adapt_system",
        "conflict_detector.contradiction_scan_system",
        "conflict_detector.arbitration_system",
        "conflict_detector.evidence_gather",
        "conclusion_synthesizer.synthesis_prompt",
        "self_reviewer.review_system",
    )
    expected_nodes = (
        "query_analyzer",
        "query_adapter",
        "multi_retriever",
        "source_evaluator",
        "conflict_detector",
        "evidence_chain",
        "conclusion_synthesizer",
        "citation_validator",
        "evidence_decision_gate",
        "report_generator",
        "self_reviewer",
    )

    assert registry.registry_schema_version == 1
    assert registry.manifest_schema_version == 1
    assert registry.workflow_version == "research-v3"
    assert registry.state_schema_version == 3
    assert registry.workflow_nodes == expected_nodes == WORKFLOW_NODES
    assert registry.citation_policy_version == "deterministic-citation-v1"
    assert registry.hitl_policy_version == "evidence-insufficient-v1"
    assert tuple(prompt.prompt_id for prompt in registry.prompts) == expected_prompt_ids
    expected_versions = {"conclusion_synthesizer.synthesis_prompt": "v5",
                         "conflict_detector.contradiction_scan_system": "v2",
                         "conflict_detector.arbitration_system": "v2"}
    assert {prompt.prompt_id: prompt.version for prompt in registry.prompts} == {
        prompt_id: expected_versions.get(prompt_id, "v1") for prompt_id in expected_prompt_ids}
    assert all(re.fullmatch(r"[0-9a-f]{64}", prompt.sha256) for prompt in registry.prompts)
    assert {
        template.report_format: template.template_version
        for template in registry.report_templates
    } == {
        "what_why_how": "what-why-how-v6",
        "evidence_first": "evidence-first-v4",
        "comparison_matrix": "comparison-matrix-v4",
    } == REPORT_TEMPLATE_VERSIONS
    assert re.fullmatch(r"[0-9a-f]{64}", registry.registry_id)


def test_core_asset_registry_hash_is_stable_and_covers_its_content():
    registry = build_core_asset_registry()
    again = build_core_asset_registry()
    changed = registry.model_copy(update={
        "workflow_nodes": (*registry.workflow_nodes, "new_core_node"),
    })

    assert registry.registry_id == again.registry_id
    assert registry.registry_id == _expected_core_asset_registry_id(registry)
    assert _expected_core_asset_registry_id(changed) != registry.registry_id


def test_core_asset_registry_contains_prompt_hashes_but_no_prompt_text():
    registry = build_core_asset_registry()
    serialized = json.dumps(registry.model_dump(mode="json"), ensure_ascii=False)
    prompt_texts = (
        DECOMPOSITION_SYSTEM,
        ADAPT_SYSTEM,
        CONTRADICTION_SCAN_SYSTEM,
        ARBITRATION_SYSTEM,
        EVIDENCE_GATHER_SYSTEM + "\n" + EVIDENCE_GATHER_USER_TEMPLATE,
        cs_mod.SYNTHESIS_PROMPT,
        REVIEW_SYSTEM,
    )

    assert all(prompt_text not in serialized for prompt_text in prompt_texts)
    assert "api_key" not in serialized.lower()
    assert "endpoint" not in serialized.lower()
    assert set(type(registry).model_fields) == {
        "registry_schema_version",
        "registry_id",
        "manifest_schema_version",
        "workflow_version",
        "state_schema_version",
        "workflow_nodes",
        "citation_policy_version",
        "hitl_policy_version",
        "prompts",
        "report_templates",
    }


@pytest.mark.parametrize(
    ("changed_asset", "report_format", "previous_template"),
    [
        ("synthesis", "what_why_how", None),
        ("synthesis_v4", "what_why_how", None),
        ("template", "what_why_how", "what-why-how-v3"),
        ("template", "evidence_first", "evidence-first-v1"),
        ("template", "comparison_matrix", "comparison-matrix-v1"),
        ("template", "what_why_how", "what-why-how-v4"),
        ("template", "evidence_first", "evidence-first-v2"),
        ("template", "comparison_matrix", "comparison-matrix-v2"),
        ("template", "what_why_how", "what-why-how-v5"),
        ("template", "evidence_first", "evidence-first-v3"),
        ("template", "comparison_matrix", "comparison-matrix-v3"),
    ],
)
def test_pre_constraint_aware_manifest_is_readable_but_cannot_resume(
    report_format, previous_template, changed_asset,
):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    task = {"query": "A vs B", "report_format": report_format}
    current = build_run_manifest(task)
    if changed_asset in ("synthesis", "synthesis_v4"):
        previous_version = "v4" if changed_asset == "synthesis_v4" else "v3"
        previous = current.model_copy(update={
            "prompts": tuple(
                prompt.model_copy(update={"version": previous_version, "sha256": "3" * 64})
                if prompt.prompt_id == "conclusion_synthesizer.synthesis_prompt"
                else prompt
                for prompt in current.prompts
            ),
        })
    else:
        previous = current.model_copy(update={
            "report": current.report.model_copy(update={
                "template_version": previous_template,
            }),
        })
    previous = previous.model_copy(update={"manifest_id": _expected_manifest_id(previous)})
    restored = RunManifest.model_validate_json(previous.model_dump_json())

    assert restored.manifest_id == _expected_manifest_id(restored)
    assert restored.workflow_version == "research-v3"
    assert restored.state_schema_version == 3
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_pre_citation_manifest_identity_is_valid_but_runtime_incompatible():
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    old = current.model_copy(update={
        "workflow_version": "research-v1",
        "workflow_nodes": tuple(
            node for node in current.workflow_nodes
            if node not in {"citation_validator", "evidence_decision_gate"}
        ),
        "state_schema_version": 1,
        "citation_policy_version": None,
        "hitl_policy_version": None,
    })
    from deepchoice.contracts.manifest import _expected_manifest_id

    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    assert old.manifest_id == _expected_manifest_id(old)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(old, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_pre_hitl_v2_manifest_identity_is_valid_but_runtime_incompatible():
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    old = current.model_copy(update={
        "workflow_version": "research-v2",
        "workflow_nodes": tuple(
            node for node in current.workflow_nodes if node != "evidence_decision_gate"
        ),
        "state_schema_version": 2,
        "hitl_policy_version": None,
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


def test_manifest_freezes_trusted_proxy_identity_hash_without_endpoint_text(monkeypatch):
    endpoint = "http://127.0.0.1:7897"
    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", endpoint)

    manifest = build_run_manifest({"query": "A vs B"})
    serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False)

    assert manifest.security_policy_version == "outbound-url-v3"
    assert re.fullmatch(r"[0-9a-f]{64}", manifest.safe_fetch_proxy_sha256 or "")
    assert endpoint not in serialized
    assert "127.0.0.1" not in serialized

    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://127.0.0.1:7898")
    changed = build_run_manifest({"query": "A vs B"})
    assert changed.safe_fetch_proxy_sha256 != manifest.safe_fetch_proxy_sha256
    assert changed.manifest_id != manifest.manifest_id


def test_historical_v1_json_without_proxy_hash_remains_readable_but_cannot_resume(monkeypatch):
    from deepchoice.contracts.manifest import _expected_manifest_id

    monkeypatch.delenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", raising=False)
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    payload = current.model_dump(mode="json")
    payload["security_policy_version"] = "outbound-url-v1"
    payload.pop("safe_fetch_proxy_sha256", None)
    payload.pop("manifest_id", None)
    payload.pop("created_at", None)
    old_id = __import__("hashlib").sha256(
        __import__("json").dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    old_json = dict(payload, manifest_id=old_id, created_at=current.created_at.isoformat())

    restored = type(current).model_validate_json(__import__("json").dumps(old_json))
    assert restored.safe_fetch_proxy_sha256 is None
    assert restored.manifest_id == old_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_historical_v2_json_remains_readable_but_cannot_resume(monkeypatch):
    from deepchoice.contracts.manifest import _expected_manifest_id

    monkeypatch.delenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", raising=False)
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    payload = current.model_dump(mode="json")
    payload["security_policy_version"] = "outbound-url-v2"
    payload.pop("manifest_id", None)
    payload.pop("created_at", None)
    old_id = __import__("hashlib").sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    old_json = dict(payload, manifest_id=old_id, created_at=current.created_at.isoformat())

    restored = type(current).model_validate_json(json.dumps(old_json))
    assert restored.security_policy_version == "outbound-url-v2"
    assert restored.safe_fetch_proxy_sha256 is None
    assert restored.manifest_id == old_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_v3_manifest_proxy_identity_changes_are_incompatible_and_canonical_equivalents_match(monkeypatch):
    task = {"query": "A vs B"}
    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://127.0.0.1:7897")
    manifest = build_run_manifest(task)

    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://127.0.0.1:7898")
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(manifest, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"

    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "")
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(manifest, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"

    monkeypatch.setenv(
        "SAFE_FETCH_TRUSTED_LOCAL_PROXY",
        "http://[0:0:0:0:0:0:0:1]:7897",
    )
    equivalent = build_run_manifest(task)
    monkeypatch.setenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", "http://[::1]:7897")
    assert equivalent.safe_fetch_proxy_sha256 == build_run_manifest(task).safe_fetch_proxy_sha256
    ensure_run_manifest_compatible(equivalent, task)


def test_manifest_model_parameters_are_deeply_immutable():
    manifest = build_run_manifest({"query": "A vs B"})
    deepseek = next(model for model in manifest.models if model.tier == "deepseek-flash")

    assert deepseek.extra_body_json == '{"thinking":{"type":"disabled"}}'
    assert isinstance(deepseek.extra_body_json, str)


def test_manifest_freezes_dynamic_synthesis_parameters(monkeypatch):
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "1")
    manifest = build_run_manifest({"query": "A vs B"})
    synthesis = next(
        call for call in manifest.llm_calls if call.call_id == "conclusion_synthesizer"
    )

    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")

    assert synthesis.tier == "deepseek-flash"
    assert synthesis.timeout_s == 900.0
    assert synthesis.seed == 0
    assert synthesis.extra_body_json == '{"thinking":{"type":"enabled"}}'


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
    synthesis["tier"] = "qwen-flash"
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

    assert captured["model"] == "deepseek-flash"
    assert captured["response_format"] == "json"
    assert captured["timeout"] == 900.0
    assert captured["seed"] == 0
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}


def test_new_manifest_has_only_deepseek_and_rejects_identity_valid_qwen_history():
    from deepchoice.contracts.manifest import _expected_manifest_id

    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    assert {model.tier for model in current.models} == {"deepseek-flash"}
    assert {call.tier for call in current.llm_calls} == {"deepseek-flash"}
    deepseek = current.models[0].model_copy(update={"extra_body_json": None})
    old_qwen = deepseek.model_copy(update={
        "tier": "qwen-flash", "provider": "dashscope", "model": "qwen3.8-flash",
        "extra_body_json": '{"enable_thinking":false}',
    })
    old_calls = tuple(
        call.model_copy(update={
            "tier": "qwen-flash",
            "extra_body_json": '{"enable_thinking":false}' if call.call_id == "conclusion_synthesizer" else None,
        }) if call.call_id in {"conclusion_synthesizer", "conflict_rearbitration"} else call
        for call in current.llm_calls
    )
    historical = current.model_copy(update={"models": (deepseek, old_qwen), "llm_calls": old_calls})
    historical = historical.model_copy(update={"manifest_id": _expected_manifest_id(historical)})
    restored = type(current).model_validate_json(historical.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_old_4096_scan_manifest_remains_readable_but_cannot_resume():
    from deepchoice.contracts.manifest import _expected_manifest_id
    task = {"query": "fixture"}
    current = build_run_manifest(task)
    calls = tuple(call.model_copy(update={"max_output_tokens": 4096})
                  if call.call_id == "conflict_scan" else call for call in current.llm_calls)
    historical = current.model_copy(update={"llm_calls": calls})
    historical = historical.model_copy(update={"manifest_id": _expected_manifest_id(historical)})
    restored = type(current).model_validate_json(historical.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


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
    assert call.tool_timeout_s == 630.0
    assert call.tools_sha256


def test_pre_throttle_tool_timeout_manifest_remains_readable_but_cannot_resume():
    from deepchoice.contracts.manifest import _expected_manifest_id

    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    calls = tuple(call.model_copy(update={"tool_timeout_s": 20.0})
                  if call.call_id == "conflict_evidence_gather" else call
                  for call in current.llm_calls)
    old = current.model_copy(update={"llm_calls": calls})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    assert type(current).model_validate_json(old.model_dump_json()).manifest_id == old.manifest_id
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(old, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


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
