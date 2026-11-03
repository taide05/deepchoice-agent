"""Server-side page extraction through Tavily (Phase-A fetch fallback).

Why this exists: the official channel fetches pages with a pinned-IP client on the
local network. Some documentation hosts (observed 2026-11: huggingface.co TGI docs,
raw.githubusercontent.com) are unreachable or reset from this machine, so those
pages end up as navigation links with no body and the decisive evidence is lost.
Tavily fetches pages server-side; when the local fetch fails for a page the runtime
already references, this module returns the extracted text so the evidence layer can
still cite a body-level source (labelled with its own provenance).

The returned text is *not* trusted as first-party by itself: callers still run the
same page-identity and admission checks they run for a locally fetched page, and the
result records ``fetch_via="tavily_extract"`` so the report and health records can
label it.
"""
from __future__ import annotations

import httpx

from .tavily_keypool import post_with_failover

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
MAX_EXTRACT_URLS = 5


async def extract_pages(urls: list[str]) -> dict[str, dict]:
    """Extract page text server-side for up to ``MAX_EXTRACT_URLS`` URLs.

    Returns ``{url: {"text": str, "title": str}}`` for extracted pages. A missing
    URL or an empty extraction is absent from the mapping; this function never
    raises for a failing API call (the caller already has a failed local fetch).
    """
    wanted = [str(url) for url in urls if str(url or "").strip()]
    if not wanted:
        return {}
    wanted = list(dict.fromkeys(wanted))[:MAX_EXTRACT_URLS]

    async with httpx.AsyncClient(timeout=40) as client:
        async def post(url, json=None, **kw):
            return await client.post(url, json=json, **kw)

        try:
            response, _ = await post_with_failover(post, {"urls": wanted})
            if response is None:
                return {}
            response.raise_for_status()
            data = response.json()
        except Exception:
            return {}

    extracted: dict[str, dict] = {}
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        text = str(item.get("raw_content") or item.get("content") or "")
        if url and text.strip():
            extracted[url] = {
                "text": text,
                "title": str(item.get("title") or ""),
            }
    return extracted
