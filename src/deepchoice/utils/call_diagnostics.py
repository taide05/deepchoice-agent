"""Content-free O1 call observations; shape checks are not semantic verification."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt


FAILURE_CATEGORIES = frozenset({
    "budget_exceeded", "budget_gate_failed", "rate_limited", "provider_timeout",
    "provider_error", "transport_error", "json_parse_error", "json_schema_error",
    "output_truncated", "lease_lost", "runtime_recovery", "cancelled", "unknown",
    "provider_unavailable", "knowledge_base_unavailable", "unsupported_tool",
    "retrieval_contract_error", "provider_admission_failed", "run_timeout",
})


class CallDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: Literal["node-shape-v1"] = "node-shape-v1"
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "function_call"] | None = None
    truncated: StrictBool | None = None
    json_status: Literal["strict", "repaired", "invalid", "non_object", "not_requested"] | None = None
    repair_attempts: StrictInt | None = None
    parse_ok: StrictBool | None = None
    schema_status: Literal["valid", "invalid", "not_configured", "not_applicable", "unknown"] = "unknown"


def strict_json(content: Any) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("non-finite JSON number")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite JSON number")
        return result

    return json.loads(content, object_pairs_hook=pairs, parse_constant=invalid_constant,
                      parse_float=finite_float)


def _matches(value: Any, shape: Any) -> bool:
    if isinstance(shape, dict):
        return isinstance(value, dict) and all(
            key in value and _matches(value[key], spec) for key, spec in shape.items()
        )
    if isinstance(shape, list):
        return isinstance(value, list) and all(_matches(item, shape[0]) for item in value)
    if isinstance(shape, tuple):
        return isinstance(value, str) and value in shape
    return type(value) is shape


_CONFIDENCE = ("high", "medium", "low")
_ARBITRATION = {
    "resolution": ("A_correct", "B_correct", "both_partial", "insufficient_data"),
    "confidence": _CONFIDENCE, "reasoning": str, "key_factor": str,
}
_SHAPES = {
    "query_analyzer": {"sub_questions": [str], "constraints": [str]},
    "query_adapter": {"adapted": [{
        "sub_question_index": int, "sub_question": str, "tavily": str, "arxiv": str,
        "github": str, "chroma": str, "community": str, "official": str,
    }]},
    "conflict_scan": {
        "has_difference": bool,
        "type": ("winner_disagreement", "tradeoff_disagreement", "vendor_bias", "none"),
        "explanation": str,
    },
    "conflict_arbitration": _ARBITRATION,
    "conflict_rearbitration": _ARBITRATION,
    "self_reviewer": {
        "checks": [{"item": int, "passed": bool, "note": str}],
        "passed_count": int, "confidence": _CONFIDENCE,
        "knowledge_gaps": [str], "critical_gaps": [str],
    },
    "conclusion_synthesizer": {
        "winner": str, "winner_rationale": str, "recommendation": str,
        "decision_basis_version": ("constraint-aware-v1",),
        "requirement_assessments": [{
            "id": str, "requirement": str,
            "status": ("satisfied", "contradicted", "unknown"),
            "decision_critical": bool, "explanation": str, "evidence_ids": [int],
        }],
        "decision_branches": [{"option": str, "condition": str}],
        "action_plan": [{
            "step": str, "verification": str, "change_trigger": str, "rollback": str,
        }],
        "ranked_options": [{
            "name": str, "rank": int, "constraint_fit": _CONFIDENCE,
            "constraint_fit_reason": str, "rationale": str,
            "key_strength": str, "key_weakness": str,
        }],
        "trade_offs": [{"dimension": str, "finding": str, "impact": str}],
        "evidence_summary": str, "confidence": _CONFIDENCE,
        "confidence_rationale": str, "unresolved_questions": [str], "scene_fit_note": str,
    },
    "o1-json-probe": {"ok": bool},
    "check": {"ok": bool},
    "search_web": {"query": str},
    "search_scholarly": {"query": str},
    "search_kb": {"query": str},
}


def observe_output(choice: Any, *, json_requested: bool = False, content: Any = None,
                   parsed: Any = None, parse_ok: bool | None = None,
                   repair_attempts: int = 0, tag: str = "") -> dict:
    reason = getattr(choice, "finish_reason", None)
    if not isinstance(reason, str) or reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:
        reason = None
    diagnostic = CallDiagnostics(
        finish_reason=reason, truncated=None if reason is None else reason == "length",
        json_status="not_requested", schema_status="not_applicable",
    )
    if json_requested:
        try:
            strict = strict_json(content)
        except (TypeError, ValueError, RecursionError):
            strict = None
            status = "repaired" if parse_ok and repair_attempts else "invalid"
        else:
            status = "strict" if isinstance(strict, dict) else "non_object"
        diagnostic.json_status = status
        diagnostic.repair_attempts = repair_attempts
        diagnostic.parse_ok = parse_ok
        shape = _SHAPES.get(tag)
        diagnostic.schema_status = (
            "not_configured" if shape is None
            else "valid" if parse_ok and _matches(parsed, shape) else "invalid"
        )
        if shape is not None and tag.startswith("search_") and isinstance(parsed, dict):
            maximum = parsed.get("max_results", 3)
            if type(maximum) is not int or not 1 <= maximum <= 5 or not parsed.get("query"):
                diagnostic.schema_status = "invalid"
    return diagnostic.model_dump()


def output_failure(diagnostic: dict) -> str | None:
    if diagnostic.get("truncated") is True:
        return "output_truncated"
    if diagnostic.get("json_status") in {"invalid", "non_object"}:
        return "json_parse_error"
    if diagnostic.get("schema_status") == "invalid":
        return "json_schema_error"
    return None


def exception_category(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code in ("RUN_BUDGET_EXCEEDED", "BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE"):
        return "budget_exceeded"
    if code == "RUN_BUDGET_PERSISTENCE_FAILED":
        return "budget_gate_failed"
    if code in ("RUN_LEASE_LOST", "RUNTIME_INSTANCE_LEASE_LOST", "RUN_BUDGET_AUTHORITY_STALE"):
        return "lease_lost"
    return safe_error_category(type(exc).__name__, getattr(exc, "status_code", None))


def safe_error_category(error_type: str, status: Any = None) -> str:
    if (type(status) is int and status == 429) or error_type in {"ProviderRateLimitError", "RateLimitError"}:
        return "rate_limited"
    if error_type in {"TimeoutError", "ReadTimeout", "ConnectTimeout", "PoolTimeout", "APITimeoutError"}:
        return "provider_timeout"
    if error_type in {"APIConnectionError", "ConnectError", "NetworkError"}:
        return "transport_error"
    if error_type == "ProviderAdmissionError":
        return "provider_admission_failed"
    if error_type == "RetrievalContractError":
        return "retrieval_contract_error"
    return "provider_error"


def retrieval_failure(error: Any) -> str:
    # BaseRetriever emits class / optional HTTP status, never inspect raw payloads.
    if error == "RetrievalContractError: invalid retrieval contract":
        return "retrieval_contract_error"
    if not isinstance(error, str):
        return "unknown"
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)(?:\(\)|: HTTP ([0-9]{3}))?", error)
    if not match:
        return "unknown"
    return safe_error_category(match[1], int(match[2]) if match[2] else None)


def public_call_result(value: Any) -> dict:
    """Validate a bounded allowlist; arbitrary stored Trace summaries stay private."""
    if not isinstance(value, str) or len(value) > 16384:
        return {}
    try:
        summary = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return {}
    if not isinstance(summary, dict):
        return {}
    category = summary.get("failure_category")
    result = {"failure_category": category} if isinstance(category, str) and category in FAILURE_CATEGORIES else {}
    diagnostic = summary.get("diagnostics")
    if isinstance(diagnostic, dict):
        fields = {key: val for key, val in diagnostic.items() if key in CallDiagnostics.model_fields}
        try:
            valid = CallDiagnostics.model_validate(fields)
            if valid.repair_attempts is not None and not 0 <= valid.repair_attempts <= 2:
                return result
            result["diagnostics"] = valid.model_dump()
        except ValueError:
            pass
    return result


def run_failure(status: str, error_id: str | None) -> str | None:
    if error_id in {"RUN_BUDGET_EXCEEDED", "BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE"}:
        return "budget_exceeded"
    if error_id in {"RUN_BUDGET_PERSISTENCE_FAILED"}:
        return "budget_gate_failed"
    if error_id in {"RUN_LEASE_LOST", "RUNTIME_INSTANCE_LEASE_LOST", "RUN_BUDGET_AUTHORITY_STALE"}:
        return "lease_lost"
    if status == "interrupted":
        return "runtime_recovery"
    if status == "timed_out":
        return "run_timeout"
    if status == "cancelled":
        return "cancelled"
    return "unknown" if status == "failed" else None
