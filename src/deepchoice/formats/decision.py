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


def _plain_analysis(value: Any) -> str:
    # Model prose is literal content, never a link, HTML node or citation badge.
    import html
    text = html.escape(_text(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]#!|])", r"\\\1", text)


def _render_model_analysis(recommendation: dict, lang: str) -> list[str]:
    from ..utils.decision_analysis import analysis_fact_reviewable, bind_analysis_basis
    facts = {item["id"]: item for item in _dict_items(recommendation.get("source_facts"), 5)
             if isinstance(item.get("id"), str)}
    accepted = []
    for item in _dict_items(recommendation.get("decision_analysis"), 8):
        ids = item.get("fact_ids")
        reviewed_unknown = (item.get("review_status") in {
                                "network_unconfirmed_human_review_required",
                                "sentence_scoped_human_review_required",
                            }
                            and "basis" in item
                            and isinstance(recommendation.get("analysis_review"), dict)
                            and recommendation["analysis_review"].get("retained", 0) > 0)
        basis_rows = item.get("basis")
        addressed = {row["fact_id"]: row for row in basis_rows
                     if isinstance(row, dict) and isinstance(row.get("fact_id"), str)} if isinstance(basis_rows, list) else {}
        if (item.get("review_status") == "human_review_required" or reviewed_unknown) and (
                isinstance(ids, list) and 0 < len(ids) <= 4
                and all(isinstance(key, str) and key in facts
                        and (facts[key].get("status") == "verified"
                             or reviewed_unknown and analysis_fact_reviewable(
                                 facts[key], addressed.get(key))) for key in ids)):
            if "basis" in item:
                basis, error = bind_analysis_basis(item["basis"], facts)
                if error or [row["fact_id"] for row in basis] != ids:
                    continue
                item = {**item, "basis": basis}
            accepted.append(item)
    zh = lang == "zh"
    review = recommendation.get("analysis_review")
    note = ""
    if (isinstance(review, dict) and review.get("status") in {"complete", "incomplete", "unavailable"}
            and all(type(review.get(key)) is int and 0 <= review[key] <= 9
                    for key in ("submitted", "retained", "revised", "withdrawn"))
            and review["submitted"] > 0):
        if review["status"] != "complete":
            note = ("部分模型分析未获得可用的自审结果，已撤回；保存的来源原文仍可核对。保留或修订的分析仍需人工审阅。"
                    if zh else "Some model analyses lacked a usable review and were withheld. Saved sources remain available for inspection. Retained or revised analyses still require human review.")
        elif review["withdrawn"]:
            note = ("部分模型分析在自审后撤回；保存的来源原文仍可核对。保留或修订的分析仍需人工审阅。"
                    if zh else "Some model analyses were withdrawn after review. Saved sources remain available for inspection. Retained or revised analyses still require human review.")
    if not accepted and not note:
        return []
    lines = ["### 模型分析 · 待人工审阅" if zh else "### Model analysis · Human review required", "",
             "以下释义、适用性判断与概念设计是模型推断，尚未经过语义验证。假设仍需确认，来源词法核验不证明建议正确；实际操作仅限下方隔离验证计划。"
             if zh else "The paraphrases, applicability judgments and conceptual designs below are model inferences, not semantically verified conclusions. Assumptions need confirmation. Source lexical checks do not prove the proposals; operations remain limited to the isolated validation plan below.", ""]
    labels = {"choice": "条件选择" if zh else "Conditional choice",
              "answer": "问题解答" if zh else "Question analysis",
              "design": "概念方案" if zh else "Conceptual design"}
    if note:
        lines.extend([note, ""])
    used = {key: fact for key, fact in facts.items() if fact.get("status") == "verified"} if note else {}
    for item in accepted:
        title = labels.get(item.get("kind"), labels["answer"])
        if item.get("option"):
            title += " — " + _plain_analysis(item["option"])
        lines.extend([f"#### {title}", ""])
        if item.get("review_status") == "network_unconfirmed_human_review_required":
            lines.extend(["来源页面本次未能核验（unknown）。以下仅为基于保存片段、待人工审阅的条件分析；未确认来源当前内容与适用性。"
                          if zh else "Live source verification was unavailable (unknown). This is a conditional analysis of saved excerpts for human review; current source content and applicability remain unconfirmed.", ""])
        elif item.get("review_status") == "sentence_scoped_human_review_required":
            lines.extend(["所引句子通过有限词法核验，但同份来源仍有未核实的限定句，整份来源保持unknown。以下模型推断需核对完整原文并由人工审阅。"
                          if zh else "Addressed sentences passed bounded lexical checks, but another qualifier in the same source remains unverified. The whole source stays unknown; inspect its full text and review this inference manually.", ""])
        requirements = item.get("requirements", [])
        if isinstance(requirements, list):
            lines.append(("对应问题：" if zh else "Addresses: ") + " / ".join(_plain_analysis(v) for v in requirements[:4]))
        if "basis" in item:
            lines.extend(["", "来源原句（完整保存上下文见下方）：" if zh else
                          "Source sentences (complete saved context below):"])
            for row in item["basis"]:
                title = _plain_analysis(facts[row["fact_id"]].get("source_title"))
                for sentence in row["source_sentences"]:
                    lines.append("- " + _plain_analysis(sentence) + " — " + title)
            lines.extend(["", "基于上述原句的模型判断：" if zh else "Model judgment based on those sentences:"])
        lines.extend(["", _plain_analysis(item.get("reasoning")), ""])
        assumptions = item.get("assumptions", [])
        if isinstance(assumptions, list):
            for assumption in assumptions[:4]:
                lines.append(("- 待确认假设：" if zh else "- Unconfirmed assumption: ") + _plain_analysis(assumption))
        lines.append(("- 改变判断的条件：" if zh else "- What would change this judgment: ") + _plain_analysis(item.get("change_condition")))
        lines.append(("- 来源原文见下方：" if zh else "- Source text below: ") + " / ".join(_code(_text(facts[key].get("source_title"))) for key in item["fact_ids"]))
        lines.append("")
        used.update({key: facts[key] for key in item["fact_ids"]})
    lines.extend(["#### 来源原文与核验状态" if zh else "#### Source text and check status", ""])
    for fact in used.values():
        lines.extend(_render_saved_excerpts({"saved_source_excerpts": [{"title": fact.get("source_title"), "text": fact.get("saved_text")}]}, lang))
        if fact.get("status") == "verified":
            lines.append("  - " + ("原文词法核验：verified；不验证上方模型推断。" if zh else "Source lexical check: verified; this does not verify the model inferences above."))
        elif fact.get("review_availability") == "sentence_scoped":
            lines.append("  - " + ("原文核验：unknown（部分限定句未核实）；完整保存片段与模型分析均需人工核对。" if zh else "Source check: unknown (a qualifier remains unverified); the complete saved excerpt and model analysis require human checking."))
        else:
            lines.append("  - " + ("原文核验：unknown（本次网络核验未完成）；保存片段与模型分析均需人工核对。" if zh else "Source check: unknown (network verification unavailable); saved excerpts and model analysis require human checking."))
    return lines + [""]


def render_decision_details(recommendation: Any, lang: str) -> list[str]:
    """Render structured decision fields without exposing internal IDs."""

    if not isinstance(recommendation, dict):
        return []

    assessments = _dict_items(recommendation.get("requirement_assessments"), 40)
    branches = _dict_items(recommendation.get("decision_branches"), 20)
    action_plan = _dict_items(recommendation.get("action_plan"), 20)
    lines: list[str] = []

    lines.extend(_render_model_analysis(recommendation, lang))

    if recommendation.get("decision_basis_version") == "constraint-aware-v1":
        # A fixed boundary, never a model-supplied readiness claim. Rendering a
        # historical snapshot must not upgrade an arbitrary readiness marker.
        lines.extend([
            "### 部署验收：未验证" if lang == "zh" else "### Deployment acceptance: unverified",
            "",
            (
                "选型依据与部署验收分开判断。本研究不执行真实部署或恢复演练；文档引用通过不表示演练通过，也不授权生产变更。仅在用户明确要求实际验收证据时，该证据才作为相应要求评估。"
                if lang == "zh" else
                "Selection evidence and deployment acceptance are separate. This research does not execute deployment or recovery rehearsals; verified document citations neither prove a successful drill nor authorize production changes. Acceptance evidence is assessed as a requirement only when the user explicitly requests it."
            ),
            "",
        ])

    facts = {item["id"]: item for item in _dict_items(recommendation.get("source_facts"), 5)
             if isinstance(item.get("id"), str)}
    choices = _dict_items(recommendation.get("conditional_choices"), 4)
    if choices:
        lines.extend(["### 条件选择依据" if lang == "zh" else "### Basis for conditional choices", ""])
        lines.append(
            "以下选择关系是模型推断；来源词法核验不证明场景适用性、需求满足或部署就绪。"
            if lang == "zh" else
            "Choice relations are model inferences; lexical checks do not prove applicability, requirement satisfaction or deployment readiness."
        )
        labels = {
            "prefer": "优先考虑" if lang == "zh" else "Prioritize considering",
            "consider": "可以考虑" if lang == "zh" else "Consider",
            "insufficient_alone": "不能仅凭所列机制认定满足需求" if lang == "zh" else "The listed mechanisms alone do not establish satisfaction",
        }
        displayed_facts = {}
        for choice in choices:
            identifiers = choice.get("fact_ids", [])
            if not isinstance(identifiers, list) or not identifiers or any(
                not isinstance(key, str) or key not in facts for key in identifiers
            ):
                continue
            verified = choice.get("basis_status") == "verified" and all(
                facts[key].get("status") == "verified" for key in identifiers
            )
            option = _code(_text(choice.get("option")))
            relation = labels.get(_text(choice.get("relation")))
            if relation is None:
                continue
            requirements = choice.get("requirements", [])
            if not isinstance(requirements, list) or not requirements:
                continue
            lines.append("- " + ("用户需求：" if lang == "zh" else "User requirements: ")
                         + " / ".join(_code(_text(value)) for value in requirements[:8]))
            lines.append(
                f"  - 模型条件推断：{option} — {relation}；仍需核对下列来源的适用前提。"
                if verified and lang == "zh" else
                f"  - Conditional model inference: {option} — {relation}; check the source prerequisites below."
                if verified else
                f"  - {option}：依据尚未通过完整核验，暂不展示选择推断。"
                if lang == "zh" else
                f"  - {option}: the evidence has not passed complete checks; choice inference withheld."
            )
            lines.append("  - " + ("依据：" if lang == "zh" else "Sources: ")
                         + " / ".join(_code(_text(facts[key].get("source_title"))) for key in identifiers))
            displayed_facts.update({key: facts[key] for key in identifiers})
        for fact in displayed_facts.values():
            lines.extend(_render_saved_excerpts({"saved_source_excerpts": [{
                "title": fact.get("source_title"), "text": fact.get("saved_text"),
            }]}, lang))
            lines.append("    " + ("引用状态：" if lang == "zh" else "Citation status: ")
                         + _code(_text(fact.get("status"))))
        lines.append("")

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
        reviewed_facts = {}
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
            ids = item.get("provisional_fact_ids")
            reviewed = (item.get("provisional_review_status") == "human_review_required"
                        and isinstance(recommendation.get("provisional_review"), dict)
                        and recommendation["provisional_review"].get("retained", 0) > 0
                        and isinstance(ids, list) and 0 < len(ids) <= 4
                        and all(isinstance(key, str) and key in facts for key in ids))
            if reviewed:
                from ..utils.decision_analysis import reviewable_source_fact
                reviewed = all(reviewable_source_fact(facts[key]) for key in ids)
            if status == "unknown" and analysis and reviewed:
                label = (
                    "待独立核验的分析（不代表需求已满足）"
                    if lang == "zh" else
                    "Analysis awaiting independent verification (not a satisfied requirement)"
                )
                lines.append(f"  - **{label}:** {_plain_analysis(analysis)}")
                lines.append("  - " + ("保存来源（自审不代表语义验证）：" if lang == "zh" else "Saved sources (review is not semantic verification): ")
                             + " / ".join(_code(facts[key]["source_title"]) for key in ids))
                reviewed_facts.update({key: facts[key] for key in ids})
            elif status == "unknown" and (analysis or item.get("provisional_review_status") == "withheld"):
                lines.append("  - " + ("未获得可用审阅的模型解释已撤回；该需求仍未知。" if lang == "zh" else
                                        "Model explanation withheld without usable review; this requirement remains unknown."))
            if status == "unknown":
                lines.extend(_render_saved_excerpts(item, lang))
        lines.append("")

        for fact in reviewed_facts.values():
            lines.extend(_render_saved_excerpts({"saved_source_excerpts": [{"title": fact["source_title"], "text": fact["saved_text"]}]}, lang))
            lines.append("  - " + ("来源核验状态：" if lang == "zh" else "Source check status: ") + _code(fact["status"]))
        if reviewed_facts:
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
