import asyncio
from ..retrievers import RETRIEVER_REGISTRY
from ..utils.views import print_agent_output


def _is_too_generic(sub_questions: list[str], query: str) -> bool:
    """Check if sub_questions are too generic to provide useful search dimensions."""
    if not sub_questions:
        return True
    # Heuristic: average length < 20 chars suggests overly generic questions
    avg_len = sum(len(q) for q in sub_questions) / len(sub_questions)
    return avg_len < 20


def _supplement_sub_questions(sub_questions: list[str], query: str) -> list[str]:
    """Inject the original query as a search dimension when sub_questions are generic."""
    return [f"{query} — detailed technical comparison"] + sub_questions


class MultiRetrieverAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        query = research_state["task"]["query"]
        sub_questions = research_state.get("sub_questions", [])
        print_agent_output(f"Searching 6 sources for: {query}", agent="MULTI_RETRIEVER")

        # Fallback: if LLM-decomposed sub_questions are too generic,
        # inject the original query as a concrete search dimension.
        if _is_too_generic(sub_questions, query):
            print_agent_output(
                f"Sub-questions too generic (avg_len < 20), supplementing with original query",
                agent="MULTI_RETRIEVER",
            )
            sub_questions = _supplement_sub_questions(sub_questions, query)

        tasks = []
        for name, cls in RETRIEVER_REGISTRY.items():
            retriever = cls()
            tasks.append(retriever.search(query, sub_questions))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        search_results = []
        partial_failures = []
        for name, result in zip(RETRIEVER_REGISTRY.keys(), raw_results):
            if isinstance(result, Exception):
                search_results.append({
                    "source": name, "status": "failed",
                    "results": [], "error": str(result), "latency_ms": 0,
                })
                partial_failures.append(name)
            else:
                search_results.append(result)
                if result["status"] == "failed":
                    partial_failures.append(name)

        return {"search_results": search_results, "partial_failures": partial_failures}
asyncio.gather