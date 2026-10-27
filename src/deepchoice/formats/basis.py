"""The report's evidence basis, derived the same way for every report format.

A retrieved page is not a finding, and its retrieval score is not evidence
strength. The basis is the set of sources the synthesis result actually cites:
the citation pass records the registered identity of every resolved citation, and
this module lists those identities. It never re-derives a source from the display
title: two sources can share a title, and a title is not an identity. Historical
material that predates the identity map falls back to full-title matching only
when that title names exactly one registered source; an ambiguous title is left
out rather than attributed to the first or all of the candidates.

Material that was retrieved but never cited stays in the raw retrieval record
(`source_scores` / `search_results`) and is not presented as a basis here —
rendering it as a "conclusion" with a strength derived from its score would
manufacture a judgement the pipeline never made.
"""
from __future__ import annotations

import html
import re

# Markdown punctuation that can start inline formatting/links/headings. Python-
# Markdown unescapes a backslash before these, so a backslash makes the character
# display as literal text. `<`, `>` and `&` are HTML-escaped first, which also
# neutralizes raw HTML and autolinks; escaping them with a backslash would leave
# the backslash visible in some renderers.
_MARKDOWN_ESCAPE_RE = re.compile(r"([\\`*_\[\]()#+.!-])")


def escape_markdown_text(text: str) -> str:
    """Render untrusted stored text as literal Markdown text.

    Source titles, claim excerpts and metadata are display data, not authored
    report prose. A scraped body can contain raw HTML (`<img>`), an autolink
    (`<https://…>`) or Markdown formatting (`*bold*`, backticks, tags). This
    helper keeps all of them literal while preserving the stored value itself;
    it is display-only and never mutates the source record. The same helper is
    used for link labels and plain text so the report has one escaping rule.
    """
    normalized = " ".join(str(text or "").split())
    escaped = html.escape(normalized, quote=False)
    return _MARKDOWN_ESCAPE_RE.sub(r"\\\1", escaped)


def short_report_title(task: dict, recommendation: dict | None = None) -> str:
    """Display-only short title for a report heading.

    Candidates first, so the heading says what was compared. When the request
    declared no candidates, the synthesis result's ranked options provide the
    names. Only when neither exists does a short query prefix stand in. The full
    request remains in the task and snapshot and is rendered once as context
    under the heading; it is never the heading itself.
    """
    task = task or {}
    candidates = [" ".join(str(c).split()) for c in (task.get("candidate_techs") or [])
                  if str(c).strip()]
    names = candidates
    if not names:
        names = []
        for opt in (recommendation or {}).get("ranked_options") or []:
            if isinstance(opt, dict):
                name = " ".join(str(opt.get("name") or "").split())
                if name and name not in names:
                    names.append(name)
    if len(names) == 2:
        return f"{names[0]} vs {names[1]}"
    if len(names) > 2:
        return " / ".join(names[:3])
    if names:
        return names[0]
    query = " ".join(str(task.get("query") or "").split())
    if not query:
        return "Technology Selection"
    if len(query) <= 48:
        return query
    cut = query[:48]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip("，,。.;；:：") + "…"


def research_question_line(task: dict, lang: str) -> str:
    """The original request as one line of context below the heading."""
    query = " ".join(str((task or {}).get("query") or "").split())
    if not query:
        return ""
    prefix = "研究问题：" if lang == "zh" else "Research question: "
    return f"> {prefix}{query}"


def _registered_citation_bindings(rec: dict) -> dict | None:
    from ..agents.conclusion_synthesizer import CITATION_SOURCES_KEY

    mapping = (rec or {}).get(CITATION_SOURCES_KEY)
    return mapping if isinstance(mapping, dict) else None


def _field_texts(rec: dict) -> list[tuple[str, str]]:
    """The cited text fields, from the same traversal binding and review use."""
    from ..agents.conclusion_synthesizer import citation_field_locations

    return [(locator, str(container.get(field) or ""))
            for locator, container, field in citation_field_locations(rec)]


