import re

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
4. ANTI-BIAS (MANDATORY three-step): Step 1 — list the constraints from Scene Context that affect this choice. Step 2 — rate each candidate's constraint-fit (high/medium/low). Step 3 — the winner MUST be the highest constraint-fit candidate, even if it is less popular or newer than a competitor with more GitHub stars or search results. Only override with a lower-fit candidate if there is overwhelming counter-evidence, and state it in winner_rationale. If the highest constraint-fit is TIED, set "winner" to "context_dependent" (rule 7).
5. If evidence is insufficient for a definitive answer, say so honestly
6. INLINE CITATIONS REQUIRED — EVERY sentence and EVERY field MUST end with a source number in double brackets, e.g. "Use FastAPI [[1]]." — no sentence or field may be left uncited, no matter how short. Short fields are factual assertions, NOT labels: key_strength, key_weakness, and impact must EACH carry a [[N]] (e.g. "key_strength": "Mature role-based abstraction [[1]]"). recommendation: EVERY sentence, INCLUDING the opening "Adopt X ..." sentence and any closing summary sentence, must carry its own [[N]]. winner_rationale, rationale, finding, scene_fit_note, and every evidence_summary sentence: same rule. CRITICAL: copy the number VERBATIM from the Retrieved sources above — NEVER invent a number that is not listed.
7. Winner selection: name a winner ONLY when evidence clearly favors one option for the scene. If balanced — both have meaningful evidence and neither clearly wins — set "winner" to "context_dependent" and give a conditional recommendation ("choose X if ..., choose Y if ..."). If your own rationale says "depends on"/"hinges on"/"context-dependent", the winner MUST be "context_dependent".
8. The "winner" value MUST be a technology/framework name (e.g., "LangGraph", "FastAPI", "PostgreSQL"), or "context_dependent" for a genuine tie (rule 7) — never a sentence.
9. CRITICAL: The winner MUST be an established, adoptable product, tool, or framework that the user could actually adopt today. NEVER recommend a research paper, academic prototype, sample repository, or obscure experimental project (e.g. "FedMon", "aws-samples/..."). NOTE: "established" does NOT mean "mainstream / most popular" — a mature but smaller product (e.g. Meilisearch, Prefect, Tiktoken) is a valid winner if it best fits the constraints. If the strongest evidence only supports a non-product, pick the closest adoptable alternative and note it in winner_rationale.

## Output Length Limits (CRITICAL — exceed and output will be rejected)
- recommendation: max 200 words
- each ranked_option rationale: max 80 words
- each trade_off finding: max 60 words
- evidence_summary: max 150 words
- scene_fit_note: max 80 words

## Output Structure
Return ONLY a JSON object:
{{
  "winner": "Single technology name (REQUIRED)",
  "winner_rationale": "One sentence citing strongest evidence (max 40 words)",
  "recommendation": "Actionable recommendation paragraph (max 200 words)",
  "ranked_options": [
    {{"name": "Option A", "rank": 1, "constraint_fit": "high|medium|low", "constraint_fit_reason": "why this fit (max 30 words)", "rationale": "Why this rank (max 80 words)", "key_strength": "strongest evidence point (max 30 words)", "key_weakness": "notable limitation (max 30 words)"}}
  ],
  "trade_offs": [
    {{"dimension": "Performance vs DX etc.", "finding": "what evidence shows (max 60 words)", "impact": "who this matters for (max 40 words)"}}
  ],
  "evidence_summary": "Concise summary of evidence landscape (max 150 words)",
  "confidence": "high|medium|low",
  "confidence_rationale": "Why this confidence (max 50 words)",
  "unresolved_questions": ["question evidence couldn't answer"],
  "scene_fit_note": "Fit to scene context (max 80 words)"
}}"""


def build_source_registry(evidence_chains: list[dict]) -> dict:
    """The numbered source identities shared by every consumer of citations.

    Synthesis, literal-marker resolution, the self-review payload and reviewer
    revisions all read citations from this one registry, so a number, a canonical
    title and the body text behind them cannot disagree between the reporting
    paths. Only fact-bearing sources are registered; a navigation link is recorded
    separately and can never be cited.
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
            entry = {
                "number": number,
                "title": title,
                "url": str(source.get("url") or ""),
                "body": source_content(source),
                "provenance": source.get("provenance") or "",
                "channel": source.get("channel") or "",
                "disputed": bool(chain.get("disputed")),
            }
            chain_entries.append(entry)
            entries.append(entry)
        chains.append(chain_entries)

    by_norm: dict[str, list[dict]] = {}
    for entry in entries:
        by_norm.setdefault(_norm_title(entry["title"]), []).append(entry)
    return {
        "entries": entries,
        "chains": chains,
        "navigation": navigation,
        "mapping": {entry["number"]: entry["title"] for entry in entries},
        "by_norm": by_norm,
    }


