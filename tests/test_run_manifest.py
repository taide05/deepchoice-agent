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
    assert first.workflow_version == "research-v5"
    assert first.workflow_nodes == WORKFLOW_NODES
    assert first.state_schema_version == 3
    assert len(first.prompts) == 6
    assert len(first.llm_calls) == 6
    assert all(
        call.max_output_tokens == max_output_tokens_for(call.call_id) for call in first.llm_calls
    )
    assert len(first.retrievers) == 6
    assert first.report.template_version == "evidence-first-v22"
    assert first.scoring_policy_version == "source-score-v17"
    assert {
        retriever.retriever_id: retriever.version
        for retriever in first.retrievers
    }["chroma"] == "v8"
    assert all(
        retriever.version == ("v4" if retriever.retriever_id in {"community", "arxiv"} else "v2" if retriever.retriever_id in {"tavily", "github"} else "v1")
        for retriever in first.retrievers
        if retriever.retriever_id not in {"chroma", "official"}
    )
    assert next(r.version for r in first.retrievers if r.retriever_id == "official") == "v12"
    assert first.security_policy_version == "outbound-url-v5"
    assert first.citation_policy_version == "deterministic-citation-v23"
    assert first.hitl_policy_version == "evidence-insufficient-v3"


@pytest.mark.parametrize("old_version", ["v1", "v2", "v3", "v4", "v5", "v6", "v7"])
def test_historical_chroma_is_readable_but_cannot_resume(old_version):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    historical = current.model_copy(update={
        "retrievers": tuple(
            retriever.model_copy(update={"version": old_version})
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
    ) == old_version
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


@pytest.mark.parametrize("source,old_version", [
    ("official", f"v{version}") for version in range(1, 11)
] + [("community", "v3"), ("arxiv", "v3")])
def test_historical_retriever_manifest_cannot_resume(source, old_version):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    historical = current.model_copy(update={"retrievers": tuple(
        row.model_copy(update={"version": old_version}) if row.retriever_id == source else row
        for row in current.retrievers
    )})
    historical = historical.model_copy(update={"manifest_id": _expected_manifest_id(historical)})
    restored = RunManifest.model_validate_json(historical.model_dump_json())
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"
    assert restored.manifest_id != current.manifest_id

    from deepchoice.cache import build_retrieval_cache_key
    from deepchoice.retrievers.contracts import RetrievalRequest
    request = RetrievalRequest(query="Alpha versus Beta")
    assert restored.manifest_id == _expected_manifest_id(restored)
    assert build_retrieval_cache_key(source=source, request=request, manifest_id=restored.manifest_id) != build_retrieval_cache_key(source=source, request=request, manifest_id=current.manifest_id)


@pytest.mark.parametrize("policy_version", [
    "deterministic-citation-v1", "deterministic-citation-v2",
    "deterministic-citation-v3",
    "deterministic-citation-v4", "deterministic-citation-v5",
    "deterministic-citation-v6",
    "deterministic-citation-v7", "deterministic-citation-v8",
    "deterministic-citation-v9", "deterministic-citation-v10", "deterministic-citation-v12",
    "deterministic-citation-v13", "deterministic-citation-v14",
    "deterministic-citation-v15", "deterministic-citation-v16", "deterministic-citation-v17", "deterministic-citation-v19", "deterministic-citation-v20",
])
def test_historical_citation_policy_is_readable_but_cannot_resume(policy_version):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    historical = current.model_copy(update={
        "citation_policy_version": policy_version
    })
    historical = historical.model_copy(update={
        "manifest_id": _expected_manifest_id(historical)
    })

    restored = RunManifest.model_validate_json(historical.model_dump_json())
    assert restored.citation_policy_version == policy_version
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


@pytest.mark.parametrize("previous_policy", ["source-score-v6", "source-score-v9", "source-score-v10", "source-score-v11", "source-score-v12", "source-score-v13"])
def test_previous_source_score_policy_remains_readable_but_incompatible(previous_policy):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    historical = current.model_copy(update={"scoring_policy_version": previous_policy})
    historical = historical.model_copy(update={
        "manifest_id": _expected_manifest_id(historical),
    })
    restored = RunManifest.model_validate_json(historical.model_dump_json())
    assert restored.scoring_policy_version == previous_policy
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_core_asset_registry_locks_the_versioned_core_asset_inventory():
    registry = build_core_asset_registry()
    expected_prompt_ids = (
        "query_analyzer.decomposition_system",
        "query_adapter.adapt_system",
        "source_evaluator.source_scope_selection",
        "conflict_detector.contradiction_scan_system",
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
        "source_selection",
        "citation_validator",
        "conclusion_synthesizer",
        "self_reviewer",
        "evidence_decision_gate",
        "report_generator",
    )

    assert registry.registry_schema_version == 1
    assert registry.manifest_schema_version == 1
    assert registry.workflow_version == "research-v5"
    assert registry.state_schema_version == 3
    assert registry.workflow_nodes == expected_nodes == WORKFLOW_NODES
    assert registry.citation_policy_version == "deterministic-citation-v23"
    assert registry.hitl_policy_version == "evidence-insufficient-v3"
    assert tuple(prompt.prompt_id for prompt in registry.prompts) == expected_prompt_ids
    expected_versions = {"self_reviewer.review_system": "v10", "conclusion_synthesizer.synthesis_prompt": "v39",
                         "query_analyzer.decomposition_system": "v3",
                         "query_adapter.adapt_system": "v6",
                         "source_evaluator.source_scope_selection": "v4",
                         "conflict_detector.contradiction_scan_system": "v4"}
    assert {prompt.prompt_id: prompt.version for prompt in registry.prompts} == {
        prompt_id: expected_versions.get(prompt_id, "v1") for prompt_id in expected_prompt_ids}
    assert all(re.fullmatch(r"[0-9a-f]{64}", prompt.sha256) for prompt in registry.prompts)
    assert {
        template.report_format: template.template_version
        for template in registry.report_templates
    } == {
        "what_why_how": "what-why-how-v23",
        "evidence_first": "evidence-first-v22",
        "comparison_matrix": "comparison-matrix-v21",
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
        ("synthesis_v5", "what_why_how", None),
        ("synthesis_v6", "what_why_how", None),
        ("synthesis_v7", "what_why_how", None),
        ("synthesis_v8", "what_why_how", None),
        ("synthesis_v9", "what_why_how", None),
        ("template", "what_why_how", "what-why-how-v21"),
        ("template", "evidence_first", "evidence-first-v20"),
        ("template", "comparison_matrix", "comparison-matrix-v19"),
        ("template", "what_why_how", "what-why-how-v20"),
        ("template", "evidence_first", "evidence-first-v19"),
        ("template", "comparison_matrix", "comparison-matrix-v18"),
        ("template", "what_why_how", "what-why-how-v7"),
        ("template", "evidence_first", "evidence-first-v6"),
        ("template", "comparison_matrix", "comparison-matrix-v5"),
        ("template", "what_why_how", "what-why-how-v6"),
        ("template", "evidence_first", "evidence-first-v5"),
        ("template", "comparison_matrix", "comparison-matrix-v4"),
        ("template", "what_why_how", "what-why-how-v3"),
        ("template", "evidence_first", "evidence-first-v1"),
        ("template", "comparison_matrix", "comparison-matrix-v1"),
        ("template", "what_why_how", "what-why-how-v4"),
        ("template", "evidence_first", "evidence-first-v2"),
        ("template", "comparison_matrix", "comparison-matrix-v2"),
        ("template", "what_why_how", "what-why-how-v5"),
        ("template", "evidence_first", "evidence-first-v3"),
        ("template", "evidence_first", "evidence-first-v4"),
        ("template", "comparison_matrix", "comparison-matrix-v3"),
    ],
)
def test_pre_constraint_aware_manifest_is_readable_but_cannot_resume(
    report_format, previous_template, changed_asset,
):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    task = {"query": "A vs B", "report_format": report_format}
    current = build_run_manifest(task)
    if changed_asset in ("synthesis", "synthesis_v4", "synthesis_v5", "synthesis_v6", "synthesis_v7", "synthesis_v8", "synthesis_v9"):
        previous_version = {
            "synthesis": "v3",
            "synthesis_v4": "v4",
            "synthesis_v5": "v5",
            "synthesis_v6": "v6",
            "synthesis_v7": "v7",
            "synthesis_v8": "v8",
            "synthesis_v9": "v9",
        }[changed_asset]
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
    assert restored.workflow_version == "research-v5"
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

    assert manifest.security_policy_version == "outbound-url-v5"
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


@pytest.mark.parametrize("policy", ("outbound-url-v2", "outbound-url-v3", "outbound-url-v4"))
def test_historical_security_policy_json_remains_readable_but_cannot_resume(monkeypatch, policy):
    from deepchoice.contracts.manifest import _expected_manifest_id

    monkeypatch.delenv("SAFE_FETCH_TRUSTED_LOCAL_PROXY", raising=False)
    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    payload = current.model_dump(mode="json")
    payload["security_policy_version"] = policy
    expected_proxy_hash = "a" * 64 if policy in {"outbound-url-v3", "outbound-url-v4"} else None
    payload["safe_fetch_proxy_sha256"] = expected_proxy_hash
    payload.pop("manifest_id", None)
    payload.pop("created_at", None)
    old_id = __import__("hashlib").sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    old_json = dict(payload, manifest_id=old_id, created_at=current.created_at.isoformat())

    restored = type(current).model_validate_json(json.dumps(old_json))
    assert restored.security_policy_version == policy
    assert restored.safe_fetch_proxy_sha256 == expected_proxy_hash
    assert restored.manifest_id == old_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_current_manifest_proxy_identity_changes_are_incompatible_and_canonical_equivalents_match(monkeypatch):
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
    assert synthesis.extra_body_json == '{"reasoning_effort":"high","thinking":{"type":"enabled"}}'


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_default", [False, True])
async def test_synthesizer_uses_frozen_call_parameters(monkeypatch, historical_default):
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "1")
    manifest = build_run_manifest({"query": "A vs B"})
    if historical_default:
        from deepchoice.contracts.manifest import _expected_manifest_id
        calls = tuple(call.model_copy(update={"extra_body_json": '{"thinking":{"type":"enabled"}}'})
                      if call.call_id == "conclusion_synthesizer" else call for call in manifest.llm_calls)
        manifest = manifest.model_copy(update={"llm_calls": calls})
        manifest = manifest.model_copy(update={"manifest_id": _expected_manifest_id(manifest)})
    monkeypatch.setenv("DEEPCHOICE_SYNTH_THINKING", "0")
    ensure_run_manifest_compatible(manifest, {"query": "A vs B"})
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
    await cs_mod.ConclusionSynthesizerAgent(run_manifest=manifest).select_sources(
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
    assert captured["extra_body"] == ({"thinking": {"type": "enabled"}} if historical_default else
                                      {"thinking": {"type": "enabled"}, "reasoning_effort": "high"})


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
    from deepchoice.agents.conflict_detector import (
        EVIDENCE_GATHER_CALL_TIMEOUT_S, EVIDENCE_GATHER_MAX_ITERATIONS,
        EVIDENCE_GATHER_TOOL_TIMEOUT_S,
    )
    from deepchoice.contracts.manifest import LLMCallSnapshot
    # Historical DTOs remain readable although these calls are no longer frozen
    # as default-path assets.
    call = LLMCallSnapshot(call_id="conflict_evidence_gather", tier="deepseek-flash",
        prompt_id="conflict_detector.evidence_gather", response_format=None,
        timeout_s=EVIDENCE_GATHER_CALL_TIMEOUT_S, max_iterations=EVIDENCE_GATHER_MAX_ITERATIONS,
        tool_timeout_s=EVIDENCE_GATHER_TOOL_TIMEOUT_S, tools_sha256="0" * 64,
        max_output_tokens=4096, sdk_max_retries=0)

    assert call.response_format is None
    assert call.timeout_s == 30.0
    assert call.max_iterations == 2
    assert call.tool_timeout_s == 630.0
    assert call.tools_sha256


def test_pre_throttle_tool_timeout_manifest_remains_readable_but_cannot_resume():
    from deepchoice.contracts.manifest import _expected_manifest_id

    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    from deepchoice.contracts.manifest import LLMCallSnapshot
    legacy_call = LLMCallSnapshot(call_id="conflict_evidence_gather", tier="deepseek-flash",
        prompt_id="conflict_detector.evidence_gather", tool_timeout_s=20.0)
    old = current.model_copy(update={"llm_calls": (*current.llm_calls, legacy_call),
                                     "conflict_policy_version": None})
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


@pytest.mark.parametrize("old_version", ["v14", "v15", "v16", "v17", "v18", "v19", "v28", "v30", "v31"])
def test_structure_correction_assets_are_frozen_and_old_synthesis_cannot_resume(monkeypatch, old_version):
    import hashlib
    from deepchoice.contracts import manifest as module
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    synthesis = next(row for row in current.prompts if row.prompt_id == "conclusion_synthesizer.synthesis_prompt")
    historical = current.model_copy(update={"prompts": tuple(
        row.model_copy(update={"version": old_version, "sha256": hashlib.sha256(cs_mod.SYNTHESIS_PROMPT.encode()).hexdigest()})
        if row == synthesis else row for row in current.prompts)})
    historical = historical.model_copy(update={"manifest_id": _expected_manifest_id(historical)})
    restored = RunManifest.model_validate_json(historical.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"
    for field in ("SYNTHESIS_CORRECTION_TEMPLATE", "SYNTHESIS_STRUCTURE_POLICY", "SOURCE_VIEW_SELECTION_POLICY", "QUESTION_BASIS_POLICY"):
        with monkeypatch.context() as patcher:
            patcher.setattr(module, field, getattr(module, field) + "changed")
            assert build_run_manifest({}).manifest_id != current.manifest_id


def test_v11_citation_manifest_remains_readable_but_cannot_resume_with_windows():
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    previous = current.model_copy(update={"citation_policy_version": "deterministic-citation-v11"})
    previous = previous.model_copy(update={"manifest_id": _expected_manifest_id(previous)})
    restored = RunManifest.model_validate_json(previous.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_post_render_review_workflow_is_readable_but_cannot_resume():
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id
    current = build_run_manifest({})
    old = current.model_copy(update={"workflow_version": "research-v3",
        "workflow_nodes": tuple(node for node in current.workflow_nodes if node != "self_reviewer") + ("self_reviewer",)})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    restored = RunManifest.model_validate_json(old.model_dump_json())
    assert restored.workflow_version == "research-v3"
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


@pytest.mark.parametrize("retired_asset,retired_version", [
    *[("conclusion_synthesizer.synthesis_prompt", version) for version in ("v24", "v25", "v26", "v27", "v32", "v33", "v34", "v35", "v36", "v37")],
    ("self_reviewer.review_system", "v8"),
    ("self_reviewer.review_system", "v9"),
    ("source_evaluator.source_scope_selection", "v2"),
])
def test_retired_manifest_identity_is_readable_but_cannot_resume(retired_asset, retired_version):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    task = {"query": "A vs B"}
    current = build_run_manifest(task)
    retired = current.model_copy(update={
        "prompts": tuple(
            prompt.model_copy(update={"version": retired_version})
            if prompt.prompt_id == retired_asset else prompt
            for prompt in current.prompts
        ),
    })
    retired = retired.model_copy(update={"manifest_id": _expected_manifest_id(retired)})
    restored = RunManifest.model_validate_json(retired.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    assert next(prompt.version for prompt in restored.prompts
                if prompt.prompt_id == retired_asset) == retired_version
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, task)
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_sdk_retry_policy_is_frozen_and_previous_identity_remains_readable():
    import hashlib
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    current = build_run_manifest({})
    assert all(call.sdk_max_retries == 0 for call in current.llm_calls)
    historical_json = current.model_dump(mode="json")
    for call in historical_json["llm_calls"]:
        call.pop("sdk_max_retries")
    identity = {key: value for key, value in historical_json.items()
                if key not in {"manifest_id", "created_at"}}
    historical_json["manifest_id"] = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    restored = RunManifest.model_validate(historical_json)
    assert all(call.sdk_max_retries is None for call in restored.llm_calls)
    assert _expected_manifest_id(restored) == historical_json["manifest_id"]
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


@pytest.mark.parametrize("component,version", [("query_adapter", "v2"), ("query_adapter", "v3"), ("query_adapter", "v4"),
    ("tavily", "v1"), ("github", "v1"), ("arxiv", "v1"), ("arxiv", "v2"), ("community", "v1"), ("community", "v2")])
def test_previous_query_allocation_identity_remains_readable_but_cannot_resume(component, version):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id
    current = build_run_manifest({})
    if component == "query_adapter":
        previous = current.model_copy(update={"prompts": tuple(
            p.model_copy(update={"version": version, "sha256": "1" * 64})
            if p.prompt_id == "query_adapter.adapt_system" else p for p in current.prompts)})
    else:
        previous = current.model_copy(update={"retrievers": tuple(
            r.model_copy(update={"version": version}) if r.retriever_id == component else r
            for r in current.retrievers)})
    previous = previous.model_copy(update={"manifest_id": _expected_manifest_id(previous)})
    restored = RunManifest.model_validate_json(previous.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_pre_scan_only_identity_is_readable_and_not_resumable():
    import hashlib
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id

    historical = build_run_manifest({}).model_dump(mode="json")
    historical.pop("conflict_policy_version")
    for prompt in historical["prompts"]:
        if prompt["prompt_id"] == "conflict_detector.contradiction_scan_system":
            prompt["version"] = "v2"
    for prompt_id, text in [
        ("conflict_detector.arbitration_system", ARBITRATION_SYSTEM),
        ("conflict_detector.evidence_gather", EVIDENCE_GATHER_SYSTEM + "\n" + EVIDENCE_GATHER_USER_TEMPLATE),
    ]:
        historical["prompts"].append({"prompt_id": prompt_id, "version": "v2" if "arbitration" in prompt_id else "v1",
                                      "sha256": hashlib.sha256(text.encode()).hexdigest()})
    from deepchoice.contracts.manifest import LLMCallSnapshot
    historical["llm_calls"].append(LLMCallSnapshot(call_id="conflict_arbitration",
        tier="deepseek-flash", prompt_id="conflict_detector.arbitration_system",
        max_output_tokens=4096, sdk_max_retries=0).model_dump(mode="json"))
    identity = {k: v for k, v in historical.items() if k not in {"manifest_id", "created_at"}}
    historical["manifest_id"] = hashlib.sha256(json.dumps(identity, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    restored = RunManifest.model_validate(historical)
    assert restored.conflict_policy_version is None
    assert _expected_manifest_id(restored) == historical["manifest_id"]
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


@pytest.mark.parametrize("old_policy", [None, "scan-only-v1"])
def test_historical_conflict_scope_policy_remains_readable_and_incompatible(old_policy):
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id
    current = build_run_manifest({})
    historical = current.model_copy(update={"conflict_policy_version": old_policy,
        "citation_policy_version": "deterministic-citation-v18",
        "prompts": tuple(prompt.model_copy(update={"version": "v3"})
            if prompt.prompt_id == "conflict_detector.contradiction_scan_system" else prompt
            for prompt in current.prompts)})
    historical = historical.model_copy(update={"manifest_id": _expected_manifest_id(historical)})
    restored = RunManifest.model_validate_json(historical.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    assert restored.conflict_policy_version == old_policy
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_historical_hitl_policy_remains_readable_but_requires_new_run():
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id
    current = build_run_manifest({})
    historical = current.model_copy(update={"hitl_policy_version": "evidence-insufficient-v1"})
    historical = historical.model_copy(update={"manifest_id": _expected_manifest_id(historical)})
    restored = RunManifest.model_validate_json(historical.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    assert restored.hitl_policy_version == "evidence-insufficient-v1"
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"


def test_manifest_imports_in_a_clean_interpreter():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "from deepchoice.contracts.manifest import RunManifest; assert RunManifest"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_preverified_judgment_workflow_keeps_old_v4_identity_readable_but_not_resumable():
    from deepchoice.contracts.manifest import RunManifest, _expected_manifest_id
    current = build_run_manifest({})
    nodes = list(current.workflow_nodes)
    nodes.remove("source_selection")
    a, b = nodes.index("citation_validator"), nodes.index("conclusion_synthesizer")
    nodes[a], nodes[b] = nodes[b], nodes[a]
    old = current.model_copy(update={"workflow_version": "research-v4", "workflow_nodes": tuple(nodes)})
    old = old.model_copy(update={"manifest_id": _expected_manifest_id(old)})
    restored = RunManifest.model_validate_json(old.model_dump_json())
    assert restored.manifest_id == _expected_manifest_id(restored)
    assert restored.workflow_version == "research-v4"
    with pytest.raises(DeepChoiceError) as caught:
        ensure_run_manifest_compatible(restored, {})
    assert caught.value.error_detail.code == "RUN_MANIFEST_INCOMPATIBLE"
