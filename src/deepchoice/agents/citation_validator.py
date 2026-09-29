"""Deterministic citation verification workflow node."""

from __future__ import annotations

from copy import deepcopy
import re

from ..citations import verify_citations
from ..citations.verifier import (
    MAX_CLAIM_TEXT,
    _resolve_title,
    _source_registry,
)
from ..utils.decision_contract import (
    PLAIN_REQUIREMENT_GAPS,
    abstain_recommendation,
    is_fixed_validation_only_plan,
    normalize_decision_branches,
    restrict_action_plan,
)
from ..utils.evidence import is_navigation_placeholder
from ..utils.views import print_agent_output
from ..utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices
from .conclusion_synthesizer import _decision_requirements


_MAX_SAVED_EXCERPT_CHARS = 1200
_MAX_DISPLAY_EXCERPTS = 4


def _saved_excerpts(checks, evidence_chains: list[dict], limit: int) -> list[dict[str, str]]:
    """Show bounded saved source text, never a model-selected or live-verified quote.

    Resolve through the same registry as citation checks.  Refuse an oversized
    excerpt rather than clipping away a qualifier at the end of its snippet.
    """
    if limit <= 0:
        return []
    registry, _ = _source_registry(evidence_chains)
    excerpts: list[dict[str, str]] = []
    seen: set[tuple[int, int]] = set()
    for check in checks:
        if not check.source_title or not check.canonical_url:
            continue
        source, error = _resolve_title(check.source_title, registry)
        if error is not None or source is None or source.canonical_url != check.canonical_url:
            continue
        if source.position in seen:
            continue
        seen.add(source.position)
        chain_index, source_index = source.position
        try:
            snippet = evidence_chains[chain_index]["sources"][source_index]["snippet"]
        except (IndexError, KeyError, TypeError):
            continue
        if not isinstance(snippet, str) or is_navigation_placeholder(snippet):
            continue
        clean = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", snippet).split())
        if not clean or len(clean) > _MAX_SAVED_EXCERPT_CHARS:
            continue
        excerpts.append({"title": source.title, "text": clean})
        if len(excerpts) >= limit:
            break
    return excerpts


