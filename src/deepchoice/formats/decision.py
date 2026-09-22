"""Shared rendering helpers for constraint-aware decision details."""

from __future__ import annotations

from typing import Any


def is_context_dependent(recommendation: Any) -> bool:
    return (
        isinstance(recommendation, dict)
        and str(recommendation.get("winner", "")).strip().lower()
        == "context_dependent"
    )


def no_single_winner(lang: str) -> str:
    return (
        "暂无唯一胜者，选择取决于你的约束条件"
        if lang == "zh"
        else "No single winner; the choice depends on your constraints"
    )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dict_items(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)][:limit]


def render_decision_details(recommendation: Any, lang: str) -> list[str]:
    """Render structured decision fields without exposing internal IDs."""

    if not isinstance(recommendation, dict):
        return []

    assessments = _dict_items(recommendation.get("requirement_assessments"), 40)
    branches = _dict_items(recommendation.get("decision_branches"), 20)
    action_plan = _dict_items(recommendation.get("action_plan"), 20)
    lines: list[str] = []

    if assessments:
        lines.extend(
            [
                "### 逐项需求判断" if lang == "zh" else "### Requirement Assessments",
                "",
            ]
        )
        status_labels = {
            "satisfied": "满足" if lang == "zh" else "Satisfied",
            "contradicted": "不满足" if lang == "zh" else "Contradicted",
            "unknown": "未知" if lang == "zh" else "Unknown",
        }
        for item in assessments:
            requirement = _text(item.get("requirement"))
            if not requirement:
                requirement = "未命名需求" if lang == "zh" else "Unnamed requirement"
            status = str(item.get("status", "unknown")).strip().lower()
            status_label = status_labels.get(status, status_labels["unknown"])
            explanation = _text(item.get("explanation"))
            critical = (
                "（决策关键）" if lang == "zh" else " (decision-critical)"
            ) if item.get("decision_critical") else ""
            suffix = f" — {explanation}" if explanation else ""
            lines.append(f"- **{requirement}**{critical}: **{status_label}**{suffix}")
            analysis = _text(item.get("provisional_explanation"))
            if status == "unknown" and analysis:
                label = (
                    "待独立核验的分析（不代表需求已满足）"
                    if lang == "zh" else
                    "Analysis awaiting independent verification (not a satisfied requirement)"
                )
                lines.append(f"  - **{label}:** {analysis}")
        lines.append("")

    if branches:
        lines.extend(
            ["### 条件分支" if lang == "zh" else "### Decision Branches", ""]
        )
        for item in branches:
            option = _text(item.get("option")) or ("当前方案" if lang == "zh" else "Current option")
            condition = _text(item.get("condition")) or ("条件待明确" if lang == "zh" else "Condition not specified")
            if lang == "zh":
                lines.append(f"- **{option}**：仅当（待验证条件）{condition}")
            else:
                lines.append(f"- **{option}**: Only if (condition to be verified): {condition}")
        lines.append("")

    if action_plan:
        lines.extend(
            [
                "### 行动计划（待验证计划）"
                if lang == "zh"
                else "### Action Plan (Proposed validation plan)",
                "",
            ]
        )
        for index, item in enumerate(action_plan, 1):
            step = _text(item.get("step")) or ("待定义步骤" if lang == "zh" else "Step not specified")
            verification = _text(item.get("verification")) or ("待定义" if lang == "zh" else "Not specified")
            trigger = _text(item.get("change_trigger")) or ("未定义" if lang == "zh" else "Not specified")
            rollback = _text(item.get("rollback")) or ("未定义" if lang == "zh" else "Not specified")
            if lang == "zh":
                lines.append(
                    f"{index}. **{step}**；验证：{verification}；"
                    f"变更触发：{trigger}；回退：{rollback}"
                )
            else:
                lines.append(
                    f"{index}. **{step}**; verification: {verification}; "
                    f"change trigger: {trigger}; rollback: {rollback}"
                )
        lines.append("")

    return lines
