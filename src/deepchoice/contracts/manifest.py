import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from ..utils.fact_selection import SOURCE_VIEW_SELECTION_POLICY
from ..utils.question_packet import QUESTION_BASIS_POLICY
from ..agents.conclusion_synthesizer import (
    SYNTHESIS_CALL_TIMEOUT_S, SYNTHESIS_CORRECTION_TEMPLATE, SYNTHESIS_PROMPT,
    FACT_SELECTION_PROMPT, QUESTION_JUDGMENT_PROMPT,
    SYNTHESIS_STRUCTURE_POLICY, SOURCE_PASSAGE_DISPLAY_POLICY,
)
from ..agents.conflict_detector import CONTRADICTION_SCAN_SYSTEM

from .errors import DeepChoiceError, ErrorCategory
from ..agents.query_adapter import ADAPT_SYSTEM
from ..agents.query_analyzer import DECOMPOSITION_SYSTEM
from ..agents.self_reviewer import REVIEW_SYSTEM
from ..agents.source_evaluator import SOURCE_SCOPE_SELECTION_PROMPT
from ..utils.llm import MAX_OUTPUT_TOKENS, SDK_MAX_RETRIES, TIERS, max_output_tokens_for, synthesis_extra_body


CURRENT_WORKFLOW_VERSION = "research-v4"

WORKFLOW_NODES = (
    "query_analyzer",
    "query_adapter",
    "multi_retriever",
    "source_evaluator",
    "conflict_detector",
    "evidence_chain",
    "conclusion_synthesizer",
    "citation_validator",
    "self_reviewer",
    "evidence_decision_gate",
    "report_generator",
)
RETRIEVER_IDS = ("tavily", "chroma", "github", "arxiv", "community", "official")
REPORT_TEMPLATE_VERSIONS = {
    "what_why_how": "what-why-how-v22",
    "evidence_first": "evidence-first-v21",
    "comparison_matrix": "comparison-matrix-v20",
}
PROMPT_VERSIONS = {
    "self_reviewer.review_system": "v9",
    "query_analyzer.decomposition_system": "v3",
    "query_adapter.adapt_system": "v5",
    "conclusion_synthesizer.synthesis_prompt": "v36",
    "source_evaluator.source_scope_selection": "v3",
    "conflict_detector.contradiction_scan_system": "v4",
}
try:
    APP_VERSION = version("deepchoice")
except PackageNotFoundError:  # pragma: no cover - editable/dev fallback
    APP_VERSION = "0.1.0+uninstalled"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelConfigSnapshot(FrozenModel):
    tier: str
    provider: str
    model: str
    temperature: Literal[0] = 0
    extra_body_json: str | None = None
    endpoint_sha256: str


class PromptSnapshot(FrozenModel):
    prompt_id: str
    version: Literal["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13", "v14", "v15", "v16", "v17", "v18", "v19", "v20", "v21", "v22", "v23", "v24", "v25", "v26", "v27", "v28", "v29", "v30", "v31", "v32", "v33", "v34", "v35", "v36"] = "v1"
    sha256: str


class LLMCallSnapshot(FrozenModel):
    call_id: str
    tier: str
    prompt_id: str
    response_format: Literal["json"] | None = "json"
    timeout_s: float = 120.0
    seed: int | None = None
    extra_body_json: str | None = None
    tools_sha256: str | None = None
    max_iterations: int | None = None
    tool_timeout_s: float | None = None
    # ``None`` is accepted only to deserialize pre-Phase-2-C manifests. New
    # manifests always freeze an explicit value and compatibility rejects old
    # snapshots before same-run resume.
    max_output_tokens: int | None = None
    # Absent in historical v1 identities; current calls disable implicit retries.
    sdk_max_retries: Literal[0] | None = None


class RetrieverSnapshot(FrozenModel):
    retriever_id: str
    version: Literal["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10"] = "v1"


class ReportTemplateSnapshot(FrozenModel):
    report_format: Literal["what_why_how", "evidence_first", "comparison_matrix"]
    template_version: str


