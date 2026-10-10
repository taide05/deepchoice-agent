"""Bounded conditional choices grounded in runtime-owned saved source text.

Bindings and lexical support are not proof of applicability or sound reasoning.
These projections never grant winner, requirement, or operational authority.
"""
from collections import Counter
from copy import deepcopy
import re

from .citation_markers import citation_spans, marker_titles
from .evidence import conclusion_source_allowed, is_navigation_placeholder

MAX_SOURCE_FACTS = 5
MAX_CONDITIONAL_CHOICES = 4
MAX_SOURCE_TEXT = 1200
RELATIONS = frozenset({"consider", "prefer", "insufficient_alone"})


def _ids(value, allowed):
    if not isinstance(value, list) or not 0 < len(value) <= 8:
        return []
    if any(not isinstance(item, str) or item not in allowed for item in value):
        return []
    return list(dict.fromkeys(value))


def whole_source_text(snippet):
    """Return a complete verifiable-sized snippet, never a truncated qualifier."""
    from ..citations.verifier import MAX_CLAIM_TEXT, MAX_FIELD_SENTENCES, _split_sentences

    if not isinstance(snippet, str) or is_navigation_placeholder(snippet):
        return ""
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", snippet).split())
    if not text or len(text) > MAX_SOURCE_TEXT or "[source:" in text.casefold() or "[[" in text:
        return ""
    sentences = _split_sentences(text)
    if len(sentences) > MAX_FIELD_SENTENCES or any(len(row) > MAX_CLAIM_TEXT for row in sentences):
        return ""
    return text


def bounded_source_passages(source):
    """Return complete bounded passages from one source, or None if malformed.

    An absent field retains the historical single-snippet path. The ordered
    passages must reproduce the visible snippet exactly after whitespace
    normalization; citation validation later locates each passage on the page.
    """
    if not isinstance(source, dict) or "passages" not in source:
        return ()
    values = source["passages"]
    if not isinstance(values, list) or not 1 <= len(values) <= 3:
        return None
    passages = []
    for value in values:
        clean = whole_source_text(value)
        if not clean or clean[-1] not in ".!?。！？；;" or clean in passages:
            return None
        passages.append(clean)
    aggregate = " ".join(passages)
    if (len(aggregate) > MAX_SOURCE_TEXT
            or whole_source_text(source.get("snippet")) != aggregate):
        return None
    return tuple(passages)


def selected_source_text(source, fact):
    """Re-derive the fact view from original source coordinates, never model text."""
    if "conflict_scope" in source:
        from .conflict_scope import conflict_fact_allowed
        if not conflict_fact_allowed(source, fact.get("source_ranges")):
            return "", None
    if "source_ranges" not in fact:
        return whole_source_text(source.get("snippet")), bounded_source_passages(source)
    from .fact_selection import selected_passages

    passages = selected_passages(source, fact["source_ranges"])
    return (" ".join(passages), passages) if passages else ("", None)


def source_fact_bindings(chains):
    """Index runtime source positions, retaining original source numbers."""
    from ..citations.verifier import _source_registry
    from .conflict_scope import validated_conflict_scope

    registry, _ = _source_registry(chains)
    by_position = {row.position: row for row in registry}
    numbered, number = {}, 0
    for chain_index, chain in enumerate(chains):
        for source_index, source in enumerate(chain.get("sources", [])[:4]):
            number += 1
            if not isinstance(source, dict) or not conclusion_source_allowed(source):
                continue
            if ((chain.get("disputed") or "conflict_scope" in source)
                    and validated_conflict_scope(source) is None):
                continue
            resolved = by_position.get((chain_index, source_index))
            if resolved is None or not resolved.canonical_url:
                continue
            marker = f"[Source: {resolved.title}]"
            spans = citation_spans(marker)
            if (len(spans) != 1 or spans[0][:2] != (0, len(marker))
                    or marker_titles(spans[0][2]) != [resolved.title]):
                continue
            numbered[number] = (source, resolved)
    return numbered


def bind_source_fact(item, binding):
    """Copy one fact from a validated registry entry; caller enforces menu/limits.

    Menu construction and full recommendation binding share this pure operation.
    No model text, status, title or URL can override the registry or saved text.
    """
    from ..citations.verifier import _split_sentences

    source, resolved = binding
    text, passages = selected_source_text(source, item)
    if not text or passages is None:
        return None
    fact = {
        "id": item["id"], "evidence_id": item["evidence_id"],
        "text": " ".join(f"{sentence} [Source: {resolved.title}]" for sentence in _split_sentences(text)),
        "source_title": resolved.title, "canonical_url": resolved.canonical_url,
        "saved_text": text, "status": "unknown",
    }
    if passages:
        fact["saved_passages"] = list(passages)
    if "source_ranges" in item:
        fact["source_ranges"] = deepcopy(item["source_ranges"])
    return fact


