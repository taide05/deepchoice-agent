"""Bounded source-to-question packet for the staged durable synthesizer.

Title mentions are routing hints only. They never establish source applicability.
"""
import re

from .evidence import candidate_name_pattern

MAX_QUESTION_ROWS = 8
_COMMON_WORDS = frozenset({"and", "with", "plus", "background", "tasks", "database", "db", "vector"})


def question_rows(query: str, requirements: list[dict]) -> list[tuple[str, str]]:
    """Original request first, then frozen user questions; never derived questions."""
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
        if not isinstance(candidate, str):
            continue
        pattern = candidate_name_pattern(candidate)
        if pattern is not None and pattern.search(lowered):
            mentions.append(candidate)
            continue
        # Preserve the historical long-token routing hint for compound labels
        # such as Apache Kafka. Complete short/symbol names need the path above.
        words = [word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", candidate)
                 if len(word) >= 4 and word.casefold() not in _COMMON_WORDS]
        if any(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered)
               for word in words):
            mentions.append(candidate)
    return mentions


def bounded_fact_packet(facts: list[dict], candidates: list[str]) -> str:
    """Show full saved, bound sentences and fact IDs; no model-authored source prose."""
    from ..citations.verifier import _split_sentences
    from .evidence_choices import bounded_source_passages

    lines = []
    for fact in facts[:5]:
        title = fact.get("source_title", "")
        text = fact.get("saved_text", "")
        if not isinstance(title, str) or not isinstance(text, str):
            continue
        passages = ()
        if "saved_passages" in fact:
            passages = bounded_source_passages({
                "snippet": text, "passages": fact["saved_passages"],
            })
            if not passages:
                continue
        mentions = candidate_mentions(title, candidates)
        lines.append(f'{fact["id"]} | title: {title} | title mentions: {mentions or "none"}')
        if passages:
            sentence_index = 1
            for passage_index, passage in enumerate(passages, 1):
                lines.append(f'  Passage {passage_index}/{len(passages)} (same source, separate location):')
                for sentence in _split_sentences(passage):
                    lines.append(f'  s{sentence_index}: {sentence}')
                    sentence_index += 1
        else:
            lines.extend(f'  s{index}: {sentence}' for index, sentence in enumerate(_split_sentences(text), 1))
    return "\n".join(lines) if lines else "No bound source facts."


def has_multi_candidate_coverage(facts: list[dict], candidates: list[str]) -> bool:
    """Withhold R0 only when titles clearly mention some choices and exclude others.

    An unclassified source leaves applicability undecided rather than proving an
    absent candidate. This is an abstention check, never positive proof of fit.
    """
    if len(candidates) < 2:
        return True
    covered = set()
    for fact in facts:
        mentions = candidate_mentions(fact.get("source_title", ""), candidates)
        if not mentions:
            return True
        covered.update(mentions)
    return set(candidates) <= covered
