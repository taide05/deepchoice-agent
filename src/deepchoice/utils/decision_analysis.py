"""Human-reviewed inference, kept separate from verified source text and authority.

Bindings establish provenance only. They never prove the reasoning, assumptions,
user fit, or proposed design, and never authorize operations.
"""
from copy import deepcopy
import re

MAX_ANALYSES = 8
MAX_ROW_BASIS_FACTS = 4
MAX_ROW_BASIS_REFS = 12
KINDS = frozenset({"choice", "answer", "design"})


def _prose_error(value, limit):
    if not isinstance(value, str):
        return "prose_type"
    if len(value) > limit:
        return "prose_length"
    if re.search(r"https?://|\[\[|\[source\s*:", value, re.I):
        return "prose_reference"
    if not " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", value).split()):
        return "prose_empty"
    return None


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


def bind_analysis_basis(raw, facts):
    """Copy addressed full saved sentences; never label an inference verified."""
    from ..citations.verifier import _split_sentences

    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_ROW_BASIS_FACTS:
        return None, "basis_missing_or_invalid"
    selected = []
    seen = set()
    reference_count = 0
    for item in raw:
        if not isinstance(item, dict):
            return None, "basis_invalid_item"
        key = item.get("fact_id")
        if not isinstance(key, str) or key not in facts or key in seen:
            return None, "basis_invalid_fact"
        text = facts[key].get("saved_text")
        if not isinstance(text, str) or not text:
            return None, "basis_invalid_fact"
        sentences = _split_sentences(text)
        indexes = item.get("sentence_ids")
        if (not isinstance(indexes, list) or not 0 < len(indexes) <= MAX_ROW_BASIS_REFS
                or any(type(index) is not int or not 1 <= index <= len(sentences) for index in indexes)
                or len(set(indexes)) != len(indexes)):
            return None, "basis_invalid_sentences"
        reference_count += len(indexes)
        if reference_count > MAX_ROW_BASIS_REFS:
            return None, "basis_invalid_sentences"
        source_sentences = [sentences[index - 1] for index in indexes]
        # Saved projections can outlive a sentence policy. Never reinterpret
        # their old numeric addresses as a different quotation during rendering.
        if "source_sentences" in item and item["source_sentences"] != source_sentences:
            return None, "basis_source_sentences_mismatch"
        seen.add(key)
        selected.append({"fact_id": key, "sentence_ids": list(indexes),
                         "source_sentences": source_sentences})
    return selected, None


