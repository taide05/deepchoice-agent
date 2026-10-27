import re

from ..utils.decision import normalize_decision
from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

# Thinking adds ~10x latency to synthesis (14s -> ~144s); give it a wide
# single-call budget so the per-case timeout (600s) is the binding constraint.
SYNTHESIS_CALL_TIMEOUT_S = 600.0

SYNTHESIS_PROMPT = """You are a senior technology advisor. Synthesize all evidence into a final, actionable recommendation.

## Original Query
{query}

## Scene Context
{scene_context}

## Declared Constraints
These are frozen constraints from the request. Every recommendation must respect
them or state which one it cannot satisfy; do not silently drop one.
{constraints}

## Original Sub-Questions
The user's question was broken into these sub-questions. Answer each one in the
recommendation or in `unresolved_questions`; do not drop one silently.
{sub_questions}

## Retrieved Source Material
{evidence_chains}

## Conflicts Found
{conflicts}

## Source Score Summary
Total sources retrieved: {source_count}
Sources flagged in a conflict pair: {flagged_source_count}
A flag means the source took part in a compared pair. It may be a difference of
position, a factual contradiction, or a comparison whose ruling was not finished —
the per-conflict resolutions above say which. A flag is not by itself proof that
the source is wrong or that the two sources contradict.

## Language
- Output explanatory/reasoning text (recommendation, rationale, trade-off findings, evidence_summary, confidence_rationale, scene_fit_note) in the SAME language as the original query.
- Technical terms (framework names, API names, algorithms, protocol names), source titles, and benchmark data MUST stay in their original language — do NOT translate them.
- This applies to the "name" field in ranked_options as well: keep the framework/library name as-is.

## Synthesis Rules
1. The retrieved sources are ranked by retrieval priority, NOT by how strongly they support anything. Read each source's content; cite it only for what it states, and do not treat the retrieval score or a source's popularity as evidence.
2. Acknowledge disputed findings — don't pretend they don't exist
3. Scene context is a TILT, not a decree — solo devs often lean simplicity/speed, enterprises reliability/scale, but strong content in a source for a different dimension (control, durability) can still win. Scene narrows the choice; it never forces it.
4. DECISION STATUS (choose exactly one): "recommended" when evidence clearly supports one candidate; "conditional" when the right choice depends on stated conditions and there is no single winner; "insufficient_evidence" when decisive evidence is missing and no candidate should be selected. Constraint-fit ratings are analysis only and never replace evidence or force a winner.
5. If evidence is insufficient for a definitive answer, say so honestly. Also state, explicitly, which constraint or evidence finding would change the recommendation (its reversal conditions) — put this in the recommendation or scene_fit_note when the answer is conditional.
6. CITE FACTUAL CLAIMS, NOT EVERY SENTENCE. Every factual claim that affects the choice, exclusion, risk boundary or a conditional conclusion must carry the source number(s) that actually state it, copied VERBATIM from the Retrieved sources (e.g. "Gitleaks scans git history [[3]]"). A statement that the evidence is missing, an explicit unknown, a qualifier, a label, or an inference that no source states must NOT be given an unrelated citation: write it as an explicit gap/inference instead. Do not invent numbers. The source list includes content ranges; do not treat material beyond the visible/truncated range as if you read it.
7. "winner" is a candidate name ONLY for decision_status="recommended", with a decisive evidence basis and applicability prerequisites in winner_rationale. For "conditional", there is no winner: provide at least two ranked_options and put the branching conditions in recommendation. For "insufficient_evidence", there is no winner: unresolved_questions must name the decisive gaps and the evidence that would change the conclusion, and recommendation states the hold. Never use ranked_options, constraint_fit, source counts or a generic default to fill a winner. If the required fields for the selected status are absent, the output is invalid rather than a valid hold.
8. The "winner" value, when present, MUST be a technology/framework name (e.g., "LangGraph", "FastAPI", "PostgreSQL") — never a sentence and never a sentinel for a hold.
9. For recommended/conditional, the winner or named branches must be established, adoptable products the user could actually adopt today. NEVER recommend a research paper, academic prototype, sample repository, or obscure experimental project as a product. This does not require the most popular option.
10. Make the analysis usable, not just short: each trade-off's `impact` must say who/which constraint it matters for; `evidence_summary` must note the evidence limits (missing official/primary sources, dates/versions absent, unmeasured claims); `confidence_rationale` must be consistent with `confidence`. Do not repeat the recommendation as the winner_rationale: state the decisive evidence basis there, and put actions/conditions in `recommendation`.
11. Distinguish documented fact, conditional inference and unknown. If the saved source list shows only a navigation link or a body-truncated range, do not present the missing text as established. If you answer a required item from general reasoning rather than a source, mark it as an inference; if it cannot be answered, record it in `unresolved_questions` with the decision impact instead of filling it with a citation.
12. PRIMARY-EVIDENCE DISCIPLINE: each source record carries its type (`official_doc`, `vendor`, `community`, `wiki`, `blog`, etc.). For a decision-decisive fact about migration cost, rollback, performance, security/audit, licensing, or long-term maintenance, prefer an official/primary source. If only a vendor or community/blog source states it, say so explicitly and do not use it as the sole basis for a recommended status. If a decisive dimension has no primary or quantified evidence, say so in `evidence_summary`/`confidence_rationale` and use conditional or insufficient_evidence; that is the correct decision-grade outcome, not a failure to choose.
13. SOURCE FRESHNESS: when a claim relies on a release note, migration guide, issue, or versioned page, state its version/date and whether it reflects the current product. An old release note cannot prove current capability; if only an old version's material is available, record the current-version gap instead of treating the old behavior as current.

## Output Structure
Return ONLY a JSON object:
{{
  "decision_status": "recommended|conditional|insufficient_evidence",
  "winner": "candidate name only when decision_status=recommended; empty for conditional/insufficient_evidence",
  "winner_rationale": "Decisive evidence basis for a recommended winner, or the decisive gap for insufficient_evidence",
  "recommendation": "Actionable recommendation; for conditional, the explicit branches and what would change them; for insufficient_evidence, the hold and the evidence that would change it",
  "ranked_options": [
    {{"name": "Option A", "rank": 1, "constraint_fit": "high|medium|low", "constraint_fit_reason": "why this fit", "rationale": "Why this rank, including the decisive evidence and applicability limits", "key_strength": "strongest evidence point", "key_weakness": "notable limitation"}}
  ],
  "trade_offs": [
    {{"dimension": "Performance vs DX etc.", "finding": "what evidence shows and its limits", "impact": "who/which constraint this matters for"}}
  ],
  "evidence_summary": "Evidence landscape, including what is missing, version/date limits and unmeasured claims",
  "confidence": "high|medium|low",
  "confidence_rationale": "Why this confidence; must agree with the confidence value",
  "unresolved_questions": ["question evidence couldn't answer, with its decision impact"],
  "scene_fit_note": "Fit to scene context"
}}"""


