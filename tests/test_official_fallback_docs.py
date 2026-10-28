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


def test_deep_doc_links_rank_question_dimensions_within_scope():
    from deepchoice.retrievers.official import _deep_doc_links

    root = "https://docs.example.com/docs/overview.md"
    body = ("[Persistence](https://docs.example.com/docs/persistence.md) "
            "[Migration](https://docs.example.com/docs/migration.md) "
            "[Security](https://docs.example.com/docs/security.md) "
            "[Pricing](https://docs.example.com/pricing) "
            "[Other host](https://evil.example/docs/migration.md)")
    terms = ("migration", "rollback", "persistence", "security", "performance")
    links = _deep_doc_links(root, body, [], terms, root, limit=2)
    assert all(link.startswith("https://docs.example.com/docs/") for link in links)
    assert "migration" in links[0] or "persistence" in links[0]
    assert "pricing" not in " ".join(links)


def test_deep_docs_are_fetched_from_curated_root(monkeypatch):
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    monkeypatch.setitem(official_mod.TECH_DOCS, "deepframework",
                        {"url": "https://docs.example.com/docs/overview.md",
                         "title": "DeepFramework — Official Documentation"})
    monkeypatch.setattr(official_mod, "load_learned", lambda: {})
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 8)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 32)
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=8,
                                             max_http_requests=32))

    async def fake_fetch(self, url, **kwargs):
        if url.endswith("/overview.md"):
            body = ("[Persistence](https://docs.example.com/docs/persistence.md) "
                    "[Migration](https://docs.example.com/docs/migration.md) "
                    "DeepFramework overview.")
        else:
            body = f"{url} — DeepFramework migration and persistence docs."
        return {"ok": True, "url": url, "body": body, "title": "DeepFramework",
                "page_chars": len(body), "stored_chars": len(body),
                "body_blocks": [body], "body_url": url,
                "bytes_read": len(body), "bytes_retained": len(body),
                "content_type": "text/markdown"}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body",
                        fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "DeepFramework migration rollback and persistence", [], 10,
        adapted_queries=[], candidate_techs=["DeepFramework"]))
    deep = [row for row in rows if row.get("_deep_doc")]
    assert deep, rows
    assert any(row.get("has_body") for row in deep), rows
    assert all(row.get("body_identity_verified") for row in deep if row.get("has_body"))


def test_batch_per_case_budget_does_not_use_shared_research_budget(monkeypatch):
    from deepchoice.retrievers import official as official_mod

    monkeypatch.setenv("OFFICIAL_FETCH_BUDGET_PER_CASE", "1")
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("shared budget must not be used in per-case mode")))
    retriever = official_mod.OfficialSearch()
    asyncio.run(retriever._do_search("q", [], 5, adapted_queries=[],
                                     candidate_techs=[]))
    assert retriever._fetch_budget is not None


def test_transient_official_fetch_is_retried_once(monkeypatch):
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    calls = {"n": 0}

    async def fake_fetch(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "failure": "timeout"}
        return {"ok": True, "body": "Official docs body", "title": "Doc",
                "url": "https://docs.example.com/page", "page_chars": 20,
                "stored_chars": 20, "body_blocks": ["Official docs body"],
                "body_url": "https://docs.example.com/page",
                "bytes_read": 20, "bytes_retained": 20}

    monkeypatch.setattr(official_mod, "fetch_official_page", fake_fetch)
    retriever = official_mod.OfficialSearch()
    retriever._fetch_budget = OfficialFetchBudget(max_page_attempts=4,
                                                  max_http_requests=8)
    result = asyncio.run(retriever._fetch_official_body(
        "https://docs.example.com/page"))
    assert result["ok"] is True
    assert calls["n"] == 2


def test_index_doc_links_pick_decision_dimensions():
    from deepchoice.retrievers.official import _index_doc_links

    text = ("<loc>https://docs.example.com/docs/audit-logging</loc>"
            "<loc>https://docs.example.com/docs/permissions</loc>"
            "<loc>https://docs.example.com/docs/marketing</loc>"
            "<loc>https://evil.example/docs/audit</loc>")
    links = _index_doc_links(
        text, "https://docs.example.com/docs/overview.md",
        ("security", "audit", "permission", "rbac"), limit=2)
    assert links and all("docs.example.com/docs/" in link for link in links)
    assert any("audit" in link for link in links)
    assert all("marketing" not in link and "evil" not in link for link in links)


def test_index_discovery_adds_deep_doc_when_root_has_no_links(monkeypatch):
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    monkeypatch.setitem(official_mod.TECH_DOCS, "indexedframework",
                        {"url": "https://docs.example.com/docs/overview.md",
                         "title": "IndexedFramework — Official Documentation"})
    monkeypatch.setattr(official_mod, "load_learned", lambda: {})
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 8)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 32)
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=8,
                                             max_http_requests=32))

    async def fake_index(url, **kwargs):
        return {"ok": True, "url": url, "body_url": url,
                "text": ("<loc>https://docs.example.com/docs/audit-logging</loc>"
                         "<loc>https://docs.example.com/docs/security</loc>"),
                "content_type": "application/xml"}

    async def fake_fetch(self, url, **kwargs):
        if url.endswith("/overview.md"):
            return {"ok": True, "url": url, "body": "IndexedFramework overview.",
                    "title": "IndexedFramework", "page_chars": 25,
                    "stored_chars": 25, "body_blocks": ["IndexedFramework overview."],
                    "body_url": url, "bytes_read": 25, "bytes_retained": 25,
                    "content_type": "text/markdown"}
        body = f"IndexedFramework official docs at {url}"
        return {"ok": True, "url": url, "body": body, "title": "IndexedFramework",
                "page_chars": len(body), "stored_chars": len(body),
                "body_blocks": [body], "body_url": url,
                "bytes_read": len(body), "bytes_retained": len(body),
                "content_type": "text/html"}

    monkeypatch.setattr(official_mod, "fetch_official_index", fake_index)
    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body",
                        fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "IndexedFramework audit permissions", [], 10,
        adapted_queries=[], candidate_techs=["IndexedFramework"]))
    deep = [row for row in rows if row.get("_deep_doc")]
    assert deep, rows
    assert any("/audit-logging" in row["url"] or "/security" in row["url"]
               for row in deep), rows
    assert any(row.get("has_body") for row in deep), rows