def bind_decision_analysis(recommendation, requirements, candidates, query="", *, diagnostics=None, require_basis=False):
    """Rebuild model output from original C/Q requirements and bound fact IDs.

    This first pass does not grant display permission. Citation calibration and
    review eligibility are evaluated separately in this same pass.
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
    facts = {row["id"]: row for row in result.get("source_facts", [])}
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
        basis = None
        if require_basis or "basis" in item:
            basis, reason = bind_analysis_basis(item.get("basis"), facts)
            if reason:
                reject(reason)
                continue
            fact_ids = [row["fact_id"] for row in basis]
        else:
            # Historical projections remain readable; current synthesis always
            # requires explicit basis and never takes this compatibility path.
            fact_ids = _refs(item.get("fact_ids"), facts)
        requirement_ids = _refs(item.get("requirement_ids"), original)
        if not fact_ids or not requirement_ids:
            reject("invalid_fact_ids" if not fact_ids else "invalid_requirement_ids")
            continue
        reasoning = _text(item.get("reasoning"), 1500)
        change_condition = _text(item.get("change_condition"), 600)
        raw_assumptions = item.get("assumptions")
        if not isinstance(raw_assumptions, list) or len(raw_assumptions) > 4:
            reject("invalid_assumptions")
            continue
        assumptions = [_text(value, 300) for value in raw_assumptions]
        if not (reasoning and change_condition and all(assumptions)):
            errors = [_prose_error(item.get("reasoning"), 1500),
                      _prose_error(item.get("change_condition"), 600)]
            errors.extend(_prose_error(value, 300) for value in raw_assumptions)
            # Exactly one fixed category per rejected analysis, never model text.
            reject(next(error for error in errors if error))
            continue
        result["decision_analysis"].append({
            "kind": item["kind"], "option": option,
            "fact_ids": fact_ids, "requirement_ids": requirement_ids,
            "requirements": [original[key] for key in requirement_ids],
            "reasoning": reasoning, "assumptions": assumptions,
            "change_condition": change_condition, "review_status": "not_checked",
        })
        if basis is not None:
            result["decision_analysis"][-1]["basis"] = basis
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
    bound = bind_decision_analysis(bound, requirements, candidates, query, diagnostics=analysis, require_basis=True)
    if "decision_analysis" in recommendation and recommendation["decision_analysis"] is None:
        errors["analysis_invalid_list"] = 1
    for reason, count in analysis["rejected"].items():
        # One invalid factual projection can invalidate every dependent analysis.
        if reason not in {"invalid_fact_ids", "basis_invalid_fact"} or not any(key.startswith("facts_") for key in errors):
            errors["analysis_" + reason] = count
    return bound, {
        "source_facts_received": len(facts) if isinstance(facts, list) else None,
        "source_facts_bound": len(bound.get("source_facts", [])),
        "analysis_binding": analysis,
        "errors": errors,
    }


def reviewable_source_fact(fact):
    return fact.get("status") == "verified" or (
        fact.get("status") == "unknown"
        and fact.get("review_availability") == "network_unconfirmed"
    )


def sentence_scoped_source_fact(fact):
    from ..citations.verifier import MAX_FIELD_SENTENCES

    indexes = fact.get("reviewable_sentence_ids")
    return (fact.get("status") == "unknown"
            and fact.get("review_availability") == "sentence_scoped"
            and isinstance(indexes, list) and bool(indexes)
            and all(type(index) is int and 1 <= index <= MAX_FIELD_SENTENCES for index in indexes)
            and len(set(indexes)) == len(indexes))


def analysis_fact_reviewable(fact, basis):
    if reviewable_source_fact(fact):
        return True
    return (sentence_scoped_source_fact(fact) and isinstance(basis, dict)
            and isinstance(basis.get("sentence_ids"), list)
            and bool(basis["sentence_ids"])
            and all(type(index) is int for index in basis["sentence_ids"])
            and set(basis["sentence_ids"]) <= set(fact["reviewable_sentence_ids"]))


def prefer_corrected_projection(original, corrected, diagnostic, *, require_gain=True):
    """Choose one independently bound response; never splice model generations."""
    allowed = {"facts_binding_loss"}
    if any(key not in allowed and not key.startswith("analysis_") for key in diagnostic["errors"]):
        return False
    if any(key in diagnostic["errors"] for key in ("analysis_invalid_list", "analysis_item_limit")):
        return False
    def coverage(value):
        return {(row["kind"], row["option"], requirement)
                for row in value.get("decision_analysis", [])
                for requirement in row["requirement_ids"]}
    before, after = coverage(original), coverage(corrected)
    def addressed(value):
        facts = {f["id"]: f for f in value.get("source_facts", [])}
        return {(row["kind"], row["option"], req,
                 facts[b["fact_id"]]["canonical_url"], facts[b["fact_id"]]["saved_text"], tuple(b["sentence_ids"]))
                for row in value.get("decision_analysis", []) for req in row["requirement_ids"]
                for b in row.get("basis", [])}
    sources = lambda value: {(f["source_title"], f["canonical_url"], f["saved_text"])
                             for f in value.get("source_facts", [])}
    statuses = lambda value: {row.get("id"): row.get("status")
                              for row in value.get("requirement_assessments", [])
                              if isinstance(row, dict) and isinstance(row.get("id"), str)}
    previous_statuses = statuses(original)
    no_upgrade = all(status == "unknown" or previous_statuses.get(key) == status
                     for key, status in statuses(corrected).items())
    gains = (before < after and len(corrected.get("decision_analysis", [])) > len(original.get("decision_analysis", [])))
    return (before <= after and (gains or not require_gain) and addressed(original) <= addressed(corrected)
            and sources(original) <= sources(corrected)
            and original.get("winner") == corrected.get("winner") == "context_dependent"
            and not corrected.get("ranked_options") and no_upgrade)


def _declared_sentence_ids(part):
    """Read a basis part's declared sentence ids defensively.

    A non-list value is unaddressable rather than fatal; the sentence-address
    binder rejects it independently.
    """
    declared = part.get("sentence_ids") if isinstance(part, dict) else None
    return declared if isinstance(declared, list) else []


def _reviewable_basis(item, facts):
    """Keep only the basis an analysis may be reviewed against.

    A citation pass can verify a narrower part of a source than synthesis saw:
    ``sentence_scoped`` marks which sentences were uniquely verified. An analysis
    that also addressed an unverified sentence still has usable, reviewable
    support, so the unverified part is dropped instead of discarding the whole
    analysis. Returns (basis or None, dropped sentence ids).
    """
    basis = item.get("basis")
    kept, dropped = [], []
    for part in basis if isinstance(basis, list) else []:
        declared = _declared_sentence_ids(part)
        key = part.get("fact_id") if isinstance(part, dict) else None
        fact = facts.get(key)
        if fact is None:
            dropped.extend(declared)
            continue
        if reviewable_source_fact(fact):
            kept.append(part)
            continue
        if not sentence_scoped_source_fact(fact):
            dropped.extend(declared)
            continue
        sentences = part.get("source_sentences")
        # The addressed quotations must line up one-to-one with the declared
        # sentences. A part that cannot be trimmed consistently is dropped whole
        # so a surviving basis never carries a quotation it cannot vouch for.
        if isinstance(sentences, list) and len(sentences) != len(declared):
            dropped.extend(declared)
            continue
        allowed = set(fact["reviewable_sentence_ids"])
        addressed = [index for index in declared if index in allowed]
        dropped.extend(index for index in declared if index not in allowed)
        if not addressed:
            continue
        trimmed = dict(part)
        trimmed["sentence_ids"] = addressed
        if isinstance(sentences, list):
            positions = {index: offset for offset, index in enumerate(declared)}
            trimmed["source_sentences"] = [sentences[positions[index]] for index in addressed]
        kept.append(trimmed)
    return (kept or None), dropped


def calibrate_decision_analysis(recommendation):
    """Permit review only against facts calibrated by this citation pass.

    Network-only uncertainty grants pending review, never display or authority.

    No inference is assigned a citation status. Even a completely supported
    source does not verify the model's translation, application or design.
    """
    if "decision_analysis" not in recommendation:
        return recommendation
    facts = {row["id"]: row for row in recommendation.get("source_facts", [])}
    accepted = []
    dropped_sentences = 0
    dropped_analyses = 0
    for item in recommendation["decision_analysis"]:
        basis, dropped = _reviewable_basis(item, facts)
        dropped_sentences += len(dropped)
        if not basis:
            dropped_analyses += 1
            continue
        item["basis"] = basis
        item["fact_ids"] = [part["fact_id"] for part in basis]
        item["review_status"] = (
            "sentence_scoped_pending_review" if any(
                sentence_scoped_source_fact(facts[key]) for key in item["fact_ids"]
            ) else "human_review_required" if all(
                facts[key]["status"] == "verified" for key in item["fact_ids"]
            ) else "network_unconfirmed_pending_review"
        )
        accepted.append(item)
    recommendation["decision_analysis"] = accepted
    # Content removed for reviewability must stay observable instead of vanishing.
    if dropped_sentences or dropped_analyses:
        recommendation["analysis_calibration"] = {
            "basis_sentences_dropped": dropped_sentences,
            "analyses_dropped": dropped_analyses,
            "retained": len(accepted),
        }
    return recommendation
