"""Human-reviewed inference, kept separate from verified source text and authority.

Bindings establish provenance only. They never prove the reasoning, assumptions,
user fit, or proposed design, and never authorize operations.
"""
from collections import Counter
from copy import deepcopy
import re

MAX_ANALYSES = 8
MAX_ROW_BASIS_FACTS = 4
MAX_ROW_BASIS_REFS = 12
KINDS = frozenset({"choice", "answer", "design"})


# The original predicate. It matches an unbalanced marker too, because a
# malformed citation attempt must not survive into displayed prose merely
# because it never closed.
_REFERENCE_MARKER = re.compile(r"https?://|\[\[|\[source\s*:", re.I)


def _prose_state(value, limit) -> tuple[str, str | None]:
    """Return model prose and its fixed state, or empty text with a category.

    Prose is accepted whole or not at all. It is never truncated: a prefix cut
    can remove a trailing condition, negation or scope limit and leave a claim
    that asserts MORE than the model wrote. An unusable field therefore rejects
    its own row instead of being bounded, which is the same rule applied to a
    revision.
    """
    if not isinstance(value, str):
        return "", "prose_type"
    if _REFERENCE_MARKER.search(value):
        # Model prose may not carry its own provenance; the runtime supplies it.
        return "", "prose_reference"
    compact = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", value).split())
    if not compact:
        return "", "prose_empty"
    if len(compact) > limit:
        return "", "prose_length"
    return compact, None


# Retained name for callers that only need the text.
def _text(value, limit):
    text, _note = _prose_state(value, limit)
    return text


def _refs(value, allowed, limit: int = 4):
    """Keep the addressed references, in order, up to `limit`.

    A non-string, unknown or duplicated address is an invalid address set and
    fails its own row. A list longer than the documented limit is rejected
    rather than trimmed: the excess addresses belong to premises the row
    addressed, and dropping them would leave the row asserting those premises
    with nothing behind them.
    """
    if not isinstance(value, list) or not 0 < len(value) <= limit:
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

    if not isinstance(raw, list) or not 0 < len(raw):
        return None, "basis_missing_or_invalid"
    selected = []
    seen = {}
    reference_count = 0
    for item in raw:
        if not isinstance(item, dict):
            return None, "basis_invalid_item"
        key = item.get("fact_id")
        if not isinstance(key, str) or key not in facts:
            return None, "basis_invalid_fact"
        if key not in seen and len(selected) >= MAX_ROW_BASIS_FACTS:
            # More distinct facts than one row may carry. Dropping the excess
            # would remove whatever premises those coordinates were the only
            # support for while the row and its conclusion were still published,
            # so the row is rejected instead of silently losing support.
            return None, "basis_fact_limit"
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
        if key in seen:
            # The same fact addressed twice is one coordinate, not a fifth fact,
            # so the row keeps its basis instead of being discarded whole.
            merged = seen[key]
            merged["sentence_ids"].extend(
                index for index in indexes if index not in merged["sentence_ids"])
            merged["source_sentences"].extend(
                sentence for sentence in source_sentences
                if sentence not in merged["source_sentences"])
            continue
        seen[key] = {"fact_id": key, "sentence_ids": list(indexes),
                     "source_sentences": source_sentences}
        selected.append(seen[key])
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
    if not isinstance(raw, list):
        reject("invalid_list")
        return result
    if len(raw) > MAX_ANALYSES:
        # A response over the row budget is a capacity overrun, not a malformed
        # response. Keep the addressed rows in request order and drop only the
        # excess, so one extra row cannot discard every independent valid row.
        counts["dropped_item_limit"] = len(raw) - MAX_ANALYSES
        raw = raw[:MAX_ANALYSES]
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
        reasoning, reasoning_note = _prose_state(item.get("reasoning"), 1500)
        change_condition, change_note = _prose_state(item.get("change_condition"), 600)
        # An answer with no reasoning or no change condition has no verifiable
        # conclusion to present, so only that row is rejected, with the fixed
        # category that explains which part was unusable.
        if not reasoning:
            reject(reasoning_note or "prose_empty")
            continue
        if not change_condition:
            reject(change_note or "prose_empty")
            continue
        raw_assumptions = item.get("assumptions")
        if not isinstance(raw_assumptions, list):
            reject("invalid_assumptions")
            continue
        assumptions, assumption_note = [], None
        if len(raw_assumptions) > 4:
            # More premises than one row may carry: keep the leading premises the
            # row was built on and drop the excess, not the whole row. This is a
            # capacity trim of extra items, not a rewrite of any premise kept.
            assumption_note = "assumptions_trimmed"
        unusable = None
        for value in raw_assumptions[:4]:
            text, note = _prose_state(value, 300)
            if not text:
                # A premise that cannot be used whole would make the row's stated
                # premises untrue, so only this row is rejected.
                unusable = note or "prose_empty"
                break
            assumptions.append(text)
        if unusable is not None:
            reject(unusable)
            continue
        row = {
            "kind": item["kind"], "option": option,
            "fact_ids": fact_ids, "requirement_ids": requirement_ids,
            "requirements": [original[key] for key in requirement_ids],
            "reasoning": reasoning, "assumptions": assumptions,
            "change_condition": change_condition, "review_status": "not_checked",
        }
        # Only one fixed capacity-trim marker exists, and only it may be
        # inherited. Arbitrary model strings must never reach this field because
        # it is published in the public snapshot.
        degraded = [assumption_note] if assumption_note == "assumptions_trimmed" else []
        if item.get("prose_degraded") == ["assumptions_trimmed"] and not degraded:
            degraded = ["assumptions_trimmed"]
        if degraded:
            # Fixed categories only; the row still needs review before display.
            row["prose_degraded"] = sorted(set(degraded))
        if basis is not None:
            row["basis"] = basis
        result["decision_analysis"].append(row)
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
    rejections = analysis["rejected"]
    if analysis.get("dropped_item_limit"):
        # A dropped over-limit row is a capacity event the caller must see, not
        # a silent loss: the model addressed more rows than can be carried.
        errors["analysis_dropped_item_limit"] = analysis["dropped_item_limit"]
    for reason, count in rejections.items():
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
    if any(key in diagnostic["errors"]
           for key in ("analysis_invalid_list", "analysis_dropped_item_limit")):
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


