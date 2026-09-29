"""Deterministic citation verification workflow node."""

from __future__ import annotations

from copy import deepcopy
import re

from ..citations import verify_citations
from ..citations.verifier import MAX_CLAIM_TEXT
from ..utils.decision_contract import abstain_recommendation, restrict_action_plan
from ..utils.views import print_agent_output


_PERFORMANCE_SIGNAL_RE = re.compile(
    r"\b(?:benchmark|performance|throughput|latency|qps|rps|ops/?s|"
    r"requests?/?s|req/?s|faster|slower|workload|load|multithread(?:ed|ing)?)\b|"
    r"(?:基准|性能|吞吐|延迟|响应时间|每秒|更快|更慢|负载|多线程)",
    re.IGNORECASE,
)
_PERFORMANCE_MEASUREMENT_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:qps|rps|ops/?s|requests?/?s|req/?s|ms|x)\b|"
    r"\d+(?:[.,]\d+)?\s*(?:%|×)|"
    r"\d+(?:[.,]\d+)?\s*(?:transactions?|operations?|queries?|requests?)\s+per\s+second\b|"
    r"\b(?:faster|slower|gap|difference|narrow(?:s|ed|ing)?|improves?|reduces?)\b|"
    r"(?:更快|更慢|差距|差异|缩小|提升|降低|优于|落后|掩盖)",
    re.IGNORECASE,
)


def _is_external_performance_measurement(value: object) -> bool:
    """Recognize source measurements that still need current-workload validation.

    Lexical citation support can establish what a source reported, but it cannot
    establish that the source's product variant, version, hardware, topology and
    workload match the user's environment. Keep that distinction deterministic.
    """
    return (
        isinstance(value, str)
        and bool(_PERFORMANCE_SIGNAL_RE.search(value))
        and bool(_PERFORMANCE_MEASUREMENT_RE.search(value))
    )


def _authorizes_current_decision(path: str) -> bool:
    return (
        path.startswith("final_recommendation.requirement_assessments[")
        or path.startswith("final_recommendation.ranked_options[")
        or path.startswith("final_recommendation.action_plan[")
        or path in {
            "final_recommendation.winner_rationale",
            "final_recommendation.recommendation",
            "final_recommendation.scene_fit_note",
        }
    )


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
        by_path.setdefault(check.claim_path, []).append(check)

    external_performance_paths = {
        check.claim_path
        for check in verification.checks
        if check.status.value == "verified"
        and _is_external_performance_measurement(check.claim_text)
    }
    performance_note = (
        "未知：外部性能测量只能说明来源报告了什么，不能证明其产品变体、版本、硬件、"
        "拓扑和负载适用于当前环境；需要当前负载的本地配对验证。"
        if is_zh else
        "Unknown: an external performance measurement establishes only what the "
        "source reported, not that its product variant, version, hardware, topology "
        "and workload apply here; validate with a local paired measurement."
    )

    def passed(path):
        checks = by_path.get(path, [])
        return (
            bool(checks)
            and all(check.status.value == "verified" for check in checks)
            and not (
                _authorizes_current_decision(path)
                and path in external_performance_paths
            )
        )

    def provisional(path, explanation):
        # Never copy unchecked tails, overflow, missing citations or a negative
        # lexical check into the uncertainty display. This is not proof of truth.
        checks = by_path.get(path, [])
        allowed_outcomes = {
            ("verified", "lexical_support"),
            ("unknown", "network_uncertain"),
            ("unknown", "cross_language"),
            ("unknown", "http_uncertain"),
            ("unknown", "content_insufficient"),
            ("unreachable", "not_publicly_accessible"),
        }
        return (
            "final_recommendation" not in by_path
            and isinstance(explanation, str)
            and 0 < len(explanation) <= MAX_CLAIM_TEXT
            and bool(checks)
            and all((check.status.value, check.reason.value) in allowed_outcomes
                    for check in checks)
        )

    withdraw = "final_recommendation" in by_path  # Bounded-check overflow summary.
    pending_analysis = {}
    rows = result.get("requirement_assessments", [])
    if not isinstance(rows, list):
        rows = []
        withdraw = True
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            withdraw = True
            continue
        # Only this pass may create the display-only field. Model input and old
        # projections cannot use it as a second, unchecked assertion channel.
        row.pop("provisional_explanation", None)
        path = f"final_recommendation.requirement_assessments[{index}].explanation"
        if row.get("status") != "unknown" and not passed(path):
            if provisional(path, row.get("explanation")):
                pending_analysis[row.get("id")] = row["explanation"]
            row.update(
                status="unknown",
                explanation=(
                    performance_note
                    if path in external_performance_paths
                    else note
                ),
                evidence_ids=[],
            )
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
    action_unverified = False
    action_plan = result.get("action_plan", [])
    if not isinstance(action_plan, list):
        action_unverified = bool(action_plan)
    else:
        for index, item in enumerate(action_plan):
            if not isinstance(item, dict):
                action_unverified = True
                continue
            for field in ("step", "verification", "change_trigger", "rollback"):
                if not item.get(field) or not passed(
                    f"final_recommendation.action_plan[{index}].{field}"
                ):
                    action_unverified = True
    branches = result.get("decision_branches", [])
    if isinstance(branches, list):
        # Branches survive abstention as conditional guidance, so remove an
        # external performance threshold even when its check is missing,
        # unknown or unsupported. A safe branch asks for a local measurement
        # without importing the source's result as the decision boundary.
        result["decision_branches"] = [
            branch for branch in branches
            if not (
                isinstance(branch, dict)
                and _is_external_performance_measurement(branch.get("condition"))
            )
        ]
    if withdraw:
        restriction_note = (
            performance_note
            if any(
                _authorizes_current_decision(path)
                for path in external_performance_paths
            )
            else note
        )
        result = abstain_recommendation(result, query, restriction_note)
    elif action_unverified:
        result = restrict_action_plan(result, query)
    # Abstention deliberately normalizes away model-supplied extension fields.
    # Attach only freshly checked analysis after that boundary; limited reports
    # normalize again and therefore remove it.
    for row in result.get("requirement_assessments", []):
        if isinstance(row, dict) and row.get("status") == "unknown":
            analysis = pending_analysis.get(row.get("id"))
            if analysis:
                row["provisional_explanation"] = analysis
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
