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


def test_bounded_official_scope_keeps_one_extra_exception_block():
    intro = "This guide describes the product and its deployment lifecycle in general terms."
    main = "Filtering can narrow the result set under the configured index and query conditions."
    adjacent = "This behavior depends on the selected query path and the data already indexed."
    exception = "However, an unindexed field requires a different path and may change the choice."
    document = extract_source_document(
        f"<p>{intro}</p><p>{main}</p><p>{adjacent}</p><p>{exception}</p>",
        truncated=False, skip_navigation=True,
    )
    snippet, _ = pages._snippet(document, {"filtering"})
    assert main in snippet and exception not in snippet
    scope = pages._scope_near_snippet(document, snippet)
    assert scope is not None
    assert exception in " ".join(scope)
    assert len(" ".join(scope)) <= pages.MAX_SCOPE_CHARS


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
    setup.side_effect = lambda _source, url, **_kw: response(url, BODY.replace("Acme", "Unlisted").replace(
        "</body>", '<a href="filtering-child/">Filtering child</a></body>'))
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "success" and len(result.results) == 1
    assert "Unlisted filtering" in result.results[0]["snippet"]
    assert result.results[0]["origin_kind"] == "discovered"
    assert setup.await_count == 1 and setup.await_args.kwargs["max_redirects"] == 0
    assert not catalog_scope_contains(ROOT, result.results[0]["url"])
    from deepchoice.agents.source_evaluator import classify_source_type
    assert classify_source_type(result.results[0]["url"], "official") == "tech_blog"


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


@pytest.mark.asyncio
async def test_dynamic_fallback_reads_exact_page_without_learning_traversal_authority(setup, monkeypatch):
    url = "https://docs.unlisted.example/docs/filtering"
    monkeypatch.setattr(official_mod, "learn", lambda *args, **kwargs: {})
    official_mod.call_model.return_value = {"url": url}
    setup.side_effect = lambda _source, target, **_kw: response(target, BODY.replace("Acme", "Unlisted"))
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "success" and len(result.results) == 1
    assert result.results[0]["origin_kind"] == "discovered"
    assert [(c.kwargs["method"], c.kwargs["max_redirects"]) for c in setup.await_args_list] == [
        ("HEAD", 0), ("GET", 0)]
    assert all(c.args[1] == url for c in setup.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://user:fixture@unlisted.example/docs", "http://unlisted.example:8080/docs",
    "https://unlisted.example/docs/%2e%2e/private", "https://unlisted.example/docs?token=fixture",
    "https://unlisted.example/docs#fragment", "https://unlisted.example/docs/../private"])
async def test_invalid_learned_page_fails_before_any_body_dispatch(setup, monkeypatch, url):
    monkeypatch.setattr(official_mod, "load_learned", lambda: {"unlisted": {"url": url, "title": "Unlisted"}})
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "failed" and result.results == []
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovered_redirect_fails_without_child_fetch(setup, monkeypatch):
    url = "https://unlisted.example/docs/filtering"
    monkeypatch.setattr(official_mod, "load_learned", lambda: {"unlisted": {"url": url, "title": "Unlisted"}})
    setup.side_effect = lambda _source, target, **_kw: response(target, "", status=302)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "failed" and result.results == []
    assert setup.await_count == 1 and setup.await_args.kwargs["max_redirects"] == 0


@pytest.mark.asyncio
async def test_curated_roots_take_capacity_before_forged_learned_metadata(setup, monkeypatch):
    monkeypatch.setattr(official_mod, "TECH_DOCS", {
        "acme": {"url": ROOT, "title": "Acme docs"},
        "beta": {"url": "https://docs.beta.example/docs/", "title": "Beta docs"}})
    monkeypatch.setattr(official_mod, "load_learned", lambda: {"unlisted": {
        "url": "https://unlisted.example/docs/filtering", "title": "Unlisted",
        "origin_kind": "curated", "allow_children": True, "via": "curated"}})
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted beta acme filtering"))
    assert result.status == "success"
    assert setup.await_count == 2
    assert all("unlisted" not in c.args[1] for c in setup.await_args_list)
    assert all(r["origin_kind"] == "curated" for r in result.results)


