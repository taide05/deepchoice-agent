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


def _validation_only_plan(query: Any) -> list[dict[str, str]]:
    """Fixed review tasks, not a model-authored production runbook.

    Do not interpolate model steps or rollback text here: an uncertainty label
    cannot make an unestablished cutover or stale-snapshot restore safe.
    """
    if _is_zh(query):
        return [
            {
                "step": "只读观察现有系统，在隔离副本中逐项核验条件分支和未决需求。",
                "verification": "记录实际负载、失败现象与基线；由负责人定义观测窗口、可接受阈值和证据来源，不把未知值当作通过。",
                "change_trigger": "关键前提或阈值未明确时只继续取证；确认后仅进入隔离演练，不放行生产变更。",
                "rollback": "保留当前生产状态；验证失败时停止实验，不用实验副本或旧快照覆盖生产。",
            },
            {
                "step": "仅在可丢弃的隔离副本中制定并演练变更、失败和恢复流程。",
                "verification": "涉及状态或写入时，明确唯一权威源、一致性检查点、已确认新增写入的保全/回放方法，以及不可逆点和禁止回退条件；这些必须有适用依据及演练结果。",
                "change_trigger": "缺写入保全、放行/中止或回退边界即停止；全部核验后仅提交独立审查，本报告及演练通过均不授权生产双写、切流或覆盖恢复。",
                "rollback": "只丢弃隔离实验副本并保留诊断；生产回退可行性未成立时明确禁止回退，继续保留当前权威数据。",
            },
        ]
    return [
        {
            "step": "Observe the current system read-only and check each conditional choice and unresolved requirement in an isolated copy.",
            "verification": "Record actual workload, failures and a baseline; have the responsible owner define the observation window, acceptable thresholds and evidence. Unknown values are not passing results.",
            "change_trigger": "Collect evidence while critical premises or thresholds remain unresolved; confirmation permits only isolated rehearsal, not production changes.",
            "rollback": "Keep production unchanged; stop a failed experiment without overwriting production with an experimental copy or old snapshot.",
        },
        {
            "step": "Design and rehearse change, failure and recovery procedures only on a disposable isolated copy.",
            "verification": "For state or writes, establish one authoritative source, a consistency checkpoint, preservation/replay of newly acknowledged writes, irreversible points and conditions that prohibit rollback, with applicable evidence and rehearsal results.",
            "change_trigger": "Stop if write preservation, advancement/abort or rollback boundaries are missing. Submit complete evidence for independent review only; neither this report nor passing rehearsal authorizes production dual writes, cutover or overwrite recovery.",
            "rollback": "Discard only the isolated experimental copy and retain diagnostics. Explicitly prohibit rollback when production rollback feasibility is unestablished; retain current authoritative data.",
        },
    ]


def is_fixed_validation_only_plan(recommendation: Any, query: Any) -> bool:
    """Return whether a restricted plan is exactly the deterministic safe plan.

    The marker alone is not trusted: model output and historical state may carry
    arbitrary fields.  Citation verification may exempt only the byte-for-byte
    normalized plan produced by this module (or the deliberate empty plan).
    """
    if not isinstance(recommendation, dict):
        return False
    if recommendation.get("action_plan_mode") != "validation_only":
        return False
    plan = recommendation.get("action_plan")
    if plan == []:
        return True
    return plan == _validation_only_plan(query)


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
    # Abstention withdraws operational authority as well as winner/rank claims.
    # Keep decision analysis, but never preserve arbitrary imperative model text
    # as a production procedure merely by labelling it "proposed".
    has_plan = bool(normalize_action_plan(result.get("action_plan")))
    result["action_plan_mode"] = "validation_only"
    result["action_plan"] = _validation_only_plan(query) if has_plan else []
    if result["decision_branches"]:
        result["recommendation"] = (
            "当前给出条件性建议：按下方各方案的前提与行动计划验证后选择，不将其视为无条件胜者。"
            if _is_zh(query) else
            "Use the conditional choices below: validate each option's prerequisites "
            "with the action plan before adoption; none is an unconditional winner."
        )
        clean_reason = _clean_text(reason, limit=500)
        if clean_reason:
            label = "限制原因" if _is_zh(query) else "Restriction reason"
            result["recommendation"] += f" {label}: {clean_reason}"
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


def restrict_action_plan(recommendation: Any, query: Any) -> dict[str, Any]:
    """Replace an unverified model plan without withdrawing a verified choice."""
    result = deepcopy(recommendation) if isinstance(recommendation, dict) else {}
    has_plan = bool(result.get("action_plan"))
    result["action_plan_mode"] = "validation_only"
    result["action_plan"] = _validation_only_plan(query) if has_plan else []
    result["unresolved_questions"] = normalize_unknowns(
        result.get("unresolved_questions")
    )
    if has_plan:
        gap = (
            "行动计划的依据尚未通过核验；仅允许隔离验证，禁止生产变更。"
            if _is_zh(query) else
            "Action-plan evidence is unverified; only isolated validation is allowed, not production changes."
        )
        if gap not in result["unresolved_questions"]:
            result["unresolved_questions"].append(gap)
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