def _summarize_chains(evidence_chains: list[dict],
                      candidate_techs: list[str] | None = None) -> tuple[str, dict[int, str]]:
    """Format evidence chains for the prompt, assigning each source a stable
    number ([[N]]) that the model cites instead of a verbatim title. Returns
    the rendered text plus the number -> title mapping used to bind citations
    back to [Source: title] after synthesis.

    Each source carries its URL and its bounded body text, not just a title and
    a score. The numbers come from `build_source_registry`, the same registry the
    citation engine and the self-review use, so prompt numbering and binding
    cannot drift apart. A source whose body was never collected is a navigation
    link: it gets no number and is listed separately.
    """
    from ..utils.candidate_identity import (
        bounded_content_summary,
        candidate_proper_nouns,
    )

    registry = build_source_registry(evidence_chains)
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
        return "\n".join(header + ["No evidence chains available."]), {}

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
            # Where the material came from, so the model cannot mistake local or
            # evaluation material for a published source.
            if entry["provenance"] or entry["channel"]:
                lines.append(f"       provenance: {entry['provenance'] or 'unknown'}; "
                             f"channel: {entry['channel'] or 'unknown'}")
            source_stub = {
                "title": entry["title"],
                "content": entry["body"],
            }
            lines.append(f"       content: {bounded_content_summary(source_stub)}")
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

    return "\n".join(lines), dict(registry["mapping"])


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
                    "conflicts was never tested.")
        return (f"Conflict check completed over {scanned} candidate pair(s) and "
                f"found no confirmed contradiction.")
    lines = []
    for i, c in enumerate(conflicts):
        lines.append(
            f"{i+1}. {c.get('claim_a', '')} vs {c.get('claim_b', '')} "
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
    return "\n".join(lines)


_GENERIC_WINNER_WORDS = {
    "flag", "gradual", "feature", "api", "app", "tool", "platform",
    "service", "system", "framework", "solution", "library", "package",
}


def _validate_winner(result: dict) -> dict:
    """Reject non-technology winners (repo paths, generic words) and fall back
    to the first valid ranked option. "context_dependent" is a valid winner for
    a genuine tie (rule 7) — never fall back, since no option should be forced."""
    winner = (result.get("winner") or "").strip()
    if winner.lower() == "context_dependent":
        return result
    if not winner or "/" in winner or winner.lower() in _GENERIC_WINNER_WORDS:
        for opt in result.get("ranked_options", []):
            name = (opt.get("name") or "").strip()
            if name and "/" not in name and name.lower() not in _GENERIC_WINNER_WORDS:
                result["winner"] = name
                break
    return result


_FIT_ORDER = {"high": 0, "medium": 1, "low": 2}


def _validate_constraint_fit(result: dict) -> dict:
    """Enforce ANTI-BIAS rule 4: if the winner is not among the highest
    constraint-fit ranked options, fall back to the highest-fit option.

    No-op when constraint_fit is absent (older/malformed outputs) — the
    validator must not corrupt a report that predates the field.
    """
    if (result.get("winner") or "").strip().lower() == "context_dependent":
        return result
    ranked = result.get("ranked_options", [])
    if not ranked:
        return result
    scored = []
    for opt in ranked:
        name = (opt.get("name") or "").strip()
        fit = (opt.get("constraint_fit") or "").strip().lower()
        if name and fit in _FIT_ORDER:
            scored.append((name, fit))
    if not scored:
        return result
    best_level = min(_FIT_ORDER[fit] for _, fit in scored)
    best_names = [name for name, fit in scored if _FIT_ORDER[fit] == best_level]
    winner = (result.get("winner") or "").strip()
    if winner.lower() in {n.lower() for n in best_names}:
        return result
    result["winner"] = best_names[0]
    return result


def _norm_title(s: str) -> str:
    """Lowercase + alphanumerics only — matches metrics._normalize_title."""
    return "".join(c for c in s.lower() if c.isalnum())


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in (text or ""))