def build_source_registry(evidence_chains: list[dict]) -> dict:
    """The numbered source identities shared by every consumer of citations.

    Synthesis, binding, the self-review payload and reviewer revisions all read
    citations from this one registry, so a number, a canonical title and the body
    text behind them cannot disagree between the reporting paths. Only fact-bearing
    sources are registered; a navigation link is recorded separately and can never
    be cited.

    Every entry carries a `source_id` independent of the title: the URL when one
    was collected, otherwise the run-local number. Two sources may share a title
    (common for mirrors and translated pages) without sharing an identity, so a
    title is never used as the identity of a resolved citation.
    """
    from ..utils.candidate_identity import source_content

    entries: list[dict] = []
    chains: list[list[dict]] = []
    navigation: list[str] = []
    number = 0
    for chain in evidence_chains or []:
        chain_entries: list[dict] = []
        for source in (chain.get("sources") or [])[:4]:
            if not is_citable_source(source):
                link = source.get("url", "")
                if link and link not in navigation:
                    navigation.append(link)
                continue
            number += 1
            title = str(source.get("title") or "Unknown")
            url = str(source.get("url") or "")
            entry = {
                "number": number,
                "source_id": url or f"source-{number}",
                "title": title,
                "url": url,
                "body": source_content(source),
                "provenance": source.get("provenance") or "",
                "channel": source.get("channel") or "",
                "date": str(source.get("date") or ""),
                "disputed": bool(chain.get("disputed")),
            }
            for key in ("source_owner", "source_kind", "source_type",
                        "body_identity_verified", "fetch_status", "body_error",
                        "body_url", "body_page_chars", "body_prose_chars",
                        "body_stored_chars", "body_page_truncated",
                        "body_stored_truncated", "body_truncated",
                        "body_admission"):
                if key in source:
                    entry[key] = source[key]
            chain_entries.append(entry)
            entries.append(entry)
        chains.append(chain_entries)

    by_norm: dict[str, list[dict]] = {}
    by_number: dict[int, dict] = {}
    by_identity: dict[str, dict] = {}
    for entry in entries:
        by_norm.setdefault(_norm_title(entry["title"]), []).append(entry)
        by_number[entry["number"]] = entry
        by_identity.setdefault(entry["source_id"], entry)
    return {
        "entries": entries,
        "chains": chains,
        "navigation": navigation,
        "mapping": {entry["number"]: entry["title"] for entry in entries},
        "by_norm": by_norm,
        "by_number": by_number,
        "by_identity": by_identity,
    }