@pytest.mark.asyncio
async def test_dynamic_body_budget_rejection_never_dispatches(setup, monkeypatch):
    monkeypatch.setattr(official_mod, "load_learned", lambda: {"unlisted": {
        "url": "https://unlisted.example/docs/filtering", "title": "Unlisted"}})
    budget_runtime.reserve_call.side_effect = BudgetExceededError("http_calls", limit=0, consumed=0, requested=1)
    with pytest.raises(BudgetExceededError):
        await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    setup.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_body_transport_failure_is_visible_and_keeps_unknown_http_spend(setup, monkeypatch):
    monkeypatch.setattr(official_mod, "load_learned", lambda: {"unlisted": {
        "url": "https://unlisted.example/docs/filtering", "title": "Unlisted"}})
    setup.side_effect = httpx.ConnectError("fixture transport unavailable")
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "failed" and result.results == []
    budget_runtime.unknown_call.assert_awaited_once()
    budget_runtime.settle_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_root_without_explicit_catalog_permission_reads_only_exact_page(setup):
    setup.side_effect = lambda _source, url, **_kw: response(
        url, BODY.replace("</body>", '<a href="filtering-child/">Filtering child</a></body>'))
    results = await pages.read_official_roots(
        [{"url": ROOT, "title": "Acme documentation", "tech": "acme"}], "acme filtering")
    assert len(results) == 1 and results[0]["origin_kind"] == "discovered"
    assert setup.await_count == 1
    assert setup.await_args.args[1] == ROOT
    assert setup.await_args.kwargs["max_redirects"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dns_uncertain", "route_unsupported", "safety_rejected", "timeout"])
async def test_discovery_head_safety_failure_is_visible_without_private_error(setup, monkeypatch, failure):
    from deepchoice.security.urls import SafeFetchFailure, UnsafeUrlError
    url = "https://docs.unlisted.example/docs/filtering"
    monkeypatch.setattr(official_mod, "TECH_DOCS", {})
    monkeypatch.setattr(official_mod, "call_model", AsyncMock(return_value={"url": url}))
    setup.side_effect = UnsafeUrlError("private URL and DNS details", failure=SafeFetchFailure(failure))
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(
        query="unlisted filtering", adapted_queries=("unlisted",)))
    assert result.status == "failed" and result.results == []
    assert result.error == "UnsafeUrlError"
    assert setup.await_count == 1 and setup.await_args.kwargs["method"] == "HEAD"
    budget_runtime.unknown_call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(404, "success"), (410, "success"), (503, "failed"), (302, "failed")])
async def test_discovery_head_http_absence_differs_from_failed_probe(setup, monkeypatch, status, expected):
    monkeypatch.setattr(official_mod, "TECH_DOCS", {})
    monkeypatch.setattr(official_mod, "call_model", AsyncMock(return_value={
        "url": "https://docs.unlisted.example/docs/filtering"}))
    setup.side_effect = lambda _source, url, **_kw: response(url, status=status)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(
        query="unlisted filtering", adapted_queries=("unlisted",)))
    assert result.status == expected and result.results == []
    assert setup.await_count == 1 and setup.await_args.kwargs["method"] == "HEAD"
    if expected == "failed":
        assert result.error == f"RuntimeError: HTTP {status}"


@pytest.mark.asyncio
async def test_discovery_range_probe_partial_response_still_reads_exact_body(setup, monkeypatch):
    monkeypatch.setattr(official_mod, "TECH_DOCS", {})
    url = "https://docs.unlisted.example/docs/filtering"
    monkeypatch.setattr(official_mod, "call_model", AsyncMock(return_value={"url": url}))
    monkeypatch.setattr(official_mod, "learn", lambda *_args, **_kw: {})
    setup.side_effect = lambda _source, target, **kw: response(
        target, BODY, status=206 if kw["method"] == "HEAD" else 200)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(
        query="unlisted filtering", adapted_queries=("unlisted",)))
    assert result.status == "success" and len(result.results) == 1
    assert result.results[0]["origin_kind"] == "discovered"
    assert [call.kwargs["method"] for call in setup.await_args_list] == ["HEAD", "GET"]
    assert all(call.kwargs["max_redirects"] == 0 for call in setup.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["malformed", "write"])
