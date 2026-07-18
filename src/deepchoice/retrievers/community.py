import httpx
from .base import BaseRetriever


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.replace(" vs ", " ").replace(" versus ", " ")[:150]
        results = []

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.stackexchange.com/2.3/search",
                params={
                    "q": keywords, "site": "stackoverflow",
                    "pagesize": max(2, max_results // 2),
                    "order": "desc", "sort": "votes",
                },
            )
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    results.append({
                        "url": item.get("link", ""),
                        "title": item.get("title", ""),
                        "snippet": f"Score: {item.get('score', 0)}",
                        "date": "",
                    })

            resp2 = await client.get(
                "https://www.reddit.com/search.json",
                params={"q": keywords, "limit": max(2, max_results // 2)},
                headers={"User-Agent": "DeepChoice/0.1"},
            )
            if resp2.status_code == 200:
                for item in resp2.json().get("data", {}).get("children", []):
                    d = item["data"]
                    results.append({
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "title": d.get("title", ""),
                        "snippet": f"r/{d.get('subreddit', '')}, Score: {d.get('score', 0)}",
                        "date": "",
                    })
        return results[:max_results]