def _summarize_chains(evidence_chains: list[dict],
                      candidate_techs: list[str] | None = None,
                      with_audit: bool = False,
                      focus_terms: list[str] | None = None):
    """Format evidence chains for the prompt, assigning each source a stable
    number ([[N]]) that the model cites instead of a verbatim title. Returns
    the rendered text plus the number -> title mapping used to bind citations
    back to [Source: title] after synthesis.

    Each source carries its URL and the **same bounded body view** the
    self-review uses, with its visible/total character range recorded. The
    numbers come from `build_source_registry`, the same registry the citation
    engine and the self-review use, so prompt numbering and binding cannot drift
    apart. A source whose body was never collected is a navigation link: it gets
    no number and is listed separately.
    """
    from ..utils.candidate_identity import (
        shared_evidence_package,
        candidate_proper_nouns,
    )

    registry = build_source_registry(evidence_chains)
    evidence_package = shared_evidence_package(
        registry["entries"], focus_terms=focus_terms or [])
    audit: list[dict] = []
    header: list[str] = []
    names = candidate_proper_nouns(candidate_techs or [])
    if names:
        header = [
            "## Declared candidates for this question",
            "",
            "These are the only technologies in scope. Do not introduce any other "
            "product as a candidate, and do not replace one of these with a "
            "same-word product you happen to have seen in a source:",
            "",
        ]
        header += [f"- {name}" for name in names]
        header.append("")

    if not evidence_chains:
        result = "\n".join(header + ["No evidence chains available."])
        return (result, {}, audit) if with_audit else (result, {})

    lines: list[str] = list(header)
    lines += [
        "Retrieved sources — cite each by its number in double brackets, e.g. [[1]]:",
        "",
        "These are retrieval results, not findings. The number and the retrieval",
        "score express how the source was found, not whether it supports a claim.",
        "Read each source's content and cite it only for what that content states.",
        "",
    ]
    for chain_entries in registry["chains"]:
        if not chain_entries:
            # Nothing to read, so nothing to cite. Recorded, not presented as a
            # finding, so the model records a gap instead of citing a link.
            lines.append("(no fact-bearing source in this retrieved item — record a "
                         "material gap instead of citing it)")
            lines.append("")
            continue
        for entry in chain_entries:
            disputed = " [DISPUTED]" if entry["disputed"] else ""
            lines.append(f"[[{entry['number']}]] {entry['title']}{disputed}")
            if entry["url"]:
                lines.append(f"       url: {entry['url']}")
            if entry.get("source_owner") or entry.get("source_kind") or \
                    entry.get("source_type"):
                verified = entry.get("body_identity_verified")
                lines.append(
                    f"       source_identity: owner={entry.get('source_owner') or 'unknown'}; "
                    f"kind={entry.get('source_kind') or 'unknown'}; "
                    f"type={entry.get('source_type') or 'unknown'}; "
                    f"body_identity_verified={verified if verified is not None else 'unknown'}; "
                    f"fetch_status={entry.get('fetch_status') or 'unknown'}")
            # Where the material came from, so the model cannot mistake local or
            # evaluation material for a published source.
            if entry["provenance"] or entry["channel"]:
                lines.append(f"       provenance: {entry['provenance'] or 'unknown'}; "
                             f"channel: {entry['channel'] or 'unknown'}")
            if entry.get("date"):
                # Publication/update date travels with the body so version and
                # applicability statements can be checked against the source.
                lines.append(f"       date: {entry['date']}")
            if entry.get("body_url") and entry["body_url"] != entry["url"]:
                lines.append(f"       body_url: {entry['body_url']}")
            source_view = evidence_package["views"].get(entry["number"])
            if source_view is None:
                # Registry entries always have numbers; this is a defensive
                # fallback for historical callers that hand-build one.
                from ..utils.candidate_identity import bounded_evidence_record
                source_view = bounded_evidence_record(entry)
            lines.append(f"       content: {source_view['text']}")
            page_extracted = (source_view["page_chars"] if source_view["page_chars_known"]
                              else "unknown")
            page_truncated = (source_view["page_truncated"]
                              if source_view["page_chars_known"] else "unknown")
            ranges = ", ".join(f"{start}-{end}" for start, end in
                               source_view.get("selection_ranges") or [])
            lines.append(
                f"       content_visible: {source_view['visible_chars']}/"
                f"{source_view['stored_chars']} stored-body chars; "
                f"full_text_included={source_view.get('full_included', False)}; "
                f"source_ranges={ranges or 'none'}; "
                f"omitted_chars={source_view.get('omitted_chars', 0)}; "
                f"page_extracted={page_extracted}; "
                f"page_truncated={page_truncated}; "
                f"stored_truncated={source_view['stored_truncated']}"
            )
            audit.append({
                "number": entry["number"],
                "title": entry["title"],
                "body_url": source_view.get("body_url", ""),
                "page_chars": source_view["page_chars"],
                "page_chars_known": source_view["page_chars_known"],
                "stored_chars": source_view["stored_chars"],
                "source_chars": source_view["source_chars"],
                "visible_chars": source_view["visible_chars"],
                "omitted_chars": source_view.get("omitted_chars", 0),
                "selection_ranges": source_view.get("selection_ranges") or [],
                "full_included": source_view.get("full_included", False),
                "page_truncated": source_view["page_truncated"],
                "stored_truncated": source_view["stored_truncated"],
                "truncated": source_view["truncated"],
            })
            lines.append("")

    if registry["navigation"]:
        # Discovered links, not evidence. They carry no citable number, so they
        # cannot be cited even by writing their title verbatim.
        lines += [
            "## Navigation links — NOT citable",
            "",
            "These pages were found but no body was collected, so they state nothing "
            "here. Do not cite them, and do not write their titles as a source:",
            "",
        ]
        lines += [f"- {link}" for link in registry["navigation"][:10]]
        lines.append("")

    text = "\n".join(lines)
    return (text, dict(registry["mapping"]), audit) if with_audit else (
        text, dict(registry["mapping"]))


def _summarize_conflicts(conflicts: list[dict], conflict_check: dict | None = None) -> str:
    """Describe the conflict check without collapsing 'not finished' into 'none'.

    An empty list means the check found no confirmed contradiction only when the
    check actually ran to completion over its candidate pairs. Otherwise the
    synthesizer is told the check is incomplete, so it cannot present an
    unfinished scan as reassurance -- including the case where the scan found a
    difference and its ruling then failed.
    """
    check = conflict_check or {}
    outcomes = check.get("scan_outcomes") or {}
    unscanned = int(outcomes.get("unscanned") or 0)
    scanned = int(check.get("pairs_scanned") or 0)
    arbitration_failed = int(check.get("pairs_arbitration_failed") or 0)
    # High-scoring sources without a collected body cannot supply a comparable
    # claim and are not scanned. When the check does complete, saying it found no
    # contradiction without this qualifier would hide that those sources were
    # never compared at all.
    excluded_no_body = int(check.get("sources_without_comparable_claim") or 0)
    no_body_note = (
        f" NOTE: {excluded_no_body} high-scoring source(s) carried no collected "
        f"body and were not compared; this does not establish that they contain "
        f"no disagreement." if excluded_no_body else "")
    if not conflicts:
        if not check:
            return ("No confirmed conflicts, but this run recorded no conflict "
                    "check coverage: treat the absence as unverified.")
        if unscanned:
            return (f"CONFLICT CHECK INCOMPLETE: {unscanned} candidate pair(s) "
                    f"were not classified out of {scanned} scanned. Do not state "
                    f"or imply that no conflicts exist.")
        if arbitration_failed:
            # A difference was confirmed and then not adjudicated. That is a
            # live disagreement, not an absence of disagreement.
            return (f"CONFLICT CHECK INCOMPLETE: {arbitration_failed} candidate "
                    f"pair(s) showed a potential disagreement but the ruling was "
                    f"not completed. Present them as unresolved potential "
                    f"disagreements; do not state or imply that no conflicts exist.")
        if scanned == 0:
            return ("No candidate pairs qualified for the conflict check "
                    f"({check.get('reason', 'no candidates')}); absence of "
                    "conflicts was never tested." + no_body_note)
        return (f"Conflict check completed over {scanned} candidate pair(s) and "
                f"found no confirmed contradiction." + no_body_note)
    lines = []
    for i, c in enumerate(conflicts):
        def _side_label(key: str) -> str:
            src = c.get(f"source_{key}") or {}
            title = str(src.get("title") or "").strip()
            url = str(src.get("url") or "").strip()
            return title or url
        label_a = _side_label("a")
        label_b = _side_label("b")
        prefix_a = f"[{label_a}] " if label_a else ""
        prefix_b = f"[{label_b}] " if label_b else ""
        lines.append(
            f"{i+1}. {prefix_a}{c.get('claim_a', '')} vs "
            f"{prefix_b}{c.get('claim_b', '')} "
            f"— resolution: {c.get('resolution', 'unknown')} "
            f"(confidence: {c.get('confidence', 'N/A')})"
        )
    if unscanned:
        lines.append(
            f"NOTE: {unscanned} further candidate pair(s) were not classified, so "
            f"this list is partial."
        )
    if arbitration_failed:
        lines.append(
            f"NOTE: {arbitration_failed} further pair(s) showed a potential "
            f"disagreement that was not adjudicated; present them as unresolved "
            f"potential disagreements rather than omitting them."
        )
    if excluded_no_body:
        lines.append(no_body_note.strip())
    return "\n".join(lines)