def _used_from_identity_map(rec: dict) -> list[dict]:
    """Aggregate the registered identities the citation pass recorded."""
    identity_map = _registered_citation_bindings(rec) or {}
    used: dict[str, dict] = {}
    for locator, _text in _field_texts(rec):
        for binding in identity_map.get(locator) or []:
            if not isinstance(binding, dict):
                continue
            identity = str(binding.get("source_id") or binding.get("url") or "")
            title = str(binding.get("title") or "")
            url = str(binding.get("url") or "")
            if not identity or not title or not url:
                # A source with no URL cannot be a linkable reference; the old
                # title-based basis also required one.
                continue
            entry = used.setdefault(identity, {
                "title": title,
                "url": url,
                "provenance": binding.get("provenance", "unknown"),
                "channel": binding.get("channel", ""),
                "date": str(binding.get("date") or ""),
                "source_type": str(binding.get("source_type") or ""),
                "citations": 0,
            })
            entry["citations"] += 1
    return list(used.values())


def _title_index(chains: list[dict]) -> dict[str, list[dict]]:
    """Registered sources grouped by normalised title, for historical material.

    Each group is de-duplicated by URL, so the same source appearing in several
    chains is one identity, while a genuinely different source that happens to
    share a title remains a separate identity.
    """
    from ..agents.conclusion_synthesizer import _norm_title
    from ..utils.candidate_identity import has_factual_content

    index: dict[str, dict[str, dict]] = {}
    for chain in chains or []:
        for src in chain.get("sources", []) or []:
            title = str(src.get("title") or "")
            url = str(src.get("url") or "")
            if not title or not url or not has_factual_content(src):
                continue
            index.setdefault(_norm_title(title), {}).setdefault(url, src)
    return {key: list(group.values()) for key, group in index.items()}


def unique_sources_for_title(chains: list[dict], title: str) -> list[dict]:
    """The one source a written title names, or [] when unknown/ambiguous.

    Used only for historical records without the identity map. A title shared by
    several sources is never resolved arbitrarily and never expanded to all of
    them.
    """
    from ..agents.conclusion_synthesizer import _norm_title

    return list(_title_index(chains).get(_norm_title(title or ""), []))


def _used_from_titles(rec: dict, chains: list[dict],
                      skip_locators: set[str] | None = None) -> list[dict]:
    """Historical fallback: full-title identity, unique sources only.

    `skip_locators` lets a partial identity map (an old record that was later
    revised) defer fields it has identities for while still resolving the fields
    it does not cover. The fallback never guesses: an unknown or ambiguous title
    contributes no source.
    """
    from ..agents.conclusion_synthesizer import _norm_title

    index = _title_index(chains)
    used: dict[str, dict] = {}
    for locator, text in _field_texts(rec):
        if skip_locators and locator in skip_locators:
            continue
        for marker in re.findall(r"\[Source:\s*([^\]]+)\]", text):
            for part in re.split(r",\s*Source:\s*", marker):
                title = part.strip()
                sources = index.get(_norm_title(title), [])
                if len(sources) != 1:
                    # Unknown or ambiguous title: do not guess a source.
                    continue
                src = sources[0]
                url = str(src.get("url") or "")
                entry = used.setdefault(url, {
                    "title": title,
                    "url": url,
                    "provenance": src.get("provenance", "unknown"),
                    "channel": src.get("channel", ""),
                    "date": str(src.get("date") or ""),
                    "source_type": str(src.get("source_type") or ""),
                    "citations": 0,
                })
                entry["citations"] += 1
    return list(used.values())


def _meaningful_candidate_name(name: str) -> bool:
    """Whether a candidate name can support a relevance judgment.

    Test fixtures and hypothetical prompts use placeholders ("A", "Candidate A");
    filtering real sources by whether they mention such a placeholder would drop
    legitimate evidence, so those names are ignored by the relevance filter.
    """
    text = str(name or "").strip()
    if len(text) < 2:
        return False
    if re.fullmatch(r"[A-Za-z]", text):
        return False
    lowered = text.lower()
    return not (lowered.startswith(("candidate ", "候选")))


