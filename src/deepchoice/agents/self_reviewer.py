from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

REVIEW_SYSTEM = """You are a rigorous quality reviewer. Evaluate research reports against a 6-item checklist.

Answer YES or NO for each, with a brief note:
1. Does every conclusion have source support?
2. Are there any unsourced claims?
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

        chains_summary = []
        for c in research_state.get("evidence_chains", []):
            strength = c.get("evidence_strength", "unknown")
            conclusion = c.get("conclusion", "")[:200]
            sources = c.get("sources", [])
            source_titles = [s.get("title", "?")[:80] for s in sources[:2]]
            chains_summary.append(
                f"[{strength}] {conclusion} (sources: {', '.join(source_titles)})"
            )
        chains_text = "\n".join(chains_summary) if chains_summary else "No evidence chains."

        user_content = f"""## Report
{research_state.get("report", "")}

## Evidence Chains
{chains_text}

## Original Sub-Questions
{research_state.get("sub_questions", [])}

## Pipeline Quality Signals
{signals_text}

## Retry Count
{research_state.get("retry_count", 0)}"""

        prompt = [
            {"role": "system", "content": REVIEW_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        local_usage: list = []
        result = await call_model(prompt, model="deepseek-flash", response_format="json", tag="self_reviewer",
                                  usage=local_usage)

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
