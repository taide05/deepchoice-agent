import os

from ..utils.decision import decision_view, withdraw_decision
from ..utils.claim_support import decisive_claim_support
from ..utils.confidence_text import align_confidence_rationale
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
        + ", ".join(_CORRECTABLE_TRADEOFF_FIELDS) + "\n"
        "* whole-decision withdrawal only (option = \"\", action = withdraw_decision): "
        "decision_status"
    )


REVIEW_SYSTEM = f"""You are a rigorous quality reviewer. Evaluate research reports against a 6-item checklist.

Answer YES or NO for each, with a brief note:
1. Source support and applicability: the pipeline only verifies that a citation names a registered source; a citation marker is NOT proof that the source supports the specific claim. For each decisive claim you check, compare the claim against the source body in the Source Register. A single vendor comparison page, a single secondary blog, or a single Stack Overflow answer/comment is not enough to rank candidates as fact; if that is all the support, require a conditional/limitation formulation or withdraw the unsupported ranking claim.
2. Citation completeness: the "Citation Completeness" section is computed from the same field list that binding uses. It lists fields with no citation and fields whose citation could not be resolved. Treat both as things to check, not as automatic truth verdicts: an uncited claim may still be a recorded gap, and an unresolved citation is not evidence that the claim is false.
3. Does the recommendation cover all 5 comparison dimensions? (Functionality, Performance, Ecosystem, Developer Experience, Scenario Fit) Does it respect the "Declared Constraints", and does it state what constraint or evidence would change the recommendation when the answer is conditional?
4. Are there unlabeled information conflicts? The recorded conflicts, if any, are under "Recorded Conflicts"; compare their resolutions with the claims in the fields.
5. Are any user sub-questions unanswered? Check each original sub-question and every declared constraint against the fields below, and say which ones have no substantive answer rather than only a marker or a gap note. A knowledge gap list entry does not answer a required item by itself.
6. Are there counter-examples or negative findings not flagged?

Also check these decisive-error patterns when applying items 1, 2, 4 and 6:
- Modality / scale strengthening: if a source says "recommended", "may", "can", "should" or gives a figure/unit/version/date, the served fields must not state it as "required", "must", "guarantees", "官方要求" or with a different figure/unit. Correct the field to the source's own strength.
- Lifecycle / roadmap facts: if a source states a merger, acquisition, archive, end-of-life, maintenance mode, ownership change or roadmap change for a candidate, the ranking and recommendation must factor it into long-term maintenance/roadmap reasoning or record it as an explicit condition or gap. Quoting it only in passing while ranking that candidate as the default branch is an incomplete analysis; add the missing condition/gap through a correction where a cited source supports it.
- Excluded material in the basis: a sentence that marks a source as irrelevant/excluded/not used must not carry a [Source: ...] citation, and a source declared excluded must not be listed among the sources the recommendation relies on. Confirm the Cited Source Register and the "excluded/unused" statements do not contradict each other.
- Coverage asymmetry: if the top option's decisive comparison rests on its own first-party material while the other candidate is only missing retrieved body text, the ordering must be presented as an evidence-availability branch or hypothesis, not as a proven capability difference.
- Comparison-mode asymmetry: a ranking that compares candidate A's managed/hosted path against candidate B's self-hosted path (or vice versa) without weighing B's equivalent option is an applicability defect; correct the claim to be like-for-like or mark the ordering as an unverified branch.
- Gap accuracy: a "missing / not covered / 完全没有 / 缺失" claim that contradicts a source body already in the Source Register is an evidence error (for example the cited page documents the import path, licence or pricing). Correct the claim to what the body supports.

- Global absence claims: "材料中没有任何… / 完全没有 / 不存在" about price, licence, import path, managed/hosted option, support or roadmap is an evidence error when any cited body already states the thing; correct it to "本报告可见材料未给出 X" and keep it as a gap.
- Managed-option search: before accepting "candidate B has no comparable managed/hosted option", scan the Source Register bodies for managed/hosted/cloud terms; if one exists, the asymmetry must be corrected or the ordering kept conditional.
- Guidance vs requirement: advice such as "as general guidance, make sure you", "recommended", "should" must not be served as "必须 / required / 官方要求".
- Unsupported exclusivity: "仅 / 唯一 / only / solely" claims about maintenance, support, ownership or availability that the Source Register or navigation links contradict are evidence errors; correct them to a bounded statement.
- Confidence prose level: the confidence rationale must not state a different level anywhere, including parenthetical labels such as "（high）"/"(medium)" next to evidence/confidence words.
- Internal metadata leakage: user-facing text must not mention rule numbers ("rule 25"), the prompt, pipeline field names, agent/model names or internal processing notes. Correct such a field to the reader-facing statement, keeping the substance.
- Bare source ordinals: prose must not contain registry numbers such as "[1]" or "[2]/[13]"; convert them to a [Source: title] marker or remove the number, keeping the statement.
- Dangling citation in the decision summary: if a summary excerpt ends inside an open "[Source: ..." fragment, the served text must not carry an unparseable marker; note it for the renderer's excerpt trimming rather than inventing a source.

Confidence Assessment:
- high: 5-6/6 passed, no critical gaps
- medium: 3-4 items passed, no critical gaps
- low: 0-2 items passed OR critical information missing

If your final confidence differs from the synthesis confidence provided in the
review body, revise the `confidence_rationale` field through the normal correction
mechanism so it states the final level and keeps the substantive reason. Do not
replace the reason with a checklist count; the checklist count is process data,
reported separately. If you cannot make the reason agree with the level, leave the
field unchanged and record the inconsistency as a gap.

If confidence is not "high", list specific information gaps as search queries.

Return ONLY a JSON object. `checks` MUST contain exactly six objects, one per
numbered item above, each with a boolean `passed`; `passed_count` MUST be an
integer from 0 to 6 and equal the number of true checks. A partial or inconsistent
result is unusable and will not be applied. Numbers are examples; give real values:
{{"checks": [{{"item": 1, "passed": true, "note": "..."}}, {{"item": 2, "passed": true, "note": "..."}}, {{"item": 3, "passed": true, "note": "..."}}, {{"item": 4, "passed": true, "note": "..."}}, {{"item": 5, "passed": true, "note": "..."}}, {{"item": 6, "passed": false, "note": "..."}}], "passed_count": 5, "confidence": "high|medium|low", "knowledge_gaps": ["gap query"], "critical_gaps": ["critical gap"], "corrections": [{{"option": "<selector, see below>", "field": "<field name, see below>", "action": "revise|withdraw|withdraw_decision", "corrected": "<field text with the error fixed, using only what a cited source supports; omit for withdraw/withdraw_decision>", "reason": "<what was wrong and which source contradicts it>"}}]}}

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
- To withdraw an unsupported recommendation entirely and turn it into an
  evidence-insufficient hold, use field "decision_status", option "", action
  "withdraw_decision", and a reason; omit "corrected". This clears the winner,
  replaces the recommendation/rationale with a hold, and preserves candidate
  analysis and citations. Do NOT use this for a recommendation you merely
  dislike, and never revise the winner to a different product.

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

# Appended to the review body for one repair attempt when the first response was
# usable JSON but violated the fixed 6-item contract. The malformed payload is
# never applied; this asks only for the contract shape again.
_REVIEW_REPAIR_NOTE = """

