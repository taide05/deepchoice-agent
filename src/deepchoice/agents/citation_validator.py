"""Deterministic citation verification workflow node."""

from __future__ import annotations

from copy import deepcopy

from ..citations import verify_citations
from ..utils.decision_contract import abstain_recommendation
from ..utils.views import print_agent_output


def _calibrate_decision(recommendation: dict, verification, query: str) -> dict:
    """Withdraw unsupported decision premises without treating unknown as false.

    This checks bounded lexical outcomes, not semantic truth. Historical results
    lacking the new contract are left readable and are never rewritten in storage.
    """
    if recommendation.get("decision_basis_version") != "constraint-aware-v1":
        return recommendation
    result = deepcopy(recommendation)
    is_zh = any("一" <= char <= "鿿" for char in query)
    note = (
        "未知：该判断的引用尚未完成可用性与词法支持核验，需要独立确认。"
        if is_zh else
        "Unknown: the citations for this assessment have not passed availability "
        "and lexical-support checks; independent confirmation is needed."
    )
    by_path = {}
    for check in verification.checks:
        by_path.setdefault(check.claim_path, []).append(check.status.value)

    def passed(path):
        statuses = by_path.get(path, [])
        return bool(statuses) and all(status == "verified" for status in statuses)

    withdraw = "final_recommendation" in by_path  # Bounded-check overflow summary.
    rows = result.get("requirement_assessments", [])
    if not isinstance(rows, list):
        rows = []
        withdraw = True
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            withdraw = True
            continue
        if row.get("status") != "unknown" and not passed(
            f"final_recommendation.requirement_assessments[{index}].explanation"
        ):
            row.update(status="unknown", explanation=note, evidence_ids=[])
        if row.get("decision_critical", True) is not False and row.get("status") != "satisfied":
            withdraw = True
    if result.get("winner") not in (None, "", "context_dependent") and not passed(
        "final_recommendation.winner_rationale"
    ):
        withdraw = True
    # A supported headline cannot legitimize an unsupported decisive sentence
    # elsewhere in the proposed recommendation or ranked comparison.
    for field in ("recommendation", "evidence_summary", "scene_fit_note", "confidence_rationale"):
        if result.get(field) and not passed(f"final_recommendation.{field}"):
            withdraw = True
    for collection, fields in (
        ("ranked_options", ("constraint_fit_reason", "rationale", "key_strength", "key_weakness")),
        ("trade_offs", ("finding", "impact")),
    ):
        items = result.get(collection, [])
        if not isinstance(items, list):
            withdraw = True
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                withdraw = True
                continue
            for field in fields:
                if item.get(field) and not passed(f"final_recommendation.{collection}[{index}].{field}"):
                    withdraw = True
    if withdraw:
        result = abstain_recommendation(result, query, note)
    return result


class CitationValidatorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        recommendation = research_state.get("final_recommendation", {})
        evidence_chains = research_state.get("evidence_chains", [])
        print_agent_output(
            "Verifying critical-claim citations deterministically",
            agent="CITATION_VALIDATOR",
        )
        verification, projected_chains = await verify_citations(
            recommendation if isinstance(recommendation, dict) else {},
            evidence_chains if isinstance(evidence_chains, list) else [],
        )
        counts = verification.status_counts
        output = {
            "citation_verification": verification.model_dump(mode="json"),
            "evidence_chains": projected_chains,
            "quality_signals": [{
                "agent": "citation_validator",
                "verified": counts.verified,
                "unsupported": counts.unsupported,
                "unreachable": counts.unreachable,
                "unknown": counts.unknown,
            }],
        }
        if isinstance(recommendation, dict) and recommendation.get("decision_basis_version"):
            output["final_recommendation"] = _calibrate_decision(
                recommendation, verification,
                str(research_state.get("task", {}).get("query", "")),
            )
        return output


__all__ = ["CitationValidatorAgent"]
