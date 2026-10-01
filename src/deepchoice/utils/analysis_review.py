"""Apply bounded model review edits to runtime-owned analysis slots only.

A model review is a second inference, never semantic verification or authority.
"""
from collections import Counter
import json
import re
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
    provisional_slots: dict
    provisional_submitted: int


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
    recommendation.pop("provisional_review", None)
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
    provisional_slots, provisional_submitted = _prepare_provisional(
        recommendation, verification, facts, requirements, query, MAX_ANALYSES - len(slots),
    )
    return AnalysisReviewContext(recommendation, slots, facts, requirements, candidates, query,
                                 submitted, provisional_slots, provisional_submitted)


def analysis_review_input(context: AnalysisReviewContext) -> dict:
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
        "requirement_explanations": [{
            "analysis_id": key, "requirement": item["requirement"],
            "reasoning": item["text"], "fact_ids": item["fact_ids"],
        } for key, item in context.provisional_slots.items()],
        "challenge_fact_ids": [fact["id"] for fact in context.facts],
        "complete_saved_sources": [{
            key: fact.get(key) for key in ("id", "source_title", "saved_text", "status", "review_availability")
        } | {"sentences": _sentences(fact)} for fact in context.facts],
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
        fields = {"analysis_id", "action"} if action == "withdraw" else {"analysis_id", "action", "source_checks"}
        if action == "revise":
            fields |= {"reasoning", "assumptions", "change_condition"}
            if "additional_basis" in row:
                fields.add("additional_basis")
        if set(row) != fields or not isinstance(action, str) or action not in {"keep", "revise", "withdraw"}:
            continue
        if action == "withdraw":
            reviewed += 1
            continue
        if not _challenge_valid(row, context.facts):
            continue
        item = deepcopy(original)
        if action == "revise":
            item.update({field: row[field] for field in ("reasoning", "assumptions", "change_condition")})
        if "additional_basis" in row:
            from .decision_analysis import bind_analysis_basis
            additions = row["additional_basis"]
            if (not isinstance(additions, list) or not additions or item.get("reasoning") == original["reasoning"]):
                continue
            challenges = {check[0]: check for check in row["source_checks"]}
            basis, error = bind_analysis_basis(original["basis"] + additions, {fact["id"]: fact for fact in context.facts})
            if error or any(
                challenges[part["fact_id"]][1] not in {"qualifies", "conflicts"}
                or not set(challenges[part["fact_id"]][2]).issubset(part["sentence_ids"])
                for part in basis[len(original["basis"]):]
            ):
                continue
            item["basis"] = basis
            item["fact_ids"] = [part["fact_id"] for part in basis]
        prose = [item.get("option"), item.get("reasoning"), item.get("change_condition")]
        if isinstance(item.get("assumptions"), list):
            prose.extend(item["assumptions"])
        if not _candidate_attribution(" ".join(value for value in prose if isinstance(value, str)), item["fact_ids"], context):
            continue
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
    _apply_provisional(result, context, response)
    return result, summary


def _sentences(fact):
    from ..citations.verifier import _split_sentences
    return [{"sentence_id": index, "text": text}
            for index, text in enumerate(_split_sentences(fact["saved_text"]), 1)]


def _challenge_valid(row, facts):
    """Enforce complete addressed review, not the truth of model stances."""
    checks = row.get("source_checks")
    expected = {fact["id"]: len(_sentences(fact)) for fact in facts}
    if not isinstance(checks, list) or len(checks) != len(expected):
        return False
    seen = set()
    for check in checks:
        if not isinstance(check, list) or len(check) != 3:
            return False
        key, stance, ids = check
        if (not isinstance(key, str) or key not in expected or key in seen
                or not isinstance(stance, str) or stance not in {"supports", "irrelevant", "qualifies", "conflicts"}
                or not isinstance(ids, list) or len(ids) > 3
                or (not ids and stance != "irrelevant")
                or any(type(index) is not int or not 1 <= index <= expected[key] for index in ids)
                or len(set(ids)) != len(ids)):
            return False
        if row.get("action") == "keep" and stance in {"qualifies", "conflicts"}:
            return False
        seen.add(key)
    return True


def _candidate_attribution(text, fact_ids, context):
    """A named candidate needs lexical coverage in its own basis, not another slot.

    This catches an unbound alternative claim even when a model reports no conflict.
    It does not establish subject attribution or entailment; aliases may be withheld.
    """
    if not isinstance(text, str):
        return False
    source = " ".join(fact["source_title"] + " " + fact["saved_text"]
                      for fact in context.facts if fact["id"] in fact_ids)
    for candidate in context.candidates if isinstance(context.candidates, list) else []:
        if not isinstance(candidate, str) or not candidate:
            continue
        pattern = r"(?<![a-z0-9_])" + re.escape(candidate.casefold()) + r"(?![a-z0-9_])"
        if re.search(pattern, text.casefold()) and not re.search(pattern, source.casefold()):
            return False
    return True