# A closed marker, or one that never closes. The unclosed form runs to the end of
# the text: it is still a claimed citation, so it must be seen and handled rather
# than passing through as ordinary prose.
_SOURCE_MARKER = re.compile(r'\[Source:[^\]]*\]|\[Source:[^\]]*$', re.IGNORECASE)
# A source number, or a comma-separated list of them, with the spacing and sign
# variants a model may emit. Two guards keep ordinary text out of it, because a
# looser grammar resolved an interval or an array index to a real source and
# fabricated an attribution the model never made:
#   - the numbers must be unspaced, which separates `[[1,2]]` from `[[0, 1]]`;
#   - the marker must not sit in an indexing context. A preceding word or `]`
#     makes it a subscript (`arr[[1,2]]`, `arr[0][[1,2]]`), as does a following
#     `[`, `=` or `]` (`[[1,2]] = x`, `[[1,2]][0]`). A model writes a citation
#     after a space or punctuation and at the end of a clause, so those contexts
#     stay valid — including after CJK text, which is not an indexing host.
# The inner pattern excludes brackets so an unspaced pair of separate markers
# (`x[[1]]y[[2]]z`) is not read as one citation running across both.
_CITE_NUMBER = re.compile(
    r'(?<!\])(?<![A-Za-z0-9_])'
    r'\[\[(\s*[+-]?\d+(?:\s*[,;][+-]?\d+)*\s*)\]\]'
    r'(?!\s*[\[\]=])')
# A leftover marker holding only digits and separators. It is a citation this
# pipeline cannot resolve — `[[1 2]]`, `[[1, 2]]`, `[[1.0]]` — so it is reported
# as an unresolved citation rather than being printed as text or silently
# removed. A marker containing words (`[[附录]]`) is not matched and is left as
# written.
_CITE_LEFTOVER = re.compile(r'\[\[\s*[+\-0-9][0-9\s,;.\-]*\]\]')


# Every field the prompt asks to cite must be resolved and listed. Leaving one
# out left raw [[N]] markers in the rendered report: the model cites
# confidence_rationale, but nothing converted its numbers. Self-review
# completeness reads these same tuples.
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
_WITHDRAWN_NOTE_EN = ("(withdrawn: no cited source supports this claim)")


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


def has_substantive_content(text: str) -> bool:
    """Whether a field still says something beyond citation/gap markers.

    A field holding only citations is not an answer; it must not be counted as
    one even when every marker in it resolved.
    """
    stripped = _VISIBLE_STRIP.sub("", text or "")
    return bool(_VISIBLE_PUNCT.sub("", stripped))


def canonical_source_title(registry: dict, title: str) -> str | None:
    """The registered title a written title names, or None.

    Full identity first: the whole written title is compared after normalization,
    so a real title containing commas or semicolons is not split. If the same
    normalized title maps to more than one distinct source identity, the title is
    ambiguous and is not resolved to an arbitrary one of them.

    A canonical title emitted from a number is itself matched by this rule on a
    later pass. Two distinct registered sources that share one title make that
    emitted form ambiguous; because the ambiguity must not be resolved
    arbitrarily, a second pass over the same field keeps the gap rather than
    picking a source. Binding runs once per field in the normal path, so emitted
    canonical titles are not re-resolved there.
    """
    key = _norm_title(title or "")
    if not key:
        return None
    matches = registry.get("by_norm", {}).get(key, [])
    identities = {(entry["title"], entry["url"]) for entry in matches}
    if len(identities) != 1:
        return None
    return matches[0]["title"]


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