def _norm_title(s: str) -> str:
    """Lowercase + alphanumerics only — matches metrics._normalize_title."""
    return "".join(c for c in s.lower() if c.isalnum())


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in (text or ""))


# A closed marker, or one that never closes. The unclosed form runs to the end of
# the text: it is still a claimed citation, so it must be seen and handled rather
# than passing through as ordinary prose.
_SOURCE_MARKER = re.compile(r'\[Source:[^\]]*\]|\[Source:[^\]]*$', re.IGNORECASE)
# Any double-bracket token. Classification of the token happens in one helper
# below: a number list is a citation attempt, a numeric fragment is an unresolved
# citation, an interval/array form is left as written, and a word marker is
# ordinary text. One grammar and one classifier replace the previous
# pattern-level lookarounds plus a second, compensating context pass.
_BRACKET_MARKER = re.compile(r"\[\[[^\[\]]*\]\]")
# The number grammar the prompt asks for: optional sign, unspaced separator.
_NUMBER_LIST = re.compile(r"^\s*([+-]?\d+(?:\s*[,;][+-]?\d+)*)\s*$")
# Characters a numeric bracket marker may contain besides letters.
_NUMERIC_FRAGMENT = re.compile(r"^\s*[+\-0-9][0-9\s,;.\-]*\s*$")

# The field on the recommendation carrying the registered identity of every
# resolved citation, keyed by the same locator the citation traversal uses.
CITATION_SOURCES_KEY = "citation_sources"

# Every field the prompt asks to cite must be resolved and listed. Leaving one
# out left raw [[N]] markers in the rendered report: the model cites
# confidence_rationale, but nothing converted its numbers. Self-review input and
# completeness read these same tuples.
_CITATION_TEXT_FIELDS = ("recommendation", "winner_rationale",
                         "evidence_summary", "scene_fit_note",
                         "confidence_rationale")
_CITATION_OPT_FIELDS = ("rationale", "key_strength", "key_weakness",
                        "constraint_fit_reason")
_CITATION_TRADEOFF_FIELDS = ("finding", "impact")


def is_citable_source(source: dict) -> bool:
    """Whether a source may be cited: it must have collected body text.

    The single predicate behind the citable set, the numbered registry and the
    body shown to every consumer, so they cannot disagree about what counts as a
    basis. The body is read through the same extraction that displays it.
    """
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(source)


_WITHDRAWN_NOTE = "（本项理由已被自审撤回：无可引来源支持其论断）"
_WITHDRAWN_NOTE_EN = "(withdrawn: no cited source supports this claim)"


def withdrawal_note(text: str) -> str:
    """The note that replaces a claim nothing citable supports.

    Follows the language of the field it replaces, so a withdrawn claim reads as
    part of the report rather than as a stray foreign sentence. Shared by the
    synthesis citation pass and the self-review, so a withdrawal looks the same
    wherever it happens.
    """
    if text and any("\u4e00" <= c <= "\u9fff" for c in text):
        return _WITHDRAWN_NOTE
    return _WITHDRAWN_NOTE_EN


# An unresolved citation is left in the text so the claim cannot read as
# supported, but it is marked so it is never mistaken for a citation the reader
# can follow. The wording is deliberately a gap, not a truth verdict.
_CITATION_GAP_ZH = "〔引用未解析：{}〕"
_CITATION_GAP_EN = "[citation-unresolved: {}]"
_CITATION_GAP_MARK = re.compile(
    r"〔引用未解析：[^〕]*〕|\[citation-unresolved: [^\]]*\]")
_SOURCE_TITLES_IN_MARKER = re.compile(r"^\[Source:\s*", re.IGNORECASE)
# The inner body of a malformed double-bracketed source marker:
# `[[Source: title]]` is a claimed citation, not ordinary bracket text.
_SOURCE_INNER_START = re.compile(r"^Source:\s*", re.IGNORECASE)
_VISIBLE_STRIP = re.compile(
    r"\[Source:[^\]]*\]|〔引用未解析：[^〕]*〕|\[citation-unresolved: [^\]]*\]")
_VISIBLE_PUNCT = re.compile(
    r"[\s。，、；：！？.,;:!?()（）\[\]〔〕\"'“”‘’…—\-]+")


def citation_gap_note(raw: str, context: str = "") -> str:
    """A locatable marker for a citation this pipeline could not resolve.

    Says what happened (the citation is unresolved), not whether the claim is
    true: an unverifiable citation is not evidence that the statement is false.
    """
    raw = " ".join(str(raw).split())
    template = _CITATION_GAP_ZH if _has_cjk(context or raw) else _CITATION_GAP_EN
    return template.format(raw)


def citation_gap_number(numbers: list[int], context: str = "") -> str:
    label = "来源编号" if _has_cjk(context) else "source number"
    return citation_gap_note(f"{label} {', '.join(str(n) for n in numbers)}", context)


def citation_gap_title(title: str, context: str = "") -> str:
    label = "来源标题" if _has_cjk(context) else "source title"
    return citation_gap_note(f"{label} “{title}”", context)


def citation_gap_marker(marker: str, context: str = "") -> str:
    label = "来源标记" if _has_cjk(context) else "source marker"
    inner = " ".join(str(marker).strip("[]").split())
    return citation_gap_note(f"{label} {inner}", context)


