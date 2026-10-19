"""Bounded official-page body fetch: success, failure, safety, budget and redirects.

All tests are offline: the outbound client and DNS resolution are fake seams.
"""
import asyncio
from types import SimpleNamespace

import pytest

from deepchoice.retrievers import official as official_mod


class _FakeResponse:
    def __init__(self, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks or [b""]

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.stream_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        self.stream_calls.append(url)
        return _StreamContext(self._responses.pop(0))


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(official_mod, "_resolve_host_ips",
                        lambda host, port: ["93.184.216.34"])


def _patch_client(monkeypatch, responses):
    client = _FakeClient(responses)
    async def make_client(source):
        return client
    monkeypatch.setattr(official_mod._outbound, "make_client", make_client)
    return client


def _html(body: str) -> bytes:
    return f"<html><head><title>Official Docs</title></head><body>{body}</body></html>".encode()


def test_fetch_success_extracts_text_and_title(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(200, {"content-type": "text/html"},
                                              [_html("<h1>Docs</h1><p>Bounded body.</p>")])])
    result = asyncio.run(official_mod._fetch_official_page("https://docs.example.com/page"))
    assert result["ok"] is True
    assert result["body_url"] == "https://docs.example.com/page"
    assert "Bounded body." in result["body"]
    assert "Official Docs" in result["title"]
    assert result["content_type"] == "text/html"


def test_fetch_redirect_is_followed_after_safety_check(monkeypatch):
    client = _patch_client(monkeypatch, [
        _FakeResponse(302, {"location": "/canonical"}),
        _FakeResponse(200, {"content-type": "text/html"},
                      [_html("<p>Canonical body.</p>")]),
    ])
    result = asyncio.run(official_mod._fetch_official_page("https://docs.example.com/old"))
    assert result["ok"] is True
    assert result["body_url"] == "https://docs.example.com/canonical"
    assert "Canonical body." in result["body"]
    assert client.stream_calls == ["https://docs.example.com/old",
                                   "https://docs.example.com/canonical"]


def test_private_ip_is_rejected_without_network(monkeypatch):
    monkeypatch.setattr(official_mod, "_resolve_host_ips",
                        lambda host, port: ["127.0.0.1"])
    client = _patch_client(monkeypatch, [])
    result = asyncio.run(official_mod._fetch_official_page("https://docs.example.com/page"))
    assert result["ok"] is False
    assert result["error"].startswith("unsafe_url:")
    assert client.stream_calls == []


def test_carrier_grade_nat_and_non_global_addresses_are_rejected(monkeypatch):
    # RFC 6598 100.64.0.0/10 is not is_private and was a gap in the flag list.
    monkeypatch.setattr(official_mod, "_resolve_host_ips",
                        lambda host, port: ["100.64.0.1"])
    result = asyncio.run(official_mod._fetch_official_page("http://docs.example.com/page"))
    assert result["ok"] is False
    assert result["error"] == "unsafe_url:non_public_ip"


def test_non_html_content_type_is_rejected(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse(200, {"content-type": "application/pdf"}, [])])
    result = asyncio.run(official_mod._fetch_official_page("https://docs.example.com/page"))
    assert result["ok"] is False
    assert result["error"] == "content_type:application/pdf"


def test_raw_body_read_is_bounded_and_marked_truncated(monkeypatch):
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_BYTES", 60)
    _patch_client(monkeypatch, [_FakeResponse(
        200, {"content-type": "text/html"},
        [_html("<p>" + "A" * 500 + "</p>")])])
    result = asyncio.run(official_mod._fetch_official_page("https://docs.example.com/page"))
    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["bytes"] <= 60


def test_official_search_fetches_body_and_keeps_failed_fetch_as_navigation(monkeypatch):
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PER_RUN", 2)

    async def fake_fetch(self, url):
        if "fastapi" in url:
            return {"ok": True, "url": url, "body_url": url, "title": "FastAPI docs",
                    "body": "FastAPI documents the mechanism.", "source_chars": 34,
                    "stored_chars": 34, "truncated": False, "bytes": 100,
                    "content_type": "text/html"}
        return {"ok": False, "url": url, "error": "http:503"}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
    asyncio.run(official_mod.OfficialSearch()._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    # Re-run through the public path to inspect rows deterministically.
    from deepchoice.retrievers.official import OfficialSearch
    rows = asyncio.run(OfficialSearch()._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    fastapi = [r for r in rows if "fastapi" in r["url"]]
    flask = [r for r in rows if "flask" in r["url"]]
    assert fastapi and fastapi[0]["has_body"] is True, rows
    assert flask and flask[0]["has_body"] is False, rows
    assert flask[0]["body_error"] == "http:503", rows


def test_official_fetch_budget_is_bounded(monkeypatch):
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PER_RUN", 1)
    calls = []

    async def fake_fetch(self, url):
        calls.append(url)
        return {"ok": True, "url": url, "body_url": url, "title": "docs",
                "body": "bounded body", "source_chars": 12, "stored_chars": 12,
                "truncated": False, "bytes": 20, "content_type": "text/html"}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    assert len(calls) == 1, calls
    assert sum(1 for r in rows if r["has_body"]) == 1, rows
    assert any(r.get("body_error") == "fetch_budget_exhausted" for r in rows), rows
