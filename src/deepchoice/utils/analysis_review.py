"""Apply bounded model review edits to runtime-owned analysis slots only.

A model review is a second inference, never semantic verification or authority.
"""
from collections import Counter
import json
from copy import deepcopy
from dataclasses import dataclass, field

from .decision_analysis import (
    MAX_ANALYSES, MAX_ROW_BASIS_REFS, bind_decision_analysis,
    calibrate_decision_analysis, reviewable_source_fact, sentence_scoped_source_fact,
)
from .evidence import candidate_product_mentions, candidate_search_name
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
    source_contexts: dict = field(default_factory=dict)


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
        if (not isinstance(fact, dict)
                or not (reviewable_source_fact(fact) or sentence_scoped_source_fact(fact))):
            continue
        bound = bound_facts.get(fact.get("id"))
        if (verification is None or not bound
                or not (reviewable_source_fact(bound) or sentence_scoped_source_fact(bound))
                or fact.get("status") != bound.get("status")
                or fact.get("review_availability") != bound.get("review_availability")
                or fact.get("reviewable_sentence_ids") != bound.get("reviewable_sentence_ids")):
            continue
        if bound and all(fact.get(key) == bound.get(key) for key in (
            "id", "evidence_id", "source_title", "canonical_url", "saved_text", "text",
            "saved_passages", "source_ranges",
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
        recommendation, verification, [fact for fact in facts if reviewable_source_fact(fact)],
        requirements, query, MAX_ANALYSES - len(slots),
    )
    from .fact_selection import original_fact_contexts
    return AnalysisReviewContext(recommendation, slots, facts, requirements, candidates, query,
                                 submitted, provisional_slots, provisional_submitted,
                                 source_contexts=original_fact_contexts(facts, state.get("evidence_chains", [])))


def analysis_review_input(context: AnalysisReviewContext) -> dict:
    return {
        "original_saved_contexts": context.source_contexts,
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
            key: fact.get(key) for key in ("id", "source_title", "saved_text", "status", "review_availability", "reviewable_sentence_ids")
        } | {"sentences": _sentences(fact)} for fact in context.facts],
    }


_REVIEW_ACTIONS = frozenset({"keep", "revise", "withdraw"})


def _revision_text_error(row) -> str | None:
    """Return the fixed category that makes a revised row unusable, else None.

    A revision is only accepted when every rewritten field is usable as it
    stands: the runtime never truncates or rewrites a revision to make it fit,
    because a trimmed conclusion or a stripped citation would misrepresent what
    the reviewer approved.
    """
    from .decision_analysis import _bounded_prose

    for name, limit in (("reasoning", 1500), ("change_condition", 600)):
        if name not in row:
            continue
        text, note = _bounded_prose(row.get(name), limit)
        if not text or note:
            return note or "prose_empty"
    assumptions = row.get("assumptions")
    if isinstance(assumptions, list):
        for value in assumptions:
            text, note = _bounded_prose(value, 300)
            if not text or note:
                return note or "prose_empty"
    return None


def _review_row_shape_category(row, facts, original=None, context=None) -> str | None:
    """Return one fixed rejection category for a malformed row, else None.

    This judges the row's own structure only. Whether the row addresses a slot
    in this review is decided by the caller, because a well-formed row for an
    unknown slot must not invalidate the rows that do address this review.
    """
    if not isinstance(row, dict) or not isinstance(row.get("analysis_id"), str):
        return "row_shape"
    action = row.get("action")
    if not isinstance(action, str) or action not in _REVIEW_ACTIONS:
        return "action_shape"
    required = {"analysis_id", "action"} if action == "withdraw" else {
        "analysis_id", "action", "source_checks"}
    if not required.issubset(row):
        return "fields_shape"
    if action != "withdraw" and not _challenge_valid(row, facts, sentence_limit=MAX_ROW_BASIS_REFS):
        return "source_checks"
    if action == "revise":
        error = _revision_text_error(row)
        if error:
            return error
        if original is not None:
            # A revision rewrites prose only. It may not move the slot to another
            # option or drop its existing basis: those decide what the published
            # answer is about, and only the original binding owns them.
            if "option" in row and row.get("option") != original.get("option"):
                return "revise_option_change"
            if "basis" in row:
                return "revise_basis_change"
            # A revision may not introduce a candidate that its own basis
            # (together with any additional basis it appends) does not cover.
            if context is not None:
                prose = [row.get("reasoning"), row.get("change_condition")]
                if isinstance(row.get("assumptions"), list):
                    prose.extend(row["assumptions"])
                covered = list(original.get("fact_ids") or [])
                additions = row.get("additional_basis")
                if isinstance(additions, list):
                    covered.extend(
                        item.get("fact_id") for item in additions
                        if isinstance(item, dict) and isinstance(item.get("fact_id"), str))
                if not _candidate_attribution(
                    " ".join(value for value in prose if isinstance(value, str)), covered, context,
                ):
                    return "candidate_attribution"
    return None