def _prepare_provisional(recommendation, verification, facts, requirements, query, capacity):
    from ..citations.verifier import _extract_claims, _strip_citations, MAX_CLAIM_TEXT
    from .decision_analysis import original_analysis_requirements
    original = original_analysis_requirements(requirements, query)
    rows = recommendation.get("requirement_assessments", [])
    rows = rows if isinstance(rows, list) else []
    identifiers = Counter(row.get("id") for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str))
    by_source = {(fact["source_title"], fact["canonical_url"]): fact["id"] for fact in facts}
    slots, submitted = {}, 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        row.pop("provisional_review_status", None)
        row.pop("provisional_fact_ids", None)
        text = row.get("provisional_explanation")
        if not text:
            continue
        submitted += 1
        key = row.get("id")
        if (index >= 40 or not isinstance(key, str) or identifiers[key] != 1
                or key not in original or row.get("requirement") != original[key]
                or row.get("status") != "unknown" or verification is None
                or not isinstance(text, str) or not 0 < len(text) <= MAX_CLAIM_TEXT
                or len(slots) >= capacity):
            continue
        path = f"final_recommendation.requirement_assessments[{index}].explanation"
        checks = [check for check in verification.checks if check.claim_path == path]
        claims, overflow = _extract_claims({"requirement_assessments": [{"explanation": text}]})
        if (overflow or any(check.claim_path == "final_recommendation" for check in verification.checks)
                or not checks or Counter((c.text, c.source_title) for c in claims)
                != Counter((c.claim_text, c.source_title) for c in checks)
                or any((c.status.value, c.reason.value) not in {
                    ("verified", "lexical_support"), ("unknown", "network_uncertain"),
                } or (c.source_title, c.canonical_url) not in by_source for c in checks)):
            continue
        slots[f"R{index + 1}"] = {"index": index, "requirement": original[key],
                                   "text": _strip_citations(text),
                                   "fact_ids": list(dict.fromkeys(by_source[(c.source_title, c.canonical_url)] for c in checks))}
    return slots, submitted


def _apply_provisional(result, context, response):
    from .decision_analysis import _text
    rows = response.get("provisional_reviews") if isinstance(response, dict) else None
    valid = isinstance(rows, list) and len(rows) <= MAX_ANALYSES
    rows = rows if valid else []
    counts = Counter(row.get("analysis_id") for row in rows if isinstance(row, dict) and isinstance(row.get("analysis_id"), str))
    indexed = {row["analysis_id"]: row for row in rows if isinstance(row, dict)
               and isinstance(row.get("analysis_id"), str) and counts[row["analysis_id"]] == 1}
    foreign = any(not isinstance(row, dict) or not isinstance(row.get("analysis_id"), str)
                  or row["analysis_id"] not in context.provisional_slots for row in rows)
    assessments = result.get("requirement_assessments", [])
    assessments = assessments if isinstance(assessments, list) else []
    for assessment in assessments:
        if isinstance(assessment, dict) and assessment.pop("provisional_explanation", None):
            assessment["provisional_review_status"] = "withheld"
    retained, revised, reviewed = 0, 0, 0
    for key, slot in context.provisional_slots.items():
        row = indexed.get(key)
        if row is None:
            continue
        action = row.get("action")
        if action == "withdraw" and set(row) == {"analysis_id", "action"}:
            reviewed += 1
            continue
        if not isinstance(action, str) or action not in {"keep", "revise"}:
            continue
        fields = {"analysis_id", "action", "source_checks"} | ({"text"} if action == "revise" else set())
        if set(row) != fields or not _challenge_valid(row, context.facts):
            continue
        text = _text(row.get("text") if action == "revise" else slot["text"], 200 if action == "revise" else 500)
        if not text or not _candidate_attribution(text, slot["fact_ids"], context):
            continue
        assessments[slot["index"]].update(provisional_explanation=text,
                                         provisional_review_status="human_review_required",
                                         provisional_fact_ids=slot["fact_ids"])
        retained += 1
        revised += action == "revise"
        reviewed += 1
    if context.provisional_submitted:
        result["provisional_review"] = {
            "status": "unavailable" if response is None else "complete" if valid and not foreign and reviewed == context.provisional_submitted else "incomplete",
            "submitted": context.provisional_submitted, "reviewed": reviewed,
            "retained": retained, "revised": revised, "withdrawn": context.provisional_submitted - retained,
        }
