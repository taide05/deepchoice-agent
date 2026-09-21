"""Pure helpers for the constraint-aware recommendation contract.

The helpers in this module intentionally do not import agents, state, or
renderers. Durable limited-report paths can therefore use the same safety
operation without creating an orchestration import cycle.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


DECISION_BASIS_VERSION = "constraint-aware-v1"
MAX_REQUIREMENT_ASSESSMENTS = 40
MAX_DECISION_BRANCHES = 20
MAX_ACTION_PLAN = 20

_ASSESSMENT_STATUSES = {"satisfied", "contradicted", "unknown"}
_REQUIREMENT_ID = re.compile(r"^(?:C|A|Q)\d+$")


def _clean_text(value: Any, *, limit: int = 2000) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    return " ".join(value.split())[:limit].strip()


def _clean_evidence_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            continue
        if item not in result:
            result.append(item)
    return result


def normalize_requirement_assessments(value: Any) -> list[dict[str, Any]]:
    """Normalize already-bounded model output without inventing support."""
    if not isinstance(value, list) or len(value) > MAX_REQUIREMENT_ASSESSMENTS:
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        identifier = _clean_text(item.get("id"), limit=20).upper()
        if not _REQUIREMENT_ID.fullmatch(identifier) or identifier in seen:
            continue
        requirement = _clean_text(item.get("requirement"), limit=500)
        status = _clean_text(item.get("status"), limit=20).lower()
        explanation = _clean_text(item.get("explanation"), limit=2000)
        evidence_ids = _clean_evidence_ids(item.get("evidence_ids"))
        if status not in _ASSESSMENT_STATUSES:
            status = "unknown"
        if status != "unknown" and (not explanation or not evidence_ids):
            status = "unknown"
            evidence_ids = []
        decision_critical = not (
            identifier.startswith("Q") and item.get("decision_critical") is False
        )
        normalized.append({
            "id": identifier,
            "requirement": requirement,
            "status": status,
            "decision_critical": decision_critical,
            "explanation": explanation,
            "evidence_ids": evidence_ids,
        })
        seen.add(identifier)
    return normalized


def normalize_decision_branches(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_DECISION_BRANCHES:
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        option = _clean_text(item.get("option"), limit=300)
        condition = _clean_text(item.get("condition"), limit=2000)
        if option and condition:
            result.append({"option": option, "condition": condition})
    return result


def normalize_action_plan(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_ACTION_PLAN:
        return []
    result: list[dict[str, str]] = []
    fields = ("step", "verification", "change_trigger", "rollback")
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {field: _clean_text(item.get(field), limit=2000) for field in fields}
        if all(normalized.values()):
            result.append(normalized)
    return result


def normalize_unknowns(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:MAX_REQUIREMENT_ASSESSMENTS]:
        text = _clean_text(item, limit=1000)
        if text and text not in result:
            result.append(text)
    return result


def _is_zh(query: Any) -> bool:
    return isinstance(query, str) and bool(re.search(r"[\u3400-\u9fff]", query))


def _restricted_message(query: Any, reason: str | None = None) -> str:
    clean_reason = _clean_text(reason, limit=500)
    if _is_zh(query):
        base = "现有证据不足以支持单一结论；请依据条件分支验证关键未知项后再决定。"
        return f"{base} 限制原因：{clean_reason}" if clean_reason else base
    base = (
        "The available evidence does not support one unconditional choice; "
        "validate the critical unknowns and use the conditional branches before deciding."
    )
    return f"{base} Restriction reason: {clean_reason}" if clean_reason else base


def abstain_recommendation(
    recommendation: Any,
    query: Any,
    reason: str | None = None,
) -> dict[str, Any]:
    """Return a safe copy that makes no unconditional winner or rank claim."""
    result = deepcopy(recommendation) if isinstance(recommendation, dict) else {}
    result["decision_basis_version"] = DECISION_BASIS_VERSION
    result["winner"] = "context_dependent"
    result["winner_rationale"] = ""
    result["recommendation"] = _restricted_message(query, reason)
    result["ranked_options"] = []
    result["scene_fit_note"] = ""
    result["trade_offs"] = []
    result["evidence_summary"] = ""
    result["confidence"] = "low"
    result["confidence_rationale"] = (
        "关键约束仍待验证，当前置信度受限。"
        if _is_zh(query)
        else "Critical requirements remain unverified, so confidence is limited."
    )
    result["decision_branches"] = normalize_decision_branches(
        result.get("decision_branches")
    )
    result["action_plan"] = normalize_action_plan(result.get("action_plan"))
    result["unresolved_questions"] = normalize_unknowns(
        result.get("unresolved_questions")
    )
    assessments = normalize_requirement_assessments(
        result.get("requirement_assessments")
    )
    for item in assessments:
        if item["decision_critical"] and item["status"] != "satisfied":
            unknown = item["requirement"] or item["id"]
            if unknown not in result["unresolved_questions"]:
                result["unresolved_questions"].append(unknown)
    result["requirement_assessments"] = assessments
    return result


def restrict_recommendation(recommendation: Any, query: Any) -> dict[str, Any]:
    """Limit a report even when budget exhaustion preceded citation checks."""
    result = abstain_recommendation(recommendation, query)
    note = (
        "未知：研究提前结束，此项判断需要独立验证。"
        if _is_zh(query)
        else "Unknown: research ended before a complete assessment; verify this requirement independently."
    )
    for item in result["requirement_assessments"]:
        item.update(status="unknown", explanation=note, evidence_ids=[])
    return abstain_recommendation(result, query)
