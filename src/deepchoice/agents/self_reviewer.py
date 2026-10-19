from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output
from .conclusion_synthesizer import (
    CITATION_SOURCES_KEY,
    _CITATION_OPT_FIELDS,
    _CITATION_TEXT_FIELDS,
    _CITATION_TRADEOFF_FIELDS,
    build_source_registry,
    citation_field_locations,
    citation_gap_present,
    clean_label,
    field_locator,
    has_substantive_content,
    resolve_citations_with_sources,
    unresolved_citations,
    withdrawal_note,
)
from .report_generator import render_report

# The fields the reviewer may correct: only the justification text it is asked to
# check. The choice, the ranking order and the candidate names are not the
# reviewer's to change.
#
# The set is the same traversal the citation binding uses — one definition, so a
# field cannot be bound but unreviewed, or reviewed but impossible to bind. It
# covers every field the result carries, not only the ones one report format
# happens to print: a decisive error in the evidence summary, a constraint-fit
# reason, the confidence rationale or a trade-off impact is served to the reader
# through the snapshot and other formats. The contract sent to the model and the
# review body are generated from it, so review coverage cannot depend on the
# user's report format.
_CORRECTABLE_OPTION_FIELDS = tuple(_CITATION_OPT_FIELDS)
_CORRECTABLE_TOP_FIELDS = tuple(_CITATION_TEXT_FIELDS)
_CORRECTABLE_TRADEOFF_FIELDS = tuple(_CITATION_TRADEOFF_FIELDS)
_CORRECTABLE_FIELDS = (_CORRECTABLE_OPTION_FIELDS + _CORRECTABLE_TOP_FIELDS
                       + _CORRECTABLE_TRADEOFF_FIELDS)


def _field_map() -> str:
    """The contract's field list, generated from the one registry above.

    Written from the same tuple the applier uses, so the two cannot drift: a
    field added to the registry is described to the model automatically, and a
    field the applier does not accept cannot appear here.
    """
    return (
        "* per-candidate (option = candidate name): "
        + ", ".join(_CORRECTABLE_OPTION_FIELDS) + "\n"
        "* top-level (option = \"\"): "
        + ", ".join(_CORRECTABLE_TOP_FIELDS) + "\n"
        "* trade-off (option = dimension): "
        + ", ".join(_CORRECTABLE_TRADEOFF_FIELDS)
    )


REVIEW_SYSTEM = f"""You are a rigorous quality reviewer. Evaluate research reports against a 6-item checklist.

Answer YES or NO for each, with a brief note:
1. Source support: the pipeline only verifies that a citation names a registered source; a citation marker is NOT proof that the source supports the specific claim. For each decisive claim you check, compare the claim against the source body in the Source Register.
2. Citation completeness: the "Citation Completeness" section is computed from the same field list that binding uses. It lists fields with no citation and fields whose citation could not be resolved. Treat both as things to check, not as automatic truth verdicts: an uncited claim may still be a recorded gap, and an unresolved citation is not evidence that the claim is false.
3. Does the recommendation cover all 5 comparison dimensions? (Functionality, Performance, Ecosystem, Developer Experience, Scenario Fit) Does it respect the "Declared Constraints", and does it state what constraint or evidence would change the recommendation when the answer is conditional?
4. Are there unlabeled information conflicts? The recorded conflicts, if any, are under "Recorded Conflicts"; compare their resolutions with the claims in the fields.
5. Are any user sub-questions unanswered? Check each original sub-question and every declared constraint against the fields below, and say which ones have no substantive answer rather than only a marker or a gap note. A knowledge gap list entry does not answer a required item by itself.
6. Are there counter-examples or negative findings not flagged?

Confidence Assessment:
- high: 5-6/6 passed, no critical gaps
- medium: 3-4 items passed, no critical gaps
- low: 0-2 items passed OR critical information missing

If confidence is not "high", list specific information gaps as search queries.

Return ONLY a JSON object (numbers are examples; give your own real values):
{{"checks": [{{"item": 1, "passed": true, "note": "..."}}], "passed_count": 5, "confidence": "high|medium|low", "knowledge_gaps": ["gap query"], "critical_gaps": ["critical gap"], "corrections": [{{"option": "<selector, see below>", "field": "<field name, see below>", "action": "revise|withdraw", "corrected": "<field text with the error fixed, using only what a cited source supports; omit for withdraw>", "reason": "<what was wrong and which source contradicts it>"}}]}}

"corrections" is how a decisive error is fixed, not merely noted. A decisive
error is a figure, unit or scale the cited source does not state (or states
differently), a justification no source supports, or a candidate dismissed for a
reason the sources do not support — anywhere the served fields state it. For
every one, return a correction entry that names WHERE it is stated:
- "option" is the selector. For a per-candidate field it is that candidate's
  exact name as shown in "Fields To Review". For a trade-off field it is that
  trade-off's dimension, exactly as shown there. Leave it empty ("") for a
  top-level field.
- "field" is one of the fields listed here — the only fields that can be
  corrected. Every listed field the result carries is present in "Fields To
  Review" with its current text, regardless of which report format the user
  selected; a field absent from the result cannot be corrected:
{_field_map()}
- "action": "revise" with the corrected field text when a cited source supports
  a corrected version — keep everything in the field that is still supported,
  change only what is wrong, and do not blank the field; "withdraw" when no cited
  source supports the claim at all, in which case that one field is replaced with
  a note that it was withdrawn.

You are not asked to invent a better answer. If the material does not support a
corrected version, withdraw the claim or leave the field out of "corrections"
entirely and record the gap in knowledge_gaps. Do not emit a correction without a
"reason" naming the source that contradicts the claim, and do not fill a field
from your own knowledge.

A decisive error reported only in knowledge_gaps is left displayed unchanged,
which is not acceptable: it must also appear in "corrections". An error you
cannot correct or withdraw from the material given — because the field is missing
from the list above, or you cannot tell which entry owns it — goes in
knowledge_gaps and is left as it is."""

