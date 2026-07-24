import asyncio
import os
import httpx
from .base import BaseRetriever


def _extract_tech_names(query: str, sub_questions: list[str]) -> list[str]:
    """Extract likely technology names from query and sub-questions."""
    names = []
    # Extract "X vs Y" pattern from query
    query_lower = query.lower()
    for sep in (" vs ", " versus ", " or "):
        if sep in query_lower:
            parts = query_lower.split(sep)
            if len(parts) >= 2:
                # Take the technology name before and after "vs"
                a = parts[0].split()[-2:]  # last 2 words before "vs"
                b = parts[1].split()[:2]   # first 2 words after "vs"
                names.extend([" ".join(a), " ".join(b)])
                break

    # Also extract capitalized/CamelCase words from sub-questions
    for sq in sub_questions[:3]:
        for word in sq.split():
            # CamelCase or capitalized proper nouns (but not sentence starters)
            clean = word.strip(".,;:?!()[]{}")
            if len(clean) >= 3 and (
                (clean[0].isupper() and any(c.islower() for c in clean[1:])) or
                (clean[0].isupper() and clean[-1].isupper())
            ):
                if clean.lower() not in {"what", "how", "why", "when", "which", "where", "does", "can", "should"}:
                    names.append(clean)

    # Deduplicate preserving order, lowercase
    seen = set()
    result = []
    for n in names:
        nl = n.lower()
        if nl not in seen:
            seen.add(nl)
            result.append(nl)
    return result[:5]  # max 5 search terms


class GitHubSearch(BaseRetriever):
    source = "github"

    def _auth_headers(self) -> dict:
        token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        # Strategy 1: Extract technology names and search for them
        tech_names = _extract_tech_names(query, sub_questions)

        # Strategy 2: If adapted_queries exists, extract additional search terms
        adapted_terms = []
        if adapted_queries:
            for aq in adapted_queries[:2]:
                # GitHub-adapted queries often contain search syntax
                for word in aq.replace("org:", "").replace("repo:", "").split():
                    clean = word.strip(",:;")
                    if len(clean) >= 3 and clean not in {"search", "find", "topic"}:
                        adapted_terms.append(clean)

        # Combine and deduplicate
        all_terms = tech_names + [t.lower() for t in adapted_terms if t.lower() not in set(tech_names)]
        if not all_terms:
            # Fallback: use original query keywords
            all_terms = [w.lower() for w in query.replace(" vs ", " ").split()
                        if len(w) >= 3 and w.lower() not in {"for", "and", "the", "with", "using"}]

        headers = self._auth_headers()
        results: list[dict] = []
        seen_full_names: set[str] = set()

        async with httpx.AsyncClient(timeout=15) as client:
            for term in all_terms[:4]:  # max 4 searches to stay within rate limits
                try:
                    resp = await client.get(
                        "https://api.github.com/search/repositories",
                        params={"q": term, "sort": "stars", "per_page": 5},
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for item in data.get("items", []):
                        full_name = item.get("full_name", "")
                        if full_name in seen_full_names:
                            continue
                        seen_full_names.add(full_name)
                        results.append({
                            "url": item.get("html_url", ""),
                            "title": full_name,
                            "snippet": (
                                f"Stars: {item.get('stargazers_count', 0)}, "
                                f"Forks: {item.get('forks_count', 0)}, "
                                f"Updated: {item.get('updated_at', '')}, "
                                f"Description: {item.get('description', '') or 'N/A'}"
                            ),
                            "date": item.get("updated_at", ""),
                        })
                except httpx.HTTPError:
                    continue

        return results[:max_results]
