import asyncio

import httpx
from .base import BaseRetriever
from .tavily_keypool import post_with_failover


class TavilySearch(BaseRetriever):
    source = "tavily"
    # Bound concurrent Tavily requests — the free tier rate-limits aggressively;
    # a small window avoids 429 bursts while cutting the serial fan-out.
    _SEM = asyncio.Semaphore(3)

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]

        async with httpx.AsyncClient(timeout=15) as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            async def _one(q):
                async with self._SEM:
                    resp, _ = await post_with_failover(post, {
                        "query": q,
                        "search_depth": "basic",
                        "max_results": max(3, max_results // len(queries)),
                    })
                    if resp is None:
                        raise RuntimeError("no Tavily API key available")
                    resp.raise_for_status()
                    data = resp.json()
                    return [{
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("content", ""),
                        "date": r.get("published_date", ""),
                    } for r in data.get("results", [])]

            batches = await asyncio.gather(*[_one(q) for q in queries])
            all_results = []
            for b in batches:
                all_results.extend(b)
            return all_results[:max_results]