def _resolve_number_marker(marker: str, inner: str, mapping: dict[int, str],
                           context: str) -> str:
    """Bind a `[[N]]` marker's known numbers; leave unresolved ones as a gap.

    A marker containing a non-positive number is not a source list at all (an
    interval or array index), so it is left exactly as written: it never becomes
    a citation and never becomes a citation gap either.
    """
    numbers = [int(n) for n in re.findall(r"[+-]?\d+", inner)]
    if any(n <= 0 for n in numbers):
        return marker
    known: list[str] = []
    unknown: list[int] = []
    for number in numbers:
        title = mapping.get(number)
        if title and title not in known:
            known.append(title)
        elif title is None:
            unknown.append(number)
    parts: list[str] = []
    if known:
        parts.append("[Source: " + ", Source: ".join(known) + "]")
    if unknown:
        parts.append(citation_gap_number(unknown, context))
    return "".join(parts)


def _resolve_source_marker(marker: str, registry: dict, context: str) -> str:
    """Resolve a literal `[Source: title]` against the registered identities."""
    body = _SOURCE_TITLES_IN_MARKER.sub("", marker)
    if body.endswith("]"):
        body = body[:-1]
    parts = _split_literal_source_body(body)
    if not parts:
        return citation_gap_note(
            "缺少来源标题" if _has_cjk(context) else "missing source title", context)
    resolved: list[str] = []
    gaps: list[str] = []
    for part in parts:
        canonical = canonical_source_title(registry, part)
        if canonical and canonical not in resolved:
            resolved.append(canonical)
        else:
            # Includes the ambiguous case: a title that names more than one
            # registered source is not silently attached to one of them.
            gaps.append(citation_gap_title(part, context))
    out = ""
    if resolved:
        out += "[Source: " + ", Source: ".join(resolved) + "]"
    out += "".join(gaps)
    return out


def _in_indexing_context(text: str, start: int, end: int) -> bool:
    """Whether a numeric bracket sits where a citation would not.

    These are the same guards the number pattern itself uses; they keep array
    indices and matrix notation from being turned into citations or gaps.
    """
    before = (text or "")[:start].rstrip()
    if before:
        previous = before[-1]
        # A marker written immediately after another citation marker is another
        # citation, not an index into the preceding one.
        another_citation_before = bool(
            before.endswith("]]")
            and re.search(r"\[\[\s*[+-]?\d+(?:\s*[,;][+-]?\d+)*\s*\]\]$", before))
        if not another_citation_before and previous.isascii() and (
                previous.isalnum() or previous in "_]"):
            # ASCII word characters and `]` are the indexing contexts the number
            # pattern already excludes. CJK text is not an indexing host, so a
            # citation may follow it directly.
            return True
    after = (text or "")[end:].lstrip()
    if re.match(r"\[\[\s*[+-]?\d", after):
        # Another citation marker follows: this is the adjacent-marker case the
        # number pattern declines, not an index into the first marker.
        return False
    return bool(after) and after[0] in "[=]"


# One scanner over the text, so the order of handling a marker is explicit and a
# marker inserted by one rule is never re-read by another.
_CITATION_TOKEN = re.compile(
    r"(?P<number>" + _CITE_NUMBER.pattern + r")"
    r"|(?P<source>" + _SOURCE_MARKER.pattern + r")"
    r"|(?P<leftover>" + _CITE_LEFTOVER.pattern + r")",
    re.IGNORECASE)


def _bare_number_marker(marker: str) -> str | None:
    """The inner numbers of a simple `[[N]]` marker, or None.

    The number pattern deliberately declines a marker followed by another
    bracket (an index like `[[1,2]][0]`), which also catches two citation markers
    written next to each other (`[[16]] [[17]]`). When a leftover marker is a
    plain number list, it is a citation the model wrote, so it is resolved as one
    instead of being left behind as a raw marker.
    """
    match = re.fullmatch(r"\[\[\s*([+-]?\d+(?:\s*[,;][+-]?\d+)*)\s*\]\]",
                         marker)
    return match.group(1) if match else None


