"""Deterministic single HITL gate for materially uncertain evidence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.budget.limited import minimum_evidence_is_met, usable_evidence_chains
from deepchoice.hitl import ALLOWED_DECISION_ACTIONS, DECISION_TTL, DecisionResolution
from deepchoice.runtime.context import get_run_context


HITL_POLICY_VERSION = "evidence-insufficient-v1"
HITL_PARTIAL_FAILURE = "evidence_insufficient_user_limited"


def _direction_is_materially_uncertain(state: dict[str, Any]) -> bool:
    recommendation = state.get("final_recommendation")
    if not isinstance(recommendation, dict):
        return False
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
    gaps: list[str] = []
    raw = state.get("knowledge_gaps")
    if isinstance(raw, list):
        gaps.extend(item.strip()[:500] for item in raw if isinstance(item, str) and item.strip())
    chains = usable_evidence_chains(state)
    if len(chains) < 3:
        gaps.append("Fewer than three non-disputed usable evidence chains are available.")
    hosts = {
        source.get("canonical_url") or source.get("url")
        for chain in chains
        for source in chain.get("sources", [])
        if isinstance(source, dict)
    }
    if len(hosts) < 2:
        gaps.append("The usable evidence does not yet provide sufficient independent source diversity.")
    verification = state.get("citation_verification")
    counts = verification.get("status_counts") if isinstance(verification, dict) else None
    if isinstance(counts, dict) and (
        int(counts.get("unsupported", 0) or 0) > 0
        or int(counts.get("unknown", 0) or 0) > 0
    ):
        gaps.append("One or more decision-critical citations remain unsupported or unknown.")
    return tuple(dict.fromkeys(gaps))[:12]


def _build_limited_report(state: dict[str, Any]) -> dict[str, Any]:
    limited = dict(state)
    limited["evidence_chains"] = usable_evidence_chains(state)
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