def test_deep_doc_links_preserve_leaf_trailing_slash():
    from deepchoice.retrievers.official import _deep_doc_links

    root = "https://docs.example.com/docs/overview.md"
    body = ("[Policy](https://docs.example.com/docs/security/policy/)\n"
            "[Policy no slash](https://docs.example.com/docs/security/policy)")
    links = _deep_doc_links(root, body, [], ("security", "policy"),
                            root, limit=2)
    assert "https://docs.example.com/docs/security/policy/" in links


def test_mapping_landing_page_uses_parent_scope():
    from deepchoice.retrievers.official import (
        _mapping_scope_identity, _mapping_scope_root_path)

    root = "https://docs.tigera.io/calico/latest/about"
    assert _mapping_scope_root_path(root) == "/calico/latest"
    assert _mapping_scope_identity(
        "Calico", "https://docs.tigera.io/calico/latest/network-policy/x",
        "Calico network policy", "Calico Kubernetes network policy guide", root) is True


def test_deep_navigation_page_follows_one_leaf_level(monkeypatch):
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    monkeypatch.setitem(official_mod.TECH_DOCS, "leafyframework",
                        {"url": "https://docs.example.com/stable/",
                         "title": "LeafyFramework — Official Documentation"})
    monkeypatch.setattr(official_mod, "load_learned", lambda: {})
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 12)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 32)
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=12,
                                             max_http_requests=32))

    async def fake_fetch(self, url, **kwargs):
        if url == "https://docs.example.com/stable/":
            body = ("[Security](https://docs.example.com/stable/security/) "
                    "LeafyFramework overview.")
            return {"ok": True, "url": url, "body": body, "title": "LeafyFramework",
                    "page_chars": len(body), "stored_chars": len(body),
                    "body_blocks": [body], "body_url": url,
                    "bytes_read": len(body), "bytes_retained": len(body),
                    "content_type": "text/html"}
        if url == "https://docs.example.com/stable/security/":
            return {"ok": False, "failure": "not_prose:navigation_like",
                    "links": ["https://docs.example.com/stable/security/intro/"],
                    "page_chars": 200, "prose_chars": 0,
                    "bytes_read": 200, "bytes_retained": 200}
        body = "LeafyFramework security policy prose. " * 20
        return {"ok": True, "url": url, "body": body, "title": "LeafyFramework",
                "page_chars": len(body), "stored_chars": len(body),
                "body_blocks": [body], "body_url": url,
                "bytes_read": len(body), "bytes_retained": len(body),
                "content_type": "text/html"}

    monkeypatch.setattr(official_mod.OfficialSearch, "_fetch_official_body",
                        fake_fetch)
    rows = asyncio.run(official_mod.OfficialSearch()._do_search(
        "LeafyFramework security audit", [], 10,
        adapted_queries=[], candidate_techs=["LeafyFramework"]))
    leaves = [row for row in rows if row.get("_deep_leaf")]
    assert leaves, rows
    assert any(row.get("has_body") for row in leaves), rows


def test_index_discovery_uses_redirect_target_scope(monkeypatch):
    from deepchoice.retrievers import official as official_mod
    from deepchoice.retrievers.official_fetch import OfficialFetchBudget

    async def fake_index(url, **kwargs):
        return {"ok": True, "url": url,
                "body_url": "https://docs.successor.example/llms.txt",
                "text": ("- [Audit logging](https://docs.successor.example/audit): "
                         "audit and permissions"),
                "content_type": "text/plain"}

    monkeypatch.setattr(official_mod, "fetch_official_index", fake_index)
    budget = OfficialFetchBudget(max_page_attempts=8, max_http_requests=16)

    async def main():
        return await official_mod.OfficialSearch()._discover_index_doc_links(
            "https://docs.example.com/", ("audit", "permission"), budget)

    links = asyncio.run(main())
    assert links == ["https://docs.successor.example/audit"]


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

def test_malformed_ipv6_urls_do_not_fail_the_official_channel():
    # urllib raises "Invalid IPv6 URL" for a malformed bracketed netloc. One bad
    # harvested link must be skipped as navigation, not fail the whole source.
    assert official_mod._valid_http_url("http://[bad") is False
    assert official_mod.urlparse("http://[bad").netloc == ""
    assert official_mod.urljoin("https://docs.example.com/", "http://[bad") == ""
    assert official_mod._fallback_doc_targets("http://[bad") == []
    assert official_mod._derived_doc_links(
        "https://docs.example.com/", ["http://[bad"]) == []
    assert official_mod._deep_doc_links(
        "https://docs.example.com/", "", ["http://[bad"],
        ("security", "policy"), "https://docs.example.com/") == []
