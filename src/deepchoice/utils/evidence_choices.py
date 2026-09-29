"""Bounded conditional choices grounded in runtime-owned saved source text.

Bindings and lexical support are not proof of applicability or sound reasoning.
These projections never grant winner, requirement, or operational authority.
"""
from collections import Counter
from copy import deepcopy
import re

from .citation_markers import citation_spans, marker_titles
from .evidence import conclusion_source_allowed, is_navigation_placeholder

MAX_SOURCE_FACTS = 4
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


def bind_evidence_choices(recommendation, chains, candidates, requirements):
    """Discard model text/status; rebuild from this request and unique sources."""
    from ..citations.verifier import (
        _resolve_title, _source_registry, _split_sentences,
    )
    result = deepcopy(recommendation)
    raw_facts = result.pop("source_facts", [])
    raw_choices = result.pop("conditional_choices", [])
    if not raw_facts and not raw_choices:
        return result
    result["source_facts"] = []
    result["conditional_choices"] = []
    if not isinstance(raw_facts, list) or len(raw_facts) > MAX_SOURCE_FACTS:
        return result
    registry, _ = _source_registry(chains)
    numbered = {}
    number = 0
    for chain_index, chain in enumerate(chains):
        for source_index, source in enumerate(chain.get("sources", [])[:4]):
            number += 1
            if chain.get("disputed") or not conclusion_source_allowed(source):
                continue
            numbered[number] = (chain_index, source_index, source)
    seen = set()
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
        chain_index, source_index, source = numbered[evidence_id]
        title = source.get("title")
        resolved, error = _resolve_title(title, registry) if isinstance(title, str) else (None, "missing")
        if error is not None or resolved is None or resolved.position != (chain_index, source_index):
            continue
        if not resolved.canonical_url:
            continue
        marker = f"[Source: {resolved.title}]"
        spans = citation_spans(marker)
        if (len(spans) != 1 or spans[0][:2] != (0, len(marker))
                or marker_titles(spans[0][2]) != [resolved.title]):
            continue
        text = whole_source_text(source.get("snippet"))
        if not text:
            continue
        sentences = _split_sentences(text)
        result["source_facts"].append({
            "id": identifier, "evidence_id": evidence_id,
            "text": " ".join(f"{sentence} [Source: {resolved.title}]" for sentence in sentences),
            "source_title": resolved.title, "canonical_url": resolved.canonical_url,
            "saved_text": text, "status": "unknown",
        })
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
    """Use the binding contract itself to advertise admissible source numbers.

    Eligibility concerns complete saved text and identity, not live citation
    verification. Batches retain the same four-fact limit as model output.
    """
    count = sum(len(chain.get("sources", [])[:4]) for chain in chains)
    eligible = set()
    for start in range(1, count + 1, MAX_SOURCE_FACTS):
        refs = [{"id": f"F{offset + 1}", "evidence_id": number}
                for offset, number in enumerate(range(start, min(start + MAX_SOURCE_FACTS, count + 1)))]
        bound = bind_evidence_choices({"source_facts": refs}, chains, [], [])
        eligible.update(fact["evidence_id"] for fact in bound.get("source_facts", []))
    return eligible


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
        statuses[fact["id"]] = status
    for choice in recommendation.get("conditional_choices", []):
        choice["basis_status"] = (
            "verified" if not overflow and choice.get("fact_ids")
            and all(statuses.get(key) == "verified" for key in choice["fact_ids"])
            else "unverified"
        )
    return recommendation
