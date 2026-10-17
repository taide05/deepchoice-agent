from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output
from .conclusion_synthesizer import (
    _summarize_chains,
    clean_label,
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
1. Source support: citation coverage is PRE-COMPUTED by the pipeline (see "Citation Coverage" in the input) — use that number, do NOT re-evaluate from the report text.
2. Unsourced claims: the pre-computed "Uncited" count is authoritative — use it, do NOT re-count.
3. Does the recommendation cover all 5 comparison dimensions? (Functionality, Performance, Ecosystem, Developer Experience, Scenario Fit)
4. Are there unlabeled information conflicts?
5. Are any user sub-questions unanswered?
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
  exact name as shown in "Decision Claims To Check". For a trade-off field it is
  that trade-off's dimension, exactly as shown there. Leave it empty ("") for a
  top-level field.
- "field" is one of the fields listed here — the only fields that can be
  corrected. Each is printed in the report, so an error left in any of them
  stays on display:
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
                       cite_map: dict[int, str] | None = None) -> tuple[list[dict], list[str]]:
    """Apply the reviewer's field-level corrections to the recommendation.

    Deterministic: the reviewer says which field is wrong and what the source
    supports; this replaces that field and nothing else. A decisive error is
    therefore fixed or withdrawn in the served result instead of only lowering
    confidence, and the untouched answers are preserved.

    `option` selects a ranked option by name, or a trade-off by dimension; it may
    be empty for a top-level field such as `recommendation`.

    Revised text goes through `resolve_citations`, the same rule synthesis uses,
    so a revision cannot reintroduce a citation the synthesizer would remove.
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
            # The revision goes through the same citation rules as synthesis. A
            # revision is the reviewer's own prose, so a marker it attaches to a
            # source that is not in the citable set is a claim of support that
            # does not exist; resolving it would leave the claim attached to
            # nothing, so that revision is withdrawn instead.
            #
            # Resolution can also leave the field empty — a revision consisting
            # only of markers loses all of them — and an empty field both blanks
            # the answer and hides the reason. That is the withdrawn case too.
            resolved = resolve_citations(corrected, evidence_chains, cite_map)
            if not resolved.strip() or unresolved_citations(resolved, evidence_chains):
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




_CITATION_FIELDS = ("recommendation", "winner_rationale", "evidence_summary",
                    "scene_fit_note")
_CITATION_OPT_FIELDS = ("rationale", "key_strength", "key_weakness")
_CITATION_TRADEOFF_FIELDS = ("finding", "impact")


def _citation_coverage(fr: dict) -> dict:
    """Deterministic citation coverage for self-review items 1/2.

    Counts factual-claim fields that carry at least one [Source: title], so the
    reviewer trusts a pre-computed fact instead of re-reading the report.
    """
    fields: list[str] = []
    for f in _CITATION_FIELDS:
        if fr.get(f):
            fields.append(fr[f])
    for opt in fr.get("ranked_options", []):
        for f in _CITATION_OPT_FIELDS:
            if opt.get(f):
                fields.append(opt[f])
    for to in fr.get("trade_offs", []):
        for f in _CITATION_TRADEOFF_FIELDS:
            if to.get(f):
                fields.append(to[f])
    total = len(fields)
    uncited = sum(1 for f in fields if "[Source:" not in f)
    return {"total_fields": total, "cited_fields": total - uncited,
            "uncited_fields": uncited}


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

        # The reviewer is asked to check claims against the cited source text, so
        # The reviewer is asked to check claims against the cited source text, so
        # the source text must be in the payload. Titles alone made the decisive
        # comparison impossible: the run's wrong scale (5 万亿) was visible while
        # the source that says 500 亿 was not, so the review could not catch it.
        #
        # The sources are listed as retrieved material, with no strength band: a
        # retrieval score is not evidence, and labelling it as such in the review
        # payload invited the reviewer to endorse the ranking for the wrong reason.
        from ..utils.candidate_identity import bounded_content_summary

        chains_summary = []
        for c in research_state.get("evidence_chains", []):
            disputed = " [DISPUTED]" if c.get("disputed") else ""
            chains_summary.append(f"retrieved item{disputed}:")
            for s in (c.get("sources") or [])[:2]:
                chains_summary.append(f"    source: {s.get('title', '?')[:80]}")
                provenance = s.get("provenance")
                channel = s.get("channel")
                if provenance or channel:
                    chains_summary.append(
                        f"      provenance: {provenance or 'unknown'}; "
                        f"channel: {channel or 'unknown'}")
                chains_summary.append(
                    f"      text: {bounded_content_summary(s, limit=700)}")
        chains_text = "\n".join(chains_summary) if chains_summary else "No retrieved sources."

        cite_stats = _citation_coverage(research_state.get("final_recommendation", {}))

        # The per-candidate justifications decide the ranking, but nothing reviewed
        # them: the reviewer saw only the headline. They are supplied here so a
        # wrong scale, an unsupported justification or an unsupported dismissal can
        # be caught before rendering.
        claims_summary: list[str] = []
        for opt in (research_state.get("final_recommendation") or {}).get("ranked_options") or []:
            if not isinstance(opt, dict):
                continue
            claims_summary.append(
                f"#{opt.get('rank', '?')} {opt.get('name', '')} "
                f"(constraint_fit={opt.get('constraint_fit', '?')})")
            for field in ("rationale", "constraint_fit_reason", "key_strength",
                          "key_weakness"):
                value = opt.get(field)
                if value:
                    claims_summary.append(f"    {field}: {value}")
        for to in (research_state.get("final_recommendation") or {}).get("trade_offs") or []:
            if isinstance(to, dict) and to.get("finding"):
                claims_summary.append(
                    f"trade-off [{to.get('dimension', '')}]: {to.get('finding')}")
        claims_text = "\n".join(claims_summary) if claims_summary else \
            "No ranked options were produced."

        user_content = f"""## Report
{research_state.get("report", "")}

## Citation Coverage (pre-computed — trust this, do NOT re-evaluate)
Total claim fields: {cite_stats["total_fields"]}
Cited: {cite_stats["cited_fields"]}
Uncited: {cite_stats["uncited_fields"]}

## Evidence Chains
{chains_text}

## Original Sub-Questions
{research_state.get("sub_questions", [])}

## Pipeline Quality Signals
{signals_text}

## Decision Claims To Check
The per-candidate justifications below are what the report presents as its
reasons. Check each against the evidence chains and the cited source text:
- a figure, unit or scale that the cited source does not state (or states
  differently) is a decisive error;
- a justification with no supporting source for its specific assertion is a
  decisive error;
- a candidate dismissed for a reason the sources do not support is a decisive
  error.
Report each such case in knowledge_gaps, naming the candidate and the claim.

{claims_text}

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

        recommendation = copy.deepcopy(research_state.get("final_recommendation") or {})
        # The citation rules for a revision are the synthesis rules, applied to
        # the same evidence: the citable set and the number -> title mapping both
        # come from the one builder the synthesizer uses, so a revision cannot
        # cite a source that the synthesizer would have refused.
        _evidence_text, cite_map = _summarize_chains(
            research_state.get("evidence_chains") or [],
            (research_state.get("task") or {}).get("candidate_techs"),
        )
        applied, rejected = _apply_corrections(
            recommendation, result.get("corrections"),
            evidence_chains=research_state.get("evidence_chains") or [],
            cite_map=cite_map,
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
