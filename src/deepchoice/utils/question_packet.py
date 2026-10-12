"""Bounded source-to-question packet for the staged durable synthesizer.

Title mentions are routing hints only. They never establish source applicability.
"""
import re

from .decision_analysis import MAX_ANALYSES, MAX_ROW_BASIS_FACTS, MAX_ROW_BASIS_REFS
from .evidence import candidate_name_pattern, candidate_search_name

# Input opportunities include the request plus all 20 admitted subquestions.
# Answer generation and review keep the existing, separate MAX_ANALYSES bound.
MAX_QUESTION_ROWS = 21
_COMMON_WORDS = frozenset({"and", "with", "plus", "background", "tasks", "database", "db", "vector"})


def question_rows(query: str, requirements: list[dict]) -> list[tuple[str, str]]:
    """Offer all admitted original questions; this is not an answer-count budget."""
    rows = [("R0", query.strip())] if isinstance(query, str) and query.strip() else []
    rows.extend((row["id"], row["requirement"]) for row in requirements
                if row.get("kind") == "frozen_sub_question")
    return rows[:MAX_QUESTION_ROWS]


def candidate_mentions(title: str, candidates: list[str]) -> list[str]:
    """Find product names in a saved title without asserting semantic support."""
    if not isinstance(title, str):
        return []
    lowered = title.casefold()
    mentions = []
    for candidate in candidates:
        identity = candidate_search_name(candidate)
        if identity is None:
            continue
        pattern = candidate_name_pattern(candidate)
        if pattern is not None and pattern.search(lowered):
            mentions.append(candidate)
            continue
        # Preserve the historical long-token routing hint for compound labels
        # such as Apache Kafka. Complete short/symbol names need the path above.
        words = [word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", identity)
                 if len(word) >= 4 and word.casefold() not in _COMMON_WORDS]
        if any(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered)
               for word in words):
            mentions.append(candidate)
    return mentions


QUESTION_BASIS_POLICY = "runtime-question-basis-v6:joint-view-quotes;original-questions;context=21;answers=8;refs=12;facts=4;per-fact-cap=removed;question-only-requirements"


def _fact_sentence_groups(fact):
    from ..citations.verifier import _split_sentences
    from .evidence_choices import bounded_source_passages

    if not isinstance(fact.get("source_title"), str) or not isinstance(fact.get("saved_text"), str):
        return None
    passages = ()
    if "saved_passages" in fact:
        passages = bounded_source_passages({"snippet": fact["saved_text"], "passages": fact["saved_passages"]})
        if not passages:
            return None
    groups = [_split_sentences(passage) for passage in passages] if passages else [_split_sentences(fact["saved_text"])]
    return groups, bool(passages)


def _fact_heading(fact, candidates):
    mentions = candidate_mentions(fact["source_title"], candidates)
    return f'{fact["id"]} | title: {fact["source_title"]} | title mentions: {mentions or "none"}'


