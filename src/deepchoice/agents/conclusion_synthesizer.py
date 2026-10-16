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

## Evidence Chains (with strength ratings)
{evidence_chains}

## Conflicts Found
{conflicts}

## Source Score Summary
Total sources scored: {source_count}
Strong evidence chains (strength=strong): {strong_count}
Disputed findings: {disputed_count}

## Language
- Output explanatory/reasoning text (recommendation, rationale, trade-off findings, evidence_summary, confidence_rationale, scene_fit_note) in the SAME language as the original query.
- Technical terms (framework names, API names, algorithms, protocol names), source titles, and benchmark data MUST stay in their original language — do NOT translate them.
- This applies to the "name" field in ranked_options as well: keep the framework/library name as-is.

## Synthesis Rules
1. Weight strong evidence chains more heavily than moderate or weak ones
2. Acknowledge disputed findings — don't pretend they don't exist
3. Scene context is a TILT, not a decree — solo devs often lean simplicity/speed, enterprises reliability/scale, but strong evidence for a different dimension (control, durability) can still win. Scene narrows the choice; it never forces it.
4. ANTI-BIAS (MANDATORY three-step): Step 1 — list the constraints from Scene Context that affect this choice. Step 2 — rate each candidate's constraint-fit (high/medium/low). Step 3 — the winner MUST be the highest constraint-fit candidate, even if it is less popular or newer than a competitor with more GitHub stars or search results. Only override with a lower-fit candidate if there is overwhelming counter-evidence, and state it in winner_rationale. If the highest constraint-fit is TIED, set "winner" to "context_dependent" (rule 7).
5. If evidence is insufficient for a definitive answer, say so honestly
6. INLINE CITATIONS REQUIRED — EVERY sentence and EVERY field MUST end with a source number in double brackets, e.g. "Use FastAPI [[1]]." — no sentence or field may be left uncited, no matter how short. Short fields are factual assertions, NOT labels: key_strength, key_weakness, and impact must EACH carry a [[N]] (e.g. "key_strength": "Mature role-based abstraction [[1]]"). recommendation: EVERY sentence, INCLUDING the opening "Adopt X ..." sentence and any closing summary sentence, must carry its own [[N]]. winner_rationale, rationale, finding, scene_fit_note, and every evidence_summary sentence: same rule. CRITICAL: copy the number VERBATIM from the Evidence sources above — NEVER invent a number that is not listed.
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


def _summarize_chains(evidence_chains: list[dict],
                      candidate_techs: list[str] | None = None) -> tuple[str, dict[int, str]]:
    """Format evidence chains for the prompt, assigning each source a stable
    number ([[N]]) that the model cites instead of a verbatim title. Returns
    the rendered text plus the number -> title mapping used to bind citations
    back to [Source: title] after synthesis.

    Each source carries its URL and its bounded body text, not just a title and
    a score. A title is an identity, not a statement: a source whose body was
    never collected is a navigation link, is excluded from the citable set and
    from the citation mapping, and is listed separately as non-citable. That way
    naming such a page by its title cannot smuggle it in as a source either.
    """
    from ..utils.candidate_identity import (
        bounded_content_summary,
        candidate_proper_nouns,
    )

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
        "Evidence sources — cite each by its number in double brackets, e.g. [[1]]:",
        "",
    ]
    mapping: dict[int, str] = {}
    navigation: list[str] = []
    n = 0
    for i, c in enumerate(evidence_chains):
        strength = c.get("evidence_strength", "unknown")
        disputed = " [DISPUTED]" if c.get("disputed") else ""
        citable = [s for s in c.get("sources", [])[:4] if is_citable_source(s)]
        for src in c.get("sources", [])[:4]:
            if not is_citable_source(src):
                link = src.get("url", "")
                if link and link not in navigation:
                    navigation.append(link)
        lines.append(f"Chain {i + 1} [{strength}]{disputed}: {c.get('conclusion', 'Untitled')}")
        if not citable:
            lines.append("  no fact-bearing source — this chain states nothing on its "
                         "own; record a material gap instead of citing it")
            lines.append("")
            continue
        for src in citable:
            n += 1
            title = src.get("title", "Unknown")
            mapping[n] = title
            url = src.get("url", "")
            lines.append(f"  [[{n}]] {title} (score: {src.get('score', 'N/A')})")
            if url:
                lines.append(f"       url: {url}")
            lines.append(f"       content: {bounded_content_summary(src)}")
        lines.append("")

    if navigation:
        # Discovered links, not evidence. They carry no citable number, so they
        # cannot be cited even by writing their title verbatim.
        lines += [
            "## Navigation links — NOT citable",
            "",
            "These pages were found but no body was collected, so they state nothing "
            "here. Do not cite them, and do not write their titles as a source:",
            "",
        ]
        lines += [f"- {link}" for link in navigation[:10]]
        lines.append("")

    return "\n".join(lines), mapping


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


