import os
import httpx
from .base import BaseRetriever


class TavilySearch(BaseRetriever):
    source = "tavily"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        api_key = os.environ.get("TAVILY_API_KEY", "")
        queries = [query] + sub_questions[:2]

        async with httpx.AsyncClient(timeout=15) as client:
            all_results = []
            for q in queries:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": q,
                        "search_depth": "basic",
                        "max_results": max(3, max_results // len(queries)),
                    },
                )
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
