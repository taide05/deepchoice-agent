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
4. ANTI-BIAS: Prefer the technology that best fits the stated constraints and scene context over the more popular or newer option. If a less popular tool better matches the specific requirements (budget, team size, compliance, scalability needs), recommend it even if the competitor has more GitHub stars or search results.
5. If evidence is insufficient for a definitive answer, say so honestly
6. INLINE CITATIONS REQUIRED: Every claim in the recommendation, ranked_options rationale, and trade_offs finding MUST include inline source citations using [Source: title] notation. Example: "FastAPI's async support gives it a performance edge [Source: FastAPI Benchmarks 2025]". The "How" section must contain at least 5 inline source citations total.
7. CRITICAL: You MUST name a specific winner in the "winner" field. Even if evidence is mixed, pick the option with the strongest overall case. Do NOT output vague text like "choose the highest-scored option" — name the technology.
8. The "winner" value MUST be a technology/framework name (e.g., "LangGraph", "FastAPI", "PostgreSQL"), not a sentence.
9. CRITICAL: The winner MUST be a widely-used, established product, tool, or framework that the user could actually adopt today. NEVER recommend a research paper, academic prototype, sample repository, or obscure experimental project (e.g. "FedMon", "aws-samples/...") — if the strongest evidence only supports such an item, pick the closest mainstream alternative instead and note it in winner_rationale.

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
    {{"name": "Option A", "rank": 1, "rationale": "Why this rank (max 80 words)", "key_strength": "strongest evidence point (max 30 words)", "key_weakness": "notable limitation (max 30 words)"}}
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

        return {
            "final_recommendation": result,
            "quality_signals": quality_signals,
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("conclusion_synthesizer", local_usage)],
        }