def _is_real_title(norm: str, real: set[str]) -> bool:
    """Exact match against a real source title.

    Substring matching was relaxed to accept a long fragment, but a shorter title
    is often a substring of a longer real one: 'PostgreSQL — Official
    Documentation' sits inside a fuller page title, so a body-less navigation
    link passed as a real source and the renderer then re-attached it. A citation
    must name a source that exists, exactly.
    """
    return norm in real


def _sanitize_text(text: str, real: set[str]) -> str:
    """Remove fabricated [Source: title] citations from a text block, keeping
    only titles whose normalized form is in `real`.

    A marker missing its closing bracket is also removed. It is not a citation
    the report can use, and leaving it would both display a fabricated title and
    hide it from the checks below, which look for closed markers.
    """
    if not text:
        return text
    out: list[str] = []
    last = 0
    for m in _SOURCE_MARKER.finditer(text):
        out.append(text[last:m.start()])
        titles = re.split(r'Source:\s*', m.group(0), flags=re.IGNORECASE)[1:]
        kept = []
        for t in titles:
            title = re.split(r'[,;\[\]]', t)[0].strip()
            if title and _is_real_title(_norm_title(title), real):
                kept.append(title)
        if kept:
            out.append('[Source: ' + ', Source: '.join(kept) + ']')
        last = m.end()
    out.append(text[last:])
    return ''.join(out)


# A closed marker, or one that never closes. The unclosed form runs to the end of
# the text: it is still a claimed citation, so it must be seen and removed rather
# than passing through as ordinary prose.
_SOURCE_MARKER = re.compile(r'\[Source:[^\]]*\]|\[Source:[^\]]*$', re.IGNORECASE)
# A source number, or a list of them, with the spacing, sign and bracket-nesting
# variants a model may emit. The match runs only to the first closing pair, so
# malformed forms like [[1][2]] are treated as one marker naming source 1 rather
# than left behind as text. Anything mapping to no entry is dropped.
_CITE_NUMBER = re.compile(r'\[\[(.+?)\]\]')


_WITHDRAWN_NOTE = "（本项理由已被自审撤回：无可引来源支持其论断）"
_WITHDRAWN_NOTE_EN = ("(withdrawn: no cited source supports this claim)")


def withdrawal_note(text: str) -> str:
    """The note that replaces a claim nothing citable supports.

    Follows the language of the field it replaces, so a withdrawn claim reads as
    part of the report rather than as a stray foreign sentence. Shared by the
    synthesis scrub and the self-review, so a withdrawal looks the same wherever
    it happens.
    """
    if text and any("\u4e00" <= c <= "\u9fff" for c in text):
        return _WITHDRAWN_NOTE
    return _WITHDRAWN_NOTE_EN


def is_citable_source(source: dict) -> bool:
    """Whether a source may be cited: it must have collected body text.

    The single predicate behind the citable set, the number mapping and the
    sanitizer, so those three cannot disagree about what counts as a basis.
    """
    from ..utils.candidate_identity import has_factual_content

    return has_factual_content(source)


def _citable_titles(evidence_chains: list[dict]) -> set[str]:
    """The normalized titles that may be cited: fact-bearing sources only."""
    real: set[str] = set()
    for c in evidence_chains or []:
        for src in c.get("sources", [])[:4]:
            if not is_citable_source(src):
                continue
            t = src.get("title", "")
            if t:
                real.add(_norm_title(t))
    return real


def unresolved_citations(text: str, evidence_chains: list[dict]) -> bool:
    """True when text still carries a citation that names nothing citable.

    A resolved citation is a `[Source: title]` whose titles are all in the
    citable set. A `[[N]]` number is only valid if the mapping covered it, and
    resolution replaces those, so any surviving number is out of range. A
    verbatim title that is not in the set is a fabrication. Either means the
    text claims support that does not exist.
    """
    if not text:
        return False
    if _CITE_NUMBER.search(text):
        return True
    real = _citable_titles(evidence_chains)
    for m in _SOURCE_MARKER.finditer(text):
        for t in re.split(r'Source:\s*', m.group(0), flags=re.IGNORECASE)[1:]:
            title = re.split(r'[,;\[\]]', t)[0].strip()
            if title and not _is_real_title(_norm_title(title), real):
                return True
    return False


def resolve_citations(text: str, evidence_chains: list[dict],
                      mapping: dict[int, str]) -> str:
    """Apply this pipeline's citation rules to one block of text.

    Verbatim titles are scrubbed against the citable set, source numbers are
    bound through the mapping built from that same set, and the result is
    scrubbed again so a bound title cannot become a route around the check.
    Unknown titles, navigation-only sources and out-of-range numbers all
    disappear; a legitimate citation survives unchanged.

    Both synthesis and the self-review's revisions use this, so a revision
    cannot reintroduce a citation the synthesizer would have removed. This
    keeps citation identity and handling consistent; it is not a claim that a
    cited source supports the sentence it is attached to.
    """
    if not text:
        return text
    # These helpers walk the known field names of a synthesis result, so the
    # block is passed under one of those names rather than an ad-hoc key.
    holder = {"recommendation": text}
    holder = _sanitize_citations(
        _bind_citations({"recommendation": _sanitize_text(text, _citable_titles(evidence_chains))},
                        mapping),
        evidence_chains,
    )
    return holder["recommendation"]


