import asyncio

from .. import outbound as _outbound
from .base import BaseRetriever, is_authority_error
from .contracts import PartialRetrievalError
from .official_pages import _read_page
from .query_results import merge_query_results
from ..budget_errors import BudgetError
from ..runtime.context import get_run_context
from ..utils.source_scope import source_terms
from .tavily_keypool import post_with_failover


class TavilySearch(BaseRetriever):
    source = "tavily"

    @staticmethod
    async def _page_backed(result: dict) -> tuple[dict, Exception | None]:
        """Keep a provider summary visibly partial if the exact page cannot be read."""
        url = result.get("url")
        snippet = result.get("snippet")
        if not isinstance(url, str) or not isinstance(snippet, str) or not snippet.strip():
            return result, ValueError("Tavily result has no readable locator or summary")
        terms = source_terms(snippet)
        if not terms:
            return result, None
        try:
            page, _, _, _ = await _read_page(
                url, url, terms, exact_page=True,
            )
        except BudgetError:
            raise
        except Exception as exc:
            if is_authority_error(exc):
                raise
            return result, exc
        if not page or not page.get("snippet"):
            return result, ValueError("Tavily page has no usable excerpt")
        updated = {**result, "snippet": page["snippet"]}
        if page.get("_source_scope_sentences"):
            updated["_source_scope_sentences"] = page["_source_scope_sentences"]
        return updated, None

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
            merged = merge_query_results(batches, max_results)
            if get_run_context() is None:
                return merged
            enriched = await asyncio.gather(
                *(self._page_backed(item) for item in merged), return_exceptions=True,
            )
            for item in enriched:
                if isinstance(item, BaseException):
                    raise item
            results = [item[0] for item in enriched]
            incomplete = next((item[1] for item in enriched if item[1] is not None), None)
            if incomplete is not None:
                raise PartialRetrievalError(results, incomplete)
            return results