def basis_reference_packet(facts: list[dict], candidates: list[str], *, evidence_chains=None, require_reviewable=False) -> tuple[str, dict]:
    """Offer opaque IDs for the exact complete sentence addresses used by binding.

    Location labels do not join separate page passages. Any sentence-policy
    disagreement leaves that fact unoffered, rather than changing its addresses.
    """
    from ..citations.verifier import _split_sentences
    from .evidence_choices import whole_source_text
    from .decision_analysis import analysis_fact_reviewable

    facts = facts[:5]
    identifiers = [fact.get("id") for fact in facts]
    if (any(not isinstance(key, str) or not re.fullmatch(r"F[1-9]\d?", key) for key in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        return "No bound source facts.", {}
    lines, offered = [], {}
    for fact in facts:
        prepared = _fact_sentence_groups(fact)
        if prepared is None or whole_source_text(fact["saved_text"]) != fact["saved_text"]:
            continue
        groups, separate = prepared
        sentences = [sentence for group in groups for sentence in group]
        if not sentences or sentences != _split_sentences(fact["saved_text"]):
            continue
        lines.append(_fact_heading(fact, candidates))
        if require_reviewable:
            lines.append(f'  citation: {fact.get("status", "unknown")}; review: {fact.get("review_availability", "lexical_only")}')
        sentence_index = 1
        for passage_index, group in enumerate(groups, 1):
            if separate:
                lines.append(f'  Passage {passage_index}/{len(groups)} (same source, separate location):')
            for sentence in group:
                if require_reviewable and not analysis_fact_reviewable(fact, {"sentence_ids": [sentence_index]}):
                    sentence_index += 1
                    continue
                token = f"B{len(offered) + 1}"
                lines.append(f"  {token}: {sentence}")
                offered[token] = {"fact_id": fact["id"], "sentence_ids": [sentence_index],
                                  "source_sentences": [sentence]}
                sentence_index += 1
    if evidence_chains is not None:
        import json
        from .fact_selection import original_fact_contexts

        lines.append(json.dumps({"original_saved_contexts": original_fact_contexts(facts, evidence_chains)},
                                ensure_ascii=False))
    return ("\n".join(lines) if lines else "No bound source facts."), offered


def bind_question_rows(rows, allowed_ids, offered, *, diagnostics):
    """Map only advertised question/quote IDs; old model provenance is ignored.

    This creates canonical proposals for the unchanged analysis binder. It does
    not assert constraint coverage, source applicability, or permission to act.
    """
    diagnostics.update(rows_received=0, rows_selected=0, rows_rejected_shape=0,
                       rows_rejected_question=0, rows_rejected_limit=0,
                       rows_dropped_item_limit=0, basis_refs_trimmed=0)
    if not isinstance(rows, list):
        return []
    diagnostics["rows_received"] = len(rows)
    capacity = min(len(allowed_ids), MAX_ANALYSES)
    if len(rows) > capacity:
        # An oversized response is a capacity overrun, not a malformed one.
        # Keep the addressed rows in request order and drop only the excess, so
        # one extra row cannot discard every independent valid row.
        diagnostics["rows_dropped_item_limit"] = len(rows) - capacity
        rows = rows[:capacity]
    selected, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("question_id"), str):
            diagnostics["rows_rejected_shape"] += 1
            continue
        question = row["question_id"]
        if (question not in allowed_ids or question in seen
                or (question != "R0" and row.get("kind") == "choice")):
            diagnostics["rows_rejected_question"] += 1
            continue
        refs = row.get("basis_refs")
        if not isinstance(refs, list) or not refs:
            diagnostics["rows_rejected_shape"] += 1
            continue
        # Every addressed reference must be offered and unique; the excess of a
        # merely longer list is a capacity overrun and is dropped on its own.
        if (any(not isinstance(ref, str) or ref not in offered for ref in refs)
                or len(set(refs)) != len(refs)):
            diagnostics["rows_rejected_shape"] += 1
            continue
        kept_refs = refs[:MAX_ROW_BASIS_REFS]
        if len(kept_refs) < len(refs):
            diagnostics["basis_refs_trimmed"] += 1
        seen.add(question)
        groups = {}
        for ref in kept_refs:
            quote = offered[ref]
            basis = groups.setdefault(quote["fact_id"], {"fact_id": quote["fact_id"],
                                                        "sentence_ids": [], "source_sentences": []})
            basis["sentence_ids"].extend(quote["sentence_ids"])
            basis["source_sentences"].extend(quote["source_sentences"])
        if len(groups) > MAX_ROW_BASIS_FACTS:
            # Addresses are ordered by the response, so the first facts are the
            # ones the row led with; the excess is dropped, not the row.
            keep = list(groups)[:MAX_ROW_BASIS_FACTS]
            groups = {key: groups[key] for key in keep}
            diagnostics["basis_refs_trimmed"] += 1
        proposal = {key: row.get(key) for key in ("kind", "option", "reasoning", "assumptions", "change_condition")}
        proposal.update(requirement_ids=[question], basis=list(groups.values()))
        selected.append(proposal)
    diagnostics["rows_selected"] = len(selected)
    return selected
