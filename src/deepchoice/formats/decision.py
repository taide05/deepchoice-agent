"""Shared rendering helpers for constraint-aware decision details."""

from __future__ import annotations

import re
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


def _code(value: str) -> str:
    """Keep untrusted saved-source text literal in the Markdown report."""
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{value}{fence}"


def _render_saved_excerpts(item: dict[str, Any], lang: str) -> list[str]:
    lines: list[str] = []
    for excerpt in _dict_items(item.get("saved_source_excerpts"), 2):
        title = _text(excerpt.get("title"))
        content = _text(excerpt.get("text"))
        if not title or not content or len(content) > 1200:
            continue
        label = (
            "保存的来源片段（空白已规范化；不证明原页完整或适用于本场景）"
            if lang == "zh" else
            "Saved source excerpt (whitespace normalized; not proof of full-page context or applicability)"
        )
        lines.append(f"  - {label}：{_code(title)} — {_code(content)}")
    return lines


def render_decision_details(recommendation: Any, lang: str) -> list[str]:
    """Render structured decision fields without exposing internal IDs."""

    if not isinstance(recommendation, dict):
        return []

    assessments = _dict_items(recommendation.get("requirement_assessments"), 40)
    branches = _dict_items(recommendation.get("decision_branches"), 20)
    action_plan = _dict_items(recommendation.get("action_plan"), 20)
    lines: list[str] = []

    if recommendation.get("decision_basis_version") == "constraint-aware-v1":
        # A fixed boundary, never a model-supplied readiness claim. Rendering a
        # historical snapshot must not upgrade an arbitrary readiness marker.
        lines.extend([
            "### 部署验收：未验证" if lang == "zh" else "### Deployment acceptance: unverified",
            "",
            (
                "选型依据与部署验收分开判断。本研究不执行真实部署或恢复演练；文档引用通过不表示演练通过，也不授权生产变更。用户明确要求的实际验收证据仍是关键条件。"
                if lang == "zh" else
                "Selection evidence and deployment acceptance are separate. This research does not execute deployment or recovery rehearsals; verified document citations neither prove a successful drill nor authorize production changes. Explicit user requirements for acceptance evidence remain decision-critical."
            ),
            "",
        ])

    if assessments:
        lines.extend(
            [
                "### 逐项需求判断" if lang == "zh" else "### Requirement Assessments",
                "",
                (
                    "决定性事实保留来源语言以便核对；词法支持不等于语义证明，也不证明实际部署已通过验证。"
                    if lang == "zh" else
                    "Decisive facts retain the source language for inspection; lexical support is not semantic proof or evidence of a successful deployment test."
                ),
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
            if status == "unknown":
                lines.extend(_render_saved_excerpts(item, lang))
        lines.append("")

    if branches:
        lines.extend(
            ["### 条件分支" if lang == "zh" else "### Decision Branches", ""]
        )
        for item in branches:
            option = _text(item.get("option")) or ("当前方案" if lang == "zh" else "Current option")
            condition = _text(item.get("condition")) or ("条件待明确" if lang == "zh" else "Condition not specified")
            if lang == "zh":
                lines.append(f"- **{option}**：适用条件（待核查，不能仅据此选型）：{condition}")
            else:
                lines.append(f"- **{option}**: Applicability condition (unverified; not a choice by itself): {condition}")
            lines.extend(_render_saved_excerpts(item, lang))
        lines.append("")

    if action_plan:
        validation_only = recommendation.get("action_plan_mode") == "validation_only"
        heading = (
            "### 行动计划（仅隔离验证；禁止生产变更）"
            if lang == "zh" else
            "### Action Plan (Isolated validation only; no production changes)"
        ) if validation_only else (
            "### 行动计划（待验证计划）" if lang == "zh"
            else "### Action Plan (Proposed validation plan)"
        )
        lines.extend(
            [
                heading,
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
