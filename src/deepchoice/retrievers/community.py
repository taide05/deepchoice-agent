import asyncio
import os
from datetime import datetime, timezone
from .base import BaseRetriever
from .. import outbound as _outbound

# Stack Exchange allows exactly ONE request per IP at a time (throttle_violation
# otherwise). This semaphore serializes community searches within the process —
# concurrency 12 would otherwise throttle all but one of them.
_SEARCH_SEM = asyncio.Semaphore(1)
_SEARCH_TIMEOUT_S = 20.0


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else query).replace(" vs ", " ").replace(" versus ", " ")[:150]
        results = []

        se_key = os.getenv("STACKEXCHANGE_API_KEY", "")
        try:
            await asyncio.wait_for(_SEARCH_SEM.acquire(), timeout=_SEARCH_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"StackExchange queue timed out after {_SEARCH_TIMEOUT_S}s (throttled)"
            )
        try:
            async with await _outbound.make_client("community") as client:
                so_resp = await client.get(
                    "https://api.stackexchange.com/2.3/search",
                    params={
                        "intitle": keywords, "site": "stackoverflow",
                        "pagesize": max(2, max_results),
                        "order": "desc", "sort": "votes",
                        "key": se_key,
                    } if se_key else {
                        "intitle": keywords, "site": "stackoverflow",
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
                # Fail loudly instead of silently scoring a starved source:
                # a non-200 (rate limit, auth error) with nothing retrieved
                # must surface as a source failure, not an empty success.
                error_body = so_resp.text[:200] if so_resp.text else ""
                raise RuntimeError(
                    f"StackExchange HTTP {so_resp.status_code}: {error_body}"
                )
        finally:
            _SEARCH_SEM.release()

        return results[:max_results]
