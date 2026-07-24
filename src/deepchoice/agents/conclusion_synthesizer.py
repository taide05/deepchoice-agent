from ..utils.llm import call_model
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
4. If evidence is insufficient for a definitive answer, say so honestly
5. Every recommendation MUST cite specific evidence (not just "based on the data")
6. CRITICAL: You MUST name a specific winner in the "winner" field. Even if evidence is mixed, pick the option with the strongest overall case. Do NOT output vague text like "choose the highest-scored option" — name the technology.
7. The "winner" value MUST be a technology/framework name (e.g., "LangGraph", "FastAPI", "PostgreSQL"), not a sentence.

## Output Structure
Return ONLY a JSON object:
{{
  "winner": "Single technology name that wins the comparison (REQUIRED — never leave empty)",
  "winner_rationale": "One sentence citing the strongest piece of evidence for this choice",
  "recommendation": "One-paragraph actionable recommendation",
  "ranked_options": [
    {{"name": "Option A", "rank": 1, "rationale": "Why this rank based on evidence", "key_strength": "strongest evidence point", "key_weakness": "notable limitation"}}
  ],
  "trade_offs": [
    {{"dimension": "e.g. Performance vs Developer Experience", "finding": "what the evidence shows", "impact": "who this matters for"}}
  ],
  "evidence_summary": "2-3 sentence summary of the evidence landscape",
  "confidence": "high|medium|low",
  "confidence_rationale": "Why this confidence level — cite evidence strength distribution and gaps",
  "unresolved_questions": ["question that evidence couldn't answer"],
  "scene_fit_note": "How this recommendation fits the scene context"
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

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
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

        return {
            "final_recommendation": result,
            "quality_signals": quality_signals,
        }