async def test_durable_discovery_retains_body_when_learning_fails(setup, monkeypatch, tmp_path, failure):
    from deepchoice.retrievers import learned_docs
    path = tmp_path / "learned.json"
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", path)
    monkeypatch.setattr(learned_docs, "_READONLY", False)
    monkeypatch.setattr(official_mod, "load_learned", learned_docs.load_learned)
    if failure == "malformed":
        path.write_bytes(b"[]")
    else:
        def denied(*args):
            raise PermissionError("unwritable local mapping")
        monkeypatch.setattr(learned_docs, "_atomic_write_text", denied)
    url = "https://unlisted.example/docs/filtering"
    monkeypatch.setattr(official_mod, "call_model", AsyncMock(return_value={"url": url}))
    setup.side_effect = lambda _source, target, **_kw: response(target, BODY)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "success" and len(result.results) == 1
    assert PROSE in result.results[0]["snippet"] and QUALIFIER in result.results[0]["snippet"]
    assert result.results[0]["origin_kind"] == "discovered"
    assert [call.kwargs["method"] for call in setup.await_args_list] == ["HEAD", "GET"]
    assert all(call.args[1] == url and call.kwargs["max_redirects"] == 0 for call in setup.await_args_list)
    assert budget_runtime.reserve_call.await_count == budget_runtime.settle_call.await_count == 2
    if failure == "malformed":
        assert path.read_bytes() == b"[]"


@pytest.mark.asyncio
async def test_url_only_learned_entry_is_consumable_on_durable_path(setup, monkeypatch, tmp_path):
    from deepchoice.retrievers import learned_docs
    path = tmp_path / "learned.json"
    raw = b'{"unlisted":{"url":"https://unlisted.example/docs/filtering"}}'
    path.write_bytes(raw)
    monkeypatch.setattr(learned_docs, "LEARNED_DOCS_PATH", path)
    monkeypatch.setattr(official_mod, "load_learned", learned_docs.load_learned)
    setup.side_effect = lambda _source, url, **_kw: response(url, BODY)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="unlisted filtering"))
    assert result.status == "success" and PROSE in result.results[0]["snippet"]
    assert result.results[0]["origin_kind"] == "discovered"
    assert setup.await_count == 1
    assert path.read_bytes() == raw
    assert learned_docs.official_mapping_identity() is not None


@pytest.mark.asyncio
async def test_saved_official_body_reaches_selection_binding_and_citation(setup, monkeypatch):
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.citations.verifier import verify_citations
    from deepchoice.utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices

    intro = "Acme provides the transactional storage described on this page."
    context = "Clients submit requests through a configured connection and keep the operation identifier for later checks."
    main = "Atomic transactions apply all recorded changes together after validation. A rejected transaction leaves the preceding records unchanged."
    limit = "If validation fails, clients must check the operation identifier before repeating a write; a timeout does not prove that no change was applied."
    body = f"<html><head><title>Transactions</title></head><body><main><p>{intro}</p><p>{context}</p><p>{main}</p><p>{limit}</p></main></body></html>"
    setup.side_effect = lambda _source, url, **_kw: response(url, body)
    retrieved = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme atomic transactions"))
    assert len(retrieved.results) == setup.await_count == 1
    raw = retrieved.results[0]
    assert "Acme" not in raw["title"] and "Acme" not in raw["snippet"]
    assert intro in " ".join(raw["_source_scope_sentences"])
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[0, len(raw["_source_scope_sentences"])]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    scored = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run({
        "task": {"query": "Evaluate Acme transactional writes", "candidate_techs": ["Acme"]},
        "search_results": [retrieved.model_dump()],
    })
    selector.assert_awaited_once()
    assert len(scored["source_scores"]) == 1
    item = scored["source_scores"][0]
    assert intro in item["snippet"] and limit in item["snippet"]
    assert "_source_scope_sentences" not in item
    chains = [{"sources": [item]}]
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]}, chains, [], [])
    monkeypatch.setattr(run_context, "get_run_context", lambda: None)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", setup)
    checks, _ = await verify_citations(bound, chains)
    checked = calibrate_evidence_choices(bound, checks)
    assert checked["source_facts"][0]["status"] == "verified"
    assert intro in checked["source_facts"][0]["saved_text"]
    assert limit in checked["source_facts"][0]["saved_text"]


