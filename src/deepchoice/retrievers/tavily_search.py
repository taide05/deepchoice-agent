import asyncio

import httpx

from .base import BaseRetriever
from .tavily_keypool import post_with_failover


def interleave_batches(batches: list[list[dict]], max_results: int) -> list[dict]:
    """Merge per-query result batches with fair query coverage.

    Each query's results are taken one at a time, round-robin, before any query
    contributes a second result. The previous flatten-by-query-then-truncate
    merge let the first queries consume the whole cap, so later adapted queries
    (for example a baseline/exit-code/version sub-question) never reached the
    downstream stages even though their results were fetched. Deduplicate by URL
    and keep the caller's result cap and ordering semantics.
    """
    merged: list[dict] = []
    seen_urls: set[str] = set()
    index = 0
    while len(merged) < max_results and any(index < len(batch) for batch in batches):
        for batch in batches:
            if len(merged) >= max_results:
                break
            if index >= len(batch):
                continue
            item = batch[index]
            url = item.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            merged.append(item)
        index += 1
    return merged


class TavilySearch(BaseRetriever):
    source = "tavily"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]

        async with httpx.AsyncClient(timeout=15) as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            async def _one(q):
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

            # Fan out concurrently: post_with_failover round-robins across the
            # key pool (24 keys) and each key's token bucket spaces 5/min, so
            # concurrent queries do not burst a single key into 429.
            batches = await asyncio.gather(*[_one(q) for q in queries])
            return interleave_batches(batches, max_results)