def calibration_rejection_reason(item, facts) -> str | None:
    """Return one fixed category for a row this calibration pass will drop.

    This explains a deletion that is otherwise invisible: a row removed here
    leaves no trace in any public artefact. The categories are fixed strings so
    they are safe to record where model prose, source text and raw exceptions
    are not. Returns None when the row is accepted.
    """
    if not item.get("fact_ids"):
        return "no_fact_reference"
    for key in item["fact_ids"]:
        fact = facts.get(key)
        if fact is None:
            return "addressed_fact_absent"
        basis = item.get("basis")
        addressed = {row["fact_id"]: row for row in basis} if isinstance(basis, list) else {}
        if not reviewable_source_fact(fact) and not (
            sentence_scoped_source_fact(fact)
            and isinstance(addressed.get(key), dict)
            and analysis_fact_reviewable(fact, addressed.get(key))
        ):
            return f"fact_not_reviewable:{fact.get('status', 'unknown')}"
    return None


def calibrate_decision_analysis(recommendation, diagnostics: dict | None = None):
    """Permit review only against facts calibrated by this citation pass.

    Network-only uncertainty grants pending review, never display or authority.

    No inference is assigned a citation status. Even a completely supported
    source does not verify the model's translation, application or design.
    """
    if "decision_analysis" not in recommendation:
        return recommendation
    facts = {row["id"]: row for row in recommendation.get("source_facts", [])}
    accepted = []
    dropped: Counter = Counter()
    for item in recommendation["decision_analysis"]:
        reason = calibration_rejection_reason(item, facts)
        if reason is not None:
            dropped[reason] += 1
            continue
        item["review_status"] = (
            "sentence_scoped_pending_review" if any(
                sentence_scoped_source_fact(facts[key]) for key in item["fact_ids"]
            ) else "human_review_required" if all(
                facts[key]["status"] == "verified" for key in item["fact_ids"]
            ) else "network_unconfirmed_pending_review"
        )
        accepted.append(item)
    if diagnostics is not None:
        diagnostics["rows_received"] = len(recommendation["decision_analysis"])
        diagnostics["rows_accepted"] = len(accepted)
        diagnostics["rows_dropped"] = dict(sorted(dropped.items()))
    recommendation["decision_analysis"] = accepted
    return recommendation