@pytest.mark.asyncio
async def test_saved_consecutive_chinese_conditions_survive_scope_selection_and_citation(setup, monkeypatch):
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.utils.source_scope import scope_sentences
    from deepchoice.utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices
    from deepchoice.citations.verifier import verify_citations

    prose = ("Acme filtering 根据已经建立索引的字段选择匹配记录，并且按照指定的谓词返回相应的数据集合。"
             "但是字段过滤不能代替权限检查，应用程序仍然需要单独限制用户允许访问的文档集合。"
             "只有在查询路径和权限限制都经过核实时，才能据此判断当前场景的访问边界。")
    body = '<html><body><main><p>' + prose + '</p></main></body></html>'
    setup.side_effect = lambda _source, url, **_kw: response(url, body)
    retrieved = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="acme filtering"))
    assert retrieved.status == "success" and len(retrieved.results) == 1
    assert retrieved.results[0].get("_source_scope_sentences") == [prose]
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[0, 1]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    scored = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run({
        "task": {"query": "Acme 的过滤是否能单独建立权限边界？", "candidate_techs": ["Acme"]},
        "search_results": [retrieved.model_dump()],
    })
    selector.assert_awaited_once()
    assert scope_sentences(prose) == (prose,)
    assert scored["source_scores"][0]["passages"] == [prose]
    assert scored["source_scores"][0]["snippet"] == prose
    chains = [{"sources": scored["source_scores"]}]
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]}, chains, [], [])
    monkeypatch.setattr(run_context, "get_run_context", lambda: None)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", setup)
    checks, _ = await verify_citations(bound, chains)
    checked = calibrate_evidence_choices(bound, checks)
    assert checked["source_facts"][0]["status"] == "verified"
    assert checked["source_facts"][0]["saved_text"] == prose


CHINESE_PROSE = ("Acme 的字段过滤会按照指定条件选择匹配记录，并按照索引状态限制可以执行的查询。"
                 "过滤操作本身不能证明权限检查已经完成，应用程序必须单独限制用户可访问的文档集合。"
                 "只有满足这些条件，才能评估当前查询路径是否符合访问要求。")


