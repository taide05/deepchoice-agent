from ..utils.llm import call_model, summarize_usage
from ..utils.views import print_agent_output

ADAPT_SYSTEM = """You are a search query optimizer. Rewrite each sub-question into 6 retriever-specific queries.

For EACH sub-question, generate 6 query variants:

1. tavily (web search): Natural language, 1-2 sentences. Include technology names and version years if relevant. Best for finding blog posts, comparisons, news.
2. arxiv (academic papers): Keywords separated by spaces. Include technical terms, method names, framework names.
3. github (code/issues): GitHub search syntax. Use repo: qualifier if known, otherwise keyword search. Include language filter if applicable.
4. chroma_kb (local knowledge base): Natural language question, similar to asking a human. Best for semantic similarity search.
5. community (StackOverflow): Include tags. Example: "site:stackoverflow.com [langgraph] agent state management"
6. official (official docs): Keywords in documentation headings or API references.

Language: Detect query language. Generate adapted queries in that language where the source supports it (Tavily/chroma_kb). For English-only sources (arxiv/github/official), use English technical terms.

Rules:
- Each variant MUST be specific and searchable
- Include version numbers or years where relevant
- If a sub-question doesn't fit a particular retriever type, still generate the best possible query

Return ONLY a JSON object:
{"adapted": [{"sub_question_index": 0, "sub_question": "...", "tavily": "...", "arxiv": "...", "github": "...", "chroma_kb": "...", "community": "...", "official": "..."}]}"""

RETRIEVER_KEYS = ["tavily", "arxiv", "github", "chroma_kb", "community", "official"]


class QueryAdapterAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        task = research_state["task"]
        sub_questions = research_state.get("sub_questions", [])

        # On retry, knowledge_gaps are the new adaptation targets
        knowledge_gaps = research_state.get("knowledge_gaps", [])
        if knowledge_gaps and research_state.get("retry_count", 0) > 0:
            sub_questions = knowledge_gaps
            print_agent_output(
                f"Retry adaptation: targeting {len(knowledge_gaps)} knowledge gaps",
                agent="QUERY_ADAPTER",
            )

        if not sub_questions:
            return {
                "adapted_queries": {},
                "quality_signals": [{"agent": "query_adapter", "adapted_count": 0, "covered_retrievers": []}],
                "token_usage": research_state.get("token_usage", [])
                + [summarize_usage("query_adapter", [])],
            }

        print_agent_output(
            f"Adapting {len(sub_questions)} sub-questions for 6 retrievers",
            agent="QUERY_ADAPTER",
        )

        prompt = [
            {"role": "system", "content": ADAPT_SYSTEM},
            {"role": "user", "content": "Sub-questions:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(sub_questions)) + f"\n\nOriginal query: {task['query']}\nConstraints: {', '.join(task.get('constraints', [])) or 'none'}"},
        ]

        local_usage: list = []
        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json",
                                      usage=local_usage)
            adapted_items = result.get("adapted", [])
        except Exception as e:
            print_agent_output(f"Query adaptation failed: {e}, using raw sub_questions", agent="QUERY_ADAPTER")
            adapted_items = []

        # Build adapted_queries dict: {retriever_name: [query_strings]}
        # Each retriever gets a flat list of its optimized queries across all sub-questions
        adapted_queries = {key: [] for key in RETRIEVER_KEYS}
        for item in adapted_items:
            for key in RETRIEVER_KEYS:
                val = item.get(key, "")
                if val:
                    adapted_queries[key].append(val)

        # Fallback: if any retriever has no adapted queries, use original sub_questions
        for key in RETRIEVER_KEYS:
            if not adapted_queries[key]:
                adapted_queries[key] = sub_questions

        quality_signals = [{
            "agent": "query_adapter",
            "adapted_count": len(adapted_items),
            "covered_retrievers": [k for k in RETRIEVER_KEYS if adapted_queries.get(k)],
            "fallback_retrievers": [k for k in RETRIEVER_KEYS if not adapted_queries.get(k)],
        }]

        return {
            "adapted_queries": adapted_queries,
            "quality_signals": quality_signals,
            "token_usage": research_state.get("token_usage", [])
            + [summarize_usage("query_adapter", local_usage)],
        }