def citation_gap_present(text: str) -> bool:
    """Whether a field carries a locatable unresolved-citation gap."""
    return bool(_CITATION_GAP_MARK.search(text or ""))


def has_substantive_content(text: str) -> bool:
    """Whether a field still says something beyond citation/gap markers.

    A field holding only citations is not an answer; it must not be counted as
    one even when every marker in it resolved.
    """
    stripped = _VISIBLE_STRIP.sub("", text or "")
    return bool(_VISIBLE_PUNCT.sub("", stripped))


def resolve_literal_entry(registry: dict, title: str) -> dict | None:
    """The registered source a written title names, or None.

    Full identity first: the whole written title is compared after normalization,
    so a real title containing commas or semicolons is not split. If the same
    normalized title names more than one distinct source identity, the title is
    ambiguous and is not resolved to an arbitrary one of them.
    """
    key = _norm_title(title or "")
    if not key:
        return None
    matches = registry.get("by_norm", {}).get(key, [])
    identities = {entry["source_id"] for entry in matches}
    if len(identities) != 1:
        return None
    return matches[0]


def canonical_source_title(registry: dict, title: str) -> str | None:
    """The registered title a written title names, or None (see above)."""
    entry = resolve_literal_entry(registry, title)
    return entry["title"] if entry else None


def source_binding(entry: dict) -> dict:
    """The identity-bearing part of a source carried by a resolved citation."""
    return {
        "source_id": entry["source_id"],
        "number": entry["number"],
        "title": entry["title"],
        "url": entry["url"],
        "provenance": entry["provenance"],
        "channel": entry["channel"],
        "date": entry.get("date", ""),
        "source_type": entry.get("source_type", ""),
    }


def _split_literal_source_body(body: str) -> list[str]:
    """Parts of a `[Source: ...]` body, splitting only on the explicit separator.

    The binding output writes several titles as `A, Source: B`, so that separator
    is tried first and, when present, each part is taken whole. Otherwise the body
    is one title, which preserves a real title that itself contains commas.
    """
    if re.search(r",\s*Source:", body, re.IGNORECASE):
        return [part.strip() for part in
                re.split(r",\s*Source:\s*", body, flags=re.IGNORECASE)
                if part.strip()]
    return [body.strip()] if body.strip() else []


def _mapping_entry(number: int, mapping: dict[int, str]) -> dict | None:
    """A registry-like entry for a caller that holds only a number -> title map."""
    title = mapping.get(number)
    if not title:
        return None
    return {
        "number": number,
        "source_id": f"mapping:{title}",
        "title": title,
        "url": "",
        "provenance": "",
        "channel": "",
    }


