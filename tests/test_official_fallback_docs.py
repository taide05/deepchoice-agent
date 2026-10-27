"""Official static-doc fallback (llms.txt / GitHub Pages README)."""
import asyncio

from deepchoice.retrievers import official as official_mod
from deepchoice.retrievers.official import _fallback_doc_targets
from deepchoice.retrievers.official_fetch import OfficialFetchBudget


def test_github_pages_root_uses_same_host_llms_candidates_only():
    # *.github.io cannot pass host identity for a product named in the path, so
    # off-host README mirrors are not attempted; only same-host llms.txt endpoints.
    targets = _fallback_doc_targets("https://langchain-ai.github.io/langgraph/")
    assert targets
    assert all(target.startswith("https://langchain-ai.github.io/") for target in targets)
    assert all("llms" in target for target in targets)
    assert not any("raw.githubusercontent" in target for target in targets)


def test_plain_docs_root_gets_llms_candidates_only():
    targets = _fallback_doc_targets("https://docs.example.com/docs/")
    assert any(target == "https://docs.example.com/llms.txt" for target in targets)
    assert any(target.endswith("/docs/llms.txt") for target in targets)
    assert all("llms" in target for target in targets)


def test_fallback_targets_are_bounded_and_http_only():
    targets = _fallback_doc_targets("https://docs.example.com/")
    assert len(targets) <= 3
    assert all(target.startswith("https://") for target in targets)
    assert _fallback_doc_targets("not-a-url") == []


def test_navigation_root_tries_static_fallback_and_can_admit_body(monkeypatch):
    from deepchoice.retrievers import official as official_mod

    monkeypatch.setitem(official_mod.TECH_DOCS, "langgraph",
                        {"url": "https://langgraph.dev/",
                         "title": "LangGraph — Official Documentation"})
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_PAGE_ATTEMPTS_PER_RUN", 8)
    monkeypatch.setattr(official_mod, "OFFICIAL_FETCH_MAX_HTTP_REQUESTS_PER_RUN", 32)
    monkeypatch.setattr(
        official_mod, "budget_for_research",
        lambda **kwargs: OfficialFetchBudget(max_page_attempts=8,
                                             max_http_requests=32))
    written = []

    async def fake_fetch(self, url, **kwargs):
        written.append(url)
        if "llms" in url:
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
    assert any("llms" in url for url in written), written
    assert any(row.get("has_body") and row.get("_from_fallback") for row in rows), written
