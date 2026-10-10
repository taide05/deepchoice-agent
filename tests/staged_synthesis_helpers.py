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
    current.update(await agent.run(current))
    with patch("deepchoice.citations.verifier.safe_fetch", fetch or synthetic_fetch):
        checked = await CitationValidatorAgent().run(current)
        checked["quality_signals"] = current.get("quality_signals", []) + checked.get("quality_signals", [])
        current.update(checked)
    return current
