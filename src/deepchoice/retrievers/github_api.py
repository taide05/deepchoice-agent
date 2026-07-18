import httpx
from .base import BaseRetriever


class GitHubSearch(BaseRetriever):
    source = "github"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.lower().replace(" vs ", " ").replace(" versus ", " ").split()
        stopwords = {"for", "and", "or", "in", "the", "a", "of", "to", "with", "using", "building"}
        repos = [w for w in keywords if w not in stopwords]

        results = []
        async with httpx.AsyncClient(timeout=15) as client:
            for repo_name in repos[:3]:
                resp = await client.get(
                    "https://api.github.com/search/repositories",
                    params={"q": repo_name, "sort": "stars", "per_page": 3},
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("items", [])[:2]:
                    results.append({
                        "url": item.get("html_url", ""),
                        "title": item.get("full_name", ""),
                        "snippet": (
                            f"Stars: {item.get('stargazers_count', 0)}, "
                            f"Forks: {item.get('forks_count', 0)}, "
                            f"Updated: {item.get('updated_at', '')}"
                        ),
                        "date": item.get("updated_at", ""),
                    })
        return results[:max_results]