# "option" may name a ranked option, a trade-off dimension, or be omitted for a
# top-level field. These are matched case-insensitively on the trimmed value.
_LEVELS = {"low": 0, "medium": 1, "high": 2}


def _normalize_confidence(value) -> str | None:
    """Map a reviewer's confidence to one of the three levels, or None."""
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    level = value.strip().lower()
    return level if level in _LEVELS else None


def _set_field_bindings(recommendation: dict, locator: str,
                        bindings: list[dict]) -> None:
    """Record (or clear) the registered identities of one revised field."""
    identity_map = recommendation.get(CITATION_SOURCES_KEY)
    if not isinstance(identity_map, dict):
        identity_map = {}
        recommendation[CITATION_SOURCES_KEY] = identity_map
    if bindings:
        identity_map[locator] = bindings
    else:
        identity_map.pop(locator, None)


def _apply_corrections(recommendation: dict, corrections,
                       evidence_chains: list[dict] | None = None,
                       cite_map: dict[int, str] | None = None,
                       registry: dict | None = None) -> tuple[list[dict], list[str]]:
    """Apply the reviewer's field-level corrections to the recommendation.

    Deterministic: the reviewer says which field is wrong and what the source
    supports; this replaces that field and nothing else. A decisive error is
    therefore fixed or withdrawn in the served result instead of only lowering
    confidence, and the untouched answers are preserved.

    `option` selects a ranked option by name, or a trade-off by dimension; it may
    be empty for a top-level field such as `recommendation`.

    Revised text goes through the same resolution synthesis uses, against the same
    numbered registry: a registered title is canonicalised, an unregistered one
    stays visible as a located gap, and a revision that says nothing beyond
    markers is withdrawn rather than counted as an answer. A revised field's
    identity bindings are written to the recommendation's citation map under the
    same locator, so a reviewer revision cannot fall back to title guessing in the
    report renderers.
    """
    applied: list[dict] = []
    rejected: list[str] = []
    if not isinstance(corrections, list):
        return applied, rejected
    evidence_chains = evidence_chains or []
    cite_map = cite_map or {}
    options = [o for o in (recommendation.get("ranked_options") or [])
               if isinstance(o, dict)]
    trade_offs = [t for t in (recommendation.get("trade_offs") or [])
                  if isinstance(t, dict)]
    for item in corrections:
        if not isinstance(item, dict):
            rejected.append("correction is not an object")
            continue
        name = str(item.get("option") or "").strip()
        field = str(item.get("field") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        if field not in _CORRECTABLE_FIELDS:
            rejected.append(f"field not correctable: {field!r}")
            continue
        if action not in ("revise", "withdraw"):
            rejected.append(f"unknown action: {action!r}")
            continue
        if not reason:
            # A correction without a stated basis is not applied.
            rejected.append(f"no reason given for {name}/{field}")
            continue

        # Resolve the owner by field family first. A top-level field is not owned
        # by a ranked option, so a correction that happens to name one must still
        # reach the top level rather than being rejected as absent from it.
        target = None
        owner = ""
        if field in _CORRECTABLE_TOP_FIELDS:
            target, owner = recommendation, field
        elif field in _CORRECTABLE_TRADEOFF_FIELDS:
            # The label the reviewer sees is the normalised one, so locating uses
            # the same identity: both sides are cleaned with the same helper, and
            # a marker the reviewer echoes back cannot make the entry unfindable.
            wanted = clean_label(name).casefold()
            match = next((t for t in trade_offs
                          if wanted and clean_label(str(t.get("dimension", ""))).casefold()
                          == wanted), None)
            if match is None and not name and len(trade_offs) == 1:
                match = trade_offs[0]
            if match is None:
                rejected.append(f"cannot tell which trade-off owns {field!r}")
                continue
            target, owner = match, str(match.get("dimension") or field)
        else:
            target = next((o for o in options
                           if str(o.get("name", "")).strip().casefold() == name.casefold()),
                          None)
            if target is None:
                rejected.append(f"unknown option: {name!r}")
                continue
            owner = str(target.get("name") or name)
        if field not in target:
            rejected.append(f"{field!r} is not present on the named entry")
            continue

        if field in _CORRECTABLE_TOP_FIELDS:
            locator = field_locator(recommendation, field)
        elif field in _CORRECTABLE_TRADEOFF_FIELDS:
            locator = field_locator(target, field, "trade-off")
        else:
            locator = field_locator(target, field, "option")

        before = target.get(field)
        if action == "withdraw":
            target[field] = withdrawal_note(str(recommendation.get("recommendation") or ""))
            _set_field_bindings(recommendation, locator, [])
        else:
            corrected = str(item.get("corrected") or "").strip()
            if not corrected:
                rejected.append(f"revise without corrected text: {name}/{field}")
                continue
            # The revision goes through the same citation rules as synthesis,
            # against the same numbered registry the reviewer read. A citation
            # that cannot be resolved stays visible as a gap, so the reviewer's
            # prose is neither silently stripped nor presented as supported. A
            # revision that is nothing but markers has no substantive content and
            # is withdrawn rather than counted as an answer.
            resolved, bindings = resolve_citations_with_sources(
                corrected, evidence_chains, cite_map, registry=registry)
            if not has_substantive_content(resolved):
                target[field] = withdrawal_note(
                    str(recommendation.get("recommendation") or ""))
                _set_field_bindings(recommendation, locator, [])
                applied.append({
                    "option": owner, "field": field, "action": "withdraw",
                    "withdrawn_marker": True,
                    "reason": ("revision left nothing citable in the field: "
                               + reason)[:200],
                    "changed": before != target.get(field),
                })
                continue
            target[field] = resolved
            _set_field_bindings(recommendation, locator, bindings)
        applied.append({"option": owner, "field": field, "action": action,
                        "reason": reason[:200], "changed": before != target.get(field)})
    return applied, rejected




def _citation_coverage(fr: dict, evidence_chains: list[dict] | None = None,
                       registry: dict | None = None) -> dict:
    """Deterministic citation completeness for the self-review input.

    This is a completeness report, not a support judgement. It walks the same
    field list that citation binding walks, so a field cannot be counted by one
    rule and missed by another, and it lists the fields that carry no citation
    or carry a citation that could not be resolved. Neither is a truth verdict:
    an uncited claim may be a recorded gap, and an unresolved citation is not
    evidence that the claim is false.

    When the recommendation carries the registered identity map, completeness is
    read from it; a display title shared by two sources therefore does not make a
    correctly resolved citation look unresolved. Only historical material without
    the map falls back to title inspection.
    """
    from .conclusion_synthesizer import has_bound_citation

    registry = registry or build_source_registry(evidence_chains or [])
    locations = citation_field_locations(fr)
    identity_map = fr.get(CITATION_SOURCES_KEY)
    identity_map = identity_map if isinstance(identity_map, dict) else None
    uncited: list[str] = []
    unresolved: list[str] = []
    for locator, container, field in locations:
        text = str(container.get(field) or "")
        if identity_map is not None and locator in identity_map:
            cited = bool(identity_map.get(locator))
            unresolved_flag = citation_gap_present(text)
        else:
            # No identity for this field: historical text, or a partial map from
            # a record revised later. Title inspection is the honest fallback and
            # never guesses an ambiguous source.
            cited = has_bound_citation(text, registry)
            unresolved_flag = unresolved_citations(text, registry=registry)
        if not cited:
            uncited.append(locator)
        if unresolved_flag:
            unresolved.append(locator)
    return {
        "total_fields": len(locations),
        "cited_fields": len(locations) - len(uncited),
        "uncited_fields": len(uncited),
        "uncited_locations": uncited,
        "unresolved_locations": unresolved,
    }


def _source_register_text(registry: dict, limit: int = 900) -> str:
    """The numbered sources, with full title, URL and body, for the reviewer.

    Rendered from the same registry the synthesizer numbered its prompt with, so
    the reviewer can cite a number back into a revision and the number means the
    same source in both paths. The body is the same extraction the report uses,
    not a separate snippet-only summary.
    """
    entries = registry.get("entries") or []
    if not entries:
        return "No citable sources were registered."
    lines: list[str] = []
    for entry in entries:
        lines.append(f"[[{entry['number']}]] {entry['title']}")
        if entry.get("url"):
            lines.append(f"    url: {entry['url']}")
        if entry.get("date"):
            lines.append(f"    date: {entry['date']}")
        body = " ".join(str(entry.get("body") or "").split())
        if len(body) > limit:
            body = body[:limit].rstrip() + "…"
        lines.append(f"    body: {body or '(no body text stored)'}")
    if registry.get("navigation"):
        lines.append("")
        lines.append("Navigation links (no body collected; NOT citable):")
        lines += [f"- {link}" for link in registry["navigation"][:10]]
    return "\n".join(lines)


def _bound_sources_line(recommendation: dict, locator: str, text: str) -> str:
    """The registered identities bound to one reviewed field, if recorded.

    Reads the citation identity map the synthesizer/revision wrote; it never
    re-derives a source from a displayed title. A historical record has no map at
    all; a partial map (an older record revised later) has no entry for the
    untouched field, which is stated as unrecorded rather than guessed — even
    though completeness may title-inspect such a field for its historical count.
    """
    identity_map = recommendation.get(CITATION_SOURCES_KEY)
    if not isinstance(identity_map, dict):
        return ("Bound sources: not recorded (historical material; "
                "not re-derived from titles)")
    bindings = identity_map.get(locator) or []
    if not bindings:
        if "[Source:" in (text or ""):
            return ("Bound sources: not recorded for this field "
                    "(markers present; title-inspected for completeness only, "
                    "not re-derived as an identity)")
        return "Bound sources: none recorded for this field"
    parts: list[str] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        number = binding.get("number")
        title = str(binding.get("title") or "")
        url = str(binding.get("url") or "")
        label = f"[[{number}]] {title}" if number is not None else title
        if url:
            label += f" — {url}"
        if label and label not in parts:
            parts.append(label)
    return "Bound sources: " + ("; ".join(parts) if parts else "none recorded")


def _review_fields_text(recommendation: dict) -> str:
    """The complete, located body of every correctable field to review.

    Generated from the shared citation traversal, so review coverage is the same
    set the binding and the correction applier use — and it does not depend on
    which report format the user selected. Every field is shown once, with the
    same locator the correction contract uses to select it, followed by the
    registered identities actually bound to that field (numbers/URLs, not a
    re-guess from the title). Source bodies appear only in the Source Register.
    """
    lines: list[str] = []
    for locator, container, field in citation_field_locations(recommendation):
        text = str(container.get(field) or "")
        lines.append(f"### {locator}")
        lines.append(text)
        lines.append(_bound_sources_line(recommendation, locator, text))
        lines.append("")
    return "\n".join(lines) if lines else "No reviewable fields are present."


def _conflict_source_identity(source, registry: dict) -> str:
    """Locate one conflict side by registered identity (URL), never by title."""
    if not isinstance(source, dict):
        return "source not recorded"
    url = str(source.get("url") or "")
    title = str(source.get("title") or "")
    entry = None
    if url:
        entry = next((candidate for candidate in registry.get("entries") or []
                      if candidate.get("url") == url), None)
    if entry is not None:
        identity = f"[[{entry['number']}]] {entry['title']} — {url}"
    elif url:
        identity = f"{title + ' — ' if title else ''}{url} (not in numbered source register)"
    elif title:
        identity = f"{title} (not in numbered source register; no URL)"
    else:
        identity = "source recorded without identity"
    if source.get("has_body") is False:
        identity += " (no body collected; not citable)"
    return identity


def _conflicts_text(research_state: dict, registry: dict) -> str:
    """The recorded conflicts with both claims and their locatable sources.

    The reviewer needs to see which side a resolution names (`A_correct` /
    `B_correct`) and where each claim's source sits in the numbered register;
    counts alone cannot be checked. The conflict set is a small part of the
    review input, so this does not re-feed the rendered report.
    """
    conflicts = research_state.get("conflicts") or []
    lines: list[str] = []
    for index, conflict in enumerate(conflicts, 1):
        if not isinstance(conflict, dict):
            continue
        resolution = conflict.get("resolution", "unresolved")
        confidence = conflict.get("confidence", "unknown")
        lines.append(f"### Conflict {index} — resolution: {resolution}; "
                     f"confidence: {confidence}")
        lines.append(f"- Claim A: {conflict.get('claim_a', '')}")
        lines.append(f"  Source A: {_conflict_source_identity(conflict.get('source_a'), registry)}")
        lines.append(f"- Claim B: {conflict.get('claim_b', '')}")
        lines.append(f"  Source B: {_conflict_source_identity(conflict.get('source_b'), registry)}")
        lines.append(f"- Reasoning: {conflict.get('reasoning', '')}")
        lines.append(f"- Key factor: {conflict.get('key_factor', '')}")
        lines.append("")
    if lines:
        return "\n".join(lines).rstrip()
    check = research_state.get("conflict_check")
    check = check if isinstance(check, dict) else {}
    outcomes = check.get("scan_outcomes") or {}
    return ("No conflicts recorded. Conflict check: "
            f"pairs scanned {check.get('pairs_scanned', 0)}, "
            f"unscanned {outcomes.get('unscanned', 0)}, "
            f"reason {check.get('reason', 'unrecorded')}")


class SelfReviewerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        print_agent_output("Running self-review quality check", agent="SELF_REVIEWER")

        upstream_signals = research_state.get("quality_signals", [])
        signals_text = "\n".join(
            f"- {s.get('agent', 'unknown')}: { {k: v for k, v in s.items() if k != 'agent'} }"
            for s in upstream_signals
        ) if upstream_signals else "No upstream quality signals available."

        # One source package for the whole review: the same numbered registry the
        # synthesizer used, with full title, URL and body. The reviewer can check
        # a specific claim against the body and cite a number back in a revision;
        # a number means the same source in both paths.
        registry = build_source_registry(research_state.get("evidence_chains") or [])
        recommendation = research_state.get("final_recommendation") or {}

        source_register_text = _source_register_text(registry)
        review_fields = _review_fields_text(recommendation)
        cite_stats = _citation_coverage(recommendation, registry=registry)
        uncited_text = ("\n".join(f"- {locator}" for locator in cite_stats["uncited_locations"])
                        or "none")
        unresolved_text = ("\n".join(f"- {locator}" for locator in cite_stats["unresolved_locations"])
                           or "none")
        recorded_questions = list(recommendation.get("unresolved_questions") or []) + \
            list(research_state.get("knowledge_gaps") or [])
        recorded_text = ("\n".join(f"- {question}" for question in recorded_questions)
                         or "none recorded")

        task = research_state.get("task") or {}
        query_text = str(task.get("query") or "(not recorded)")
        scene_text = str(task.get("scene_context") or "(not recorded)")
        constraints = [str(c) for c in (task.get("constraints") or []) if str(c).strip()]
        constraints_text = ("\n".join(f"- {c}" for c in constraints)
                            or "(none recorded)")
        conflicts_text = _conflicts_text(research_state, registry)

        user_content = f"""## Original Query
{query_text}

## Scene Context
{scene_text}

## Declared Constraints
Every frozen constraint from the request is listed here. A claim, exclusion or
recommendation violates the request when it ignores one; a recommendation with no
statement of what would change it is incomplete.
{constraints_text}

## Fields To Review
Every correctable served field the result carries is below, once, under the same
locator the correction contract uses to select it. This body does not depend on
the report format the user chose. Check each claim against the source bodies, not
against the citation markers.

{review_fields}

## Citation Completeness (deterministic; a citation is not proof of support)
Total claim fields: {cite_stats["total_fields"]}
Fields carrying a resolvable citation: {cite_stats["cited_fields"]}
Fields with no citation: {cite_stats["uncited_fields"]}
Field locations with no citation:
{uncited_text}
Field locations with an unresolved citation:
{unresolved_text}

## Source Register (numbered; same numbering as synthesis)
{source_register_text}

## Recorded Conflicts
{conflicts_text}

## Original Sub-Questions
{research_state.get("sub_questions", [])}

## Open Questions Recorded By Synthesis
{recorded_text}

## Pipeline Quality Signals
{signals_text}

## Retry Count
{research_state.get("retry_count", 0)}"""

        prompt = [
            {"role": "system", "content": REVIEW_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        local_usage: list = []
        try:
            result = await call_model(prompt, model="deepseek-flash", response_format="json", tag="self_reviewer",
                                      usage=local_usage)
        except Exception as e:
            print_agent_output(f"Self-review failed: {e}, falling back to medium", agent="SELF_REVIEWER")
            result = {}

        if not isinstance(result, dict):
            result = {}

        # A decisive error must change the served result, not only its
        # confidence. The reviewer names the field and what the source supports;
        # this applies it deterministically, in place, so the report the endpoints
        # render from carries the correction.
        #
        # Deep-copied first: editing the caller's nested dicts in place would also
        # rewrite the checkpointed pre-review state, so the report would look
        # unchanged and the original would be lost.
        import copy

        recommendation = copy.deepcopy(recommendation)
        # Revisions are resolved with the same numbered source registry the
        # reviewer read, so a number the reviewer cites means the source it saw,
        # and a title is matched by full identity rather than truncated.
        applied, rejected = _apply_corrections(
            recommendation, result.get("corrections"),
            evidence_chains=research_state.get("evidence_chains") or [],
            cite_map=dict(registry["mapping"]),
            registry=registry,
        )

        # The top-level confidence and the recommendation's own confidence are one
        # verdict, not two: the review is the later judgement, so both report it
        # and neither can contradict the other.
        #
        # Normalized first. Requiring the exact lowercase triple meant any other
        # spelling skipped the cap entirely, so a reviewer answering "HIGH" raised
        # a low-confidence result and an invalid value reached the report. An
        # unusable answer now falls back to the weaker of the two priors rather
        # than passing through.
        prior = _normalize_confidence(recommendation.get("confidence"))
        reviewed = _normalize_confidence(result.get("confidence"))
        candidates = [c for c in (reviewed, prior) if c is not None]
        confidence = min(candidates, key=lambda c: _LEVELS[c]) if candidates else "low"
        recommendation["confidence"] = confidence

        # The report body is re-rendered from the **complete** reviewed state, so
        # the saved report.md, the snapshot's `report`, the report endpoint, the
        # reading view and every export all show the same post-review result.
        #
        # Previously only the recommendation was merged: the reviewer's own
        # confidence and knowledge_gaps were returned but never part of the state
        # it rendered from, so the saved file omitted the "what we don't know yet"
        # section that the endpoint (rendering from the final snapshot) showed.
        reviewed_state = dict(research_state)
        reviewed_state["final_recommendation"] = recommendation
        reviewed_state["confidence"] = confidence
        reviewed_state["knowledge_gaps"] = list(result.get("knowledge_gaps") or [])
        final_report, _ = render_report(reviewed_state)

        return {
            "report": final_report,
            "final_recommendation": recommendation,
            "confidence": confidence,
            "knowledge_gaps": result.get("knowledge_gaps", []),
            "retry_count": research_state.get("retry_count", 0) + 1,
            "quality_signals": [{
                "agent": "self_reviewer",
                "passed_count": result.get("passed_count", 0),
                "total_checks": 6,
                "confidence": confidence,
                "gaps_found": len(result.get("knowledge_gaps", [])),
                # Counts and fixed categories only; never model prose.
                "corrections_applied": len(applied),
                "corrections_rejected": len(rejected),
                "corrected_fields": [f"{c['option']}/{c['field']}" for c in applied],
                "report_rerendered": True,
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("self_reviewer", local_usage)],
        }