def resolve_text(text: str, evidence_chains: list[dict] | None = None,
                 mapping: dict[int, str] | None = None,
                 registry: dict | None = None) -> str:
    """Apply every citation rule to one block of text in a single pass.

    Known numbers and registered titles become the registered canonical title;
    anything that cannot be resolved is left as a locatable gap instead of being
    silently deleted. The result is the text the report should show; it is not a
    judgement that any cited source supports the sentence.
    """
    if not text:
        return text
    registry = registry or build_source_registry(evidence_chains or [])
    effective_mapping = (dict(registry.get("mapping") or {})
                         if mapping is None else mapping)
    out: list[str] = []
    last = 0
    for match in _CITATION_TOKEN.finditer(text):
        out.append(text[last:match.start()])
        marker = match.group(0)
        if match.group("number") is not None:
            inner = _CITE_NUMBER.match(marker).group(1)
            out.append(_resolve_number_marker(marker, inner, effective_mapping,
                                              text))
        elif match.group("source") is not None:
            out.append(_resolve_source_marker(marker, registry, text))
        else:
            if _in_indexing_context(text, match.start(), match.end()):
                out.append(marker)
                last = match.end()
                continue
            inner = _bare_number_marker(marker)
            if inner is not None:
                out.append(_resolve_number_marker(marker, inner,
                                                  effective_mapping, text))
            else:
                out.append(citation_gap_marker(marker, text))
        last = match.end()
    out.append(text[last:])
    return "".join(out)


def citation_field_locations(result: dict) -> list[tuple[str, dict, str]]:
    """Every field the pipeline asks the model to cite, with a stable locator.

    One traversal for binding, for the self-review completeness report and for
    the reviewer's revision parsing; the three cannot miss a different set.
    """
    locations: list[tuple[str, dict, str]] = []
    for field in _CITATION_TEXT_FIELDS:
        if result.get(field):
            locations.append((field, result, field))
    for option in result.get("ranked_options") or []:
        if not isinstance(option, dict):
            continue
        label = str(option.get("name") or "?")
        for field in _CITATION_OPT_FIELDS:
            if option.get(field):
                locations.append((f"option={label}/{field}", option, field))
    for trade_off in result.get("trade_offs") or []:
        if not isinstance(trade_off, dict):
            continue
        label = str(trade_off.get("dimension") or "?")
        for field in _CITATION_TRADEOFF_FIELDS:
            if trade_off.get(field):
                locations.append((f"trade-off={label}/{field}", trade_off, field))
    return locations


def apply_citation_rules(result: dict, evidence_chains: list[dict],
                         mapping: dict[int, str] | None = None) -> dict:
    """Resolve citations in every cited field exactly once.

    Replaces the previous two-pass scrub-then-bind sequence, whose scrub step
    could truncate a bound title at a comma. A field that carried prose and is
    left with no substantive content (only markers or unresolved gaps) is
    recorded as withdrawn rather than silently blanked.
    """
    registry = build_source_registry(evidence_chains)
    effective_mapping = (dict(registry["mapping"]) if mapping is None else mapping)
    for _locator, container, field in citation_field_locations(result):
        original = str(container[field])
        resolved = resolve_text(original, registry=registry,
                                mapping=effective_mapping)
        if has_substantive_content(original) and not has_substantive_content(resolved):
            resolved = withdrawal_note(original)
        container[field] = resolved
    return result


