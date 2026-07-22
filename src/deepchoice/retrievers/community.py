import asyncio
from datetime import datetime, timezone
import httpx
from .base import BaseRetriever


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else query).replace(" vs ", " ").replace(" versus ", " ")[:150]
        results = []

        async with httpx.AsyncClient(timeout=15) as client:
            so_resp, reddit_resp = await asyncio.gather(
                client.get(
                    "https://api.stackexchange.com/2.3/search",
                    params={
                        "q": keywords, "site": "stackoverflow",
                        "pagesize": max(2, max_results // 2),
                        "order": "desc", "sort": "votes",
                    },
                ),
                client.get(
                    "https://www.reddit.com/search.json",
                    params={"q": keywords, "limit": max(2, max_results // 2)},
                    headers={"User-Agent": "DeepChoice/0.1"},
                ),
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
                        "snippet": f"Score: {item.get('score', 0)}",
                        "date": date_str,
                    })

            if reddit_resp.status_code == 200:
                for item in reddit_resp.json().get("data", {}).get("children", []):
                    d = item["data"]
                    date_str = ""
                    ts = d.get("created_utc")
                    if ts:
                        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    results.append({
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "title": d.get("title", ""),
                        "snippet": f"r/{d.get('subreddit', '')}, Score: {d.get('score', 0)}",
                        "date": date_str,
                    })
        return results[:max_results]
