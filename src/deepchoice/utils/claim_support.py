"""Deterministic claim-support audit for a synthesis decision.

This is a *diagnostic/ledger* layer, not a content judge. It answers:

- which sources support the decision-bearing fields;
- whether those sources include an official/primary source;
- whether the recommendation rests on a single source or community-only material.

It never changes the decision by itself. The self-reviewer receives the counts and
flags so its content check can reason about the decisive claim, instead of the
pipeline silently rewriting the winner.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def _canonical(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    return (parsed.scheme + "://" + parsed.netloc + parsed.path).rstrip("/")


def _source_class(source: dict) -> str:
    source_type = str((source or {}).get("source_type") or "").lower()
    provenance = str((source or {}).get("provenance") or "").lower()
    channel = str((source or {}).get("channel") or "").lower()
    if source_type == "official_doc":
        return "primary"
    if source_type == "arxiv_paper":
        return "independent"
    if source_type in {"stackoverflow", "reddit"} or provenance == "community" \
            or channel == "community":
        return "community"
    return "secondary"


def _decision_locators(rec: dict) -> list[str]:
    locators = ["recommendation", "winner_rationale"]
    winner = str((rec or {}).get("winner") or "").strip()
    if winner:
        locators.extend([
            f"option={winner}/rationale",
            f"option={winner}/key_strength",
            f"option={winner}/constraint_fit_reason",
        ])
    return locators


def decisive_claim_support(rec: dict) -> dict:
    """Summarise the sources supporting the decision-bearing fields."""
    rec = rec or {}
    bindings = rec.get("citation_sources") or {}
    sources: list[dict] = []
    seen: set[str] = set()
    for locator in _decision_locators(rec):
        for binding in bindings.get(locator) or []:
            if not isinstance(binding, dict):
                continue
            url = str(binding.get("url") or "")
            key = _canonical(url) or str(binding.get("source_id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            sources.append({
                "title": str(binding.get("title") or ""),
                "url": url,
                "source_type": str(binding.get("source_type") or ""),
                "source_owner": str(binding.get("source_owner") or ""),
                "class": _source_class(binding),
            })
    counts = {"primary": 0, "independent": 0, "secondary": 0, "community": 0}
    for source in sources:
        counts[source["class"]] += 1
    winner = str(rec.get("winner") or "").strip()
    winner_owned = sum(
        1 for source in sources
        if winner and source.get("source_owner")
        and source["source_owner"].casefold() == winner.casefold())
    primary_owners = {
        source.get("source_owner", "").casefold()
        for source in sources if source["class"] == "primary" and source.get("source_owner")
    }
    status = str(rec.get("decision_status") or "")
    flags: list[str] = []
    if status == "recommended":
        if not sources:
            flags.append("recommended_uncited")
        if counts["primary"] == 0:
            flags.append("recommended_no_primary")
        if len(sources) == 1:
            flags.append("recommended_single_source")
        if sources and counts["community"] == len(sources):
            flags.append("recommended_community_only")
        if not (rec.get("citation_sources") or {}).get("winner_rationale"):
            flags.append("winner_rationale_uncited")
        if winner_owned >= 2 and winner_owned > (counts["primary"] - winner_owned):
            # The winner's own docs dominate the decisive fields while the
            # non-winner primary support is thinner. This is a review signal,
            # not an automatic downgrade.
            flags.append("recommended_winner_owner_dominates")
    elif status == "conditional":
        if not sources:
            flags.append("conditional_uncited")
        if counts["primary"] == 0:
            flags.append("conditional_no_primary")
    return {
        "status": status,
        "winner": winner,
        "counts": counts,
        "winner_owned": winner_owned,
        "primary_owners": sorted(owner for owner in primary_owners if owner),
        "distinct_sources": len(sources),
        "flags": flags,
        "sources": sources,
    }


def claim_support_flags(rec: dict) -> list[str]:
    return list(decisive_claim_support(rec).get("flags") or [])