def unresolved_citations(text: str, evidence_chains: list[dict] | None = None,
                         registry: dict | None = None) -> bool:
    """True when text still carries a citation this pipeline could not resolve.

    That includes a gap marker, a raw number marker, or a literal `[Source:]`
    whose titles are not all registered. A non-positive number marker (interval,
    array index) is not a citation and is not counted. This says the citation is
    unresolved; it does not say the sentence is false.
    """
    if not text:
        return False
    if _CITATION_GAP_MARK.search(text):
        return True
    registry = registry or build_source_registry(evidence_chains or [])
    for match in _CITATION_TOKEN.finditer(text):
        if match.group("number") is not None:
            inner = _CITE_NUMBER.match(match.group(0)).group(1)
            numbers = [int(n) for n in re.findall(r"[+-]?\d+", inner)]
            if any(n <= 0 for n in numbers):
                continue
            return True
        if match.group("source") is not None:
            body = _SOURCE_TITLES_IN_MARKER.sub("", match.group(0))
            if body.endswith("]"):
                body = body[:-1]
            parts = _split_literal_source_body(body)
            if not parts:
                return True
            for part in parts:
                if canonical_source_title(registry, part) is None:
                    return True
        else:
            if not _in_indexing_context(text, match.start(), match.end()):
                return True
    return False


_BOUND_SOURCE_MARKER = re.compile(r"\[Source:[^\]]*\]")


def has_bound_citation(text: str, registry: dict) -> bool:
    """Whether text carries at least one citation resolved to a registered source.

    Identity/format only: this says a citation is attached and resolvable, not
    that the cited source supports the sentence.
    """
    for match in _BOUND_SOURCE_MARKER.finditer(text or ""):
        body = _SOURCE_TITLES_IN_MARKER.sub("", match.group(0))
        if body.endswith("]"):
            body = body[:-1]
        parts = _split_literal_source_body(body)
        if parts and all(canonical_source_title(registry, part) for part in parts):
            return True
    return False


def resolve_citations(text: str, evidence_chains: list[dict],
                      mapping: dict[int, str] | None = None,
                      registry: dict | None = None) -> str:
    """Resolve one block of text with this pipeline's citation rules.

    Synthesis and the self-review's revisions both call this, and the caller may
    pass the same registry the source list was rendered from. A block that loses
    all substantive content becomes the withdrawal note.
    """
    if not text:
        return text
    registry = registry or build_source_registry(evidence_chains)
    effective_mapping = (dict(registry["mapping"]) if mapping is None else mapping)
    resolved = resolve_text(text, registry=registry, mapping=effective_mapping)
    if has_substantive_content(text) and not has_substantive_content(resolved):
        return withdrawal_note(text)
    return resolved


def clean_label(text: str) -> str:
    """Strip citation markers from a display label.

    A trade-off `dimension` is a label, not a factual claim: the model put source
    numbers in it and they were printed verbatim ("内存效率与成本 [[16]]").
    The label is not a field that can be revised — it is also the key the
    self-review uses to locate a trade-off — so the markers are removed and the
    remaining text is the one identity used for both display and locating.

    Reuses the compiled marker patterns already used for citation handling; no
    second grammar is introduced.
    """
    if not text:
        return text
    cleaned = _CITE_NUMBER.sub("", str(text))
    cleaned = _CITE_LEFTOVER.sub("", cleaned)
    cleaned = _SOURCE_MARKER.sub("", cleaned)
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

        evidence_text, cite_map = _summarize_chains(
            evidence_chains, task.get("candidate_techs") or [])
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

        quality_signals = [{
            "agent": "conclusion_synthesizer",
            "evidence_chain_count": len(evidence_chains),
            # Sources that appeared in a compared pair; not a contradiction count.
            "flagged_sources": flagged_source_count,
            "options_ranked": len(result.get("ranked_options", [])),
            "synthesis_confidence": result.get("confidence", "low"),
        }]

        _validate_winner(result)
        _validate_constraint_fit(result)
        # One pass over one shared field list: numbers and literal titles are
        # resolved against the same numbered source registry the prompt used, a
        # bound title is canonicalised once, and an unresolvable citation stays
        # visible as a gap instead of being deleted.
        apply_citation_rules(result, evidence_chains, cite_map)
        _normalize_labels(result)

        return {
            "final_recommendation": result,
            "quality_signals": quality_signals,
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conclusion_synthesizer", local_usage)],
        }
