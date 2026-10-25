"""Deterministic single HITL gate for materially uncertain evidence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.budget.limited import minimum_evidence_gaps, minimum_evidence_is_met, usable_evidence_chains
from deepchoice.hitl import ALLOWED_DECISION_ACTIONS, DECISION_TTL, DecisionResolution
from deepchoice.hitl.contracts import MAX_DECISION_GAPS
from deepchoice.runtime.context import get_run_context
from deepchoice.utils.decision_contract import restrict_recommendation
from deepchoice.utils.answer_delivery import finalize_answer_delivery, is_answer_delivery


HITL_POLICY_VERSION = "evidence-insufficient-v3"
HITL_PARTIAL_FAILURE = "evidence_insufficient_user_limited"


def _direction_is_materially_uncertain(state: dict[str, Any]) -> bool:
    recommendation = state.get("final_recommendation")
    if not isinstance(recommendation, dict):
        return False
    if (
        recommendation.get("decision_basis_version") == "constraint-aware-v1"
        and recommendation.get("winner") == "context_dependent"
    ):
        # The new contract deliberately removes ordinal rankings on abstention.
        return True
    ranked = recommendation.get("ranked_options")
    if not isinstance(ranked, list) or len(ranked) < 2:
        return False
    if recommendation.get("winner") == "context_dependent":
        return True
    if recommendation.get("confidence") == "low":
        return True
    if any(
        isinstance(option, dict) and option.get("constraint_fit") == "low"
        for option in ranked
    ):
        return True
    conflicts = state.get("conflicts")
    return isinstance(conflicts, list) and any(
        isinstance(conflict, dict)
        and conflict.get("resolution") in {"insufficient_data", "unresolved"}
        for conflict in conflicts
    )


def should_request_evidence_decision(state: dict[str, Any]) -> bool:
    """Require both structural insufficiency and meaningful option uncertainty."""

    return (
        not bool(state.get("_evidence_decision_gate_seen"))
        and not minimum_evidence_is_met(state)
        and _direction_is_materially_uncertain(state)
    )


def _public_gaps(state: dict[str, Any]) -> tuple[str, ...]:
    gaps = list(minimum_evidence_gaps(state))
    raw = state.get("knowledge_gaps")
    if isinstance(raw, list) and any(isinstance(item, str) and item.strip() for item in raw):
        # Historical or model-authored gaps can contain private source/user text.
        gaps.append("Additional unresolved evidence or reasoning gaps were reported.")
    verification = state.get("citation_verification")
    counts = verification.get("status_counts") if isinstance(verification, dict) else None
    if isinstance(verification, dict):
        unresolved = (counts.get("unsupported"), counts.get("unknown")) if isinstance(counts, dict) else (None, None)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in unresolved):
            gaps.append("Citation status information is unavailable.")
        elif any(value > 0 for value in unresolved):
            gaps.append("One or more decision-critical citations remain unsupported or unknown.")
    return tuple(dict.fromkeys(gaps))[:MAX_DECISION_GAPS]


def _build_limited_report(state: dict[str, Any]) -> dict[str, Any]:
    limited = dict(state)
    recommendation = state.get("final_recommendation", {})
    canonical = is_answer_delivery(recommendation)
    # Reuse the existing source/citation binder and display boundary before
    # carrying a reviewed answer through the user-selected restricted report.
    if canonical:
        from deepchoice.utils.analysis_review import prepare_analysis_review
        from deepchoice.utils.decision_analysis import ADVISORY_STATUS
        from deepchoice.formats.decision import _displayable_analyses

        context = prepare_analysis_review(state)
        summary = recommendation.get("analysis_review")
        rows = recommendation.get("decision_analysis", [])
        unreviewed = summary.get("unreviewed_retained", 0) if isinstance(summary, dict) else 0
        review_valid = (
            isinstance(summary, dict) and isinstance(rows, list)
            and summary.get("status") in {"complete", "incomplete"}
            and all(type(summary.get(key)) is int and 0 <= summary[key] <= 9
                    for key in ("submitted", "reviewed", "retained", "revised", "withdrawn"))
            and type(unreviewed) is int and 0 <= unreviewed <= 9
            and summary["retained"] == len(rows)
            and summary["retained"] == summary["reviewed"] - summary["withdrawn"] + unreviewed
            and summary["revised"] <= summary["reviewed"] <= summary["submitted"]
            and summary["withdrawn"] <= summary["reviewed"]
            and summary["retained"] <= summary["submitted"]
        )
        visible = _displayable_analyses(recommendation) if review_valid else []
        retained = [row for row in visible if row.get("review_status") == ADVISORY_STATUS
                    or any(row == {**bound, "review_status": row["review_status"]}
                           for bound in context.slots.values())]
        recommendation = {**recommendation, "source_facts": context.facts,
                          "decision_analysis": retained}
        if review_valid:
            removed = max(0, summary["retained"] - len(retained))
            displayed_unreviewed = sum(
                1 for row in retained if row.get("review_status") == ADVISORY_STATUS)
            # Keep the fixed review-summary identity
            # retained == reviewed - withdrawn + unreviewed_retained after the
            # display filter removes rows, without re-labelling any of them.
            recommendation["analysis_review"] = {
                **summary, "retained": len(retained),
                "unreviewed_retained": displayed_unreviewed,
                "withdrawn": summary["reviewed"] - len(retained) + displayed_unreviewed,
                "status": "incomplete" if removed else summary.get("status"),
            }
        else:
            recommendation.pop("analysis_review", None)
    # Preserve source numbering. Early budget results retain their strict path.
    limited["evidence_chains"] = state.get("evidence_chains", []) if canonical else usable_evidence_chains(state)
    failures = [
        item for item in state.get("partial_failures", []) if isinstance(item, str)
    ]
    if HITL_PARTIAL_FAILURE not in failures:
        failures.append(HITL_PARTIAL_FAILURE)
    limited["partial_failures"] = failures
    task = state.get("task") if isinstance(state.get("task"), dict) else {}
    query = str(task.get("query", ""))
    is_zh = any("一" <= char <= "鿿" for char in query)
    limited["data_source_note"] = (
        "证据不足；本报告仅基于暂停前取得的有限证据，结论需要谨慎使用。"
        if is_zh
        else "Evidence is insufficient. This restricted report uses only evidence collected before the pause and should be interpreted cautiously."
    )
    limited["final_recommendation"] = (
        finalize_answer_delivery(recommendation, query) if canonical
        else restrict_recommendation(recommendation, query)
    )
    renderer = FORMAT_RENDERERS.get(
        task.get("report_format", "what_why_how"), FORMAT_RENDERERS["what_why_how"]
    )
    banner = (
        "> **证据受限报告**：用户选择基于当前证据生成报告。"
        if is_zh
        else "> **Evidence-limited report:** The user chose to report from the currently available evidence."
    )
    limited["report"] = f"{banner}\n\n{renderer(limited)}"
    limited["_hitl_limited_report"] = True
    limited["_evidence_decision_gate_seen"] = True
    return limited


class EvidenceDecisionGateAgent:
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Legacy/in-memory execution has no durable decision repository and is
        # intentionally unchanged for its one-version compatibility window.
        if get_run_context() is None or not should_request_evidence_decision(state):
            return {
                "_evidence_decision_gate_seen": True,
                "_evidence_decision_route": "continue_report",
            }
        created_at = datetime.now(UTC)
        decision_id = str(uuid.uuid4())
        resumed = interrupt(
            {
                "decision_id": decision_id,
                "kind": "evidence-insufficient",
                "reason": "The available evidence is structurally insufficient for a materially uncertain choice.",
                "gaps": list(_public_gaps(state)),
                "allowed_actions": list(ALLOWED_DECISION_ACTIONS),
                "expires_at": (created_at + DECISION_TTL).isoformat(),
            }
        )
        resolution = DecisionResolution.model_validate(resumed)
        if resolution.action == "provide_context":
            return {
                "_evidence_decision_gate_seen": True,
                "_evidence_decision_route": "provide_context",
                "_supplemental_input": resolution.supplemental_input,
            }
        if resolution.action == "limited_report":
            limited = _build_limited_report(state)
            limited["_evidence_decision_route"] = "limited_report"
            return limited
        # Cancellation is resolved transactionally without resuming the graph.
        raise RuntimeError("cancel decisions must not resume graph execution")


def route_after_evidence_decision(state: dict[str, Any]) -> str:
    return str(state.get("_evidence_decision_route", "continue_report"))


__all__ = [
    "EvidenceDecisionGateAgent",
    "HITL_POLICY_VERSION",
    "route_after_evidence_decision",
    "should_request_evidence_decision",
]