def _decision_candidates(rec: dict) -> list[str]:
    """Candidate names the decision actually carries (for source relevance)."""
    names: list[str] = []
    for value in (rec.get("winner"),):
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)
    for option in rec.get("ranked_options") or []:
        if not isinstance(option, dict):
            continue
        name = str(option.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return [name for name in names if _meaningful_candidate_name(name)]


def source_entry_relevant(rec: dict, chains: list[dict],
                          title: str, url: str) -> bool:
    """Whether one cited source visibly discusses a decision candidate."""
    candidates = _decision_candidates(rec)
    if not candidates:
        return True
    from ..utils.candidate_identity import (names_candidate, source_content,
                                            source_text_discusses_candidate)

    content = ""
    found = False
    for chain in chains or []:
        for src in chain.get("sources") or []:
            if str(src.get("url") or "") == url:
                content = source_content(src)
                found = True
                break
        if found:
            break
    if not found:
        # No collected body/content to judge: keep the source rather than hide a
        # citation on incomplete information (the historical fixtures and imported
        # records can legitimately have title/url only).
        return True
    return any(names_candidate(f"{title} {url}", candidate)
               or source_text_discusses_candidate(candidate, title, content)
               for candidate in candidates)


def _filter_relevant_used(rec: dict, chains: list[dict],
                          used: list[dict]) -> list[dict]:
    """Keep only cited sources that visibly discuss a declared candidate.

    A source can enter the citation map because the model cited it in a field
    that the report never renders (or cited it for an unrelated aside); the
    2026-10-27 F200-130 report listed finance/crypto articles in "why this was
    used" even though they discuss no candidate. Dropping those from the basis
    list is deterministic and does not hide a source that actually names a
    candidate. With no candidates to test against, nothing is filtered.
    """
    return [entry for entry in used
            if source_entry_relevant(rec, chains, str(entry.get("title") or ""),
                                     str(entry.get("url") or ""))]


def used_sources(rec: dict, chains: list[dict]) -> list[dict]:
    """The registered sources the synthesis result actually cites.

    A source belongs here only because a resolved citation carries its identity.
    A partial identity map defers only the fields it actually covers; fields it
    does not cover are resolved from their full titles, and an unknown or shared
    title there contributes nothing rather than a guessed source.

    Body-less links are excluded: a link with no collected body is navigation, not
    a basis. The count says how often the source is used, not how strongly it
    supports anything.
    """
    identity_map = _registered_citation_bindings(rec)
    if identity_map is None:
        return _filter_relevant_used(rec, chains,
                                     _used_from_titles(rec, chains))
    used = {entry["url"]: entry for entry in _used_from_identity_map(rec)}
    for entry in _used_from_titles(rec, chains,
                                   skip_locators=set(identity_map)):
        if not entry["url"]:
            continue
        existing = used.setdefault(entry["url"], entry)
        if existing is not entry:
            existing["citations"] += entry["citations"]
    return _filter_relevant_used(rec, chains, list(used.values()))


def source_provenance_note(src: dict, lang: str) -> str:
    """Describe a source's origin honestly, without calling local material public.

    Only material whose origin could be mistaken for something else is
    annotated: locally held documents, evaluation material, and official primary
    documents (with their saved date when one exists). A page fetched from the
    web needs no note — its URL already says where it came from — except that the
    reader of a decision-grade report should be able to see which references are
    official primary documentation and how old they are.
    """
    provenance = str(src.get("provenance") or "").strip().lower()
    channel = str(src.get("channel") or "").strip().lower()
    source_type = str(src.get("source_type") or "").strip().lower()
    date = str(src.get("date") or "").strip()
    url = str(src.get("url", "")).lower()
    if provenance == "benchmark_ground_truth" or channel == "benchmark_ground_truth":
        return "（评测答案材料）" if lang == "zh" else " (benchmark answer material)"
    if channel == "local_kb" or url.startswith("file://"):
        return "（本地知识库文档）" if lang == "zh" else " (local knowledge-base document)"
    if source_type == "official_doc":
        note = "（官方文档）" if lang == "zh" else " (official docs)"
        if date:
            note += f"（{date}）" if lang == "zh" else f" ({date})"
        return note
    if url.startswith(("http://", "https://")):
        if date:
            return f"（来源日期：{date}）" if lang == "zh" else f" (source date: {date})"
        return ""
    return "（出处未知）" if lang == "zh" else " (provenance unknown)"
