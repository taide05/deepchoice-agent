import asyncio

import httpx

from .base import BaseRetriever
from .tavily_keypool import post_with_failover


def interleave_batches(batches: list[list[dict]], max_results: int) -> list[dict]:
    """Merge per-query result batches with fair query coverage.

    Each query's results are taken one at a time, round-robin, before any query
    contributes a second result. A flatten-by-query-then-truncate merge lets the
    first queries consume the whole cap, so later adapted queries (for example a
    baseline/exit-code/version sub-question) may not reach the downstream stages.
    Deduplicate by URL and keep the caller's result cap and ordering semantics.
    A result without a URL has no usable identity; it is skipped rather than
    allowed to consume a cap slot and push a valid result out.
    """
    merged: list[dict] = []
    seen_urls: set[str] = set()
    index = 0
    while len(merged) < max_results and any(index < len(batch) for batch in batches):
        for batch in batches:
            if len(merged) >= max_results:
                break
            if index >= len(batch):
                continue
            item = batch[index]
            url = item.get("url", "")
            if not url:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(item)
        index += 1
    return merged


INDEPENDENT_SOURCE_DOMAINS = ("reddit.com", "stackoverflow.com",
                              "news.ycombinator.com", "dev.to")


def diversity_queries(candidate_techs: list[str] | None) -> list[str]:
    """Neutral comparison queries for an independent (non-vendor) source pass.

    Limitation 2 (source concentration / single-source): ordinary retrieval ranks
    each candidate's own documentation highest, so the decisive comparison can
    rest on vendor material. One extra search restricted to independent community
    domains gives every candidate pair a chance at a non-owner comparison without
    changing the official channel or the evidence rules. Generic placeholders
    ("A"/"B") are ignored.
    """
    names = [str(name).strip() for name in candidate_techs or []
             if str(name or "").strip()]
    names = [name for name in names if len(name) >= 2 and name.upper() != name.lower()]
    if len(names) < 2:
        return []
    return [f"{names[0]} vs {names[1]} independent comparison review"]


class TavilySearch(BaseRetriever):
    source = "tavily"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]

        async with httpx.AsyncClient(timeout=15) as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            async def _one(q, include_domains=None):
                payload = {
                    "query": q,
                    "search_depth": "basic",
                    "max_results": max(3, max_results // max(1, len(queries))),
                }
                if include_domains:
                    payload["include_domains"] = list(include_domains)
                resp, _ = await post_with_failover(post, payload)
                if resp is None:
                    raise RuntimeError("no Tavily API key available")
                resp.raise_for_status()
                data = resp.json()
                return [{
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                    "date": r.get("published_date", ""),
                } for r in data.get("results", [])]

            # Fan out concurrently: post_with_failover round-robins across the
            # key pool (24 keys) and each key's token bucket spaces 5/min, so
            # concurrent queries do not burst a single key into 429.
            pending = [_one(q) for q in queries]
            for extra_q in diversity_queries(candidate_techs):
                pending.append(_one(extra_q,
                                    include_domains=INDEPENDENT_SOURCE_DOMAINS))
            batches = await asyncio.gather(*pending)
            return interleave_batches(batches, max_results)
