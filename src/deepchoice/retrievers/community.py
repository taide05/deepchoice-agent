import asyncio
import os
from datetime import datetime, timezone
import httpx
from .base import BaseRetriever


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else query).replace(" vs ", " ").replace(" versus ", " ")[:150]
        results = []

        se_key = os.getenv("STACKEXCHANGE_API_KEY", "")
        async with httpx.AsyncClient(timeout=15) as client:
            so_resp = await client.get(
                "https://api.stackexchange.com/2.3/search",
                params={
                    "q": keywords, "site": "stackoverflow",
                    "pagesize": max(2, max_results),
                    "order": "desc", "sort": "votes",
                    "key": se_key,
                } if se_key else {
                    "q": keywords, "site": "stackoverflow",
                    "pagesize": max(2, max_results),
                    "order": "desc", "sort": "votes",
                },
            )

            if so_resp.status_code == 200:
                for item in so_resp.json().get("items", []):
                    date_str = ""
                    ts = item.get("creation_date")
                    if ts:
                        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    results.append({
                        "url": item.get("link", ""),
                        "title": item.get("title", ""),
                        "snippet": f"Score: {item.get('score', 0)}, Tags: {', '.join(item.get('tags', []))}",
                        "date": date_str,
                    })
            elif so_resp.status_code != 200:
                # Log non-200 (rate limit, auth error, etc.) instead of silently skipping
                error_body = so_resp.text[:200] if so_resp.text else ""
                print(f"[community] StackExchange HTTP {so_resp.status_code}: {error_body}")

        return results[:max_results]
