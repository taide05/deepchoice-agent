"""Human-reviewed inference, kept separate from verified source text and authority.

Bindings establish provenance only. They never prove the reasoning, assumptions,
user fit, or proposed design, and never authorize operations.
"""
from copy import deepcopy
import re

MAX_ANALYSES = 8
KINDS = frozenset({"choice", "answer", "design"})


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        return ""
    # Provenance and links are supplied by the runtime, never by model prose.
    if re.search(r"https?://|\[\[|\[source\s*:", value, re.I):
        return ""
    return " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", value).split())


def _refs(value, allowed):
    if not isinstance(value, list) or not 0 < len(value) <= 4:
        return []
    if any(not isinstance(item, str) or item not in allowed for item in value):
        return []
    if len(set(value)) != len(value):
        return []
    return value


def original_analysis_requirements(requirements, query=""):
    """The same original-request inventory for binding and correction feedback."""
    original = {
        row["id"]: row["requirement"] for row in requirements
        if row.get("kind") in {"frozen_constraint", "scene_requirement", "scene_preference", "frozen_sub_question"}
    }
    if isinstance(query, str) and query.strip():
        original["R0"] = query
    return original


def bind_decision_analysis(recommendation, requirements, candidates, query="", *, diagnostics=None):
    """Rebuild model output from original C/Q requirements and bound fact IDs.

    This first pass does not grant display permission. Citation calibration must
    subsequently establish complete source-text support in this same pass.
    """
    result = deepcopy(recommendation)
    raw = result.pop("decision_analysis", None)
    counts = {"provided": "decision_analysis" in recommendation,
              "received": len(raw) if isinstance(raw, list) else None,
              "retained": 0, "rejected": {}}
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(counts)
        counts = diagnostics

    def reject(reason):
        counts["rejected"][reason] = counts["rejected"].get(reason, 0) + 1

    if raw is None:
        return result
    result["decision_analysis"] = []
    if not isinstance(raw, list) or len(raw) > MAX_ANALYSES:
        reject("invalid_list" if not isinstance(raw, list) else "item_limit")
        return result
    original = original_analysis_requirements(requirements, query)
    facts = {row["id"] for row in result.get("source_facts", [])}
    options = {value for value in candidates if isinstance(value, str)} if isinstance(candidates, list) else set()
    for item in raw:
        if (not isinstance(item, dict) or not isinstance(item.get("kind"), str)
                or item["kind"] not in KINDS):
            reject("invalid_kind")
            continue
        option = item.get("option", "")
        if (not isinstance(option, str) or (option and option not in options)
                or (item["kind"] == "choice" and not option)):
            reject("invalid_option")
            continue
        fact_ids = _refs(item.get("fact_ids"), facts)
        requirement_ids = _refs(item.get("requirement_ids"), original)
        if not fact_ids or not requirement_ids:
            reject("invalid_fact_ids" if not fact_ids else "invalid_requirement_ids")
            continue
        reasoning = _text(item.get("reasoning"), 1500)
        change_condition = _text(item.get("change_condition"), 600)
        raw_assumptions = item.get("assumptions")
        if not isinstance(raw_assumptions, list) or not 0 < len(raw_assumptions) <= 4:
            reject("invalid_assumptions")
            continue
        assumptions = [_text(value, 300) for value in raw_assumptions]
        if not (reasoning and change_condition and all(assumptions)):
            reject("invalid_prose")
            continue
        result["decision_analysis"].append({
            "kind": item["kind"], "option": option,
            "fact_ids": fact_ids, "requirement_ids": requirement_ids,
            "requirements": [original[key] for key in requirement_ids],
            "reasoning": reasoning, "assumptions": assumptions,
            "change_condition": change_condition, "review_status": "not_checked",
        })
        counts["retained"] += 1
    return result


def inspect_synthesis_bindings(recommendation, chains, requirements, candidates, query=""):
    """Bind once and report only structural losses, never semantic satisfaction.

    Missing optional projections and explicit empty lists are valid. The binders
    remain the authority for source identity, reference and prose restrictions.
    """
    from .evidence_choices import MAX_SOURCE_FACTS, bind_evidence_choices

    facts = recommendation.get("source_facts", [])
    errors = {}
    bound = bind_evidence_choices(recommendation, chains, candidates, requirements)
    if not isinstance(facts, list):
        errors["facts_invalid_list"] = 1
    elif len(facts) > MAX_SOURCE_FACTS:
        errors["facts_item_limit"] = 1
    elif len(bound.get("source_facts", [])) != len(facts):
        errors["facts_binding_loss"] = len(facts) - len(bound.get("source_facts", []))
    analysis = {}
    bound = bind_decision_analysis(bound, requirements, candidates, query, diagnostics=analysis)
    if "decision_analysis" in recommendation and recommendation["decision_analysis"] is None:
        errors["analysis_invalid_list"] = 1
    for reason, count in analysis["rejected"].items():
        # One invalid factual projection can invalidate every dependent analysis.
        if reason != "invalid_fact_ids" or not any(key.startswith("facts_") for key in errors):
            errors["analysis_" + reason] = count
    return bound, {
        "source_facts_received": len(facts) if isinstance(facts, list) else None,
        "source_facts_bound": len(bound.get("source_facts", [])),
        "analysis_binding": analysis,
        "errors": errors,
    }


def calibrate_decision_analysis(recommendation):
    """Permit review only against facts calibrated by this citation pass.

    No inference is assigned a citation status. Even a completely supported
    source does not verify the model's translation, application or design.
    """
    if "decision_analysis" not in recommendation:
        return recommendation
    facts = {row["id"]: row for row in recommendation.get("source_facts", [])}
    accepted = []
    for item in recommendation["decision_analysis"]:
        if item["fact_ids"] and all(facts[key]["status"] == "verified" for key in item["fact_ids"]):
            item["review_status"] = "human_review_required"
            accepted.append(item)
    recommendation["decision_analysis"] = accepted
    return recommendation
