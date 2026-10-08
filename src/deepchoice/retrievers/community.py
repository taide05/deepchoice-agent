import asyncio
from datetime import UTC, datetime

from .. import outbound as _outbound
from ..outbound import throttle
from ..outbound.credentials import stackexchange_params
from .base import BaseRetriever
from .http import budgeted_http, check_response_size
from .query_results import merge_query_results

_SEARCH_TIMEOUT_S = 180.0


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        from ..runtime.context import get_run_context

        queries = list(dict.fromkeys(adapted_queries)) if adapted_queries else [
            query.replace(" vs ", " ").replace(" versus ", " ")[:150]]
        batches = []
        async with asyncio.timeout(_SEARCH_TIMEOUT_S):
            for keywords in queries:
                params = stackexchange_params({"q": keywords, "site": "stackoverflow",
                                              "pagesize": max(2, max_results),
                                              "order": "desc", "sort": "relevance"})
                async def dispatch():
                    # Resolve outside the provider slot so its probe can use it.
                    async with await _outbound.make_client("community") as client:
                        return await throttle.get(
                            "community", client, "https://api.stackexchange.com/2.3/search/advanced",
                            params=params, timeout=15.0, request_timeout=15.0,
                        )
                response = await budgeted_http(dispatch, kind="community_query",
                                               require_budget=get_run_context() is not None)
                check_response_size(response)
                if response.status_code != 200:
                    raise RuntimeError(f"StackExchange HTTP {response.status_code}")
                body = response.json()
                if isinstance(body, dict) and body.get("error_id") is not None:
                    raise RuntimeError("StackExchange API error")
                results = []
                for item in body.get("items", [])[:max_results]:
                    date_str = ""
                    if ts := item.get("creation_date"):
                        date_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
                    results.append({
                        "url": item.get("link", ""), "title": item.get("title", ""),
                        "snippet": f"Score: {item.get('score', 0)}, Tags: {', '.join(item.get('tags', []))}",
                        "date": date_str,
                    })
                batches.append(results)
        return merge_query_results(batches, max_results)
