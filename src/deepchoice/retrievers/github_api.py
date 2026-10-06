import os

import httpx

from .. import outbound as _outbound
from ..outbound.throttle import ProviderRateLimitError, is_limited
from . import github_rate
from .base import BaseRetriever
from .query_results import merge_query_results


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
        if adapted_queries:
            # Qualifiers, quoted phrases and negation are one expression.
            # Never reinterpret a repository query as independent keywords.
            all_terms = list(dict.fromkeys(adapted_queries))
        else:
            # Preserve the deprecated search() and raw-query fallback path.
            all_terms = _extract_tech_names(query, sub_questions)
            if not all_terms:
                all_terms = [w.lower() for w in query.replace(" vs ", " ").split()
                             if len(w) >= 3 and w.lower() not in {"for", "and", "the", "with", "using"}]

        headers = self._auth_headers()
        batches: list[list[dict]] = []
        errors: list[str] = []

        async with await _outbound.make_client("github") as client:
            for term in all_terms[:4]:  # max 4 searches per case (throttling centralized in github_rate)
                try:
                    resp = await github_rate.get_with_throttle(
                        client,
                        "https://api.github.com/search/repositories",
                        params={"q": term, "sort": "stars", "per_page": 5},
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        if is_limited("github", resp):
                            raise ProviderRateLimitError("GitHub rate limited")
                        errors.append(f"{term}: HTTP {resp.status_code}")
                        continue
                    data = resp.json()
                    results = []
                    for item in data.get("items", []):
                        full_name = item.get("full_name", "")
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
                    batches.append(results)
                except httpx.HTTPError as exc:
                    errors.append(f"{term}: {exc.__class__.__name__}")

        # The v1 envelope cannot represent partial source results. Keep any
        # failed query visible; an HTTP 200 with zero items is still success.
        if errors:
            raise RuntimeError("GitHub search failed: " + "; ".join(errors[:3]))
        return merge_query_results(batches, max_results)
