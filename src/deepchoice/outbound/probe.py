"""Probe definitions: one lightweight check per retrieval source.

A probe verifies BOTH the channel (reachable) AND the source (request OK)
through that channel, so the route table reflects reality instead of
assumptions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from .channels import BaseChannel


@dataclass(frozen=True)
class ProbeSpec:
    source: str
    method: str
    url: str
    params: dict | None = None
    ok_codes: tuple[int, ...] = (200,)


PROBES: dict[str, ProbeSpec] = {
    "github": ProbeSpec(
        source="github", method="GET",
        url="https://api.github.com/search/repositories",
        params={"q": "langgraph", "per_page": 1}, ok_codes=(200,),
    ),
    "arxiv": ProbeSpec(
        source="arxiv", method="GET",
        url="https://export.arxiv.org/api/query",
        params={"search_query": "all:langgraph", "max_results": 1}, ok_codes=(200,),
    ),
    "community": ProbeSpec(
        source="community", method="GET",
        url="https://api.stackexchange.com/2.3/search/advanced",
        params={"site": "stackoverflow", "q": "langgraph", "pagesize": 1},
        ok_codes=(200,),
    ),
}


def _auth_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN", "")
    return {"Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}"} if token else {}


async def _tavily_headers() -> dict:
    key = ""
    try:
        from ..retrievers.tavily_keypool import current as pool_current

        key = await pool_current()
    except Exception:
        pass
    if not key:
        first = os.getenv("TAVILY_API_KEYS", "") or os.getenv("TAVILY_API_KEY", "")
        key = first.split(",")[0].strip() if first else ""
    return {"Authorization": f"Bearer {key}"} if key else {}


async def ok_for(source: str, client: httpx.AsyncClient) -> bool:
    """One real request through the already-wired client."""
    spec = PROBES.get(source)
    if spec is None:
        return False
    try:
        if source == "github":
            headers = _auth_headers()
        elif source == "tavily":
            headers = await _tavily_headers()
        else:
            headers = {}
        if spec.method == "POST":
            resp = await client.post(spec.url, json={"query": "langgraph", "max_results": 1},
                                     headers=headers)
        else:
            resp = await client.get(spec.url, params=spec.params, headers=headers)
        return resp.status_code in spec.ok_codes
    except Exception:
        return False


async def probe_source(source: str, channel: BaseChannel,
                       make_client=None) -> bool:
    """Full probe: channel reachable + source request OK through it.

    `make_client(source_name)` builds a client wired to the channel; used by
    the resolver. Falls back to a plain client when not provided.
    """
    try:
        # v6 channel probes against the source's own host, not a hard-coded one
        if channel.name == "direct-v6":
            from urllib.parse import urlparse

            probing = PROBES.get(source)
            host = urlparse(probing.url).hostname or "" if probing else ""
            if host:
                if not await channel.reachable(host):
                    return False
        elif not await channel.reachable():
            return False
    except Exception:
        return False

    client_factory = make_client or (lambda s: httpx.AsyncClient(timeout=9))
    try:
        async with client_factory(source) as client:
            return await ok_for(source, client)
    except Exception:
        return False