@pytest.mark.asyncio
@pytest.mark.parametrize("query,adapted,keys,expected", [
    ("Beta与Acme比较", (), ["acme", "beta"], ["beta", "acme"]),
    ("Acme是否支持字段过滤？", (), ["acme"], ["acme"]),
    ("Beta与Acme比较", ("acme filtering",), ["acme", "beta"], ["beta", "acme"]),
    ("Acme-Core与Beta比较，之后再考虑Acme", (), ["acme", "acme-core", "beta"], ["acme-core", "beta"]),
    ("myacme库与Acme2服务", (), ["acme"], []),
    ("AWS Lambda与Beta比较", (), ["aws-lambda", "beta"], ["aws-lambda", "beta"]),
    ("awsLambda是否适用", (), ["aws-lambda"], ["aws-lambda"]),
    ("k8s与Go比较", (), ["kubernetes", "go", "mongodb"], ["kubernetes", "go"]),
    ("Next.js是否适用", (), ["next.js"], ["next.js"]),
])
async def test_durable_catalog_locator_keeps_original_mixed_script_order_and_name_boundaries(
        setup, monkeypatch, query, adapted, keys, expected):
    catalog = {key: {"url": f"https://docs.{key.replace('.', '-')}.example/docs/", "title": key + " docs"}
               for key in keys}
    monkeypatch.setattr(official_mod, "TECH_DOCS", catalog)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query=query, adapted_queries=adapted))
    assert result.status == "success"
    assert [call.args[1] for call in setup.await_args_list] == [catalog[key]["url"] for key in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("query,body", [
    ("Acme是否支持字段过滤？", CHINESE_PROSE),
    ("Acme是否支持字段过滤？", PROSE + ' ' + QUALIFIER),
    ("Acme filtering access boundary", CHINESE_PROSE),
])
async def test_chinese_request_body_is_only_a_proposal_until_selected_then_bound_and_verified(setup, monkeypatch, query, body):
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.citations.verifier import verify_citations
    from deepchoice.utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices
    setup.side_effect = lambda _source, url, **_kw: response(url, '<p>' + body + '</p>')
    retrieved = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query=query))
    assert retrieved.status == "success" and len(retrieved.results) == 1
    raw = retrieved.results[0]
    assert raw["snippet"] == "" and ' '.join(raw["_source_scope_sentences"]) == body
    state = {"task": {"query": query, "candidate_techs": ["Acme"]},
             "search_results": [retrieved.model_dump()]}
    assert not (await SourceEvaluatorAgent().run(state))["source_scores"]
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[0, len(raw["_source_scope_sentences"])]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    scored = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    selector.assert_awaited_once()
    assert len(scored["source_scores"]) == 1
    selected = scored["source_scores"][0]
    assert selected["passages"] == [body] and selected["snippet"] == body
    assert '_source_scope_sentences' not in selected
    chains = [{"sources": [selected]}]
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]}, chains, [], [])
    monkeypatch.setattr(run_context, "get_run_context", lambda: None)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", setup)
    checks, _ = await verify_citations(bound, chains)
    checked = calibrate_evidence_choices(bound, checks)
    assert checked["source_facts"][0]["status"] == "verified"
    assert checked["source_facts"][0]["saved_text"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("labels,query,expected", [
    ([('other/', '其他说明'), ('filtering/', '字段过滤'), ('access/', '访问限制')], "Acme字段过滤", ['filtering/']),
    ([('storage/', 'Storage'), ('queries/', 'Queries'), ('reference/', 'Reference')], "Acme字段过滤", ['storage/', 'queries/']),
    ([('storage/', 'Storage'), ('filtering/', 'Filtering'), ('reference/', 'Reference')], "Acme filtering", ['filtering/']),
])
async def test_curated_children_use_bounded_unicode_hints_or_no_overlap_fallback(setup, labels, query, expected):
    root = '<nav>' + ''.join(f'<a href="{href}">{label}</a>' for href, label in labels) + '</nav>'
    setup.side_effect = lambda _source, url, **_kw: response(url, root if url == ROOT else '<p>' + CHINESE_PROSE + '</p>')
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query=query))
    assert result.status == "success"
    assert [call.args[1] for call in setup.await_args_list] == [ROOT, *[ROOT + path for path in expected]]
    assert budget_runtime.reserve_call.await_count == budget_runtime.settle_call.await_count == 1 + len(expected)
    assert all(item["snippet"] == "" for item in result.results)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["navigation", "code", "hidden", "truncated", "oversized", "duplicate"])
async def test_fallback_scope_cannot_promote_hidden_incomplete_or_ambiguous_context(setup, kind):
    wrappers = {"navigation": '<nav>{}</nav>', "code": '<pre>{}</pre>', "hidden": '<div hidden>{}</div>'}
    if kind in wrappers:
        body = wrappers[kind].format('<p>' + CHINESE_PROSE + '</p>')
    elif kind == "oversized":
        body = '<p>' + CHINESE_PROSE + '</p><p>' + 'x' * 2100 + '.</p>'
    elif kind == "duplicate":
        # A long page requires windows, all of which repeat verbatim.
        body = ('<p>' + CHINESE_PROSE + '</p>') * 25
    else:
        body = '<p>' + CHINESE_PROSE + '</p>'
    setup.side_effect = lambda _source, url, **_kw: response(url, body, truncated=kind == "truncated")
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="Acme字段过滤"))
    assert result.status == "success" and result.results == []