def _unique_entries(entries: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in entries:
        if entry["source_id"] in seen:
            continue
        seen.add(entry["source_id"])
        unique.append(entry)
    return unique


def _citation_marker(entries: list[dict]) -> str:
    if not entries:
        return ""
    return "[Source: " + ", Source: ".join(entry["title"] for entry in entries) + "]"


def _classify_bracket(inner: str) -> tuple[str, list[int]]:
    """Classify one double-bracket token.

    Returns ("citation", numbers) for a valid positive number list, ("leave", [])
    for an interval, negative index or word marker that is not a citation at all,
    and ("gap", numbers) for a numeric fragment that claims a citation this
    pipeline cannot resolve (`[[1 2]]`, `[[1, 2]]`, `[[1.0]]`, unknown numbers are
    handled later by the mapping lookup, not here).
    """
    number_list = _NUMBER_LIST.fullmatch(inner)
    if number_list is not None:
        numbers = [int(n) for n in re.findall(r"[+-]?\d+", number_list.group(1))]
        if any(number <= 0 for number in numbers):
            # An interval or negative index: not a citation, not a gap.
            return "leave", numbers
        return "citation", numbers
    if _NUMERIC_FRAGMENT.fullmatch(inner):
        numbers = [int(n) for n in re.findall(r"[+-]?\d+", inner)]
        if "." in inner:
            return "gap", numbers
        if ("," in inner or ";" in inner) and any(number <= 0 for number in numbers):
            # A spaced interval such as `[[0, 1]]`: still not a citation.
            return "leave", numbers
        return "gap", numbers
    return "leave", []


def _resolve_literal_marker(marker: str, registry: dict,
                            context: str) -> tuple[str, list[dict]]:
    """Resolve a literal `[Source: title]` to registered identities and a gap."""
    body = _SOURCE_TITLES_IN_MARKER.sub("", marker)
    if body.endswith("]"):
        body = body[:-1]
    parts = _split_literal_source_body(body)
    if not parts:
        return citation_gap_note(
            "缺少来源标题" if _has_cjk(context) else "missing source title",
            context), []
    entries: list[dict] = []
    gaps: list[str] = []
    for part in parts:
        entry = resolve_literal_entry(registry, part)
        if entry is None:
            # Unknown or ambiguous: never pick one of several same-title sources.
            gaps.append(citation_gap_title(part, context))
        else:
            entries.append(entry)
    entries = _unique_entries(entries)
    return _citation_marker(entries) + "".join(gaps), entries


def _resolve_number_marker(inner: str, registry: dict, mapping: dict[int, str],
                           context: str) -> tuple[str, list[dict]]:
    """Resolve a positive number-list marker to identities and a numeric gap."""
    numbers = [int(n) for n in re.findall(r"[+-]?\d+", inner)]
    entries: list[dict] = []
    unknown: list[int] = []
    for number in numbers:
        entry = registry.get("by_number", {}).get(number) or _mapping_entry(number, mapping)
        if entry is None:
            unknown.append(number)
        else:
            entries.append(entry)
    entries = _unique_entries(entries)
    resolved = _citation_marker(entries)
    if unknown:
        resolved += citation_gap_number(unknown, context)
    return resolved, entries


def _is_index_context(text: str, start: int, end: int, inner: str) -> bool:
    """Whether a bracket token sits where a citation would not.

    One rule, applied once:
    - attached directly to an ASCII word/`_`/`]` before it, a token is indexing
      (`arr[[1,2]]`); a token that follows another citation token is not;
    - a spaced numeric fragment (not a clean number list) after an ASCII word is
      indexing too (`matrix [[1, 2]]`);
    - attached directly to `[`, `=` or `]` after it, a token is indexing
      (`row[[2,3]][0]`);
    - separated by whitespace from a following citation token, it is a citation;
      separated from `=`/`]`/a single bracket, it is indexing.

    Whitespace separates tokens, so a citation written after a space — including
    a clean number list between two other citation markers — is not indexing.
    """
    before = text[:start]
    if before.endswith("]]"):
        previous = re.search(r"\[\[([^\[\]]*)\]\]$", before)
        if previous is not None and _classify_bracket(previous.group(1))[0] == "citation":
            return False
    if before and before[-1].isascii() and (
            before[-1].isalnum() or before[-1] in "_]"):
        return True
    if before and before[-1].isspace():
        previous_nonspace = before.rstrip()[-1:] or ""
        if (previous_nonspace.isascii()
                and (previous_nonspace.isalnum() or previous_nonspace in "_]")
                and _NUMBER_LIST.fullmatch(inner) is None
                and _NUMERIC_FRAGMENT.fullmatch(inner) is not None):
            # A spaced array/matrix fragment attached to a word, e.g.
            # `matrix [[1, 2]]`.
            return True
    after = text[end:]
    if not after:
        return False
    if after.startswith("[[") and re.match(r"\[\[\s*[+-]?\d", after):
        # A citation token follows directly or after whitespace.
        return False
    if after[0] in "[=]":
        return True
    if after[0].isspace():
        rest = after.lstrip()
        if rest.startswith("[["):
            return not bool(re.match(r"\[\[\s*[+-]?\d", rest))
        if rest and rest[0] in "[=]":
            return True
    return False


def resolve_text_with_sources(
        text: str, evidence_chains: list[dict] | None = None,
        mapping: dict[int, str] | None = None,
        registry: dict | None = None) -> tuple[str, list[dict]]:
    """Apply the citation rules and keep the registered identity of every hit.

    Returns the display text and the ordered, de-duplicated bindings of every
    resolved citation in it. Unresolved citations stay in the text as located
    gaps and contribute no identity. Repeating the same resolved citation next to
    itself is collapsed to one; two different sources that happen to share a
    display title are both kept, because their identities differ.
    """
    if not text:
        return text, []
    registry = registry or build_source_registry(evidence_chains or [])
    effective_mapping = (dict(registry.get("mapping") or {})
                         if mapping is None else mapping)
    pieces: list[str] = []
    bindings: list[dict] = []
    last = 0
    previous_citation: tuple[str, tuple[str, ...]] | None = None
    previous_citation_end = 0
    for match in _CITATION_TOKEN.finditer(text):
        pieces.append(text[last:match.start()])
        marker = match.group(0)
        entries: list[dict] = []
        if match.group("source") is not None:
            replacement, entries = _resolve_literal_marker(marker, registry, text)
        else:
            inner = marker[2:-2]
            if _SOURCE_INNER_START.match(inner):
                # `[[Source: title]]`: a malformed but claimed citation. Resolve
                # the inner marker rather than leaving double-bracket junk in the
                # served text.
                replacement, entries = _resolve_literal_marker(
                    "[" + inner + "]", registry, text)
            elif _is_index_context(text, match.start(), match.end(), inner):
                pieces.append(marker)
                previous_citation = None
                last = match.end()
                continue
            else:
                kind, numbers = _classify_bracket(inner)
                if kind == "leave":
                    pieces.append(marker)
                    previous_citation = None
                    last = match.end()
                    continue
                if kind == "citation":
                    replacement, entries = _resolve_number_marker(
                        inner, registry, effective_mapping, text)
                else:
                    replacement = citation_gap_marker(marker, text)
        if entries:
            identity = tuple(entry["source_id"] for entry in entries)
            only_space_between = not text[previous_citation_end:match.start()].strip()
            if previous_citation == (replacement, identity) and only_space_between:
                # An effective duplicate of the citation just written.
                previous_citation_end = match.end()
                last = match.end()
                continue
            pieces.append(replacement)
            bindings.extend(source_binding(entry) for entry in entries)
            previous_citation = (replacement, identity)
            previous_citation_end = match.end()
        else:
            pieces.append(replacement)
            previous_citation = None
            previous_citation_end = match.end()
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces), bindings


def resolve_text(text: str, evidence_chains: list[dict] | None = None,
                 mapping: dict[int, str] | None = None,
                 registry: dict | None = None) -> str:
    """Display text after the citation rules; identity bindings are discarded."""
    return resolve_text_with_sources(
        text, evidence_chains=evidence_chains, mapping=mapping,
        registry=registry)[0]


def field_locator(container: dict, field: str, kind: str = "top") -> str:
    """The stable locator the citation traversal and self-review both address."""
    if kind == "option":
        return f"option={container.get('name') or '?'}/{field}"
    if kind == "trade-off":
        return f"trade-off={container.get('dimension') or '?'}/{field}"
    return field


def citation_field_locations(result: dict) -> list[tuple[str, dict, str]]:
    """Every field the pipeline asks the model to cite, with a stable locator.

    One traversal for binding, the identity map, the self-review review body,
    completeness and revision parsing; they cannot miss a different set.
    """
    locations: list[tuple[str, dict, str]] = []
    for field in _CITATION_TEXT_FIELDS:
        if result.get(field):
            locations.append((field_locator(result, field), result, field))
    for option in result.get("ranked_options") or []:
        if not isinstance(option, dict):
            continue
        for field in _CITATION_OPT_FIELDS:
            if option.get(field):
                locations.append((field_locator(option, field, "option"),
                                  option, field))
    for trade_off in result.get("trade_offs") or []:
        if not isinstance(trade_off, dict):
            continue
        for field in _CITATION_TRADEOFF_FIELDS:
            if trade_off.get(field):
                locations.append((field_locator(trade_off, field, "trade-off"),
                                  trade_off, field))
    return locations


