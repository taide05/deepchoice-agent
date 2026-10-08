"""Complete arXiv abstract and bounded source-selection regressions."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.sax.saxutils import escape

import httpx
import pytest

from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.retrievers import arxiv_api
from deepchoice.retrievers.contracts import RetrievalRequest

URL = "https://arxiv.org/abs/2601.12345"
ATOM = "http://www.w3.org/2005/Atom"


def _feed(summary, *, title="Alpha persistence study", url=URL):
    body = "" if summary is None else f"<summary>{escape(summary)}</summary>"
    return f'<feed xmlns="{ATOM}"><entry><id>{url}</id><title>{title}</title>{body}</entry></feed>'


@pytest.fixture
def provider(monkeypatch):
    response = httpx.Response(200, text=f'<feed xmlns="{ATOM}"/>', request=httpx.Request("GET", URL))
    get = AsyncMock(return_value=response)
    client = AsyncMock()
    client.__aenter__.return_value = client
    monkeypatch.setattr(arxiv_api._outbound, "make_client", AsyncMock(return_value=client))
    monkeypatch.setattr(arxiv_api.throttle, "get", get)
    monkeypatch.setattr(arxiv_api._outbound, "get_resolver", lambda: SimpleNamespace(invalidate=AsyncMock()))
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    return get


def _respond(provider, xml):
    provider.return_value = httpx.Response(200, text=xml, request=httpx.Request("GET", URL))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("late_keyword", [False, True])
async def test_complete_abstract_keeps_tail_before_relevance_and_binding(provider, monkeypatch, legacy, late_keyword):
    background = " ".join(f"Background clause {i} describes the measurement setup." for i in range(10))
    limit = "Alpha preserves data only when its persistence option is enabled."
    prose = background + " " + limit
    title = "Experimental observations" if late_keyword else "Alpha persistence study"
    _respond(provider, _feed(prose, title=title))
    retriever = arxiv_api.ArxivSearch()
    result = (await retriever.search("Alpha persistence", []) if legacy else
              (await retriever.retrieve(RetrievalRequest(query="Alpha persistence"))).model_dump())
    assert result["status"] == "success" and len(result["results"]) == 1
    assert result["results"][0]["snippet"] == prose
    assert "_source_scope_sentences" not in result["results"][0]
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[0, 1]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    scored = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run({
        "task": {"query": "Alpha persistence", "candidate_techs": ["Alpha"]}, "search_results": [result]})
    assert scored["source_scores"][0]["snippet"] == prose
    selector.assert_not_awaited()
    from deepchoice.utils.evidence_choices import bind_evidence_choices
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]},
                                 [{"sources": scored["source_scores"]}], ["Alpha"], [])
    assert bound["source_facts"][0]["saved_text"] == prose
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_abstract_math_and_wrapped_lines_are_xml_text_not_html(provider):
    prose = "Alpha requires x < y and <beta> parameters.\n  The bound is $n^2$ & not a runtime guarantee."
    _respond(provider, _feed(prose))
    result = await arxiv_api.ArxivSearch().retrieve(RetrievalRequest(query="Alpha"))
    assert result.status == "success"
    assert result.results[0]["snippet"] == " ".join(prose.split())


@pytest.mark.asyncio
@pytest.mark.parametrize("paragraphs", [False, True])
@pytest.mark.parametrize("named_title", [False, True])
async def test_long_abstract_offers_complete_scope_then_requires_selection(provider, monkeypatch, paragraphs, named_title):
    main = "Alpha retains queued jobs only when its persistent journal option is enabled during execution."
    limit = "If that option is disabled, queued jobs cannot be guaranteed to survive a process restart."
    background = [f"Background section {i} describes an unrelated measurement setup." for i in range(60 if paragraphs else 20)]
    prose = ("\n\n" if paragraphs else "\n").join([*background, main, limit])
    _respond(provider, _feed(prose, title="Alpha study" if named_title else "Recovery observations"))
    result = await arxiv_api.ArxivSearch().retrieve(RetrievalRequest(query="Alpha journal recovery"))
    assert result.status == "success"
    item = result.results[0]
    assert item["snippet"] == ""
    scope = item["_source_scope_sentences"]
    assert main in scope and limit in scope and len(" ".join(scope)) <= 2000
    state = {"task": {"query": "Alpha journal recovery", "candidate_techs": ["Alpha"]},
             "search_results": [result.model_dump()]}
    assert not (await SourceEvaluatorAgent().run(state))["source_scores"]
    start = scope.index(main)
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[start, start + 2]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert output["source_scores"][0]["passages"] == [f"{main} {limit}"]
    assert item["snippet"] == ""
    selector.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("xml", [
    "<html><body>private provider detail</body></html>",
    "<feed/>", _feed(None), _feed("   "),
    _feed("private provider detail", title="Error", url="http://arxiv.org/api/errors#private_detail"),
    f'<feed xmlns="{ATOM}"><entry><id>{URL}</id><title>Alpha</title><summary>Alpha <b>private nested detail</b>.</summary></entry></feed>',
    _feed("Alpha persists data.", title=""), _feed("Alpha persists data.", url=""),
], ids=["non_atom", "wrong_namespace", "missing_summary", "blank_summary", "provider_error", "nested_summary", "missing_title", "missing_id"])
async def test_invalid_abstract_envelope_is_visible_failure(provider, xml):
    _respond(provider, xml)
    result = await arxiv_api.ArxivSearch().retrieve(RetrievalRequest(query="Alpha"))
    assert result.status == "failed" and result.results == [] and result.error
    assert "private" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("prose", [
    "\n".join(f"Alpha background section {i} describes an unrelated measurement setup." for i in range(60)),
    "Alpha " + "x" * 501 + ".", "Alpha " + "x" * (64 * 1024) + ".",
], ids=["soft_wrapping_is_not_paragraphs", "oversize_sentence", "document_limit"])
async def test_unadmitted_abstract_fails_without_clipped_evidence(provider, prose):
    _respond(provider, _feed(prose))
    result = await arxiv_api.ArxivSearch().retrieve(RetrievalRequest(query="Alpha"))
    assert result.status == "failed" and result.results == [] and result.error == "ValueError"


@pytest.mark.asyncio
async def test_valid_empty_atom_feed_is_success(provider):
    result = await arxiv_api.ArxivSearch().retrieve(RetrievalRequest(query="Alpha"))
    assert result.status == "success" and result.results == [] and result.error is None
