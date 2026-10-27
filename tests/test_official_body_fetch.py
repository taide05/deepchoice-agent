"""Pinned official-page fetch: total deadline, budgets, safety and navigation."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from deepchoice import outbound
from deepchoice.outbound import safe_fetch as safe_fetch_mod
from deepchoice.retrievers import official as official_mod
from deepchoice.retrievers import official_fetch
from deepchoice.retrievers.official_fetch import (
    OfficialFetchBudget,
    fetch_official_page,
)
from deepchoice.security.urls import ResolvedUrl, SafeUrlPolicy, UnsafeUrlError

LONG_PROSE = "This documentation paragraph states a bounded, traceable fact. " * 6
DOCS_HTML = f"<html><body><main><h1>Docs</h1><p>{LONG_PROSE}</p></main></body></html>"
NAV_HTML = ("<html><body><nav><a>Home</a><a>Docs</a></nav>"
            "<main><p>Sign in to continue.</p></main></body></html>")


class _PublicPolicy:
    def __init__(self, redirect_private: str | None = None):
        self.redirect_private = redirect_private

    async def resolve(self, url):
        if self.redirect_private and url.startswith(self.redirect_private):
            raise UnsafeUrlError("private redirect target")
        return ResolvedUrl(url, "docs.example.com", 443, ("93.184.216.34",))


@pytest.fixture(autouse=True)
def _reset_official_fetch_budgets():
    official_fetch.reset_research_budgets()
    outbound.reset_for_tests()
    yield
    official_fetch.reset_research_budgets()
    outbound.reset_for_tests()


def _patch_transport(monkeypatch, handler):
    monkeypatch.setattr(
        safe_fetch_mod, "_transport_factory",
        lambda pinned_ip: httpx.MockTransport(handler),
    )


def _response(body: str, *, status=200, content_type="text/html", headers=None):
    merged = {"content-type": content_type}
    merged.update(headers or {})
    return httpx.Response(status, headers=merged, content=body.encode())


def test_transport_construction_failure_does_not_consume_http_budget(monkeypatch):
    def fail_factory(pinned_ip):
        raise RuntimeError("transport setup failed")

    monkeypatch.setattr(safe_fetch_mod, "_transport_factory", fail_factory)
    budget = OfficialFetchBudget()
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
        store_chars=1000,
    ))
    assert result["ok"] is False
    assert budget.http_requests == 0


def test_gzip_is_rejected_before_decompression(monkeypatch):
    import gzip

    compressed = gzip.compress(DOCS_HTML.encode())
    _patch_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/html", "content-encoding": "gzip"},
        content=compressed))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["ok"] is False
    assert result["failure"].startswith("content_encoding:")
    assert result["budget"]["bytes_read"] == 0
    assert result["budget"]["bytes_retained"] == 0


def test_identity_encoding_is_accepted(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "text/html", "content-encoding": "identity"},
        content=DOCS_HTML.encode()))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["ok"] is True
    assert result["budget"]["bytes_read"] > 0


def test_fetched_page_is_citable_and_records_page_storage_split(monkeypatch):
    _patch_transport(monkeypatch, lambda request: _response(DOCS_HTML))
    budget = OfficialFetchBudget(max_page_attempts=1, max_http_requests=3)
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
        store_chars=100,
    ))
    assert result["ok"] is True
    assert "bounded, traceable fact" in result["body"]
    assert result["body_url"] == "https://docs.example.com/page"
    assert result["page_chars"] > result["stored_chars"]
    assert result["page_truncated"] is False
    assert result["stored_truncated"] is True
    assert budget.http_requests == 1


def test_markdown_documentation_is_citable(monkeypatch):
    """Docs sites increasingly expose .md pages; they are plain text, not HTML."""
    markdown = "# LangGraph\n\n" + LONG_PROSE
    _patch_transport(monkeypatch, lambda request: _response(
        markdown, content_type="text/markdown; charset=utf-8"))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page.md", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(max_page_attempts=1, max_http_requests=3),
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
        store_chars=5000,
    ))
    assert result["ok"] is True
    assert "bounded, traceable fact" in result["body"]
    assert result["content_type"].startswith("text/markdown")


def test_navigation_or_login_page_is_not_citable(monkeypatch):
    _patch_transport(monkeypatch, lambda request: _response(NAV_HTML))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/login", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["ok"] is False
    assert result["failure"].startswith("not_prose:")
    assert "body" not in result


def test_div_based_documentation_with_low_link_density_is_admitted(monkeypatch):
    divs = "".join(
        f"<div>Documentation paragraph {index} explains the bounded mechanism "
        f"with conditions and consequences in prose form.</div>"
        for index in range(5)
    )
    html = f"<html><body><main>{divs}</main></body></html>"
    _patch_transport(monkeypatch, lambda request: _response(html))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/guide", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=4000,
    ))
    assert result["ok"] is True, result
    assert "bounded mechanism" in result["body"]


def test_link_heavy_menu_is_not_admitted(monkeypatch):
    items = "".join(
        f"<li><a href='/p{index}'>Navigation item {index} documentation section</a></li>"
        for index in range(20)
    )
    html = f"<html><body><ul>{items}</ul></body></html>"
    _patch_transport(monkeypatch, lambda request: _response(html))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/menu", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=4000,
    ))
    assert result["ok"] is False
    assert result["failure"].startswith("not_prose:")


def test_heading_only_toc_and_button_menu_are_not_admitted(monkeypatch):
    headings = "".join(
        f"<h2>Table of contents entry {index} with a long descriptive heading</h2>"
        for index in range(10)
    )
    buttons = "".join(
        f"<div><button>Menu control {index} opens a navigation section</button></div>"
        for index in range(15)
    )
    for html in (f"<html><body>{headings}</body></html>",
                 f"<html><body>{buttons}</body></html>"):
        _patch_transport(monkeypatch, lambda request, h=html: _response(h))
        result = asyncio.run(fetch_official_page(
            "https://docs.example.com/menu", policy=_PublicPolicy(),
            budget=OfficialFetchBudget(), deadline_s=1.0,
            max_response_bytes=100_000, max_redirects=2, store_chars=4000,
        ))
        assert result["ok"] is False, result
        assert result["failure"].startswith("not_prose:")


def test_redirects_are_counted_and_revalidated(monkeypatch):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/canonical"})
        return _response(DOCS_HTML)

    _patch_transport(monkeypatch, handler)
    budget = OfficialFetchBudget(max_page_attempts=1, max_http_requests=3)
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/start", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
        store_chars=1000,
    ))
    assert result["ok"] is True
    assert result["body_url"] == "https://docs.example.com/canonical"
    assert budget.http_requests == 2
    assert budget.redirects == 1


def test_redirect_to_private_target_is_rejected_before_second_request(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://private.example/next"})

    _patch_transport(monkeypatch, handler)
    policy = _PublicPolicy(redirect_private="https://private.example")
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/start", policy=policy,
        budget=OfficialFetchBudget(max_http_requests=3),
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
        store_chars=1000,
    ))
    assert result["ok"] is False
    assert result["failure"] == "unsafe_url"
    assert calls == ["https://docs.example.com/start"]


def test_http_request_budget_stops_redirect_chain(monkeypatch):
    _patch_transport(
        monkeypatch,
        lambda request: httpx.Response(302, headers={"location": "/next"}),
    )
    budget = OfficialFetchBudget(max_http_requests=1)
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/start", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=3,
        store_chars=1000,
    ))
    assert result["ok"] is False
    assert result["failure"] == "http_budget_exhausted"
    assert budget.http_requests == 1


def test_total_deadline_covers_slow_reading(monkeypatch):
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.25)
            yield b"slow body"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=SlowStream())

    _patch_transport(monkeypatch, handler)
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/slow", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=0.05,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["ok"] is False
    assert result["failure"] == "timeout"


def test_content_type_missing_and_unsupported_are_explicit(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(
        200, headers={}, content=DOCS_HTML.encode()))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["failure"] == "content_type_missing"

    _patch_transport(monkeypatch, lambda request: _response(
        DOCS_HTML, content_type="application/json"))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["failure"] == "content_type:application/json"


def test_pinned_backend_connects_to_validated_ip_not_hostname(monkeypatch):
    records = []

    class FakeBackend:
        async def connect_tcp(self, host, port, timeout=None, local_address=None,
                              socket_options=None):
            records.append((host, port))
            return object()

    monkeypatch.setattr(safe_fetch_mod.httpcore, "AnyIOBackend", FakeBackend)
    backend = safe_fetch_mod._PinnedNetworkBackend("93.184.216.34")
    asyncio.run(backend.connect_tcp("docs.example.com", 443))
    assert records == [("93.184.216.34", 443)]


def _resolver(order, channels):
    cfg = SimpleNamespace(order_for=lambda source: order)
    return outbound.ChannelResolver(cfg=cfg, channels=channels)


def test_proxy_or_forward_route_is_rejected_without_fetch(monkeypatch):
    resolver = _resolver(
        ("local-proxy",),
        [SimpleNamespace(name="local-proxy", kind="local-proxy",
                         proxy_url="http://127.0.0.1:8080")],
    )
    outbound.set_resolver(resolver)
    budget = OfficialFetchBudget()
    search = official_mod.OfficialSearch()
    search._fetch_budget = budget
    result = asyncio.run(search._fetch_official_body("https://docs.example.com/page"))
    assert result["ok"] is False
    assert result["failure"] == "route_unsupported"
    assert budget.http_requests == 0
    assert [entry.kind for entry in resolver.audit] == ["safe_fetch"]
    assert resolver.audit[0].channel is None


def test_configured_proxy_is_rejected_before_probe(monkeypatch):
    resolver = _resolver(
        ("local-proxy", "direct"),
        [SimpleNamespace(name="local-proxy", kind="local-proxy",
                         proxy_url="http://127.0.0.1:8080"),
         SimpleNamespace(name="direct", kind="direct")],
    )
    outbound.set_resolver(resolver)
    budget = OfficialFetchBudget()
    search = official_mod.OfficialSearch()
    search._fetch_budget = budget
    result = asyncio.run(search._fetch_official_body("https://docs.example.com/page"))
    assert result["failure"] == "route_unsupported"
    assert [entry.kind for entry in resolver.audit] == ["safe_fetch"]
    assert budget.http_requests == 0


def test_direct_route_selection_makes_no_network_probe(monkeypatch):
    resolver = _resolver(("direct",),
                         [SimpleNamespace(name="direct", kind="direct")])
    channel, error = safe_fetch_mod.select_direct_channel(
        resolver.cfg, resolver.channels)
    assert channel is not None and error is None
    assert resolver.audit == []


def test_outbound_safe_entry_owns_route_and_audit(monkeypatch):
    _patch_transport(monkeypatch, lambda request: _response(DOCS_HTML))
    budget = OfficialFetchBudget()
    resolver = outbound.get_resolver()
    result = asyncio.run(outbound.safe_fetch_page(
        "official", "https://docs.example.com/page",
        request_budget=budget, policy=_PublicPolicy(),
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
    ))
    assert result["ok"] is True
    assert budget.http_requests == 1
    assert [entry.kind for entry in resolver.audit] == ["safe_fetch"]
    assert resolver.audit[0].channel == "direct"
    assert resolver.audit[0].ok is True


def test_fetch_connects_pinned_ip_but_keeps_original_host_in_url(monkeypatch):
    seen = {"pinned": None, "url": None}

    def factory(pinned_ip):
        seen["pinned"] = pinned_ip

        def handler(request):
            seen["url"] = str(request.url)
            return _response(DOCS_HTML)

        return httpx.MockTransport(handler)

    monkeypatch.setattr(safe_fetch_mod, "_transport_factory", factory)
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=1000,
    ))
    assert result["ok"] is True
    assert seen["pinned"] == "93.184.216.34"
    assert seen["url"].startswith("https://docs.example.com/")


def test_read_time_byte_cap_and_page_truncation_are_distinct(monkeypatch):
    first = "A" * 180 + "."
    second = "<p>" + "B" * 300 + ".</p>"
    html = f"<html><body><main><p>{first}</p>{second}</main></body></html>"
    payload = html.encode()

    class ChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            midpoint = len(payload) // 2
            yield payload[:midpoint]
            yield payload[midpoint:]

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=ChunkStream())

    _patch_transport(monkeypatch, handler)
    budget = OfficialFetchBudget()
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=300, max_redirects=2, store_chars=1000,
    ))
    if result["ok"]:
        assert result["page_truncated"] is True
        assert result["stored_truncated"] is False
    else:
        assert result["failure"].startswith("not_prose:")
    assert budget.bytes_retained == 300
    assert budget.bytes_read == len(payload)
    assert budget.bytes_read > budget.bytes_retained
    if result["ok"]:
        assert result["bytes_read"] == budget.bytes_read
        assert result["bytes_retained"] == budget.bytes_retained


def test_declared_oversize_uses_the_same_bounded_stream_as_unknown_length(monkeypatch):
    payload = ("<html><body><main><h1>Docs</h1><p>"
               + LONG_PROSE + "</p></main></body></html>").encode()

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html",
                          "content-length": str(len(payload) + 10_000)},
            content=payload)

    _patch_transport(monkeypatch, handler)
    budget = OfficialFetchBudget()
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=300, max_redirects=2, store_chars=1000,
    ))
    if result.get("ok"):
        assert result["page_truncated"] is True
        assert result["truncation_reason"] == "response_size_cap"
        assert result["declared_content_length"] is not None
        assert result["content_length_exceeded"] is True
        assert result["bytes_retained"] <= 300
    else:
        assert result["failure"].startswith("not_prose:")
    assert budget.bytes_retained <= 300


def test_main_paragraphs_keep_heading_context_but_not_navigation(monkeypatch):
    html = (
        "<html><body><nav><a>Home</a><a>Pricing</a><a>Docs</a></nav>"
        "<main><h1>Collection</h1><h2>Failure behavior</h2>"
        "<p>Exporter queues are bounded and drop when full; this is the decisive "
        "documented behavior for the scenario.</p>"
        "<p>Retry windows and WAL recovery have explicit limits.</p>"
        "<div><a>Next page</a><a>Previous page</a></div></main></body></html>"
    )
    _patch_transport(monkeypatch, lambda request: _response(html))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/collection", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=4000,
    ))
    assert result["ok"] is True, result
    assert "Failure behavior" in result["body"]
    assert "Exporter queues are bounded" in result["body"]
    assert "Pricing" not in result["body"]
    assert result["main_block_count"] >= 3
    assert result["page_role"] in {"prose_document", "mixed_document"}


def test_main_content_keeps_lists_code_and_tables_but_not_navigation(monkeypatch):
    html = (
        "<html><body><nav><a>Home</a><a>Pricing</a></nav><main>"
        "<h1>Configuration</h1>"
        "<p>The exporter uses a bounded queue and explicit retry behavior.</p>"
        "<h2>Drop policy</h2>"
        "<ul><li>Queue full drops the newest item.</li>"
        "<li>Retry timeout drops the oldest item.</li></ul>"
        "<pre><code>queue:\n  size: 1000\nretry: 5m</code></pre>"
        "<table><tr><th>Signal</th><th>Limit</th></tr>"
        "<tr><td>logs</td><td>bounded</td></tr></table>"
        "<p>These settings require a PoC before production use.</p>"
        "</main></body></html>"
    )
    _patch_transport(monkeypatch, lambda request: _response(html))
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/config", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=100_000, max_redirects=2, store_chars=4000,
    ))
    assert result["ok"] is True, result
    body = result["body"]
    assert "Drop policy" in body
    assert "Queue full drops the newest item" in body
    assert "queue:" in body and "retry: 5m" in body
    assert "Signal" in body and "logs" in body
    assert "Pricing" not in body
    assert result["page_role"] in {"prose_document", "content_document"}


def test_declared_oversize_read_path_succeeds_with_explicit_truncation(monkeypatch):
    from deepchoice.outbound.safe_fetch import fetch_pinned_bytes
    payload = b"<html><body>" + b"X" * 900 + b"</body></html>"

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html",
                          "content-length": str(len(payload) + 10_000)},
            content=payload)

    _patch_transport(monkeypatch, handler)
    budget = OfficialFetchBudget()
    result = asyncio.run(fetch_pinned_bytes(
        "https://docs.example.com/page", policy=_PublicPolicy(),
        request_budget=budget, deadline_s=1.0, max_response_bytes=300,
        max_redirects=2,
    ))
    assert result["ok"] is True
    assert result["page_truncated"] is True
    assert result["truncation_reason"] == "response_size_cap"
    assert result["declared_content_length"] == len(payload) + 10_000
    assert result["content_length_exceeded"] is True
    assert result["bytes_retained"] <= 300


def test_truncated_then_rejected_page_keeps_known_read_metadata(monkeypatch):
    payload = ("<html><body><nav>"
               + "<a>menu</a>" * 200
               + "</nav></body></html>").encode()

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html",
                          "content-length": str(len(payload) + 5000)},
            content=payload)

    _patch_transport(monkeypatch, handler)
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/menu", policy=_PublicPolicy(),
        budget=OfficialFetchBudget(), deadline_s=1.0,
        max_response_bytes=300, max_redirects=2, store_chars=1000,
    ))
    assert result["ok"] is False
    assert result["failure"].startswith("not_prose:")
    assert result["bytes_read"] is not None
    assert result["bytes_retained"] == 300
    assert result["declared_content_length"] == len(payload) + 5000
    assert result["content_length_exceeded"] is True
    assert result["page_truncated"] is True
    assert result["truncation_reason"] == "response_size_cap"


def test_client_construction_failure_does_not_consume_http_budget(monkeypatch):
    _patch_transport(monkeypatch, lambda request: _response(DOCS_HTML))

    class BadClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("client setup failed")

    monkeypatch.setattr(safe_fetch_mod.httpx, "AsyncClient", BadClient)
    budget = OfficialFetchBudget()
    result = asyncio.run(fetch_official_page(
        "https://docs.example.com/page", policy=_PublicPolicy(), budget=budget,
        deadline_s=1.0, max_response_bytes=100_000, max_redirects=2,
        store_chars=1000,
    ))
    assert result["ok"] is False
    assert budget.http_requests == 0


def test_research_budget_accumulates_on_reentry_and_is_isolated_by_identity(monkeypatch):
    monkeypatch.setattr(official_fetch, "_research_identity", lambda: "run-A")
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 2)
    monkeypatch.setattr("deepchoice.outbound.resolver.SafeUrlPolicy",
                        lambda: _PublicPolicy())
    _patch_transport(monkeypatch, lambda request: _response(DOCS_HTML))
    official_fetch.reset_research_budgets()

    first = official_mod.OfficialSearch()
    first_rows = asyncio.run(first._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    assert first._last_fetch_stats["page_attempts"] == 2
    assert first._last_fetch_stats["http_requests"] == 2
    assert all(r.get("has_body") for r in first_rows)

    second = official_mod.OfficialSearch()
    second_rows = asyncio.run(second._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    assert second._last_fetch_stats["page_attempts"] == 2
    assert second._last_fetch_stats["http_requests"] == 2
    assert all(r.get("body_error") == "page_attempt_budget_exhausted"
               for r in second_rows), second_rows

    monkeypatch.setattr(official_fetch, "_research_identity", lambda: "run-B")
    third = official_mod.OfficialSearch()
    third_rows = asyncio.run(third._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    assert third._last_fetch_stats["page_attempts"] == 2
    assert all(r.get("has_body") for r in third_rows)


def test_safe_url_policy_rejects_special_and_nat64_addresses():

    async def check(value):
        async def fake_resolver(host, port):
            return [value]
        policy = SafeUrlPolicy(resolver=fake_resolver)
        await policy.resolve("https://docs.example.com/page")

    for value in ("127.0.0.1", "100.64.0.1", "224.0.0.1",
                  "::ffff:100.64.0.1", "64:ff9b::a9fe:101",
                  "2001:db8::1", "fe80::1"):
        with pytest.raises(UnsafeUrlError):
            asyncio.run(check(value))


def test_official_search_counts_page_attempts_separately(monkeypatch):
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 1)

    async def fake_fetch(self, url, **kwargs):
        return {"ok": True, "url": url, "body_url": url,
                "body": LONG_PROSE, "page_chars": len(LONG_PROSE),
                "stored_chars": len(LONG_PROSE), "page_truncated": False,
                "stored_truncated": False, "truncated": False,
                "prose_chars": len(LONG_PROSE), "content_type": "text/html"}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body", fake_fetch)
    search = official_mod.OfficialSearch()
    rows = asyncio.run(search._do_search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    assert search._last_fetch_stats["page_attempts"] == 1
    assert any(r.get("body_error") == "page_attempt_budget_exhausted" for r in rows)

    envelope = asyncio.run(search.search(
        "FastAPI vs Flask", [], 10, None, ["FastAPI", "Flask"]))
    assert envelope["fetch_stats"]["page_attempts"] == 1
    assert envelope["fetch_stats"]["max_http_requests"] == \
        official_mod.OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN

