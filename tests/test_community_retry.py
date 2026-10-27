"""Community (StackExchange) outbound-channel retry."""
import asyncio

import pytest

from deepchoice.retrievers import community as community_mod
from deepchoice.retrievers.community import CommunitySearch


@pytest.mark.asyncio
async def test_community_missing_channel_is_retried_once(monkeypatch):
    attempts = {"n": 0}

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"items": [{
                "link": "https://stackoverflow.com/q/1",
                "title": "LangGraph checkpoint",
                "score": 5,
                "tags": ["langgraph"],
                "creation_date": 1700000000,
            }]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return Response()

    async def make_client(source):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("no outbound channel available for source: community")
        return Client()

    async def no_backoff():
        return None

    monkeypatch.setattr(community_mod._outbound, "make_client", make_client)
    monkeypatch.setattr(community_mod, "_wait_for_backoff", no_backoff)
    results = await CommunitySearch()._do_search(
        "LangGraph vs AutoGen", [], 5, adapted_queries=[], candidate_techs=None)
    assert attempts["n"] == 2
    assert results and results[0]["title"] == "LangGraph checkpoint"
