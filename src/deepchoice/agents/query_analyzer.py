from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

DECOMPOSITION_SYSTEM = """You are a technical research analyst. Decompose the user's technology selection question into 5 analysis dimensions.

For EACH of these 5 dimensions, generate 1-2 specific sub-questions:
1. Functionality: Feature coverage, API completeness, capability fit
2. Performance: Throughput, latency, resource consumption
3. Ecosystem: Community activity, plugins/extensions, documentation quality
4. Developer Experience: Learning curve, debugging difficulty, productivity
5. Scenario Fit: Applicability boundaries, anti-patterns, context match

CRITICAL: Each sub-question MUST include:
- At least one concrete technology/framework name from the user's query
- A specific metric or comparison point
- Minimum 15 Chinese characters or 10 English words
- NO generic "Compare X and Y" questions — always narrow to a specific aspect

Scene context is ALREADY DETERMINED by the pipeline and given in the user message — do NOT re-detect it; decompose sub-questions for that scene.

Return ONLY a JSON object (no markdown):
{"sub_questions": ["q1", "q2", "..."], "constraints": ["c1", "c2", "..."]}"""


_SCENE_KEYWORDS = {
    "solo": ("solo", "side project", "personal", "individual", "startup",
             "myself", "my own", "single developer", "1-5 people"),
    "enterprise": ("enterprise", "large org", "corporate", "500+", "compliance",
                   "sla", "security", "scale", "dozens of", "billions"),
}


def _detect_scene(query: str, given: str) -> str:
    """Deterministic scene classification: explicit input wins, else keyword
    match, else team. Runs BEFORE the LLM so it only decomposes sub-questions
    instead of also guessing the scene."""
    given = (given or "").strip().lower()
    if given in ("solo", "team", "enterprise"):
        return given
    q = query.lower()
    for scene, keywords in _SCENE_KEYWORDS.items():
        if any(k in q for k in keywords):
            return scene
    return "team"


class QueryAnalyzerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        task = research_state["task"]
        print_agent_output(f"Analyzing query: {task['query']}", agent="QUERY_ANALYZER")

        scene = _detect_scene(task["query"], task.get("scene_context", "unspecified"))

        prompt = [
            {"role": "system", "content": DECOMPOSITION_SYSTEM},
            {"role": "user", "content": f"User query: {task['query']}\nScene context (already determined): {scene}\nKnown constraints: {', '.join(task.get('constraints', [])) or 'none'}"},
        ]

        local_usage: list = []
        result = await call_model(prompt, model="deepseek-flash", response_format="json", tag="query_analyzer",
                                  usage=local_usage)

        sub_questions = result.get("sub_questions", [])
        return {
            "sub_questions": sub_questions,
            "scene_context": scene,
            "constraints": result.get("constraints", task.get("constraints", [])),
            "quality_signals": [{
                "agent": "query_analyzer",
                "sub_question_count": len(sub_questions),
                "dimensions_covered": 5,
                "scene_context": scene,
                "has_constraints": bool(task.get("constraints")),
            }],
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("query_analyzer", local_usage)],
        }