@pytest.mark.asyncio
async def test_large_multitopic_chinese_page_offers_complete_neighbour_conditions(setup):
    noise = [('Other topic ' + str(i) + ': ') + ('records consume storage in this isolated fixture. ' * 4) for i in range(12)]
    body = ''.join('<p>' + text + '</p>' for text in [*noise[:6], CHINESE_PROSE, *noise[6:]])
    setup.side_effect = lambda _source, url, **_kw: response(url, body)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query="Acme字段过滤权限边界"))
    assert len(result.results) == 1 and result.results[0]["snippet"] == ""
    offered = ' '.join(result.results[0]["_source_scope_sentences"])
    assert CHINESE_PROSE in offered and noise[5].strip() in offered and noise[6].strip() in offered
    assert len(offered) <= pages.MAX_SCOPE_CHARS


@pytest.mark.asyncio
async def test_unrelated_chinese_official_prose_is_not_admitted_when_selector_omits_it(setup, monkeypatch):
    from deepchoice.contracts.manifest import build_run_manifest
    unrelated = ("Acme 的备份目录会保存已经写入的文件，操作之前需要检查所需的剩余磁盘空间和文件写入权限。"
                 "但是备份文件不能说明查询结果是否符合访问限制，恢复之前仍然必须核实保存的文件版本。"
                 "这些记录只描述离线备份过程，没有说明字段过滤能力或用户访问边界。")
    setup.side_effect = lambda _source, url, **_kw: response(url, '<p>' + unrelated + '</p>')
    retrieved = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query='Acme字段过滤权限边界'))
    assert retrieved.results[0]['snippet'] == ''
    selector = AsyncMock(return_value={'sources': []})
    monkeypatch.setattr('deepchoice.utils.llm.call_model', selector)
    scored = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run({
        'task': {'query': 'Acme字段过滤权限边界', 'candidate_techs': ['Acme']},
        'search_results': [retrieved.model_dump()],
    })
    selector.assert_awaited_once()
    assert not scored['source_scores']


@pytest.mark.asyncio
async def test_unicode_child_path_keeps_existing_encoded_path_failure_visible(setup):
    setup.side_effect = lambda _source, url, **_kw: response(
        url, '<a href="字段过滤/">字段过滤</a>' if url == ROOT else '<p>' + CHINESE_PROSE + '</p>')
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query='Acme字段过滤'))
    assert result.status == 'failed' and not result.results
    assert setup.await_count == 2
    assert budget_runtime.reserve_call.await_count == budget_runtime.settle_call.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['Acme-Pro与Beta比较', 'Acme.2与Beta比较', 'Other-Acme与Beta比较'])
async def test_compound_locator_does_not_fall_back_to_catalog_short_name(setup, monkeypatch, text):
    beta = 'https://docs.beta.example/docs/'
    monkeypatch.setattr(official_mod, 'TECH_DOCS', {
        'acme': {'url': ROOT, 'title': 'Acme guide'}, 'beta': {'url': beta, 'title': 'Beta guide'},
    })
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query=text))
    assert result.status == 'success'
    assert [call.args[1] for call in setup.await_args_list] == [beta]
    setup.reset_mock()
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query=text + '，另行考虑 Acme。'))
    assert result.status == 'success'
    assert [call.args[1] for call in setup.await_args_list] == [beta, ROOT]


@pytest.mark.asyncio
@pytest.mark.parametrize('query,body', [('acme filtering', BODY), ('Acme字段过滤', '<p>' + CHINESE_PROSE + '</p>')])
async def test_no_overlap_children_never_risk_existing_root_body(setup, query, body):
    root_body = body + '<nav><a href="login/">Login</a><a href="old-guide/">Old guide</a></nav>'
    setup.side_effect = lambda _source, url, **_kw: response(url, root_body, status=200 if url == ROOT else 404)
    result = await official_mod.OfficialSearch().retrieve(RetrievalRequest(query=query))
    assert result.status == 'success' and len(result.results) == 1
    assert setup.await_count == 1
    assert result.results[0].get('snippet') or result.results[0].get('_source_scope_sentences')