class RunManifest(FrozenModel):
    manifest_schema_version: Literal[1] = 1
    manifest_id: str
    created_at: datetime
    app_version: str
    workflow_version: Literal["research-v1", "research-v2", "research-v3", "research-v4"] = "research-v4"
    workflow_nodes: tuple[str, ...] = WORKFLOW_NODES
    state_schema_version: Literal[1, 2, 3] = 3
    models: tuple[ModelConfigSnapshot, ...]
    prompts: tuple[PromptSnapshot, ...]
    llm_calls: tuple[LLMCallSnapshot, ...]
    retrievers: tuple[RetrieverSnapshot, ...]
    scoring_policy_version: Literal["source-score-v1", "source-score-v2", "source-score-v3", "source-score-v4", "source-score-v5", "source-score-v6", "source-score-v7", "source-score-v8", "source-score-v9", "source-score-v10", "source-score-v11", "source-score-v12", "source-score-v13", "source-score-v14", "source-score-v15"] = "source-score-v15"
    security_policy_version: Literal[
        "outbound-url-v1", "outbound-url-v2", "outbound-url-v3", "outbound-url-v4", "outbound-url-v5"
    ] = "outbound-url-v5"
    safe_fetch_proxy_sha256: str | None = None
    citation_policy_version: Literal[
        "deterministic-citation-v1", "deterministic-citation-v2",
        "deterministic-citation-v3", "deterministic-citation-v4",
        "deterministic-citation-v5", "deterministic-citation-v6",
        "deterministic-citation-v7",
        "deterministic-citation-v8",
        "deterministic-citation-v9",
        "deterministic-citation-v10", "deterministic-citation-v11",
        "deterministic-citation-v12", "deterministic-citation-v13", "deterministic-citation-v14",
        "deterministic-citation-v15", "deterministic-citation-v16",
        "deterministic-citation-v17", "deterministic-citation-v18", "deterministic-citation-v19", "deterministic-citation-v20",
    ] | None = None
    hitl_policy_version: Literal["evidence-insufficient-v1", "evidence-insufficient-v2"] | None = None
    # Missing in historical schema-v1 identities; current default is scan-only.
    conflict_policy_version: Literal["scan-only-v1", "scan-only-v2"] | None = None
    gather_evidence: bool
    report: ReportTemplateSnapshot


class CoreAssetRegistry(FrozenModel):
    """Small, deterministic index of the versioned assets in the core path."""

    registry_schema_version: Literal[1] = 1
    registry_id: str
    manifest_schema_version: Literal[1] = 1
    workflow_version: Literal["research-v4"] = "research-v4"
    state_schema_version: Literal[3] = 3
    workflow_nodes: tuple[str, ...]
    citation_policy_version: Literal["deterministic-citation-v20"]
    hitl_policy_version: Literal["evidence-insufficient-v2"]
    prompts: tuple[PromptSnapshot, ...]
    report_templates: tuple[ReportTemplateSnapshot, ...]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _expected_core_asset_registry_id(registry: CoreAssetRegistry) -> str:
    content = registry.model_dump(mode="json", exclude={"registry_id"})
    return _sha256(_canonical_json(content))


def build_core_asset_registry() -> CoreAssetRegistry:
    """Project the current manifest's core assets without copying prompt text."""

    manifest = build_run_manifest({})
    content = {
        "registry_schema_version": 1,
        "manifest_schema_version": manifest.manifest_schema_version,
        "workflow_version": manifest.workflow_version,
        "state_schema_version": manifest.state_schema_version,
        "workflow_nodes": manifest.workflow_nodes,
        "citation_policy_version": manifest.citation_policy_version,
        "hitl_policy_version": manifest.hitl_policy_version,
        "prompts": manifest.prompts,
        "report_templates": tuple(
            ReportTemplateSnapshot(
                report_format=report_format,
                template_version=template_version,
            )
            for report_format, template_version in REPORT_TEMPLATE_VERSIONS.items()
        ),
    }
    normalized = {
        key: value.model_dump(mode="json") if isinstance(value, BaseModel) else [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ] if isinstance(value, tuple) else value
        for key, value in content.items()
    }
    registry_id = _sha256(_canonical_json(normalized))
    return CoreAssetRegistry(registry_id=registry_id, **content)


