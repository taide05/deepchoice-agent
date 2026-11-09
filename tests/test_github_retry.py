"""GitHub source-level channel retry."""
import asyncio

import pytest

from deepchoice.retrievers import github_api


def test_make_github_client_retries_after_channel_failure(monkeypatch):
    calls = {"n": 0}
    invalidated = {"n": 0}
    fake_client = object()

    async def fake_make_client(source):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("no outbound channel available for source: github")
        return fake_client

    async def fake_invalidate(source):
        invalidated["n"] += 1

    class Resolver:
        invalidate = staticmethod(fake_invalidate)

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(github_api._outbound, "make_client", fake_make_client)
    monkeypatch.setattr(github_api._outbound, "get_resolver", lambda: Resolver())
    monkeypatch.setattr(github_api.asyncio, "sleep", fake_sleep)
    result = asyncio.run(github_api._make_github_client())
    assert result is fake_client
    assert calls["n"] == 2
    assert invalidated["n"] == 1


def test_make_github_client_raises_after_two_failures(monkeypatch):
    async def fake_make_client(source):
        raise RuntimeError("no outbound channel available for source: github")

    async def fake_invalidate(source):
        return None

    class Resolver:
        invalidate = staticmethod(fake_invalidate)

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(github_api._outbound, "make_client", fake_make_client)
    monkeypatch.setattr(github_api._outbound, "get_resolver", lambda: Resolver())
    monkeypatch.setattr(github_api.asyncio, "sleep", fake_sleep)
    with pytest.raises(RuntimeError, match="no outbound channel"):
        asyncio.run(github_api._make_github_client())
