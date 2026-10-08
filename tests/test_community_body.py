"""Community question-body provenance, bounds and selection regressions."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.budget_errors import BudgetPersistenceError
from deepchoice.citations import source_windows
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.retrievers import community
from deepchoice.retrievers.contracts import RetrievalRequest

URL = "https://stackoverflow.com/questions/123/alpha-retention"


@pytest.fixture
def provider(monkeypatch):
    response = httpx.Response(200, json={"items": []}, request=httpx.Request("GET", URL))
    get = AsyncMock(return_value=response)
    client = AsyncMock()
    client.__aenter__.return_value = client
    monkeypatch.setattr(community._outbound, "make_client", AsyncMock(return_value=client))
    monkeypatch.setattr(community.throttle, "get", get)
    monkeypatch.setattr(community._outbound, "get_resolver", lambda: SimpleNamespace(invalidate=AsyncMock()))
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    return get


def _response(body):
    return httpx.Response(200, json={"items": [{"link": URL, "title": "Alpha retention question",
        "body": body, "score": 19, "tags": ["python"]}]}, request=httpx.Request("GET", URL))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("prose", [
    "Alpha retains jobs only with its journal enabled. Without the journal jobs can be lost.",
    "Alpha仅在启用日志时保留任务。关闭日志后不能保证任务在重启后保留。",
])
async def test_complete_question_body_replaces_metadata(provider, prose, legacy):
    provider.return_value = _response(f"<p>{prose}</p>")
    retriever = community.CommunitySearch()
    result = (await retriever.search("Alpha retention", []) if legacy else
              (await retriever.retrieve(RetrievalRequest(query="Alpha retention"))).model_dump())
    assert result["status"] == "success"
    assert result["results"][0]["snippet"] == prose
    assert result["results"][0]["url"] == URL
    assert provider.await_args.kwargs["params"]["filter"] == "withbody"
    assert provider.await_count == 1
    assert "Score:" not in str(result) and "Tags:" not in str(result)


@pytest.mark.asyncio
async def test_question_code_conditions_survive_but_hidden_navigation_does_not(provider):
    provider.return_value = _response(
        '<nav>Always durable.</nav><form>Always safe.</form><p hidden>Never lost.</p>'
        '<p aria-hidden="true">Always restored.</p><p>Alpha recovery uses this setting:</p>'
        '<pre><code>journal = disabled</code></pre><p>In this configuration recovery is not guaranteed.</p>')
    result = await community.CommunitySearch().retrieve(RetrievalRequest(query="Alpha recovery"))
    assert result.status == "success"
    assert result.results[0]["snippet"] == (
        "Alpha recovery uses this setting: journal = disabled In this configuration recovery is not guaranteed.")
    assert "Always" not in str(result.results) and "Never lost" not in str(result.results)


def test_preserved_pre_does_not_inherit_blockquote_prose_eligibility():
    from deepchoice.retrievers.official_pages import _proposal_scope

    body = "<blockquote><pre>Alpha requires journaling.</pre></blockquote>"
    document = source_windows.extract_source_document(
        body, truncated=False, skip_navigation=True, preserve_pre=True)
    assert document.blocks == ("Alpha requires journaling.",)
    assert not document.incomplete and document.prose_indices == ()
    assert _proposal_scope(document, {"alpha"}) is None
    assert not source_windows.extract_source_document(body, truncated=False, skip_navigation=True).blocks
    assert source_windows.extract_source_document(body, truncated=False).blocks == document.blocks


@pytest.mark.asyncio
@pytest.mark.parametrize("paragraph_count", [28, 100])
async def test_long_question_offers_complete_conditions_then_requires_selection(provider, monkeypatch, paragraph_count):
    main = "Alpha retains queued jobs only when its persistent journal is enabled."
    limit = "If that journal is disabled, Alpha cannot guarantee recovery of queued jobs after restart."
    background = [f"Background section {index} describes another unrelated topic." for index in range(paragraph_count)]
    provider.return_value = _response("".join(f"<p>{row}</p>" for row in [*background, main, limit]))
    result = await community.CommunitySearch().retrieve(RetrievalRequest(query="Alpha journal recovery"))
    assert result.status == "success"
    item = result.results[0]
    assert item["snippet"] == ""
    scope = item["_source_scope_sentences"]
    assert main in scope and limit in scope
    assert len(" ".join(scope)) <= 2000
    start = scope.index(main)
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[start, start + 2]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    state = {"task": {"query": "Alpha journal recovery", "candidate_techs": ["Alpha"]},
             "search_results": [result.model_dump()]}
    assert not (await SourceEvaluatorAgent().run(state))["source_scores"]
    selector.assert_not_awaited()
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    selected = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert selected["source_scores"][0]["snippet"] == f"{main} {limit}"
    assert selected["source_scores"][0]["passages"] == [f"{main} {limit}"]
    assert "_source_scope_sentences" not in selected["source_scores"][0]
    assert item["snippet"] == ""
    selector.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, 42, "", "  ", "<p>Alpha retains jobs only if",
    "<p>" + "x" * (64 * 1024) + "</p>", "<p>" + "x" * 2100 + ".</p>"],
    ids=["null", "number", "empty", "blank", "unfinished", "document_limit", "no_bounded_scope"])
async def test_unusable_body_is_visible_failure_not_metadata_success(provider, body):
    provider.return_value = _response(body)
    result = await community.CommunitySearch().retrieve(RetrievalRequest(query="Alpha"))
    assert result.status == "failed" and result.results == []
    assert result.error == "ValueError"
    assert "retains jobs" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"items": {}}, {"items": [42]},
    {"items": [{"link": URL, "title": "Alpha", "score": 9}]},
    {"error_id": 400, "error_message": "private provider detail"}])
async def test_invalid_question_envelope_fails_without_payload_disclosure(provider, payload):
    provider.return_value = httpx.Response(200, json=payload, request=httpx.Request("GET", URL))
    result = await community.CommunitySearch().retrieve(RetrievalRequest(query="Alpha"))
    assert result.status == "failed" and result.results == [] and result.error
    assert "private provider detail" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("private parser detail"), BudgetPersistenceError("budget"), asyncio.CancelledError()])
async def test_body_parser_failure_and_authority_boundaries(provider, monkeypatch, error):
    provider.return_value = _response("<p>Alpha retains jobs only with journaling.</p>")
    def fail(_self, _body):
        raise error
    monkeypatch.setattr(source_windows._Blocks, "feed", fail)
    operation = community.CommunitySearch().retrieve(RetrievalRequest(query="Alpha"))
    if isinstance(error, ValueError):
        result = await operation
        assert result.status == "failed" and result.error == "ValueError"
        assert "private parser detail" not in result.model_dump_json()
    else:
        with pytest.raises(type(error)) as caught:
            await operation
        assert caught.value is error


@pytest.mark.asyncio
async def test_short_question_keeps_all_conditions_through_default_scoring(provider, monkeypatch):
    paragraphs = ["Alpha stores jobs.", "Setup requires configuration.", "Only when journaling is enabled."]
    provider.return_value = _response("".join(f"<p>{row}</p>" for row in paragraphs))
    result = await community.CommunitySearch().retrieve(RetrievalRequest(query="Alpha retention"))
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[0, 1]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    selected = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run({
        "task": {"query": "Alpha retention", "candidate_techs": ["Alpha"]},
        "search_results": [result.model_dump()]})
    assert selected["source_scores"][0]["snippet"] == " ".join(paragraphs)
    assert "_source_scope_sentences" not in result.results[0]
    selector.assert_not_awaited()

    from deepchoice.citations import verify_citations
    from deepchoice.utils.evidence_choices import bind_evidence_choices

    chains = [{"sources": selected["source_scores"]}]
    bound = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]},
                                 chains, ["Alpha"], [])
    assert bound["source_facts"][0]["saved_text"] == " ".join(paragraphs)
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    fetch = AsyncMock(return_value=httpx.Response(200,
        text="".join(f"<p>{row}</p>" for row in paragraphs),
        headers={"content-type": "text/html"}, request=httpx.Request("GET", URL)))
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    verification, _ = await verify_citations(bound, chains)
    checks = [row for row in verification.checks if "source_facts" in row.claim_path]
    assert checks and all(row.status.value == "verified" for row in checks)
    fetch.assert_awaited_once()
