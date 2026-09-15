import hashlib
import json
import os
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from ..agents.conclusion_synthesizer import SYNTHESIS_CALL_TIMEOUT_S, SYNTHESIS_PROMPT
from ..agents.conflict_detector import (
    ARBITRATION_SYSTEM,
    CONTRADICTION_SCAN_SYSTEM,
    EVIDENCE_GATHER_CALL_TIMEOUT_S,
    EVIDENCE_GATHER_MAX_ITERATIONS,
    EVIDENCE_GATHER_SYSTEM,
    EVIDENCE_GATHER_TOOL_TIMEOUT_S,
    EVIDENCE_GATHER_USER_TEMPLATE,
    SEARCH_TOOLS,
)
from .errors import DeepChoiceError, ErrorCategory
from ..agents.query_adapter import ADAPT_SYSTEM
from ..agents.query_analyzer import DECOMPOSITION_SYSTEM
from ..agents.self_reviewer import REVIEW_SYSTEM
from ..utils.llm import MAX_OUTPUT_TOKENS, TIERS


WORKFLOW_NODES = (
    "query_analyzer",
    "query_adapter",
    "multi_retriever",
    "source_evaluator",
    "conflict_detector",
    "evidence_chain",
    "conclusion_synthesizer",
    "report_generator",
    "self_reviewer",
)
RETRIEVER_IDS = ("tavily", "chroma", "github", "arxiv", "community", "official")
REPORT_TEMPLATE_VERSIONS = {
    "what_why_how": "what-why-how-v1",
    "evidence_first": "evidence-first-v1",
    "comparison_matrix": "comparison-matrix-v1",
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
    version: Literal["v1"] = "v1"
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


class RetrieverSnapshot(FrozenModel):
    retriever_id: str
    version: Literal["v1"] = "v1"


class ReportTemplateSnapshot(FrozenModel):
    report_format: Literal["what_why_how", "evidence_first", "comparison_matrix"]
    template_version: str


class RunManifest(FrozenModel):
    manifest_schema_version: Literal[1] = 1
    manifest_id: str
    created_at: datetime
    app_version: str
    workflow_version: Literal["research-v1"] = "research-v1"
    workflow_nodes: tuple[str, ...] = WORKFLOW_NODES
    state_schema_version: Literal[1] = 1
    models: tuple[ModelConfigSnapshot, ...]
    prompts: tuple[PromptSnapshot, ...]
    llm_calls: tuple[LLMCallSnapshot, ...]
    retrievers: tuple[RetrieverSnapshot, ...]
    scoring_policy_version: Literal["source-score-v1"] = "source-score-v1"
    security_policy_version: Literal["outbound-url-v1"] = "outbound-url-v1"
    gather_evidence: bool
    report: ReportTemplateSnapshot


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    prompts = (
        ("query_analyzer.decomposition_system", DECOMPOSITION_SYSTEM),
        ("query_adapter.adapt_system", ADAPT_SYSTEM),
        ("conflict_detector.contradiction_scan_system", CONTRADICTION_SCAN_SYSTEM),
        ("conflict_detector.arbitration_system", ARBITRATION_SYSTEM),
        (
            "conflict_detector.evidence_gather",
            EVIDENCE_GATHER_SYSTEM + "\n" + EVIDENCE_GATHER_USER_TEMPLATE,
        ),
        ("conclusion_synthesizer.synthesis_prompt", SYNTHESIS_PROMPT),
        ("self_reviewer.review_system", REVIEW_SYSTEM),
    )
    report_format = task.get("report_format", "what_why_how")
    if report_format not in REPORT_TEMPLATE_VERSIONS:
        report_format = "what_why_how"
    synthesis_extra_body = {
        "enable_thinking": os.environ.get("DEEPCHOICE_SYNTH_THINKING", "0") == "1",
    }

    return {
        "manifest_schema_version": 1,
        "app_version": APP_VERSION,
        "workflow_version": "research-v1",
        "workflow_nodes": WORKFLOW_NODES,
        "state_schema_version": 1,
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
            PromptSnapshot(prompt_id=prompt_id, sha256=_sha256(text))
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
                call_id="conflict_scan",
                tier="deepseek-flash",
                prompt_id="conflict_detector.contradiction_scan_system",
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="conflict_arbitration",
                tier="deepseek-flash",
                prompt_id="conflict_detector.arbitration_system",
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="conflict_evidence_gather",
                tier="deepseek-flash",
                prompt_id="conflict_detector.evidence_gather",
                response_format=None,
                timeout_s=EVIDENCE_GATHER_CALL_TIMEOUT_S,
                tools_sha256=_sha256(_canonical_json(SEARCH_TOOLS)),
                max_iterations=EVIDENCE_GATHER_MAX_ITERATIONS,
                tool_timeout_s=EVIDENCE_GATHER_TOOL_TIMEOUT_S,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="conflict_rearbitration",
                tier="qwen-flash",
                prompt_id="conflict_detector.arbitration_system",
                timeout_s=300.0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            LLMCallSnapshot(
                call_id="conclusion_synthesizer",
                tier="qwen-flash",
                prompt_id="conclusion_synthesizer.synthesis_prompt",
                timeout_s=SYNTHESIS_CALL_TIMEOUT_S,
                seed=0,
                extra_body_json=_canonical_json(synthesis_extra_body),
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
            RetrieverSnapshot(retriever_id=retriever_id)
            for retriever_id in RETRIEVER_IDS
        ),
        "scoring_policy_version": "source-score-v1",
        "security_policy_version": "outbound-url-v1",
        "gather_evidence": task.get("gather_evidence", True),
        "report": ReportTemplateSnapshot(
            report_format=report_format,
            template_version=REPORT_TEMPLATE_VERSIONS[report_format],
        ),
    }


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
