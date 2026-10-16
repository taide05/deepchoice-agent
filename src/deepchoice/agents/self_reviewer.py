from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

REVIEW_SYSTEM = """You are a rigorous quality reviewer. Evaluate research reports against a 6-item checklist.

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

Return ONLY a JSON object:
{"checks": [{"item": 1, "passed": true, "note": "..."}], "passed_count": N, "confidence": "high|medium|low", "knowledge_gaps": ["gap query"], "critical_gaps": ["critical gap"]}"""


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
        # the source text must be in the payload. Titles alone made the decisive
        # comparison impossible: the run's wrong scale (5 万亿) was visible while
        # the source that says 500 亿 was not, so the review could not catch it.
        from ..utils.candidate_identity import bounded_content_summary

        chains_summary = []
        for c in research_state.get("evidence_chains", []):
            strength = c.get("evidence_strength", "unknown")
            conclusion = c.get("conclusion", "")[:200]
            chains_summary.append(f"[{strength}] {conclusion}")
            for s in (c.get("sources") or [])[:2]:
                chains_summary.append(f"    source: {s.get('title', '?')[:80]}")
                chains_summary.append(
                    f"      text: {bounded_content_summary(s, limit=700)}")
        chains_text = "\n".join(chains_summary) if chains_summary else "No evidence chains."

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

        return {
            "confidence": result.get("confidence", "medium"),
            "knowledge_gaps": result.get("knowledge_gaps", []),
            "retry_count": research_state.get("retry_count", 0) + 1,
            "quality_signals": [{
                "agent": "self_reviewer",
                "passed_count": result.get("passed_count", 0),
                "total_checks": 6,
                "confidence": result.get("confidence", "medium"),
                "gaps_found": len(result.get("knowledge_gaps", [])),
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("self_reviewer", local_usage)],
        }
