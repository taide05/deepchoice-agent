import httpx
from .base import BaseRetriever


class OfficialSearch(BaseRetriever):
    source = "official"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.lower().replace(" vs ", " ").split()
        results = []

        async with httpx.AsyncClient(timeout=15) as client:
            for kw in keywords[:3]:
                if len(kw) < 3:
                    continue
                resp = await client.get(f"https://pypi.org/pypi/{kw}/json")
                if resp.status_code != 200:
                    continue
                info = resp.json().get("info", {})
                results.append({
                    "url": info.get("package_url", f"https://pypi.org/project/{kw}/"),
                    "title": f"{kw} (PyPI)",
                    "snippet": f"Version: {info.get('version', 'N/A')}, Summary: {info.get('summary', '')}",
                    "date": "",
                })
        return results[:max_results]