def apply_citation_rules(result: dict, evidence_chains: list[dict],
                         mapping: dict[int, str] | None = None) -> dict:
    """Resolve citations in every cited field once and record their identity.

    The display text keeps the canonical title because a title reads well; the
    registered identity of each resolved citation is stored in
    `result[CITATION_SOURCES_KEY]` under the field's locator, and every consumer
    that needs to link, list or annotate a source reads that map instead of
    guessing a source from a title. An unresolved citation stays visible as a
    located gap. A field left with no substantive content is recorded as
    withdrawn rather than silently blanked.
    """
    registry = build_source_registry(evidence_chains)
    effective_mapping = (dict(registry["mapping"]) if mapping is None else mapping)
    bindings_by_field: dict[str, list[dict]] = {}
    for locator, container, field in citation_field_locations(result):
        original = str(container[field])
        resolved, bindings = resolve_text_with_sources(
            original, registry=registry, mapping=effective_mapping)
        if has_substantive_content(original) and not has_substantive_content(resolved):
            resolved, bindings = withdrawal_note(original), []
        container[field] = resolved
        if bindings:
            bindings_by_field[locator] = bindings
    result[CITATION_SOURCES_KEY] = bindings_by_field
    return result


def resolve_citations_with_sources(
        text: str, evidence_chains: list[dict],
        mapping: dict[int, str] | None = None,
        registry: dict | None = None) -> tuple[str, list[dict]]:
    """Resolve one block and return both display text and identity bindings.

    Synthesis and the self-review's revisions both use this; the caller may pass
    the same registry the source list was rendered from. A block that loses all
    substantive content becomes the withdrawal note and carries no citations.
    """
    if not text:
        return text, []
    registry = registry or build_source_registry(evidence_chains)
    effective_mapping = (dict(registry["mapping"]) if mapping is None else mapping)
    resolved, bindings = resolve_text_with_sources(
        text, registry=registry, mapping=effective_mapping)
    if has_substantive_content(text) and not has_substantive_content(resolved):
        return withdrawal_note(text), []
    return resolved, bindings


def resolve_citations(text: str, evidence_chains: list[dict],
                      mapping: dict[int, str] | None = None,
                      registry: dict | None = None) -> str:
    """Resolve one block of text with this pipeline's citation rules."""
    return resolve_citations_with_sources(
        text, evidence_chains, mapping=mapping, registry=registry)[0]


def unresolved_citations(text: str, evidence_chains: list[dict] | None = None,
                         registry: dict | None = None) -> bool:
    """True when text still carries a citation this pipeline could not resolve.

    That includes a gap marker, a number-list marker, a numeric fragment, or a
    literal `[Source:]` whose titles are not all registered unambiguously. An
    interval or array index is not a citation and is not counted; word markers are
    ordinary text. This says the citation is unresolved; it does not say the
    sentence is false.
    """
    if not text:
        return False
    if _CITATION_GAP_MARK.search(text):
        return True
    registry = registry or build_source_registry(evidence_chains or [])
    for match in _CITATION_TOKEN.finditer(text):
        if match.group("source") is not None:
            body = _SOURCE_TITLES_IN_MARKER.sub("", match.group(0))
            if body.endswith("]"):
                body = body[:-1]
            parts = _split_literal_source_body(body)
            if not parts:
                return True
            for part in parts:
                if resolve_literal_entry(registry, part) is None:
                    return True
            continue
        inner = match.group(0)[2:-2]
        if _SOURCE_INNER_START.match(inner):
            body = _SOURCE_INNER_START.sub("", inner)
            parts = _split_literal_source_body(body)
            if not parts:
                return True
            for part in parts:
                if resolve_literal_entry(registry, part) is None:
                    return True
            continue
        if _is_index_context(text, match.start(), match.end(), inner):
            continue
        kind, _numbers = _classify_bracket(inner)
        if kind != "leave":
            return True
    return False


def has_bound_citation(text: str, registry: dict) -> bool:
    """Whether text carries a title marker that names one registered source.

    Identity/format only, for text that has no identity map (historical
    snapshots, reviewer prose). It says a citation is attached and resolvable,
    not that the cited source supports the sentence.
    """
    for match in _SOURCE_MARKER.finditer(text or ""):
        body = _SOURCE_TITLES_IN_MARKER.sub("", match.group(0))
        if body.endswith("]"):
            body = body[:-1]
        parts = _split_literal_source_body(body)
        if parts and all(resolve_literal_entry(registry, part) for part in parts):
            return True
    for match in _BRACKET_MARKER.finditer(text or ""):
        inner = match.group(0)[2:-2]
        if not _SOURCE_INNER_START.match(inner):
            continue
        parts = _split_literal_source_body(_SOURCE_INNER_START.sub("", inner))
        if parts and all(resolve_literal_entry(registry, part) for part in parts):
            return True
    return False


# One scanner over the text: source markers first, then any double-bracket token
# whose classification is decided once in `_classify_bracket`. No pattern-level
# lookaround and no second context pass can disagree about the same marker.
_CITATION_TOKEN = re.compile(
    r"(?P<source>" + _SOURCE_MARKER.pattern + r")"
    r"|(?P<bracket>" + _BRACKET_MARKER.pattern + r")",
    re.IGNORECASE)


def clean_label(text: str) -> str:
    """Strip citation markers from a display label.

    A trade-off `dimension` is a label, not a factual claim: the model put source
    numbers in it and they were printed verbatim ("内存效率与成本 [[16]]").
    The label is not a field that can be revised — it is also the key the
    self-review uses to locate a trade-off — so the markers are removed and the
    remaining text is the one identity used for both display and locating.

    The same bracket grammar as citation resolution is used; no second grammar is
    introduced.
    """
    if not text:
        return text
    cleaned = _SOURCE_MARKER.sub("", str(text))

    def _drop(match: re.Match) -> str:
        kind, _numbers = _classify_bracket(match.group(0)[2:-2])
        return "" if kind != "leave" or _NUMERIC_FRAGMENT.fullmatch(
            match.group(0)[2:-2]) else match.group(0)

    cleaned = _BRACKET_MARKER.sub(_drop, cleaned)
    # Collapse the spacing the removals left behind.
    return " ".join(cleaned.split())


