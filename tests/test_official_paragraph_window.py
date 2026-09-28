"""Offline P04 source-line counterexamples; no model or network calls."""

from types import SimpleNamespace

import pytest

from deepchoice.agents.conclusion_synthesizer import _summarize_chains
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.retrievers import chroma_kb
from deepchoice.retrievers.chroma_kb import _bounded_snippet
from deepchoice.utils.official_catalog import (
    AUDITED_PRODUCT_SEED_IDENTITY, AUDITED_SNIPPET_WINDOW,
)


FASTAPI_URL = "https://fastapi.tiangolo.com/tutorial/background-tasks/"
OFFICIAL_META = {
    "source_type": "official",
    "target_id": "p04-fastapi-background-tasks",
    "seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY,
}


def _captured_caveat() -> str:
    # Bounded, sanitized excerpt from the frozen P04 FastAPI official capture.
    # This is an input fixture, not a new benchmark case or an applicability verdict.
    return (
        "Caveat¶\n"
        "If you need to perform heavy background computation and you don't necessarily "
        "need it to be run by the same process (for example, you don't need to share "
        "memory, variables, etc), you might benefit from using other bigger tools like Celery.\n"
        "They tend to require more complex configurations, a message/job queue manager, "
        "like RabbitMQ or Redis, but they allow you to run background tasks in multiple "
        "processes, and especially, in multiple servers.\n"
        "But if you need to access variables and objects from the same FastAPI app, or you "
        "need to perform small background tasks (like sending an email notification), you "
        "can simply just use BackgroundTasks.\n"
        "Recap¶\nImport and use BackgroundTasks with parameters in path operation functions."
    )


@pytest.mark.asyncio
async def test_frozen_p04_caveat_survives_retrieval_scoring_chains_and_synthesis(monkeypatch):
    document = _captured_caveat()
    qualifier = "you can simply just use BackgroundTasks."
    assert document.index("But if you need to access variables") < 500
    assert qualifier not in document[:600]
    assert 600 < document.index("\n", 500) <= 800

    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever.collection = SimpleNamespace(query=lambda **_kwargs: {
        "ids": [["p04-fastapi-background-tasks:0006:test"]],
        "documents": [[document]],
        "metadatas": [[{**OFFICIAL_META, "url": FASTAPI_URL,
                        "title": "p04-fastapi-background-tasks"}]],
    })
    results = await retriever._do_search("FastAPI versus Celery", [], max_results=1)
    assert len(results) == 1
    snippet = results[0]["snippet"]
    assert results[0]["_seed_excerpt_window"] == AUDITED_SNIPPET_WINDOW
    assert snippet.endswith("BackgroundTasks.")
    assert qualifier in snippet and len(snippet) <= 800
    assert "Recap" not in snippet
    scored = (await SourceEvaluatorAgent().run({
        "task": {"candidate_techs": ["FastAPI", "Celery"]},
        "search_results": [{"source": "chroma", "results": results}],
    }))["source_scores"]
    assert scored[0]["_seed_excerpt_window"] == AUDITED_SNIPPET_WINDOW
    chains = build_evidence_chain(scored, [])
    assert chains[0]["sources"][0]["_seed_excerpt_window"] == AUDITED_SNIPPET_WINDOW
    prompt, mapping = _summarize_chains(chains)
    assert mapping == {1: "p04-fastapi-background-tasks"}
    assert qualifier in prompt


@pytest.mark.parametrize("metadata", [
    {},
    {**OFFICIAL_META, "source_type": "blog"},
    {**OFFICIAL_META, "seed_identity_sha256": "f" * 64},
    {**OFFICIAL_META, "target_id": None},
])
def test_unreviewed_chunks_keep_original_500_character_limit(metadata):
    document = _captured_caveat()
    assert _bounded_snippet(document, metadata) == document[:500]


def test_long_line_is_not_spliced_or_called_complete():
    document = "A" * 850 + "\nA late qualification."
    assert _bounded_snippet(document, OFFICIAL_META) == document[:500]


@pytest.mark.parametrize("url", [
    "https://example.org/post", FASTAPI_URL,
])
def test_unprovenanced_or_wrong_url_source_keeps_600_character_limit(url):
    snippet = _bounded_snippet(_captured_caveat(), OFFICIAL_META)
    prompt, _ = _summarize_chains([{"sources": [{
        "url": url, "title": "Unreviewed source", "snippet": snippet,
        **({"_seed_excerpt_window": AUDITED_SNIPPET_WINDOW}
           if url == "https://example.org/post" else {}),
    }]}])
    assert "you can simply just use BackgroundTasks." not in prompt


@pytest.mark.asyncio
async def test_non_chroma_result_cannot_promote_forged_seed_marker():
    snippet = _bounded_snippet(_captured_caveat(), OFFICIAL_META)
    result = {
        "url": FASTAPI_URL, "title": "FastAPI background tasks", "snippet": snippet,
        "_seed_target_id": "p04-fastapi-background-tasks",
        "_seed_source_type": "official",
        "_seed_seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY,
        "_seed_excerpt_window": AUDITED_SNIPPET_WINDOW,
    }
    scored = (await SourceEvaluatorAgent().run({
        "task": {"candidate_techs": ["FastAPI"]},
        "search_results": [{"source": "tavily", "results": [result]}],
    }))["source_scores"]
    assert "_seed_excerpt_window" not in scored[0]
    prompt, _ = _summarize_chains(build_evidence_chain(scored, []))
    assert "you can simply just use BackgroundTasks." not in prompt