def _calibrate_decision(
    recommendation: dict, verification, query: str,
    evidence_chains: list[dict] | None = None,
) -> dict:
    """Withdraw unsupported decision premises without treating unknown as false.

    This checks bounded lexical outcomes, not semantic truth. Historical results
    lacking the new contract are left readable and are never rewritten in storage.
    """
    if recommendation.get("decision_basis_version") != "constraint-aware-v1":
        return recommendation
    result = deepcopy(recommendation)
    evidence_chains = evidence_chains if isinstance(evidence_chains, list) else []
    # Even fully verified lexical citations cannot attest to a deployment drill.
    result["deployment_readiness"] = "unverified"
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

    def passed(path):
        checks = by_path.get(path, [])
        return bool(checks) and all(check.status.value == "verified" for check in checks)

    def provisional(path, explanation):
        # Never copy unchecked tails, overflow, missing citations or a negative
        # lexical check into the uncertainty display. This is not proof of truth.
        checks = by_path.get(path, [])
        allowed_outcomes = {
            ("verified", "lexical_support"),
            ("unknown", "network_uncertain"),
            ("unknown", "cross_language"),
            ("unknown", "qualifier_unverified"),
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
        row.pop("saved_source_excerpts", None)
        path = f"final_recommendation.requirement_assessments[{index}].explanation"
        plain_gap = (
            row.get("status") == "unknown"
            and not row.get("evidence_ids")
            and isinstance(row.get("explanation"), str)
            and row.get("explanation") in PLAIN_REQUIREMENT_GAPS
        )
        if not plain_gap and not passed(path):
            checks = by_path.get(path, [])
            if provisional(path, row.get("explanation")):
                pending_analysis[row.get("id")] = (row["explanation"], checks)
            elif checks and any(
                check.reason.value in {"cross_language", "qualifier_unverified"}
                for check in checks
            ):
                # A mixed explanation may contain an uncited inference after
                # a cited source fact. Never display that model-authored line,
                # but keep bounded source text available for inspection.
                pending_analysis[row.get("id")] = (None, checks)
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
    action_unverified = False
    action_plan = result.get("action_plan", [])
    if is_fixed_validation_only_plan(result, query):
        # This exact plan is deterministic safety output, not model-authored
        # operational authority. It neither earns citation support nor needs a
        # second replacement pass.
        action_unverified = False
    elif not isinstance(action_plan, list):
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
    branch_paths = []
    original_branches = result.get("decision_branches", [])
    for original_index, branch in enumerate(original_branches if isinstance(original_branches, list) else []):
        if isinstance(branch, dict):
            branch.pop("saved_source_excerpts", None)
            normalized = normalize_decision_branches([branch])
            if normalized:
                branch_paths.append((original_index, normalized[0]))
    if withdraw:
        result = abstain_recommendation(result, query, note)
    elif action_unverified:
        result = restrict_action_plan(result, query)
    # Abstention deliberately normalizes away model-supplied extension fields.
    # Attach only freshly checked analysis after that boundary; limited reports
    # normalize again and therefore remove it.
    # Reserve the bounded report-wide occurrence budget for decision branches
    # first. Earlier requirement rows otherwise crowd out decisive qualifiers.
    remaining_excerpts = _MAX_DISPLAY_EXCERPTS
    branches = result.get("decision_branches", [])
    for visible_index, branch in enumerate(branches if isinstance(branches, list) else []):
        if not isinstance(branch, dict):
            continue
        if withdraw:
            if visible_index >= len(branch_paths):
                continue
            original_index, expected = branch_paths[visible_index]
            if branch.get("option") != expected["option"] or branch.get("condition") != expected["condition"]:
                continue
        else:
            original_index = visible_index
        path = f"final_recommendation.decision_branches[{original_index}].condition"
        checks = by_path.get(path, [])
        qualifier_unknown = any(
            check.reason.value in {"cross_language", "qualifier_unverified"}
            for check in checks
        )
        if qualifier_unknown:
            # A translated or strengthened model condition may omit the source's
            # applicability boundary. Do not repeat it as a usable branch.
            branch["condition"] = (
                "适用前提待核对来源原文与当前工作负载。" if is_zh else
                "Applicability requires checking the original source and this workload."
            )
        excerpts = _saved_excerpts(checks, evidence_chains, min(2, remaining_excerpts)) if qualifier_unknown else []
        if excerpts:
            branch["saved_source_excerpts"] = excerpts
            remaining_excerpts -= len(excerpts)
    visible_rows = result.get("requirement_assessments", [])
    # Keep report order unchanged, but allocate the small source-excerpt
    # allowance to critical mixed rows before ordinary provisional analysis.
    def mixed_critical(row: object) -> bool:
        if not isinstance(row, dict) or row.get("decision_critical", True) is False:
            return False
        analysis = pending_analysis.get(row.get("id"))
        return analysis is not None and analysis[0] is None

    priority_rows = [row for row in visible_rows if mixed_critical(row)]
    remaining_rows = [row for row in visible_rows if not mixed_critical(row)]
    for row in priority_rows + remaining_rows:
        if isinstance(row, dict) and row.get("status") == "unknown":
            analysis = pending_analysis.get(row.get("id"))
            if analysis:
                qualifier_unknown = any(
                    check.reason.value in {"cross_language", "qualifier_unverified"}
                    for check in analysis[1]
                )
                if not qualifier_unknown and analysis[0]:
                    row["provisional_explanation"] = analysis[0]
                eligible_checks = [
                    check for check in analysis[1]
                    if check.reason.value in {"cross_language", "qualifier_unverified"}
                ]
                per_row_limit = 1 if mixed_critical(row) else 2
                excerpts = (_saved_excerpts(eligible_checks, evidence_chains,
                                            min(per_row_limit, remaining_excerpts))
                            if qualifier_unknown else [])
                if excerpts:
                    row["saved_source_excerpts"] = excerpts
                    remaining_excerpts -= len(excerpts)
    return calibrate_evidence_choices(result, verification)


class CitationValidatorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        recommendation = research_state.get("final_recommendation", {})
        evidence_chains = research_state.get("evidence_chains", [])
        query = str(research_state.get("task", {}).get("query", ""))
        task = research_state.get("task", {})
        requirements, _ = _decision_requirements(
            task.get("query", ""), task.get("constraints", []), [],
            task.get("sub_questions", []), [], task.get("scene_context", ""),
        )
        if isinstance(recommendation, dict):
            recommendation = bind_evidence_choices(
                recommendation, evidence_chains, task.get("candidate_techs", []), requirements,
            )
        verification_input = recommendation
        if (
            isinstance(recommendation, dict)
            and is_fixed_validation_only_plan(recommendation, query)
        ):
            verification_input = deepcopy(recommendation)
            # The fixed plan is generated by the safety boundary itself. It is
            # not a model-authored factual claim and must not inflate
            # citation_missing counts.
            verification_input["action_plan"] = []
        print_agent_output(
            "Verifying critical-claim citations deterministically",
            agent="CITATION_VALIDATOR",
        )
        verification, projected_chains = await verify_citations(
            verification_input if isinstance(verification_input, dict) else {},
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
                query,
                evidence_chains if isinstance(evidence_chains, list) else [],
            )
        return output


__all__ = ["CitationValidatorAgent"]
