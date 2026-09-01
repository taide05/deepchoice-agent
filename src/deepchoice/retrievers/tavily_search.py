from .base import BaseRetriever
from .tavily_keypool import post_with_failover
from .. import outbound as _outbound


class TavilySearch(BaseRetriever):
    source = "tavily"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]

        async with await _outbound.make_client("tavily") as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            all_results = []
            for q in queries:
                resp, _ = await post_with_failover(post, {
                    "query": q,
                    "search_depth": "basic",
                    "max_results": max(3, max_results // len(queries)),
                })
                if resp is None:
                    raise RuntimeError("no Tavily API key available")
                resp.raise_for_status()
                data = resp.json()
                for r in data.get("results", []):
                    all_results.append({
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("content", ""),
                        "date": r.get("published_date", ""),
                    })
            return all_results[:max_results]