## Previous Response Did Not Meet The Review Contract
Your previous answer was rejected with `{error}`. Re-issue the review now.
`checks` MUST contain exactly six objects with `item` values 1,2,3,4,5,6 (each
exactly once) and a boolean `passed`; `passed_count` MUST equal the number of
true checks; `confidence` MUST be exactly one of "low", "medium", "high".
Return the same JSON contract, corrected, and nothing else."""

# "option" may name a ranked option, a trade-off dimension, or be omitted for a
# top-level field. These are matched case-insensitively on the trimmed value.
_LEVELS = {"low": 0, "medium": 1, "high": 2}


def _normalize_confidence(value) -> str | None:
    """Map a reviewer's confidence to one of the three levels, or None."""
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    level = value.strip().lower()
    return level if level in _LEVELS else None


def _validate_review_counts(checks, passed_count) -> tuple[int | None, str | None]:
    """Strictly validate the 6/6 checklist accounting.

    A malformed, partial or internally inconsistent count makes the review
    unusable rather than being coerced to 0/6 or 7/6. The denominator is fixed by
    the review contract; counts are reported separately from the substantive
    confidence reason.
    """
    if not isinstance(checks, list) or len(checks) != 6:
        return None, "checks_not_six"
    items: list[int] = []
    passed_values = []
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
            return None, "malformed_check"
        item = check.get("item")
        if isinstance(item, bool) or not isinstance(item, int):
            return None, "invalid_item"
        items.append(item)
        passed_values.append(check["passed"])
    if sorted(items) != [1, 2, 3, 4, 5, 6]:
        return None, "item_coverage_invalid"
    if isinstance(passed_count, bool) or not isinstance(passed_count, int):
        return None, "passed_count_not_int"
    if not 0 <= passed_count <= 6:
        return None, "passed_count_out_of_range"
    if passed_count != sum(1 for value in passed_values if value):
        return None, "passed_count_mismatch"
    return passed_count, None


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
                       registry: dict | None = None,
                       language: str = "zh") -> tuple[list[dict], list[str]]:
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
        if field == "decision_status" and action == "withdraw_decision":
            if not reason:
                rejected.append("no reason given for decision withdrawal")
                continue
            if not recommendation.get("winner") and \
                    recommendation.get("decision_status") == "insufficient_evidence":
                rejected.append("recommendation is already an insufficient-evidence hold")
                continue
            if decision_view(recommendation)["invalid"]:
                rejected.append("cannot convert an invalid decision into a valid hold")
                continue
            before_decision = dict(recommendation)

            def rebind_top_field(rec: dict, field: str, text: str) -> None:
                resolved, bindings = resolve_citations_with_sources(
                    text, evidence_chains, cite_map, registry=registry)
                rec[field] = resolved
                _set_field_bindings(rec, field_locator(rec, field), bindings)

            withdraw_decision(recommendation, reason, language=language,
                              rebind_top_field=rebind_top_field)
            applied.append({
                "option": "", "field": "decision_status",
                "action": "withdraw_decision", "reason": reason[:200],
                "changed": before_decision != recommendation,
            })
            continue
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