def _provider_for_tier(tier: str) -> str:
    if tier.startswith("deepseek"):
        return "deepseek"
    if tier.startswith("qwen"):
        return "dashscope"
    return "openai-compatible"


def _endpoint_identity(value: str) -> str:
    """Return a credential-free endpoint identity suitable for hashing."""

    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return "invalid-endpoint"
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme.lower()}://{host}{port}{path}"
    except ValueError:
        return "invalid-endpoint"


def _manifest_content(task: dict) -> dict[str, Any]:
    from ..outbound.channels import OutboundConfig

    prompts = (
        ("query_analyzer.decomposition_system", DECOMPOSITION_SYSTEM),
        ("query_adapter.adapt_system", ADAPT_SYSTEM),
        ("source_evaluator.source_scope_selection", SOURCE_SCOPE_SELECTION_PROMPT),
        ("conflict_detector.contradiction_scan_system", CONTRADICTION_SCAN_SYSTEM),
        ("conclusion_synthesizer.synthesis_prompt",
         SYNTHESIS_PROMPT + "\n" + SYNTHESIS_STRUCTURE_POLICY + "\n" + SYNTHESIS_CORRECTION_TEMPLATE
         + "\n" + FACT_SELECTION_PROMPT + "\n" + QUESTION_JUDGMENT_PROMPT
         + "\n" + SOURCE_PASSAGE_DISPLAY_POLICY + "\n" + SOURCE_VIEW_SELECTION_POLICY
         + "\n" + QUESTION_BASIS_POLICY),
        ("self_reviewer.review_system", REVIEW_SYSTEM),
    )
    report_format = task.get("report_format", "what_why_how")
    if report_format not in REPORT_TEMPLATE_VERSIONS:
        report_format = "what_why_how"

    content = {
        "manifest_schema_version": 1,
        "app_version": APP_VERSION,
        "workflow_version": CURRENT_WORKFLOW_VERSION,
        "workflow_nodes": WORKFLOW_NODES,
        "state_schema_version": 3,
        "models": tuple(
            ModelConfigSnapshot(
                tier=tier,
                provider=_provider_for_tier(tier),
                model=config["model"],
                temperature=0,
                extra_body_json=(
                    _canonical_json(config["extra_body"])
                    if config.get("extra_body") is not None
                    else None
                ),
                endpoint_sha256=_sha256(_endpoint_identity(config.get("base", ""))),
            )
            for tier, config in sorted(TIERS.items())
        ),
        "prompts": tuple(
            PromptSnapshot(prompt_id=prompt_id, sha256=_sha256(text),
                           version=PROMPT_VERSIONS.get(prompt_id, "v1"))
            for prompt_id, text in prompts
        ),
        "llm_calls": (
            LLMCallSnapshot(
                call_id="query_analyzer",
                tier="deepseek-flash",
                prompt_id="query_analyzer.decomposition_system",
                seed=0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="query_adapter",
                tier="deepseek-flash",
                prompt_id="query_adapter.adapt_system",
                seed=0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="source_scope_selector",
                tier="deepseek-flash",
                prompt_id="source_evaluator.source_scope_selection",
                seed=0,
                max_output_tokens=max_output_tokens_for("source_scope_selector"),
            ),
            LLMCallSnapshot(
                call_id="conflict_scan",
                tier="deepseek-flash",
                prompt_id="conflict_detector.contradiction_scan_system",
                max_output_tokens=max_output_tokens_for("conflict_scan"),
            ),
            LLMCallSnapshot(
                call_id="conclusion_synthesizer",
                tier="deepseek-flash",
                prompt_id="conclusion_synthesizer.synthesis_prompt",
                timeout_s=SYNTHESIS_CALL_TIMEOUT_S,
                seed=0,
                extra_body_json=_canonical_json(synthesis_extra_body()),
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="self_reviewer",
                tier="deepseek-flash",
                prompt_id="self_reviewer.review_system",
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        ),
        "retrievers": tuple(
            RetrieverSnapshot(
                retriever_id=retriever_id,
                version="v8" if retriever_id == "chroma" else "v10" if retriever_id == "official"
                        else "v3" if retriever_id in {"community", "arxiv"}
                        else "v2" if retriever_id in {"tavily", "github"} else "v1",
            )
            for retriever_id in RETRIEVER_IDS
        ),
        "scoring_policy_version": "source-score-v15",
        "security_policy_version": "outbound-url-v5",
        "safe_fetch_proxy_sha256": OutboundConfig.from_env().safe_fetch_proxy_sha256,
        "citation_policy_version": "deterministic-citation-v20",
        "hitl_policy_version": "evidence-insufficient-v2",
        "conflict_policy_version": "scan-only-v2",
        "gather_evidence": task.get("gather_evidence", True),
        "report": ReportTemplateSnapshot(
            report_format=report_format,
            template_version=REPORT_TEMPLATE_VERSIONS[report_format],
        ),
    }
    content["llm_calls"] = tuple(
        call.model_copy(update={"sdk_max_retries": SDK_MAX_RETRIES})
        for call in content["llm_calls"]
    )
    return content


def build_run_manifest(task: dict) -> RunManifest:
    """Capture the effective run configuration without persisting credentials."""

    content = _manifest_content(task)
    canonical = _canonical_json(
        {
            key: value.model_dump(mode="json") if isinstance(value, BaseModel) else [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ] if isinstance(value, tuple) else value
            for key, value in content.items()
        },
    )
    return RunManifest(
        manifest_id=_sha256(canonical),
        created_at=datetime.now(UTC),
        **content,
    )


def _expected_manifest_id(manifest: RunManifest) -> str:
    content = manifest.model_dump(mode="json", exclude={"manifest_id", "created_at"})
    # Old v1 manifests predate this field; preserve their historical identity
    # so they fail as incompatible, rather than appearing corrupt.
    for call in content["llm_calls"]:
        if call.get("max_output_tokens") is None:
            call.pop("max_output_tokens", None)
        if call.get("sdk_max_retries") is None:
            call.pop("sdk_max_retries", None)
    if content.get("conflict_policy_version") is None:
        content.pop("conflict_policy_version", None)
    if content.get("citation_policy_version") is None:
        content.pop("citation_policy_version", None)
    if content.get("hitl_policy_version") is None:
        content.pop("hitl_policy_version", None)
    if content["security_policy_version"] == "outbound-url-v1" and content.get("safe_fetch_proxy_sha256") is None:
        content.pop("safe_fetch_proxy_sha256", None)
    return _sha256(_canonical_json(content))


def _compatibility_content(manifest: RunManifest) -> dict[str, Any]:
    content = manifest.model_dump(mode="json", exclude={"manifest_id", "created_at"})
    # This is a resolved per-run option and the synthesis node consumes it
    # directly from the manifest; an environment change must not alter it.
    for call in content["llm_calls"]:
        if call["call_id"] == "conclusion_synthesizer":
            call["extra_body_json"] = "<run-specific>"
    return content


def ensure_run_manifest_compatible(manifest: RunManifest, task: dict) -> None:
    """Fail closed when code/runtime assets no longer match a saved run."""

    if manifest.manifest_id != _expected_manifest_id(manifest):
        raise DeepChoiceError(
            "Run manifest identity does not match its content",
            category=ErrorCategory.COMPATIBILITY,
            code="RUN_MANIFEST_ID_MISMATCH",
            status_code=409,
            action="Start a new research run from a verified manifest.",
        )
    current = build_run_manifest(task)
    if _compatibility_content(manifest) != _compatibility_content(current):
        raise DeepChoiceError(
            "Run manifest is incompatible with the current runtime",
            category=ErrorCategory.COMPATIBILITY,
            code="RUN_MANIFEST_INCOMPATIBLE",
            status_code=409,
            action="Start a new research run with the current runtime versions.",
        )
