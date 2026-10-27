"""Official static-doc fallback (common docs paths / llms.txt)."""
import asyncio

from deepchoice.retrievers import official as official_mod
from deepchoice.retrievers.official import _fallback_doc_targets
from deepchoice.retrievers.official_fetch import OfficialFetchBudget


def test_github_pages_root_gets_same_host_static_paths_first():
    # GitHub Pages project sites put the product in the path, not the host; the
    # fallback tries common static docs paths before llms.txt, all same-host.
    targets = _fallback_doc_targets("https://langchain-ai.github.io/langgraph/")
    assert targets
    assert targets[0].startswith("https://langchain-ai.github.io/langgraph/")
    assert targets[0].endswith("/stable/")
    assert all(target.startswith("https://langchain-ai.github.io/") for target in targets)
    assert not any("raw.githubusercontent" in target for target in targets)


def test_plain_docs_root_gets_path_candidates_and_llms():
    targets = _fallback_doc_targets("https://docs.example.com/docs/")
    assert targets[0] == "https://docs.example.com/docs/stable/"
    assert any(target == "https://docs.example.com/llms.txt" for target in targets)


def test_fallback_targets_are_bounded_and_http_only():
    targets = _fallback_doc_targets("https://docs.example.com/")
    assert len(targets) <= 4
    assert all(target.startswith("https://") for target in targets)
    assert _fallback_doc_targets("not-a-url") == []


def test_mapping_scope_identity_is_limited_to_curated_host_and_path():
    from deepchoice.retrievers.official import _mapping_scope_identity

    root = "https://microsoft.github.io/autogen/"
    assert _mapping_scope_identity(
        "AutoGen", "https://microsoft.github.io/autogen/stable/",
        "AutoGen — AutoGen", "AutoGen is a framework", root) is True
    assert _mapping_scope_identity(
        "AutoGen", "https://evil.example/autogen/stable/",
        "AutoGen — AutoGen", "AutoGen is a framework", root) is False
    assert _mapping_scope_identity(
        "AutoGen", "https://microsoft.github.io/other/",
        "Other", "unrelated docs", root) is False
    assert _mapping_scope_identity(
        "AutoGen", "https://microsoft.github.io/autogen/stable/",
        "Something Else", "unrelated docs", root) is False


def test_curated_langgraph_autogen_mappings_yield_two_official_bodies(monkeypatch):
    """F200-144 fix: both curated roots now fetch an admissible body.

    LangGraph's documentation moved to docs.langchain.com markdown; AutoGen's
    GitHub Pages landing page is a JS/short shell but /stable/ is static HTML.
    Mapping roots are hand-curated, so their bodies are admitted directly.
    """
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 8)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 32)
    monkeypatch.setattr(official_mod, "load_learned", lambda: {})
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=8,
                                             max_http_requests=32))
    mapping_urls = {
        "https://docs.langchain.com/oss/python/langgraph/overview.md":
            ("LangGraph", "# LangGraph\n\nLangGraph is a stateful agent graph."),
        "https://microsoft.github.io/autogen/stable/":
            ("AutoGen", "AutoGen is a framework for building AI agents."),
    }

    async def fake_fetch(self, url, **kwargs):
        if url in mapping_urls:
            title, body = mapping_urls[url]
            return {"ok": True, "url": url, "body": body, "title": title,
                    "page_chars": len(body), "stored_chars": len(body),
                    "body_blocks": [body], "body_url": url,
                    "bytes_read": len(body), "bytes_retained": len(body),
                    "content_type": "text/markdown" if url.endswith(".md") else "text/html"}
        return {"ok": False, "failure": "not_prose:short_prose_only",
                "links": [], "page_chars": 40, "prose_chars": 20,
                "bytes_read": 40, "bytes_retained": 40}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body",
                        fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "LangGraph vs AutoGen", [], 10,
        adapted_queries=[], candidate_techs=["LangGraph", "AutoGen"]))
    bodies = {row.get("source_owner"): row for row in rows if row.get("has_body")}
    assert "LangGraph" in bodies, rows
    assert "AutoGen" in bodies, rows
    assert bodies["LangGraph"]["body_url"].endswith("overview.md")
    assert bodies["AutoGen"]["body_url"].endswith("/stable/")


def test_curated_mapping_wins_over_stale_learned_entry(monkeypatch):
    """A learned URL must not shadow the curated docs root (stale LangGraph path)."""
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    monkeypatch.setattr(official_mod, "load_learned", lambda: {
        "LangGraph": {"url": "https://langgraph.dev/stable/",
                      "title": "LangGraph — Official Documentation",
                      "via": "body_fetch"}})
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 4)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 16)
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=4,
                                             max_http_requests=16))
    seen = []

    async def fake_fetch(self, url, **kwargs):
        seen.append(url)
        return {"ok": False, "failure": "not_prose:short_prose_only",
                "links": [], "page_chars": 40, "prose_chars": 20,
                "bytes_read": 40, "bytes_retained": 40}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body",
                        fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "LangGraph vs AutoGen", [], 10,
        adapted_queries=[], candidate_techs=["LangGraph"]))
    urls = [row.get("url") for row in rows]
    assert "https://docs.langchain.com/oss/python/langgraph/overview.md" in urls, urls
    assert "https://langgraph.dev/stable/" not in urls, urls


def test_navigation_root_tries_static_fallback_and_can_admit_body(monkeypatch):
    from deepchoice.retrievers import official as official_mod

    monkeypatch.setitem(official_mod.TECH_DOCS, "langgraph",
                        {"url": "https://langgraph.dev/",
                         "title": "LangGraph — Official Documentation"})
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 8)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 32)
    monkeypatch.setattr(official_mod, "load_learned", lambda: {})
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=8,
                                             max_http_requests=32))
    written = []

    async def fake_fetch(self, url, **kwargs):
        written.append(url)
        if "stable/" in url or "llms" in url:
            body = "LangGraph is a framework for stateful agent workflows. " * 10
            return {
                "ok": True, "url": url, "body": body, "title": "LangGraph",
                "page_chars": len(body), "stored_chars": len(body),
                "body_blocks": [body],
                "body_url": url, "bytes_read": len(body),
                "bytes_retained": len(body), "content_type": "text/plain",
            }
        return {"ok": False, "failure": "not_prose:short_prose_only",
                "links": [], "page_chars": 40, "prose_chars": 20,
                "bytes_read": 40, "bytes_retained": 40}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body",
                        fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "LangGraph vs AutoGen", [], 10,
        adapted_queries=[], candidate_techs=["LangGraph"]))
    assert any("stable/" in url for url in written), written
    assert any(row.get("has_body") and row.get("_from_fallback") for row in rows), written
