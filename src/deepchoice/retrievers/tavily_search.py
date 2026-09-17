import asyncio

from .. import outbound as _outbound
from .base import BaseRetriever
from ..budget_errors import BudgetError
from .tavily_keypool import post_with_failover


class TavilySearch(BaseRetriever):
    source = "tavily"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]

        async with await _outbound.make_client("tavily") as client:

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

            # Settle all sibling requests before the routed client closes on a
            # source failure. Cancellation of the parent cancels the group.
            batches = await asyncio.gather(*[_one(q) for q in queries], return_exceptions=True)
            for batch in batches:
                if isinstance(batch, BudgetError):
                    raise batch
            for batch in batches:
                if isinstance(batch, BaseException):
                    raise batch
            all_results = []
            seen_urls = set()
            for b in batches:
                for r in b:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
            return all_results[:max_results]
