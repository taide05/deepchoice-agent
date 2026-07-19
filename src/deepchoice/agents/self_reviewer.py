from ..utils.llm import call_model
from ..utils.views import print_agent_output

REVIEW_PROMPT = """You are a rigorous quality reviewer. Evaluate this research report against a 6-item checklist.

## Report
{report}

## Evidence Chains
{evidence_chains}

## Original Sub-Questions
{sub_questions}

## Retry Count
{retry_count}

## Checklist — Answer YES or NO for each, with a brief note:
1. Does every conclusion have source support? (If not, list unsupported conclusions)
2. Are there any unsourced claims? (List them if yes)
3. Does the recommendation cover all 5 comparison dimensions? (Functionality, Performance, Ecosystem, Developer Experience, Scenario Fit)
4. Are there unlabeled information conflicts? (List them if yes)
5. Are any user sub-questions unanswered? (List which ones)
6. Are there counter-examples or negative findings not flagged? (List them if yes)

## Confidence Assessment
- high: 6/6 passed, all evidence chains have strong or moderate strength
- medium: 1-2 items failed, no critical gaps
- low: 3+ items failed OR critical information missing

## Gap Analysis
If confidence is not "high", list the specific information gaps. Each gap should be a specific search query that could fill the gap.

Return ONLY a JSON object:
{{
  "checks": [
    {{"item": 1, "passed": true, "note": "..."}},
    ...
  ],
  "passed_count": N,
  "confidence": "high|medium|low",
  "knowledge_gaps": ["gap query 1", "gap query 2"],
  "critical_gaps": ["critical gap"]
}}"""


class SelfReviewerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        print_agent_output("Running self-review quality check", agent="SELF_REVIEWER")

        prompt = [{
            "role": "user",
            "content": REVIEW_PROMPT.format(
                report=research_state.get("report", ""),
                evidence_chains=str(research_state.get("evidence_chains", [])),
                sub_questions=str(research_state.get("sub_questions", [])),
                retry_count=research_state.get("retry_count", 0),
            ),
        }]

        result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")

        return {
            "confidence": result.get("confidence", "medium"),
            "knowledge_gaps": result.get("knowledge_gaps", []),
            "retry_count": research_state.get("retry_count", 0) + 1,
        }