def _self_review_budget_chars() -> int | None:
    """Optional self-review-only evidence budget for cost experiments.

    Unset (default) keeps the shared 24k package used by synthesis. The A/B
    experiment sets SELF_REVIEW_EVIDENCE_BUDGET_CHARS and compares review output;
    the default product behaviour is unchanged.
    """
    raw = os.environ.get("SELF_REVIEW_EVIDENCE_BUDGET_CHARS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 500 else None


def _self_review_mode() -> str:
    """full (default) or triggered (opt-in cost experiment)."""
    return (os.environ.get("SELF_REVIEW_MODE", "full").strip().lower() or "full")


def _self_review_output_constraint() -> bool:
    return os.environ.get("SELF_REVIEW_OUTPUT_CONSTRAINT", "").strip().lower() in (
        "1", "true", "yes", "on")


_OUTPUT_CONSTRAINT_TEXT = """

## Cost Experiment Output Constraint
Keep the JSON compact: each checklist note at most 20 words; each correction's
`corrected` value contains only the changed clause/sentence (do not repeat the
whole field); `reason` at most 30 words; knowledge_gaps at most 5 concise queries.
Do not omit any correction or required JSON field to save space."""


def _should_self_review(recommendation: dict, cite_stats: dict,
                        research_state: dict) -> tuple[bool, str]:
    """Deterministic pre-review trigger used only when SELF_REVIEW_MODE=triggered.

    The rule was derived from the saved 200-case data: review whenever the
    decision is invalid/insufficient, any conflict was recorded, or the report has
    fewer than 20 citations. This is an experiment guard, not a claim that the
    skipped reviews are correction-free; the default mode still reviews every run.
    """
    if _self_review_mode() != "triggered":
        return True, "full"
    status = str(recommendation.get("decision_status") or "")
    if status in ("invalid", "insufficient_evidence"):
        return True, "trigger:decision_status"
    if research_state.get("conflicts"):
        return True, "trigger:conflicts"
    report = str(research_state.get("report") or "")
    if report.count("[Source:") < 20:
        return True, "trigger:few_citations"
    return False, "skip:low_risk"


def _skipped_review_result(research_state: dict, reason: str) -> dict:
    """Return the pre-review result unchanged, with an explicit skip signal."""
    recommendation = research_state.get("final_recommendation") or {}
    report = str(research_state.get("report") or "")
    if not report:
        final_report, _ = render_report(dict(research_state))
    else:
        final_report = report
    return {
        "report": final_report,
        "final_recommendation": recommendation,
        "confidence": research_state.get("confidence"),
        "knowledge_gaps": list(research_state.get("knowledge_gaps") or []),
        "retry_count": research_state.get("retry_count", 0),
        "quality_signals": [{
            "agent": "self_reviewer",
            "review_status": "skipped_by_trigger",
            "review_mode": _self_review_mode(),
            "skip_reason": reason,
            "review_validation_error": None,
            "passed_count": None,
            "total_checks": 6,
            "confidence": research_state.get("confidence"),
            "gaps_found": len(research_state.get("knowledge_gaps") or []),
            "corrections_applied": 0,
            "corrections_rejected": 0,
            "corrected_fields": [],
            "report_rerendered": False,
        }],
        "token_usage": list(research_state.get("token_usage") or []),
    }


def _source_register_text(registry: dict, with_audit: bool = False,
                          focus_terms: list[str] | None = None,
                          budget_chars: int | None = None):
    """The numbered sources, with title, URL and the shared evidence package.

    Rendered from the same package builder the synthesizer used: complete saved
    bodies when they fit the total input budget, otherwise the same recorded
    source ranges. A visible/total character line and omitted-span line make the
    selection explicit instead of silently showing a shorter body.
    """
    from ..utils.candidate_identity import shared_evidence_package

    entries = registry.get("entries") or []
    if not entries:
        text = "No citable sources were registered."
        return (text, []) if with_audit else text
    package = shared_evidence_package(entries, focus_terms=focus_terms or [],
                                      budget_chars=budget_chars)
    lines: list[str] = []
    audit: list[dict] = []
    for entry in entries:
        lines.append(f"[[{entry['number']}]] {entry['title']}")
        if entry.get("url"):
            lines.append(f"    url: {entry['url']}")
        if entry.get("source_owner") or entry.get("source_kind") or \
                entry.get("source_type"):
            lines.append(
                f"    source_identity: owner={entry.get('source_owner') or 'unknown'}; "
                f"kind={entry.get('source_kind') or 'unknown'}; "
                f"type={entry.get('source_type') or 'unknown'}; "
                f"body_identity_verified="
                f"{entry.get('body_identity_verified') if entry.get('body_identity_verified') is not None else 'unknown'}; "
                f"fetch_status={entry.get('fetch_status') or 'unknown'}")
        if entry.get("date"):
            lines.append(f"    date: {entry['date']}")
        if entry.get("body_url") and entry["body_url"] != entry.get("url"):
            lines.append(f"    body_url: {entry['body_url']}")
        view = package["views"].get(entry["number"])
        if view is None:
            from ..utils.candidate_identity import bounded_evidence_record
            view = bounded_evidence_record(entry)
        lines.append(f"    body: {view['text']}")
        page_extracted = (view["page_chars"] if view["page_chars_known"]
                          else "unknown")
        page_truncated = (view["page_truncated"]
                          if view["page_chars_known"] else "unknown")
        ranges = ", ".join(f"{start}-{end}" for start, end in
                           view.get("selection_ranges") or [])
        lines.append(
            f"    visible: {view['visible_chars']}/{view['stored_chars']} stored-body chars; "
            f"full_text_included={view.get('full_included', False)}; "
            f"source_ranges={ranges or 'none'}; "
            f"omitted_chars={view.get('omitted_chars', 0)}; "
            f"page_extracted={page_extracted}; "
            f"page_truncated={page_truncated}; "
            f"stored_truncated={view['stored_truncated']}"
        )
        audit.append({
            "number": entry["number"],
            "title": entry["title"],
            "body_url": view.get("body_url", ""),
            "page_chars": view["page_chars"],
            "page_chars_known": view["page_chars_known"],
            "stored_chars": view["stored_chars"],
            "source_chars": view["source_chars"],
            "visible_chars": view["visible_chars"],
            "omitted_chars": view.get("omitted_chars", 0),
            "selection_ranges": view.get("selection_ranges") or [],
            "full_included": view.get("full_included", False),
            "page_truncated": view["page_truncated"],
            "stored_truncated": view["stored_truncated"],
            "truncated": view["truncated"],
        })
    if registry.get("navigation"):
        lines.append("")
        lines.append("Navigation links (no body collected; NOT citable):")
        lines += [f"- {link}" for link in registry["navigation"][:10]]
    text = "\n".join(lines)
    return (text, audit) if with_audit else text


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
    view = decision_view(recommendation)
    lines.extend([
        "### decision_status",
        view["status"],
        "### winner",
        view["winner"] or "(no winner)",
        "",
    ])
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
        from ..utils.candidate_identity import evidence_focus_terms_for_state

        focus_terms = evidence_focus_terms_for_state(research_state)

        # Cheap pre-review signals first: the opt-in trigger may skip the paid
        # review entirely and must not build an evidence package for it.
        cite_stats = _citation_coverage(recommendation, registry=registry)
        claim_support = decisive_claim_support(recommendation)
        support_lines = [
            f"- status: {claim_support['status']}",
            f"- distinct decisive sources: {claim_support['distinct_sources']}",
            "- source classes: " + ", ".join(
                f"{name}={count}" for name, count in claim_support["counts"].items()),
            "- flags: " + (", ".join(claim_support["flags"]) or "none"),
        ]
        for source in claim_support["sources"][:12]:
            support_lines.append(
                f"- [{source['class']}/{source['source_type'] or 'unknown'}] "
                f"{source['title']} <{source['url']}>")
        claim_support_text = "\n".join(support_lines)
        review_budget = _self_review_budget_chars()
        should_review, review_reason = _should_self_review(
            recommendation, cite_stats, research_state)
        critical_support_flags = [
            flag for flag in claim_support["flags"]
            if flag.startswith("recommended_")
            or flag in {"conditional_top_option_owner_dominates",
                        "conditional_top_option_secondary_dominant"}
        ]
        if not should_review and critical_support_flags:
            # A deterministic *recommended* claim-support flag is a concrete
            # reason to spend the review even when the cheap trigger would skip
            # it. A conditional hold without a primary source may be an honest
            # evidence gap, so it does not override the trigger.
            should_review, review_reason = True, "claim-support-flag"
        if not should_review:
            print_agent_output(
                f"Self-review skipped by trigger ({review_reason})", agent="SELF_REVIEWER")
            return _skipped_review_result(research_state, review_reason)

        source_register_text, evidence_audit = _source_register_text(
            registry, with_audit=True, focus_terms=focus_terms,
            budget_chars=review_budget)
        review_fields = _review_fields_text(recommendation)
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

Synthesis confidence to check: {recommendation.get("confidence", "unknown")}

{review_fields}

## Citation Completeness (deterministic; a citation is not proof of support)
Total claim fields: {cite_stats["total_fields"]}
Fields carrying a resolvable citation: {cite_stats["cited_fields"]}
Fields with no citation: {cite_stats["uncited_fields"]}
Field locations with no citation:
{uncited_text}
Field locations with an unresolved citation:
{unresolved_text}

## Decisive Claim Support (deterministic; a citation count is not proof)
{claim_support_text}

If status is `recommended` and the flags include
`recommended_winner_owner_dominates`, check whether any non-winner independent
source actually supports the comparative ranking. If not, the correct outcome is
a conditional/PoC recommendation or an evidence-insufficient hold — not a
recommended winner based only on the winner's own docs plus secondary/community
material.

If status is `conditional` and the flags include
`conditional_top_option_owner_dominates`, apply the same check to the top-ranked
default option: if its decisive comparison rests only on its own first-party
material and secondary/community material, the default branch must be presented
as a hypothesis/PoC condition, not as a supported ordering.
If the flags include `conditional_top_option_secondary_dominant`, check whether
the top option's comparison is supported only by secondary/community material;
if so, downgrade it to a PoC hypothesis or remove the ordering claim.

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
{research_state.get("retry_count", 0)}{_OUTPUT_CONSTRAINT_TEXT if _self_review_output_constraint() else ""}"""

        prompt = [
            {"role": "system", "content": REVIEW_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        local_usage: list = []
        try:
            result = await call_model(prompt, model="deepseek-flash", response_format="json", tag="self_reviewer",
                                      usage=local_usage)
        except Exception as e:
            print_agent_output(f"Self-review unavailable: {type(e).__name__}; prior result retained",
                               agent="SELF_REVIEWER")
            result = {}

        if not isinstance(result, dict):
            result = {}

        def _validated(payload: dict):
            pc, err = _validate_review_counts(
                payload.get("checks"), payload.get("passed_count"))
            conf = _normalize_confidence(payload.get("confidence"))
            if err is None and conf is None:
                err = "confidence_invalid"
            return pc, err, conf

        # Strict accounting before trusting anything from the review. A partial,
        # malformed or internally inconsistent checklist is unavailable, not a
        # 0/6 or 7/6 result; its corrections and confidence are not applied.
        passed_count, review_error, reviewed = _validated(result)
        review_attempts = 1
        if review_error is not None and result:
            # One structured repair attempt. The first answer was usable JSON but
            # broke the fixed 6-item contract, and the 2026-11-02 final-200 review
            # found 15/200 runs marked unavailable this way (a pipeline quality
            # signal, not a content defect). Ask again for the exact contract shape
            # and keep the first response that validates; the malformed payload is
            # still never trusted.
            print_agent_output(
                f"Self-review contract invalid ({review_error}); retrying once with "
                f"the fixed 6-item contract", agent="SELF_REVIEWER")
            repair_prompt = [
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user",
                 "content": user_content + _REVIEW_REPAIR_NOTE.format(error=review_error)},
            ]
            try:
                retried = await call_model(
                    repair_prompt, model="deepseek-flash", response_format="json",
                    tag="self_reviewer", usage=local_usage)
            except Exception as e:
                print_agent_output(
                    f"Self-review repair attempt unavailable: {type(e).__name__}",
                    agent="SELF_REVIEWER")
                retried = {}
            if isinstance(retried, dict):
                pc2, err2, conf2 = _validated(retried)
                if err2 is None:
                    result, passed_count, review_error, reviewed = (
                        retried, pc2, err2, conf2)
                review_attempts = 2
        review_usable = review_error is None

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
        prior = _normalize_confidence(recommendation.get("confidence"))
        prior_rationale = str(recommendation.get("confidence_rationale") or "").strip()
        if review_usable:
            # Revisions are resolved with the same numbered source registry the
            # reviewer read, so a number the reviewer cites means the source it saw,
            # and a title is matched by full identity rather than truncated.
            applied, rejected = _apply_corrections(
                recommendation, result.get("corrections"),
                evidence_chains=research_state.get("evidence_chains") or [],
                cite_map=dict(registry["mapping"]),
                registry=registry,
                language=str(((research_state.get("task") or {}).get("language"))
                             or "zh"),
            )
        else:
            applied, rejected = [], []

        # The top-level confidence and the recommendation's own confidence are one
        # verdict, not two. Use the reviewer's level only when the review itself is
        # usable; otherwise retain the prior level rather than trusting a fragment.
        candidates = [c for c in ((reviewed if review_usable else None), prior)
                      if c is not None]
        confidence = min(candidates, key=lambda c: _LEVELS[c]) if candidates else "low"
        recommendation["confidence"] = confidence

        # Keep the served confidence prose consistent with the authoritative field.
        # The final-200 review found reports whose rationale named a different final
        # level than the field (5/200) and every usable review appended an internal
        # "（自审调整：…）" note to user-facing text (173/200). The structured
        # confidence field already reports the review's final level, so the
        # rationale keeps its substantive reason (including a reviewer-supplied
        # correction) and only explicit final-level claims are aligned; the process
        # note is removed.
        served_rationale = str(recommendation.get("confidence_rationale") or "").strip()
        if served_rationale:
            recommendation["confidence_rationale"] = align_confidence_rationale(
                served_rationale, confidence)

        # A claim-support flag is a structural problem: the reviewer may have
        # corrected wording, but a ranking whose decisive support is winner-owned
        # or secondary-only must be reduced in strength before it is rendered.
        from ..utils.decision_guard import apply_claim_support_guard
        recommendation, guard_actions = apply_claim_support_guard(
            recommendation, lang=str((research_state.get("task") or {}).get("language") or ""))

        # The report body is re-rendered from the **complete** reviewed state, so
        # the saved report.md, the snapshot's `report`, the report endpoint, the
        # reading view and every export all show the same post-review result.
        #
        # Previously only the recommendation was merged: the reviewer's own
        # confidence and knowledge_gaps were returned but never part of the state
        # it rendered from, so the saved file omitted the "what we don't know yet"
        # section that the endpoint (rendering from the final snapshot) showed.
        from ..utils.candidate_identity import EVIDENCE_INPUT_BUDGET_CHARS

        reported_gaps = (
            list(result.get("knowledge_gaps") or [])
            if review_usable and isinstance(result.get("knowledge_gaps"), list)
            else list(research_state.get("knowledge_gaps") or [])
        )
        reviewed_state = dict(research_state)
        reviewed_state["final_recommendation"] = recommendation
        reviewed_state["confidence"] = confidence
        reviewed_state["knowledge_gaps"] = reported_gaps
        final_report, _ = render_report(reviewed_state)

        return {
            "report": final_report,
            "final_recommendation": recommendation,
            "confidence": confidence,
            "knowledge_gaps": reported_gaps,
            "retry_count": research_state.get("retry_count", 0) + 1,
            "quality_signals": [{
                "agent": "self_reviewer",
                "review_status": "completed" if review_usable else "unavailable",
                "review_mode": _self_review_mode(),
                "review_validation_error": review_error,
                "review_attempts": review_attempts,
                "passed_count": passed_count if review_usable else None,
                "total_checks": 6,
                "confidence": confidence,
                "gaps_found": len(reported_gaps),
                # Counts and fixed categories only; never model prose.
                "corrections_applied": len(applied),
                "corrections_rejected": len(rejected),
                "decision_guard_actions": guard_actions,
                "corrected_fields": [f"{c['option']}/{c['field']}" for c in applied],
                "report_rerendered": True,
                "evidence_input_budget_chars": review_budget or EVIDENCE_INPUT_BUDGET_CHARS,
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
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("self_reviewer", local_usage)],
        }