def _indexed_review_rows(rows, facts, slots=None, context=None) -> tuple[dict, Counter]:
    """Index structurally valid rows by slot, counting fixed rejections."""
    rejections: Counter = Counter()
    valid = []
    slots = slots if isinstance(slots, dict) else {}
    for row in rows:
        original = None
        if isinstance(row, dict):
            key = row.get("analysis_id")
            if isinstance(key, str):
                original = slots.get(key)
        category = _review_row_shape_category(row, facts, original=original, context=context)
        if category is not None:
            # Fixed category only; never the model's text.
            rejections[category] += 1
            continue
        valid.append(row)
    counts = Counter(row["analysis_id"] for row in valid)
    indexed = {}
    for row in valid:
        key = row["analysis_id"]
        if counts[key] != 1:
            rejections["duplicate_analysis_id"] += 1
            continue
        indexed[key] = row
    return indexed, rejections


def apply_analysis_review(context: AnalysisReviewContext, response: dict | None) -> tuple[dict, dict]:
    result = deepcopy(context.recommendation)
    rows = response.get("analysis_reviews") if isinstance(response, dict) else None
    valid_list = isinstance(rows, list)
    rows = rows if valid_list else []
    indexed, rejections = _indexed_review_rows(rows, context.facts, context.slots, context)
    kept, revised, reviewed = [], 0, 0
    for key, original in context.slots.items():
        row = indexed.get(key)
        if row is None:
            continue
        # The response carried a row for this slot, so the reviewer adjudicated
        # it even when a later gate rejects the row itself. Only a slot the
        # response never contained counts as unaddressed.
        reviewed += 1
        action = row["action"]
        if action == "withdraw":
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
                part["fact_id"] not in challenges
                or challenges[part["fact_id"]][1] not in {"qualifies", "conflicts"}
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
        elif accepted[0]["review_status"] == "sentence_scoped_pending_review":
            accepted[0]["review_status"] = "sentence_scoped_human_review_required"
        kept.append(accepted[0])
        revised += action == "revise"
    if context.submitted:
        result["decision_analysis"] = kept
    status = ("unavailable" if response is None else
              "complete" if valid_list and reviewed == context.submitted else "incomplete")
    summary = {"status": status, "submitted": context.submitted, "reviewed": reviewed,
               "retained": len(kept), "revised": revised, "withdrawn": context.submitted - len(kept),
               "unaddressed": context.submitted - reviewed}
    if rejections:
        summary["row_rejections"] = dict(sorted(rejections.items()))
    if context.submitted:
        result["analysis_review"] = summary
    _apply_provisional(result, context, response)
    return result, summary


def _sentences(fact):
    from ..citations.verifier import _split_sentences
    return [{"sentence_id": index, "text": text}
            for index, text in enumerate(_split_sentences(fact["saved_text"]), 1)]


def _challenge_valid(row, facts, *, sentence_limit: int = 3):
    """Enforce complete addressed review, not the truth of model stances.

    A decision analysis addresses up to `MAX_ROW_BASIS_REFS` sentences per fact,
    while a provisional requirement explanation keeps the tighter review bound.
    """
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
                or not isinstance(ids, list) or len(ids) > sentence_limit
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
    Use the same literal product identity as source admission, preserving action
    labels for display. This does not establish entailment or infer product aliases.
    """
    if not isinstance(text, str):
        return False
    source = " ".join(fact["source_title"] + " " + fact["saved_text"]
                      for fact in context.facts if fact["id"] in fact_ids)
    text, source = text.casefold(), source.casefold()
    for candidate in context.candidates if isinstance(context.candidates, list) else []:
        if isinstance(candidate, str) and candidate.strip() and candidate_search_name(candidate) is None:
            # Action-only/nested labels cannot gain a product identity from a source.
            if " ".join(candidate.casefold().split()) in " ".join(text.split()):
                return False
    return candidate_product_mentions(text, context.candidates) <= candidate_product_mentions(source, context.candidates)



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
    from .decision_analysis import _bounded_prose
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
        text, _note = _bounded_prose(
            row.get("text") if action == "revise" else slot["text"],
            200 if action == "revise" else 500,
        )
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
            "unaddressed": context.provisional_submitted - reviewed,
        }