def _normalize_labels(result: dict) -> dict:
    """Normalise display labels in the synthesis result."""
    for to in result.get("trade_offs", []) or []:
        if isinstance(to, dict) and to.get("dimension"):
            to["dimension"] = clean_label(to["dimension"])
    return result


class ConclusionSynthesizerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        task = research_state["task"]
        evidence_chains = research_state.get("evidence_chains", [])
        conflicts = research_state.get("conflicts", [])
        conflict_check = research_state.get("conflict_check") or {}

        print_agent_output(
            f"Synthesizing final recommendation from {len(evidence_chains)} evidence chains",
            agent="CONCLUSION_SYNTHESIZER",
        )

        # How many retrieved sources appeared in a compared pair. This is not a
        # count of contradictions: a pair may be a position difference, an actual
        # factual contradiction, or a comparison whose ruling was not finished, and
        # the per-conflict resolution is what distinguishes them.
        flagged_source_count = sum(1 for c in evidence_chains if c.get("disputed"))

        from ..utils.candidate_identity import (
            EVIDENCE_INPUT_BUDGET_CHARS,
            evidence_focus_terms_for_state,
        )

        focus_terms = evidence_focus_terms_for_state(research_state)
        evidence_text, cite_map, evidence_audit = _summarize_chains(
            evidence_chains, task.get("candidate_techs") or [], with_audit=True,
            focus_terms=focus_terms)
        # The same sub-questions the self-review is given. Synthesis used to
        # receive only the original query, so the questions the pipeline had
        # already decomposed could be silently dropped from the answer.
        sub_questions = [str(q).strip() for q in (research_state.get("sub_questions") or [])
                         if str(q).strip()]
        prompt = [{
            "role": "user",
            "content": SYNTHESIS_PROMPT.format(
                query=task["query"],
                scene_context=task.get("scene_context", "team"),
                constraints=("\n".join(f"- {c}" for c in (task.get("constraints") or []))
                             if task.get("constraints") else "(none recorded)"),
                sub_questions=("\n".join(f"{i}. {q}" for i, q in enumerate(sub_questions, 1))
                               if sub_questions else "(none recorded)"),
                evidence_chains=evidence_text,
                conflicts=_summarize_conflicts(conflicts, conflict_check),
                source_count=len(research_state.get("source_scores", [])),
                flagged_source_count=flagged_source_count,
            ),
        }]

        local_usage: list = []
        try:
            result = await call_model(prompt, model="qwen-flash", response_format="json", tag="conclusion_synthesizer",
                                      usage=local_usage,
                                      timeout=SYNTHESIS_CALL_TIMEOUT_S)
        except Exception as e:
            print_agent_output(f"Synthesis failed: {e}", agent="CONCLUSION_SYNTHESIZER")
            result = {
                "recommendation": "Unable to synthesize recommendation due to insufficient evidence.",
                "ranked_options": [],
                "trade_offs": [],
                "evidence_summary": "Synthesis failed — see individual evidence chains.",
                "confidence": "low",
                "confidence_rationale": f"Synthesis step failed: {e}",
                "unresolved_questions": [],
                "scene_fit_note": "",
            }
        if not isinstance(result, dict):
            result = {
                "recommendation": "",
                "ranked_options": [],
                "trade_offs": [],
                "evidence_summary": "Model returned a non-object decision output.",
                "confidence": "low",
                "confidence_rationale": "invalid_model_output",
                "unresolved_questions": [],
                "scene_fit_note": "",
            }

        # Validate structure before any len/traversal/rendering consumer.
        normalize_decision(result, declared_candidates=task.get("candidate_techs") or [])

        quality_signals = [{
            "agent": "conclusion_synthesizer",
            "evidence_chain_count": len(evidence_chains),
            # Sources that appeared in a compared pair; not a contradiction count.
            "flagged_sources": flagged_source_count,
            "options_ranked": len(result.get("ranked_options", [])),
            "synthesis_confidence": result.get("confidence", "low"),
            "evidence_input_budget_chars": EVIDENCE_INPUT_BUDGET_CHARS,
            "evidence_full_included": bool(evidence_audit) and all(
                a.get("full_included") for a in evidence_audit),
            "evidence_sources_visible": len(evidence_audit),
            "evidence_sources_excerpted": sum(
                1 for a in evidence_audit if not a.get("full_included", False)),
            "evidence_visible_chars": sum(a["visible_chars"] for a in evidence_audit),
            "evidence_omitted_chars": sum(
                a.get("omitted_chars", 0) for a in evidence_audit),
            "evidence_source_chars": sum(a["source_chars"] for a in evidence_audit),
            "evidence_page_chars": sum(
                a["page_chars"] for a in evidence_audit if a["page_chars_known"]),
            "evidence_page_chars_known_sources": sum(
                1 for a in evidence_audit if a["page_chars_known"]),
            "evidence_stored_chars": sum(a["stored_chars"] for a in evidence_audit),
            "evidence_page_truncated_sources": sum(
                1 for a in evidence_audit if a["page_truncated"] is True),
            "evidence_page_truncated_unknown_sources": sum(
                1 for a in evidence_audit if a["page_truncated"] is None),
            "evidence_stored_truncated_sources": sum(
                1 for a in evidence_audit if a["stored_truncated"]),
        }]

        quality_signals[0]["decision_status"] = result.get("decision_status")
        quality_signals[0]["decision_winner_present"] = bool(
            (result.get("winner") or "").strip())
        # Labels are display/locator identity, so they are normalised before the
        # citation pass records its locators; otherwise a marker in a dimension
        # would make the bindings and the renderer address the same field by two
        # different names.
        _normalize_labels(result)
        # One pass over one shared field list: numbers and literal titles are
        # resolved against the same numbered source registry the prompt used, a
        # bound title is canonicalised once, the identity of every resolved
        # citation is recorded, and an unresolvable citation stays visible as a
        # gap instead of being deleted.
        apply_citation_rules(result, evidence_chains, cite_map)

        return {
            "final_recommendation": result,
            "quality_signals": quality_signals,
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conclusion_synthesizer", local_usage)],
        }
