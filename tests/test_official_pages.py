"""Official v2 body acquisition: bounded fixture HTTP, never live providers."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.budget.contracts import BudgetResource
from deepchoice.budget import runtime as budget_runtime
from deepchoice.runtime import context as run_context
from deepchoice.budget_errors import BudgetExceededError, BudgetPersistenceError
from deepchoice.citations.source_windows import extract_source_document
from deepchoice.retrievers import official as official_mod
from deepchoice.retrievers import official_pages as pages
from deepchoice.retrievers.contracts import RetrievalRequest
from deepchoice.utils.official_catalog import catalog_scope_contains

ROOT = "https://docs.acme.example/docs/"
PROSE = ("Acme filtering evaluates the documented fields against a predicate before returning matching records. "
         "The selected fields remain subject to the configured access rules.")
QUALIFIER = ("However, filtering alone does not establish a permission boundary. "
             "Applications must separately enforce the user's permitted document set.")
BODY = f"<html><head><title>Acme filtering</title></head><body><main><h1>Filtering</h1><p>{PROSE}</p><p>{QUALIFIER}</p></main></body></html>"


def response(url, body=BODY, status=200, *, truncated=False):
    return httpx.Response(status, text=body, headers={"content-type": "text/html"},
                          request=httpx.Request("GET", url),
                          extensions={"deepchoice_body_truncated": truncated})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(official_mod, "TECH_DOCS", {"acme": {"url": ROOT, "title": "Acme documentation"}})
    monkeypatch.setattr(official_mod, "load_learned", lambda: {})
    monkeypatch.setattr(official_mod, "call_model", AsyncMock(return_value={"url": None}))
    monkeypatch.setattr(run_context, "get_run_context", lambda: object())
    monkeypatch.setattr(budget_runtime, "reserve_call", AsyncMock(return_value=("reservation",)))
    monkeypatch.setattr(budget_runtime, "settle_call", AsyncMock())
    monkeypatch.setattr(budget_runtime, "unknown_call", AsyncMock())
    monkeypatch.setattr(pages.outbound, "get_resolver", lambda: SimpleNamespace(invalidate=AsyncMock()))
    fetch = AsyncMock(side_effect=lambda _source, url, **_kw: response(url))
    monkeypatch.setattr(pages.outbound, "safe_fetch", fetch)
    return fetch


@pytest.mark.asyncio
async def test_directory_root_follows_real_relevant_child_and_retains_limitation(setup, monkeypatch):
    root_html = ('<html><head><title>Acme docs</title></head><body><nav>'
                 '<a href="filtering-records/">Learn more</a><a href="release-notes/">Release notes</a>'
                 '<a href="https://other.example/filtering">Filtering elsewhere</a></nav></body></html>')
    setup.side_effect = lambda _source, url, **_kw: response(url, root_html if url == ROOT else BODY)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme filtering"))
    assert result.status == "success" and len(result.results) == 1
    item = result.results[0]
    assert item["url"] == ROOT + "filtering-records/"
    assert PROSE in item["snippet"] and QUALIFIER in item["snippet"]
    assert "Official documentation site" not in item["snippet"]
    assert [call.args[1] for call in setup.await_args_list] == [ROOT, ROOT + "filtering-records/"]
    scored = await SourceEvaluatorAgent().run({"task": {"candidate_techs": ["Acme"]},
                                              "search_results": [result.model_dump()]})
    assert len(scored["source_scores"]) == 1
    assert budget_runtime.reserve_call.await_count == budget_runtime.settle_call.await_count == 2
    for call in setup.await_args_list:
        assert call.kwargs["max_response_bytes"] == 128 * 1024
        assert call.kwargs["max_redirects"] == 3 and call.kwargs["timeout_s"] == 15
    budget_runtime.unknown_call.assert_not_awaited()
    # The acquired text must survive the actual source binding/citation path.
    from deepchoice.citations.verifier import verify_citations
    from deepchoice.utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices
    chains = [{"sources": [item]}]
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]}, chains, [], [])
    monkeypatch.setattr(run_context, "get_run_context", lambda: None)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", setup)
    checks, _ = await verify_citations(bound, chains)
    checked = calibrate_evidence_choices(bound, checks)
    assert checked["source_facts"][0]["status"] == "verified"
    assert QUALIFIER in checked["source_facts"][0]["saved_text"]


@pytest.mark.asyncio
async def test_two_roots_two_children_limit_and_round_robin_coverage(setup, monkeypatch):
    roots = [ROOT, "https://docs.beta.example/docs/"]
    monkeypatch.setattr(official_mod, "TECH_DOCS", {
        "acme": {"url": roots[0], "title": "Acme documentation"},
        "beta": {"url": roots[1], "title": "Beta documentation"},
        "gamma": {"url": "https://docs.gamma.example/", "title": "Gamma documentation"},
    })
    html = BODY.replace("</body>", '<a href="filtering-one/">Filtering one</a><a href="filtering-two/">Filtering two</a><a href="filtering-three/">Filtering three</a></body>')
    setup.side_effect = lambda _source, url, **_kw: response(url, html)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme beta gamma filtering", max_results=2))
    assert result.status == "success" and len(result.results) == 2
    assert [r["url"] for r in result.results] == roots
    assert setup.await_count == 6
    assert all("three" not in call.args[1] and "gamma" not in call.args[1] for call in setup.await_args_list)


@pytest.mark.parametrize("href", ["https://evil.example/docs/filter", "/docsevil/filter", "../filter",
                                  "filter?q=secret", "filter%2Fadmin", "https://user:pass@docs.acme.example/docs/filter",
                                  "https://docs.acme.example:444/docs/filter", "https://docs.acme.example:80/docs/filter", "http://docs.acme.example/docs/filter",
                                  "#filter", "javascript:alert(1)", "filter.pdf", "https://docs.acme.example.evil/docs/filter"])
def test_discovered_url_rejects_scope_and_transport_ambiguity(href):
    assert pages._scoped_url(ROOT, ROOT, href) is None


def test_catalog_alias_and_path_segment_boundaries():
    assert catalog_scope_contains("https://sqlite.org/", "https://www.sqlite.org/backup.html")
    assert catalog_scope_contains(ROOT, ROOT + "filtering/")
    assert not catalog_scope_contains(ROOT, "https://docs.acme.example/Docs/filtering/")
    assert not catalog_scope_contains(ROOT, "https://docs.acme.example/docsevil/filtering/")
    assert pages._scoped_url(ROOT, ROOT, "filtering/#details") == ROOT + "filtering/"


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["root", "child"])
async def test_cross_scope_final_response_never_becomes_evidence(setup, which):
    def fake(_source, url, **_kw):
        if url == ROOT and which == "child":
            return response(url, '<a href="filtering/">Filtering</a>')
        return response("https://other.example/docs/filtering/", BODY)
    setup.side_effect = fake
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme filtering"))
    assert result.status == "failed" and not result.results
    assert setup.await_count == (1 if which == "root" else 2)
    budget_runtime.unknown_call.assert_not_awaited()  # A real response was received/charged.


def test_navigation_code_and_incomplete_or_oversized_context_are_not_prose():
    nav = f'<nav><p>{PROSE}</p></nav><pre>{PROSE}</pre><div role="navigation"><div><p>{PROSE}</p></div></div>'
    document = extract_source_document(nav, truncated=False, skip_navigation=True)
    assert pages._snippet(document, {"filtering"}) == ("", 0)
    # The default citation parser retains its previous navigation behavior.
    assert PROSE in " ".join(extract_source_document(nav, truncated=False).blocks)
    caveat = extract_source_document(f'<main><p>{PROSE}</p><aside role="note" class="sidebar">{QUALIFIER}</aside></main>',
                                    truncated=False, skip_navigation=True)
    assert QUALIFIER in pages._snippet(caveat, {"filtering"})[0]
    assert pages._snippet(caveat, set()) == ("", 0)
    unfinished = extract_source_document(f"<p>{PROSE}</p><p>Only if", truncated=True, skip_navigation=True)
    assert pages._snippet(unfinished, {"filtering"}) == ("", 0)
    oversized = extract_source_document(f"<p>{PROSE}</p><p>{QUALIFIER * 12}</p>", truncated=False, skip_navigation=True)
    assert pages._snippet(oversized, {"filtering"}) == ("", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [404, 429, "timeout", "cancel"])
async def test_child_failure_is_atomic_and_uncertain_spend_is_not_zero(setup, failure):
    def fake(_source, url, **_kw):
        if url == ROOT:
            return response(url, BODY.replace("</body>", '<a href="filtering/">Filtering</a></body>'))
        if failure == "timeout":
            raise TimeoutError("private provider message")
        if failure == "cancel":
            raise asyncio.CancelledError()
        return response(url, status=failure)
    setup.side_effect = fake
    invoke = official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme filtering"))
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await invoke
    else:
        result = await invoke
        assert result.status == "failed" and result.results == []
        assert "private provider message" not in result.error
    assert setup.await_count == 2
    assert budget_runtime.unknown_call.await_count == (1 if isinstance(failure, str) else 0)
    assert budget_runtime.settle_call.await_count == (1 if isinstance(failure, str) else 2)


@pytest.mark.asyncio
async def test_budget_rejection_prevents_next_http_and_propagates(setup):
    budget_runtime.reserve_call.side_effect = BudgetExceededError(BudgetResource.HTTP_CALLS, limit=1, consumed=1, requested=1)
    with pytest.raises(BudgetExceededError):
        await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme filtering"))
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_real_budget_fails_closed_in_durable_body_path(setup):
    budget_runtime.reserve_call.return_value = ()
    with pytest.raises(BudgetPersistenceError):
        await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme filtering"))
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_search_keeps_directory_path_without_new_body_calls(setup, monkeypatch):
    monkeypatch.setattr(run_context, "get_run_context", lambda: None)
    result = await official_mod.OfficialSearch().search("acme filtering", [])
    assert result["status"] == "success" and result["results"][0]["snippet"] == "Official documentation site for acme"
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_learned_mapping_cannot_acquire_body_traversal_authority(setup, monkeypatch):
    monkeypatch.setattr(official_mod, "load_learned", lambda: {"unlisted": {"url": "https://unlisted.example/docs/", "title": "Unlisted"}})
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted"))
    assert result.status == "success" and result.results[0]["snippet"].startswith("Official documentation site")
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_reachability_and_pypi_passes_use_http_accounting(setup, monkeypatch):
    retriever = official_mod.OfficialSearch()
    assert await retriever._verify_reachable(ROOT)
    assert budget_runtime.reserve_call.await_args.kwargs["summary"] == {"kind": "official_reachability"}
    monkeypatch.setattr(run_context, "get_run_context", lambda: None)
    client = AsyncMock()
    client.__aenter__.return_value = client
    monkeypatch.setattr(official_mod._outbound, "make_client", AsyncMock(return_value=client))
    monkeypatch.setattr(official_mod.throttle, "get", AsyncMock(return_value=httpx.Response(404)))
    await retriever.search("acme vs beta", [])
    kinds = [call.kwargs["summary"]["kind"] for call in budget_runtime.reserve_call.await_args_list]
    assert "official_package_metadata" in kinds
    assert len(kinds) <= 4


@pytest.mark.asyncio
async def test_adapted_query_keeps_original_words_out_of_legacy_fallback(setup):
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(
        query="acme demanding deployment filtering operations", adapted_queries=["acme"]))
    assert result.status == "success" and result.results
    official_mod.call_model.assert_not_awaited()
    assert PROSE in result.results[0]["snippet"]


def test_hidden_machine_metadata_and_void_elements_do_not_replace_visible_prose():
    metadata = '{"description":"Filtering overview contains enough textual material to look like a sentence. This is machine metadata."}'
    html = f'<main><input hidden><div hidden data-page-metadata>{metadata}</div><p>{PROSE}</p><aside>{QUALIFIER}</aside></main>'
    document = extract_source_document(html, truncated=False, skip_navigation=True)
    snippet, _ = pages._snippet(document, {"filtering"})
    assert PROSE in snippet and QUALIFIER in snippet
    assert metadata not in snippet
    assert metadata in " ".join(extract_source_document(html, truncated=False).blocks)
