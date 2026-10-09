"""Exercise the real staged ordering with offline source pages."""
from copy import deepcopy
from html import escape
from unittest.mock import patch

import httpx

from deepchoice.agents.citation_validator import CitationValidatorAgent


async def run_staged(agent, state, *, fetch=None):
    current = deepcopy(state)
    sources = {source["url"]: source for chain in state.get("evidence_chains", [])
               for source in chain.get("sources", [])}
    async def synthetic_fetch(source, url, **kwargs):
        item = sources.get(url, {})
        passages = item.get("passages") or [item.get("snippet", "")]
        body = "".join("<p>" + escape(text) + "</p>" for text in passages)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})
    selection = await agent.select_sources(current)
    current.update(selection)
    with patch("deepchoice.citations.verifier.safe_fetch", fetch or synthetic_fetch):
        current.update(await CitationValidatorAgent().run(current))
    current.update(await agent.run(current))
    return current