# Every field the prompt asks to cite must be bound and sanitized. Leaving one
# out left raw [[N]] markers in the rendered report: the model cites
# confidence_rationale, but nothing converted its numbers.
_CITATION_TEXT_FIELDS = ("recommendation", "winner_rationale",
                         "evidence_summary", "scene_fit_note",
                         "confidence_rationale")
_CITATION_OPT_FIELDS = ("rationale", "key_strength", "key_weakness", "constraint_fit_reason")
_CITATION_TRADEOFF_FIELDS = ("finding", "impact")


def _sanitize_citations(result: dict, evidence_chains: list[dict]) -> dict:
    """Strip hallucinated [Source: title] citations (title not among the real
    source titles fed to the synthesizer) from every factual claim field.

    Only fact-bearing sources are real here. A discovered page with no collected
    body is a navigation link, so writing its title as a source is stripped just
    like any other fabrication.
    """
    real = _citable_titles(evidence_chains)

    def _clean(value: str) -> str:
        """Scrub a field, and record that it has no content left.

        A field whose entire content was a fabricated marker becomes empty.
        Emptied is not the same as never having had content: the claim was
        withdrawn by this pass, and printing a blank leaves the reader unable to
        tell the difference. The marker is replaced with a withdrawal note.
        """
        cleaned = _sanitize_text(value, real)
        return cleaned if cleaned.strip() else withdrawal_note(value)

    for field in _CITATION_TEXT_FIELDS:
        if result.get(field):
            result[field] = _clean(result[field])
    for opt in result.get("ranked_options", []):
        for field in _CITATION_OPT_FIELDS:
            if opt.get(field):
                opt[field] = _clean(opt[field])
    for to in result.get("trade_offs", []):
        for field in _CITATION_TRADEOFF_FIELDS:
            if to.get(field):
                to[field] = _clean(to[field])
    return result


def _bind_citations(result: dict, mapping: dict[int, str]) -> dict:
    """Replace source-number citations [[N]] with the real [Source: title]
    they denote. Unknown numbers are dropped (never fabricated). Runs AFTER
    _sanitize_citations so verbatim [Source: ...] is scrubbed first and the
    bound titles are not re-processed by the title sanitizer."""
    def _bind(text: str) -> str:
        if not text:
            return text

        def _sub(m: re.Match[str]) -> str:
            # The marker may name several sources, or be malformed. The leading
            # number is what it cites, and any further numbers in the same pair
            # are additional sources. A number with no entry is dropped, and if
            # none resolve the whole marker disappears rather than leaving its
            # digits behind as text.
            numbers = re.findall(r'\d+', m.group(1))
            if not numbers:
                return ""
            titles = [mapping[int(n)] for n in numbers if int(n) in mapping]
            if not titles:
                return ""
            return '[Source: ' + ', Source: '.join(titles) + ']'

        return _CITE_NUMBER.sub(_sub, text)

    for field in _CITATION_TEXT_FIELDS:
        if result.get(field):
            result[field] = _bind(result[field])
    for opt in result.get("ranked_options", []):
        for field in _CITATION_OPT_FIELDS:
            if opt.get(field):
                opt[field] = _bind(opt[field])
    for to in result.get("trade_offs", []):
        for field in _CITATION_TRADEOFF_FIELDS:
            if to.get(field):
                to[field] = _bind(to[field])
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

        strong_count = sum(1 for c in evidence_chains if c.get("evidence_strength") == "strong")
        disputed_count = sum(1 for c in evidence_chains if c.get("disputed"))

        evidence_text, cite_map = _summarize_chains(
            evidence_chains, task.get("candidate_techs") or [])
        prompt = [{
            "role": "user",
            "content": SYNTHESIS_PROMPT.format(
                query=task["query"],
                scene_context=task.get("scene_context", "team"),
                evidence_chains=evidence_text,
                conflicts=_summarize_conflicts(conflicts, conflict_check),
                source_count=len(research_state.get("source_scores", [])),
                strong_count=strong_count,
                disputed_count=disputed_count,
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
            "strong_chains": strong_count,
            "disputed_chains": disputed_count,
            "options_ranked": len(result.get("ranked_options", [])),
            "synthesis_confidence": result.get("confidence", "low"),
        }]

        _validate_winner(result)
        _validate_constraint_fit(result)
        _sanitize_citations(result, evidence_chains)
        _bind_citations(result, cite_map)

        return {
            "final_recommendation": result,
            "quality_signals": quality_signals,
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conclusion_synthesizer", local_usage)],
        }
