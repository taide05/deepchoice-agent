import re

from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

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
3. Consider scene context: solo devs prioritize simplicity, enterprises prioritize reliability
4. ANTI-BIAS (MANDATORY three-step): Step 1 — list the constraints from Scene Context that affect this choice. Step 2 — rate each candidate's constraint-fit (high/medium/low). Step 3 — the winner MUST be the highest constraint-fit candidate, even if it is less popular or newer than a competitor with more GitHub stars or search results. Only override with a lower-fit candidate if there is overwhelming counter-evidence, and state it in winner_rationale.
5. If evidence is insufficient for a definitive answer, say so honestly
6. INLINE CITATIONS REQUIRED: EVERY factual claim field — recommendation, winner_rationale, each ranked_option (rationale, key_strength, key_weakness), each trade_off (finding, impact), evidence_summary, and scene_fit_note — MUST include inline [Source: title] citations. CRITICAL: copy the title VERBATIM from the "Evidence Chains" source titles above; NEVER invent, paraphrase, abbreviate, or rephrase a title. If unsure of the exact title, use the closest title you actually see in Evidence Chains. Example: "FastAPI's async support gives it a performance edge [Source: FastAPI Benchmarks 2025]". The "How" section must contain at least 5 inline source citations total.
7. CRITICAL: You MUST name a specific winner in the "winner" field. Even if evidence is mixed, pick the option with the strongest overall case. Do NOT output vague text like "choose the highest-scored option" — name the technology.
8. The "winner" value MUST be a technology/framework name (e.g., "LangGraph", "FastAPI", "PostgreSQL"), not a sentence.
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


def _summarize_chains(evidence_chains: list[dict]) -> str:
    if not evidence_chains:
        return "No evidence chains available."
    lines = []
    for i, c in enumerate(evidence_chains):
        strength = c.get("evidence_strength", "unknown")
        disputed = " [DISPUTED]" if c.get("disputed") else ""
        lines.append(f"{i+1}. [{strength}]{disputed} {c.get('conclusion', 'Untitled')}")
        for src in c.get("sources", [])[:2]:
            lines.append(f"   - {src.get('title', 'Unknown')} (score: {src.get('score', 'N/A')})")
    return "\n".join(lines)


def _summarize_conflicts(conflicts: list[dict]) -> str:
    if not conflicts:
        return "No conflicts found."
    lines = []
    for i, c in enumerate(conflicts):
        lines.append(
            f"{i+1}. {c.get('claim_a', '')} vs {c.get('claim_b', '')} "
            f"— resolution: {c.get('resolution', 'unknown')} "
            f"(confidence: {c.get('confidence', 'N/A')})"
        )
    return "\n".join(lines)


_GENERIC_WINNER_WORDS = {
    "flag", "gradual", "feature", "api", "app", "tool", "platform",
    "service", "system", "framework", "solution", "library", "package",
}


def _validate_winner(result: dict) -> dict:
    """Reject non-technology winners (repo paths, generic words) and fall back
    to the first valid ranked option."""
    winner = (result.get("winner") or "").strip()
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


def _sanitize_text(text: str, real: set[str]) -> str:
    """Remove fabricated [Source: title] citations from a text block, keeping
    only titles whose normalized form is in `real`."""
    if not text:
        return text
    out: list[str] = []
    last = 0
    for m in re.finditer(r'\[Source:[^\]]*\]', text, re.IGNORECASE):
        out.append(text[last:m.start()])
        titles = re.split(r'Source:\s*', m.group(0), flags=re.IGNORECASE)[1:]
        kept = []
        for t in titles:
            title = re.split(r'[,;\[\]]', t)[0].strip()
            if title and _norm_title(title) in real:
                kept.append(title)
        if kept:
            out.append('[Source: ' + ', Source: '.join(kept) + ']')
        last = m.end()
    out.append(text[last:])
    return ''.join(out)


_CITATION_TEXT_FIELDS = ("recommendation", "winner_rationale",
                         "evidence_summary", "scene_fit_note")
_CITATION_OPT_FIELDS = ("rationale", "key_strength", "key_weakness")
_CITATION_TRADEOFF_FIELDS = ("finding", "impact")


def _sanitize_citations(result: dict, evidence_chains: list[dict]) -> dict:
    """Strip hallucinated [Source: title] citations (title not among the real
    source titles fed to the synthesizer) from every factual claim field."""
    real: set[str] = set()
    for c in evidence_chains:
        for src in c.get("sources", [])[:2]:
            t = src.get("title", "")
            if t:
                real.add(_norm_title(t))
    for field in _CITATION_TEXT_FIELDS:
        if result.get(field):
            result[field] = _sanitize_text(result[field], real)
    for opt in result.get("ranked_options", []):
        for field in _CITATION_OPT_FIELDS:
            if opt.get(field):
                opt[field] = _sanitize_text(opt[field], real)
    for to in result.get("trade_offs", []):
        for field in _CITATION_TRADEOFF_FIELDS:
            if to.get(field):
                to[field] = _sanitize_text(to[field], real)
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

        print_agent_output(
            f"Synthesizing final recommendation from {len(evidence_chains)} evidence chains",
            agent="CONCLUSION_SYNTHESIZER",
        )

        strong_count = sum(1 for c in evidence_chains if c.get("evidence_strength") == "strong")
        disputed_count = sum(1 for c in evidence_chains if c.get("disputed"))

        prompt = [{
            "role": "user",
            "content": SYNTHESIS_PROMPT.format(
                query=task["query"],
                scene_context=task.get("scene_context", "team"),
                evidence_chains=_summarize_chains(evidence_chains),
                conflicts=_summarize_conflicts(conflicts),
                source_count=len(research_state.get("source_scores", [])),
                strong_count=strong_count,
                disputed_count=disputed_count,
            ),
        }]

        local_usage: list = []
        try:
            result = await call_model(prompt, model="deepseek-v4-pro", response_format="json",
                                      usage=local_usage)
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

        return {
            "final_recommendation": result,
            "quality_signals": quality_signals,
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conclusion_synthesizer", local_usage)],
        }
