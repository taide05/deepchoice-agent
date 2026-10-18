from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output
from .conclusion_synthesizer import (
    build_source_registry,
    citation_field_locations,
    clean_label,
    has_substantive_content,
    resolve_citations,
    unresolved_citations,
    withdrawal_note,
)
from .report_generator import render_report

# The fields the reviewer may correct: only the justification text it is asked to
# check. The choice, the ranking order and the candidate names are not the
# reviewer's to change.
#
# The set covers every field the report prints verbatim, not only the
# per-candidate ones: a decisive error named in the recommendation, the winner
# rationale, the confidence rationale or a trade-off finding was reported and
# then still displayed, which is the outcome this is meant to remove. It is the
# single definition: the contract sent to the model is generated from it.
_CORRECTABLE_OPTION_FIELDS = ("rationale", "key_strength", "key_weakness",
                              "constraint_fit_reason")
_CORRECTABLE_TOP_FIELDS = ("recommendation", "winner_rationale",
                           "confidence_rationale", "evidence_summary",
                           "scene_fit_note")
_CORRECTABLE_TRADEOFF_FIELDS = ("finding", "impact")
_CORRECTABLE_FIELDS = (_CORRECTABLE_OPTION_FIELDS + _CORRECTABLE_TOP_FIELDS
                       + _CORRECTABLE_TRADEOFF_FIELDS)

# Correctable fields the `what_why_how` renderer does not print: they are still
# part of the served result (other formats and the snapshot carry them), so the
# reviewer must see their current text to review them, but repeating the printed
# ones would make the payload a second copy of the report.
_UNRENDERED_CORRECTABLE_FIELDS = ("evidence_summary", "constraint_fit_reason",
                                 "impact")


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
3. Does the recommendation cover all 5 comparison dimensions? (Functionality, Performance, Ecosystem, Developer Experience, Scenario Fit)
4. Are there unlabeled information conflicts?
5. Are any user sub-questions unanswered? Check each original sub-question against the report, and say which ones have no substantive answer rather than only a marker or a gap note.
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
reason the sources do not support — anywhere the report states it. For every one,
return a correction entry that names WHERE it is stated:
- "option" is the selector. For a per-candidate field it is that candidate's
  exact name as shown in "Revision Targets". For a trade-off field it is that
  trade-off's dimension, exactly as shown there. Leave it empty ("") for a
  top-level field.
- "field" is one of the fields listed here — the only fields that can be
  corrected. Most are printed in the report. A field marked "(not printed by
  this report format)" is still part of the served result and its current text
  is supplied under "Revision Targets"; an error left in any listed field is
  still served to the reader:
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

    Revised text goes through `resolve_citations`, the same rule synthesis uses,
    against the same numbered registry: a registered title is canonicalised, an
    unregistered one stays visible as a located gap, and a revision that says
    nothing beyond markers is withdrawn rather than counted as an answer.
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

        before = target.get(field)
        if action == "withdraw":
            target[field] = withdrawal_note(str(recommendation.get("recommendation") or ""))
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
            resolved = resolve_citations(corrected, evidence_chains, cite_map,
                                         registry=registry)
            if not has_substantive_content(resolved):
                target[field] = withdrawal_note(
                    str(recommendation.get("recommendation") or ""))
                applied.append({
                    "option": owner, "field": field, "action": "withdraw",
                    "withdrawn_marker": True,
                    "reason": ("revision left nothing citable in the field: "
                               + reason)[:200],
                    "changed": before != target.get(field),
                })
                continue
            target[field] = resolved
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
    """
    from .conclusion_synthesizer import has_bound_citation

    registry = registry or build_source_registry(evidence_chains or [])
    locations = citation_field_locations(fr)
    uncited: list[str] = []
    unresolved: list[str] = []
    for locator, container, field in locations:
        text = str(container.get(field) or "")
        if not has_bound_citation(text, registry):
            uncited.append(locator)
        if unresolved_citations(text, registry=registry):
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
        body = " ".join(str(entry.get("body") or "").split())
        if len(body) > limit:
            body = body[:limit].rstrip() + "…"
        lines.append(f"    body: {body or '(no body text stored)'}")
    if registry.get("navigation"):
        lines.append("")
        lines.append("Navigation links (no body collected; NOT citable):")
        lines += [f"- {link}" for link in registry["navigation"][:10]]
    return "\n".join(lines)


def _revision_targets_text(recommendation: dict) -> str:
    """Where each correctable field lives, without repeating printed prose.

    The report above is the authoritative content; this is the locating index the
    reviewer needs to name a field in a correction. Fields the report format does
    not print are the exception: their current text is included here, because the
    reviewer cannot check a claim that is nowhere in the payload.
    """
    def _entry(label: str, container: dict, field: str) -> str:
        locator = f"{label}: {field}"
        if field in _UNRENDERED_CORRECTABLE_FIELDS:
            text = " ".join(str(container.get(field) or "").split())
            return f"{locator} (not printed by this report format) — {text}"
        return locator

    lines: list[str] = []
    for field in _CORRECTABLE_TOP_FIELDS:
        if recommendation.get(field):
            lines.append(_entry("top-level", recommendation, field))
    for option in recommendation.get("ranked_options") or []:
        if not isinstance(option, dict):
            continue
        for field in _CORRECTABLE_OPTION_FIELDS:
            if option.get(field):
                lines.append(_entry(f"option={option.get('name', '?')}",
                                    option, field))
    for trade_off in recommendation.get("trade_offs") or []:
        if not isinstance(trade_off, dict):
            continue
        for field in _CORRECTABLE_TRADEOFF_FIELDS:
            if trade_off.get(field):
                lines.append(_entry(f"trade-off={trade_off.get('dimension', '?')}",
                                    trade_off, field))
    return "\n".join(lines) if lines else "No correctable fields are present."


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
        revision_targets = _revision_targets_text(recommendation)
        cite_stats = _citation_coverage(recommendation, registry=registry)
        uncited_text = ("\n".join(f"- {locator}" for locator in cite_stats["uncited_locations"])
                        or "none")
        unresolved_text = ("\n".join(f"- {locator}" for locator in cite_stats["unresolved_locations"])
                           or "none")
        recorded_questions = list(recommendation.get("unresolved_questions") or []) + \
            list(research_state.get("knowledge_gaps") or [])
        recorded_text = ("\n".join(f"- {question}" for question in recorded_questions)
                         or "none recorded")

        user_content = f"""## Report To Review
The report body below is the served content; the later sections add the source
material and a locating index. Check the claims in the report against the source
bodies, not against the citation markers.

{research_state.get("report", "")}

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

## Original Sub-Questions
{research_state.get("sub_questions", [])}

## Open Questions Recorded By Synthesis
{recorded_text}

## Revision Targets (locations only; content is in the report above)
{revision_targets}

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
