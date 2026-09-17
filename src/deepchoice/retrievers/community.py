from datetime import UTC, datetime

from .. import outbound as _outbound
from ..outbound import throttle
from ..outbound.credentials import stackexchange_params
from .base import BaseRetriever


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else query).replace(" vs ", " ").replace(" versus ", " ")[:150]
        params = stackexchange_params({"intitle": keywords, "site": "stackoverflow",
                                      "pagesize": max(2, max_results), "order": "desc", "sort": "votes"})
        # Resolve/probe first; never hold the provider slot while its route
        # probe tries to enter the same shared queue.
        async with await _outbound.make_client("community") as client:
            response = await throttle.get(
                "community", client, "https://api.stackexchange.com/2.3/search",
                params=params, timeout=15.0, request_timeout=15.0,
            )
        if response.status_code != 200:
            raise RuntimeError(f"StackExchange HTTP {response.status_code}")
        body = response.json()
        if isinstance(body, dict) and body.get("error_id") is not None:
            raise RuntimeError("StackExchange API error")
        results = []
        for item in body.get("items", []):
            date_str = ""
            if ts := item.get("creation_date"):
                date_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
            results.append({
                "url": item.get("link", ""), "title": item.get("title", ""),
                "snippet": f"Score: {item.get('score', 0)}, Tags: {', '.join(item.get('tags', []))}",
                "date": date_str,
            })
        return results[:max_results]