def bind_evidence_choices(recommendation, chains, candidates, requirements):
    """Discard model text/status; rebuild from this request and unique sources."""
    result = deepcopy(recommendation)
    raw_facts = result.pop("source_facts", [])
    raw_choices = result.pop("conditional_choices", [])
    if not raw_facts and not raw_choices:
        return result
    result["source_facts"] = []
    result["conditional_choices"] = []
    if not isinstance(raw_facts, list) or len(raw_facts) > MAX_SOURCE_FACTS:
        return result
    numbered = source_fact_bindings(chains)
    seen = set()
    offered = None
    for item in raw_facts:
        if not isinstance(item, dict):
            continue
        identifier, evidence_id = item.get("id"), item.get("evidence_id")
        if (not isinstance(identifier, str) or not re.fullmatch(r"F[1-9]\d?", identifier)
                or identifier in seen or type(evidence_id) is not int
                or evidence_id not in numbered):
            continue
        # A duplicate identifier invalidates the entire factual projection.
        seen.add(identifier)
        fact = bind_source_fact(item, numbered[evidence_id])
        if fact is None:
            continue
        if "source_ranges" in item:
            if offered is None:
                from .fact_selection import admitted_source_ids
                offered = admitted_source_ids(chains, candidates, bindings=numbered)
            if evidence_id not in offered:
                continue
        result["source_facts"].append(fact)
    identifiers = [item.get("id") for item in raw_facts if isinstance(item, dict)]
    if len(identifiers) != len(set(str(item) for item in identifiers)):
        result["source_facts"] = []
        return result
    facts = {item["id"] for item in result["source_facts"]}
    user_requirements = {
        item["id"]: item["requirement"] for item in requirements
        if item.get("kind") in {"frozen_constraint", "scene_requirement", "scene_preference"}
    }
    allowed_options = {
        item for item in candidates if isinstance(item, str) and 0 < len(item) <= 300
        and item.casefold() != "context_dependent"
    } if isinstance(candidates, list) else set()
    if not isinstance(raw_choices, list) or len(raw_choices) > MAX_CONDITIONAL_CHOICES:
        return result
    for item in raw_choices:
        if not isinstance(item, dict):
            continue
        option, relation = item.get("option"), item.get("relation")
        if not isinstance(option, str) or option not in allowed_options or not isinstance(relation, str) or relation not in RELATIONS:
            continue
        fact_ids = _ids(item.get("fact_ids"), facts)
        requirement_ids = _ids(item.get("requirement_ids"), user_requirements)
        if fact_ids and requirement_ids:
            result["conditional_choices"].append({
                "option": option, "relation": relation, "fact_ids": fact_ids,
                "requirement_ids": requirement_ids,
                "requirements": [user_requirements[key] for key in requirement_ids],
                "basis_status": "unverified",
            })
    return result


def eligible_source_fact_ids(chains):
    """Whole-source compatibility eligibility, sharing identity and text checks."""
    return {number for number, binding in source_fact_bindings(chains).items()
            if bind_source_fact({"id": "F1", "evidence_id": number}, binding) is not None}


def calibrate_evidence_choices(recommendation, verification):
    """Require whole-snippet coverage; leave uncertainty and choice authority separate."""
    from ..citations.verifier import _split_sentences, _strip_citations

    by_path = {}
    for check in verification.checks:
        by_path.setdefault(check.claim_path, []).append(check)
    overflow = "final_recommendation" in by_path
    statuses = {}
    for index, fact in enumerate(recommendation.get("source_facts", [])):
        checks = by_path.get(f"final_recommendation.source_facts[{index}].text", [])
        values = {check.status.value for check in checks}
        complete_binding = (
            Counter(check.claim_text for check in checks)
            == Counter(_strip_citations(text) for text in _split_sentences(fact["saved_text"]))
            and all(check.source_title == fact["source_title"]
                    and check.canonical_url == fact["canonical_url"] for check in checks)
        )
        status = ("verified" if checks and complete_binding and values == {"verified"} and not overflow
                  else "unsupported" if "unsupported" in values
                  else "unreachable" if "unreachable" in values else "unknown")
        fact["status"] = status
        fact.pop("review_availability", None)
        fact.pop("reviewable_sentence_ids", None)
        if status == "unknown" and checks and complete_binding and not overflow:
            outcomes = {(check.status.value, check.reason.value) for check in checks}
            if outcomes <= {("verified", "lexical_support"), ("unknown", "network_uncertain")}:
                # Availability uncertainty is not a contradiction of the exact saved text.
                # This grants review eligibility only, never citation/decision authority.
                fact["review_availability"] = "network_unconfirmed"
            elif (outcomes <= {("verified", "lexical_support"),
                               ("unknown", "qualifier_unverified"),
                               ("unknown", "content_insufficient")}
                  and ("verified", "lexical_support") in outcomes
                  and any(status == "unknown" for status, _ in outcomes)):
                # A whole fact stays unknown. Only uniquely addressed, verified
                # sentences may be considered for a bounded analysis review.
                sentences = [_strip_citations(text) for text in _split_sentences(fact["saved_text"])]
                if len(set(sentences)) == len(sentences):
                    by_text = {check.claim_text: check for check in checks}
                    fact["review_availability"] = "sentence_scoped"
                    fact["reviewable_sentence_ids"] = [
                        index for index, sentence in enumerate(sentences, 1)
                        if (by_text[sentence].status.value, by_text[sentence].reason.value)
                        == ("verified", "lexical_support")
                    ]
        statuses[fact["id"]] = status
    for choice in recommendation.get("conditional_choices", []):
        choice["basis_status"] = (
            "verified" if not overflow and choice.get("fact_ids")
            and all(statuses.get(key) == "verified" for key in choice["fact_ids"])
            else "unverified"
        )
    return recommendation
