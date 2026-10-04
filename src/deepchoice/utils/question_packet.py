"""Bounded source-to-question packet for the staged durable synthesizer.

Title mentions are routing hints only. They never establish source applicability.
"""
import re

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
        words = [word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", candidate)
                 if len(word) >= 4 and word.casefold() not in _COMMON_WORDS]
        if any(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered)
               for word in words):
            mentions.append(candidate)
    return mentions


def preferred_official_fact_ids(chains: list[dict], candidates: list[str]) -> set[int] | None:
    """Prefer the top five only when each candidate owns part of that pool.

    A catalog host and source title are routing hints, not semantic proof.
    Sparse, mixed, disputed, or composite-candidate pools keep all sources.
    """
    from .evidence_choices import MAX_SOURCE_FACTS, eligible_source_fact_ids
    from .official_catalog import (
        TECH_DOCS, catalog_scope_contains, is_catalog_official_url, normalized_hostname,
    )

    if not isinstance(candidates, list) or len(candidates) < 2:
        return None
    owners = {}
    for candidate in candidates:
        if not isinstance(candidate, str):
            return None
        entry = TECH_DOCS.get(candidate.casefold())
        host = normalized_hostname(entry["url"]) if entry else None
        # A shared repository host cannot identify which project owns a page.
        if not host or host == "github.com":
            return None
        owners[candidate] = entry["url"]
    eligible = eligible_source_fact_ids(chains)
    top = sorted(eligible)[:MAX_SOURCE_FACTS]
    if len(top) < MAX_SOURCE_FACTS:
        return None
    covered = set()
    seen_urls = set()
    number = 0
    for chain in chains:
        for source in chain.get("sources", [])[:4]:
            number += 1
            if number not in top:
                continue
            url = source.get("url", "")
            if chain.get("disputed") or not is_catalog_official_url(url) or url in seen_urls:
                return None
            seen_urls.add(url)
            mentions = candidate_mentions(source.get("title", ""), candidates)
            owners_here = {
                candidate for candidate, root_url in owners.items()
                if candidate in mentions and catalog_scope_contains(root_url, source["url"])
            }
            if len(owners_here) != 1:
                return None
            covered.update(owners_here)
    return set(top) if len(covered) == len(owners) else None

def bounded_fact_packet(facts: list[dict], candidates: list[str]) -> str:
    """Show full saved, bound sentences and fact IDs; no model-authored source prose."""
    from ..citations.verifier import _split_sentences

    lines = []
    for fact in facts[:5]:
        title = fact.get("source_title", "")
        text = fact.get("saved_text", "")
        if not isinstance(title, str) or not isinstance(text, str):
            continue
        mentions = candidate_mentions(title, candidates)
        lines.append(f'{fact["id"]} | title: {title} | title mentions: {mentions or "none"}')
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
