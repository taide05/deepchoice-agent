"""Apply bounded model review edits to runtime-owned analysis slots only.

A model review is a second inference, never semantic verification or authority.
"""
from collections import Counter
import json
from copy import deepcopy
from dataclasses import dataclass

from .decision_analysis import MAX_ANALYSES, bind_decision_analysis, calibrate_decision_analysis, reviewable_source_fact
from .evidence_choices import bind_evidence_choices


@dataclass(slots=True)
class AnalysisReviewContext:
    recommendation: dict
    slots: dict
    facts: list
    requirements: list
    candidates: list
    query: str
    submitted: int


def prepare_analysis_review(state: dict) -> AnalysisReviewContext:
    from ..agents.conclusion_synthesizer import _decision_requirements

    task = state.get("task", {})
    query = task.get("query", "")
    candidates = task.get("candidate_techs", [])
    requirements, _ = _decision_requirements(
        query, task.get("constraints", []), [], task.get("sub_questions", []), [],
        task.get("scene_context", ""),
    )
    recommendation = deepcopy(state.get("final_recommendation", {}))
    recommendation.pop("analysis_review", None)  # Never trust model/history metadata.
    raw = recommendation.get("decision_analysis", [])
    raw = raw if isinstance(raw, list) else []
    # Preserve original positions, including invalid slots; never compact IDs.
    submitted = min(len(raw), MAX_ANALYSES + 1)
    raw = raw if len(raw) <= MAX_ANALYSES else []
    rebound = bind_evidence_choices(
        recommendation, state.get("evidence_chains", []), candidates, requirements,
    )
    bound_facts = {row["id"]: row for row in rebound.get("source_facts", [])}
    from ..citations.contracts import CitationVerification
    from .evidence_choices import calibrate_evidence_choices
    try:
        verification = CitationVerification.model_validate_json(json.dumps(state.get("citation_verification", {})))
    except (TypeError, ValueError):
        verification = None
    if verification is not None:
        rebound = calibrate_evidence_choices(rebound, verification)
        bound_facts = {row["id"]: row for row in rebound.get("source_facts", [])}
    facts = []
    for fact in recommendation.get("source_facts", []):
        if not isinstance(fact, dict) or not reviewable_source_fact(fact):
            continue
        bound = bound_facts.get(fact.get("id"))
        if (verification is None or not bound or not reviewable_source_fact(bound)
                or fact.get("status") != bound.get("status")
                or fact.get("review_availability") != bound.get("review_availability")):
            continue
        if bound and all(fact.get(key) == bound.get(key) for key in (
            "id", "evidence_id", "source_title", "canonical_url", "saved_text", "text",
        )):
            facts.append(deepcopy(fact))
    slots = {}
    for index, item in enumerate(raw, 1):
        bound = bind_decision_analysis(
            {"source_facts": facts, "decision_analysis": [item]}, requirements, candidates,
            query, require_basis=True,
        )
        calibrated = calibrate_decision_analysis(bound)["decision_analysis"]
        if len(calibrated) == 1:
            slots[f"A{index}"] = calibrated[0]
    return AnalysisReviewContext(recommendation, slots, facts, requirements, candidates, query, submitted)


def analysis_review_input(context: AnalysisReviewContext) -> dict:
    used = {key for item in context.slots.values() for key in item["fact_ids"]}
    return {
        "analyses": [{
            "analysis_id": key,
            **{field: item[field] for field in (
                "kind", "option", "requirements", "reasoning", "assumptions", "change_condition",
            )},
            "basis": [{"fact_id": row["fact_id"], "sentence_ids": row["sentence_ids"],
                       "source_sentences": row["source_sentences"]}
                      for row in item["basis"]],
        } for key, item in context.slots.items()],
        "complete_saved_sources": [{
            key: fact.get(key) for key in ("id", "source_title", "saved_text", "status", "review_availability")
        } for fact in context.facts if fact["id"] in used],
    }


def apply_analysis_review(context: AnalysisReviewContext, response: dict | None) -> tuple[dict, dict]:
    result = deepcopy(context.recommendation)
    rows = response.get("analysis_reviews") if isinstance(response, dict) else None
    valid_list = isinstance(rows, list) and len(rows) <= MAX_ANALYSES
    rows = rows if valid_list else []
    ids = [row.get("analysis_id") for row in rows if isinstance(row, dict)]
    counts = Counter(key for key in ids if isinstance(key, str))
    indexed = {row["analysis_id"]: row for row in rows if isinstance(row, dict)
               and isinstance(row.get("analysis_id"), str) and counts[row["analysis_id"]] == 1}
    foreign = any(not isinstance(row, dict) or not isinstance(row.get("analysis_id"), str) or row["analysis_id"] not in context.slots for row in rows)
    kept, revised, reviewed = [], 0, 0
    for key, original in context.slots.items():
        row = indexed.get(key)
        if row is None:
            continue
        action = row.get("action")
        fields = {"analysis_id", "action"}
        if action == "revise":
            fields |= {"reasoning", "assumptions", "change_condition"}
        if set(row) != fields or not isinstance(action, str) or action not in {"keep", "revise", "withdraw"}:
            continue
        if action == "withdraw":
            reviewed += 1
            continue
        item = deepcopy(original)
        if action == "revise":
            item.update({field: row[field] for field in ("reasoning", "assumptions", "change_condition")})
        bound = bind_decision_analysis(
            {"source_facts": context.facts, "decision_analysis": [item]}, context.requirements,
            context.candidates, context.query, require_basis=True,
        )
        accepted = calibrate_decision_analysis(bound)["decision_analysis"]
        if len(accepted) != 1:
            continue
        if accepted[0]["review_status"] == "network_unconfirmed_pending_review":
            accepted[0]["review_status"] = "network_unconfirmed_human_review_required"
        kept.append(accepted[0])
        reviewed += 1
        revised += action == "revise"
    if context.submitted:
        result["decision_analysis"] = kept
    status = ("unavailable" if response is None else
              "complete" if valid_list and not foreign and reviewed == context.submitted else "incomplete")
    summary = {"status": status, "submitted": context.submitted, "reviewed": reviewed,
               "retained": len(kept), "revised": revised, "withdrawn": context.submitted - len(kept)}
    if context.submitted:
        result["analysis_review"] = summary
    return result, summary
