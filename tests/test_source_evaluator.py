import asyncio
from datetime import datetime, timedelta
import json
from unittest.mock import AsyncMock

import pytest

from deepchoice.budget_errors import BudgetPersistenceError
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.utils.source_scope import scope_sentences

from deepchoice.agents.source_evaluator import (
    SourceEvaluatorAgent,
    classify_source_type,
    compute_total_score,
    score_authority,
    score_timeliness,
)


class TestScoreAuthority:
    def test_official_docs_get_10(self):
        assert score_authority("official_doc") == 10

    def test_paper_gets_10(self):
        assert score_authority("arxiv_paper") == 10

    def test_well_known_blog_gets_7(self):
        assert score_authority("tech_blog") == 7

    def test_github_gets_6(self):
        assert score_authority("github") == 6

    def test_stackoverflow_gets_5(self):
        assert score_authority("stackoverflow") == 5

    def test_reddit_gets_4(self):
        assert score_authority("reddit") == 4

    def test_anonymous_gets_2(self):
        assert score_authority("anonymous") == 2

    def test_unknown_gets_4_default(self):
        assert score_authority("something_unknown") == 4


class TestScoreTimeliness:
    def test_less_than_3_months(self):
        recent = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        assert score_timeliness(recent) == 10

    def test_3_to_6_months(self):
        mid = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
        assert score_timeliness(mid) == 8

    def test_6_to_12_months(self):
        older = (datetime.now() - timedelta(days=270)).strftime("%Y-%m-%d")
        assert score_timeliness(older) == 6

    def test_1_to_2_years(self):
        old = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
        assert score_timeliness(old) == 4

    def test_over_2_years(self):
        ancient = (datetime.now() - timedelta(days=800)).strftime("%Y-%m-%d")
        assert score_timeliness(ancient) == 2

    def test_missing_date_defaults_5(self):
        assert score_timeliness(None) == 5
        assert score_timeliness("") == 5


class TestComputeTotalScore:
    def test_weighted_formula(self):
        scores = {"authority": 10, "timeliness": 10, "consistency": 10, "verifiability": 10}
        total = compute_total_score(scores)
        assert total == 10.0

    def test_zero_scores(self):
        scores = {"authority": 0, "timeliness": 0, "consistency": 0, "verifiability": 0}
        total = compute_total_score(scores)
        assert total == 0.0


class TestClassifySourceType:
    def test_arxiv_url(self):
        assert classify_source_type("https://arxiv.org/abs/2401.12345", "unknown") == "arxiv_paper"

    def test_github_url(self):
        assert classify_source_type("https://github.com/langchain-ai/langgraph", "unknown") == "github"

    def test_unregistered_readthedocs_tenant_is_not_an_official_identity(self):
        assert classify_source_type("https://langchain.readthedocs.io/en/latest/", "unknown") == "tech_blog"

    def test_chroma_source(self):
        assert classify_source_type("some-internal-id", "chroma") == "tech_blog"

    @pytest.mark.parametrize("source", ["chroma", "official"])
    def test_local_templates_cannot_inherit_official_authority(self, source):
        source_type = classify_source_type("file:///knowledge/docs.sqlite.org/template.md", source)
        assert source_type == "tech_blog"
        assert score_authority(source_type) == 7

    def test_chroma_preserves_known_http_official_document_classification(self):
        assert classify_source_type("https://docs.python.org/3/", "chroma") == "official_doc"


class TestSourceEvaluatorAgent:
    @pytest.mark.asyncio
    async def test_scores_and_ranks_results(self):
        state = {
            "search_results": [
                {
                    "source": "tavily",
                    "status": "success",
                    "results": [
                        {
                            "url": "https://docs.python.org/3/library/asyncio.html",
                            "title": "asyncio - Official Python docs",
                            "snippet": "This module provides infrastructure for writing concurrent code using the async/await syntax.",
                            "date": "2026-06-01",
                        },
                        {
                            "url": "https://www.reddit.com/r/Python/comments/xyz",
                            "title": "Python async is the worst, here's why",
                            "snippet": "in my opinion async programming in Python is overcomplicated for most projects",
                            "date": "2024-03-15",
                        },
                    ],
                    "error": None,
                    "latency_ms": 800,
                }
            ]
        }

        agent = SourceEvaluatorAgent()
        result = await agent.run(state)

        scores = result["source_scores"]
        assert len(scores) == 2
        assert scores[0]["rank"] == 1
        assert scores[1]["rank"] == 2
        assert scores[0]["total_score"] > scores[1]["total_score"]
        assert all("authority" in s["scores"] for s in scores)
        assert all("timeliness" in s["scores"] for s in scores)

    @pytest.mark.asyncio
    async def test_empty_results(self):
        agent = SourceEvaluatorAgent()
        result = await agent.run({"search_results": []})
        assert result["source_scores"] == []


_SCOPE_FIRST = "Alpha persists jobs only when the journal is enabled."
_SCOPE_MIDDLE = "An unrelated deployment note describes startup logs."
_SCOPE_LAST = "After a worker crash, a child-exit exception still acknowledges the job."
_SCOPE_DOCUMENT = " ".join((_SCOPE_FIRST, _SCOPE_MIDDLE, _SCOPE_LAST))


def _scoped_source_state():
    return {
        "task": {
            "query": "Choose Alpha or Beta for jobs that must recover after restart?",
            "candidate_techs": ["Alpha", "Beta"],
            "constraints": ["Do not promise recovery without conditions"],
            "sub_questions": ["What happens after a worker exits?"],
        },
        "search_results": [{
            "source": "chroma", "status": "success", "results": [{
                "url": "https://example.org/alpha",
                "title": "Alpha guide",
                "snippet": _SCOPE_FIRST,
                "_source_scope_sentences": list(scope_sentences(_SCOPE_DOCUMENT)),
            }],
        }],
    }


@pytest.mark.asyncio
async def test_durable_scope_proposal_uses_original_question_and_exact_ranges(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    calls = []

    async def select(prompt, **kwargs):
        calls.append((prompt, kwargs))
        kwargs["usage"].append({"model": "deepseek-flash", "prompt_tokens": 9,
                                "completion_tokens": 5, "total_tokens": 14})
        return {"sources": [{"id": "S1", "ranges": [[0, 1], [2, 3]]}]}

    monkeypatch.setattr("deepchoice.utils.llm.call_model", select)
    output = await SourceEvaluatorAgent(
        run_manifest=build_run_manifest({}),
    ).run(_scoped_source_state())
    assert len(calls) == 1
    assert "jobs that must recover after restart" in calls[0][0][0]["content"]
    assert calls[0][1]["tag"] == "source_scope_selector"
    assert output["source_scores"][0]["passages"] == [_SCOPE_FIRST, _SCOPE_LAST]
    assert output["source_scores"][0]["snippet"] == _SCOPE_FIRST + "\n\n" + _SCOPE_LAST
    assert output["quality_signals"][0]["source_scope_proposal"] == {
        "offered": 1, "accepted": 1, "status": "completed",
    }
    assert output["token_usage"][-1]["total_tokens"] == 14
    assert "_source_scope_sentences" not in output["source_scores"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_result", [
    {"sources": [{"id": "S1", "ranges": [[2, 3], [0, 1]]}]},
    {"sources": [{"id": "S1", "ranges": [[0, 1], [1, 99]]}]},
    {"sources": [{"id": "S1", "ranges": [[True, 1]]}]},
    {"sources": [{"id": "S1", "ranges": [[0, 1], [0, 1]]}]},
    {"sources": [{"id": [], "ranges": [[0, 1]]}]},
    {"sources": [{"id": {}, "ranges": [[0, 1]]}]},
])
async def test_invalid_scope_proposal_preserves_original_snippet(monkeypatch, model_result):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    monkeypatch.setattr(
        "deepchoice.utils.llm.call_model",
        AsyncMock(return_value=model_result),
    )
    output = await SourceEvaluatorAgent(
        run_manifest=build_run_manifest({}),
    ).run(_scoped_source_state())
    assert output["source_scores"][0]["snippet"] == _SCOPE_FIRST
    assert "passages" not in output["source_scores"][0]
    assert output["quality_signals"][0]["source_scope_proposal"]["accepted"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["budget", "cancel"])
async def test_scope_selection_budget_failure_propagates_and_legacy_skips(monkeypatch, failure):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    error = BudgetPersistenceError("budget store unavailable") if failure == "budget" else asyncio.CancelledError()
    selector = AsyncMock(side_effect=error)
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    state = {**_scoped_source_state(), "_supplemental_input": "Supplementary user condition"}
    with pytest.raises(type(error)):
        await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    output = await SourceEvaluatorAgent().run(state)
    assert output["source_scores"][0]["snippet"] == _SCOPE_FIRST
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    direct = await SourceEvaluatorAgent(
        run_manifest=build_run_manifest({}),
    ).run(state)
    assert direct["source_scores"][0]["snippet"] == _SCOPE_FIRST
    assert selector.await_count == 1


@pytest.mark.asyncio
async def test_scope_prompt_retains_scene_and_versioned_source_paths(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    seen = []

    async def select(messages, **_kwargs):
        seen.append(json.loads(messages[0]["content"].split("\n")[-1]))
        return {"sources": []}

    monkeypatch.setattr("deepchoice.utils.llm.call_model", select)
    state = _scoped_source_state()
    state["task"]["query"] = "Choose Alpha or Beta"
    state["task"]["scene_context"] = "Must preserve jobs after restart on version 2."
    state["search_results"] = [{
        "source": "official", "status": "success",
        "results": [
            {
                "url": f"https://docs.example.org/v{version}/jobs?token=private",
                "title": "Alpha manual",
                "snippet": _SCOPE_FIRST,
                "_source_scope_sentences": list(scope_sentences(_SCOPE_DOCUMENT)),
            }
            for version in (1, 2)
        ],
    }]
    await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert len(seen) == 1
    assert seen[0]["request"]["scene_context"] == state["task"]["scene_context"]
    assert [row["source_url"] for row in seen[0]["sources"]] == [
        "https://docs.example.org/v1/jobs",
        "https://docs.example.org/v2/jobs",
    ]
    assert "private" not in json.dumps(seen[0])


@pytest.mark.asyncio
async def test_scope_prompt_balances_late_official_source_and_utf8_bytes(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    seen = []

    async def select(messages, **_kwargs):
        seen.append(messages[0]["content"])
        return {"sources": []}

    monkeypatch.setattr("deepchoice.utils.llm.call_model", select)
    long_text = "Alpha 中文约束" + "条件" * 60 + "。"
    sentences = scope_sentences(" ".join([long_text] * 12))
    assert sentences is not None
    state = _scoped_source_state()
    state["search_results"] = [
        {"source": "chroma", "status": "success", "results": [
            {
                "url": f"https://docs.example.org/alpha/{index}",
                "title": "Alpha guide",
                "snippet": long_text,
                "_source_scope_sentences": list(sentences),
            }
            for index in range(10)
        ]},
        {"source": "official", "status": "success", "results": [{
            "url": "https://docs.example.org/beta/current",
            "title": "Beta guide",
            "snippet": "Beta requires a durable broker.",
            "_source_scope_sentences": ["Beta requires a durable broker."],
        }]},
    ]
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert len(seen) == 1
    assert len(seen[0].encode("utf-8")) <= 12000
    payload = json.loads(seen[0].split("\n")[-1])
    assert payload["sources"][0]["source_url"].endswith("/beta/current")
    assert output["quality_signals"][0]["source_scope_proposal"]["offered"] < 8


@pytest.mark.asyncio
async def test_scope_prompt_reserves_late_distinct_candidate(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    seen = []

    async def select(messages, **_kwargs):
        seen.append(json.loads(messages[0]["content"].split("\n")[-1]))
        return {"sources": []}

    monkeypatch.setattr("deepchoice.utils.llm.call_model", select)
    alpha = {
        "title": "Alpha guide", "snippet": "Alpha stores jobs.",
        "_source_scope_sentences": ["Alpha stores jobs."],
    }
    beta = {
        "title": "Beta guide", "snippet": "Beta requires a broker.",
        "_source_scope_sentences": ["Beta requires a broker."],
    }
    state = _scoped_source_state()
    state["search_results"] = [{
        "source": "chroma", "status": "success",
        "results": [
            {**alpha, "url": f"https://docs.example.org/alpha/{index}"}
            for index in range(10)
        ] + [{**beta, "url": "https://docs.example.org/beta"}],
    }]
    await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert len(seen) == 1
    urls = [row["source_url"] for row in seen[0]["sources"]]
    assert "https://docs.example.org/beta" in urls
    assert len(urls) == 8


# Broad community/paper channels keep their lexical gate. Documentation bodies
# are request-specific proposals even when the full candidate label is absent.
def _scope_only_state(source="official"):
    state = _scoped_source_state()
    channel = state["search_results"][0]
    channel["source"] = source
    channel["results"][0].update(title="Job journal", snippet=_SCOPE_MIDDLE)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("proposal, admitted", [
    ({"sources": [{"id": "S1", "ranges": [[0, 3]]}]}, True),
    ({"sources": []}, False),
    ({"sources": [{"id": "S1", "ranges": [[1, 3]]}]}, False),
    ({"sources": [{"id": "S1", "ranges": [[0, 99]]}]}, False),
    (RuntimeError("provider unavailable"), False),
])
@pytest.mark.parametrize("source", ["official", "community", "arxiv"])
async def test_scope_only_candidate_requires_delivered_literal_name(monkeypatch, source, proposal, admitted):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    selector = AsyncMock(side_effect=proposal) if isinstance(proposal, Exception) else AsyncMock(return_value=proposal)
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(_scope_only_state(source))
    selector.assert_awaited_once()
    admitted = admitted or source == "official"
    assert len(output["source_scores"]) == int(admitted)
    assert output["quality_signals"][0]["candidate_excluded_count"] == int(not admitted)
    if admitted and proposal == {"sources": [{"id": "S1", "ranges": [[0, 3]]}]}:
        item = output["source_scores"][0]
        assert item["snippet"] == _SCOPE_DOCUMENT
        assert item["passages"] == [_SCOPE_DOCUMENT]
        assert "_source_scope_sentences" not in item
        assert "_source_passages" not in item


@pytest.mark.asyncio
@pytest.mark.parametrize("source,variant", [
    ("official", v) for v in ("chroma", "github", "public_passages", "private_passages", "navigation", "wrong_seed", "wrong_pair")
] + [(src, v) for src in ("community", "arxiv") for v in ("nameless", "oversized", "public_passages", "private_passages")])
async def test_scope_only_candidate_does_not_bypass_producer_or_scope_boundaries(monkeypatch, source, variant):
    from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY

    state = _scope_only_state(source)
    channel = state["search_results"][0]
    item = channel["results"][0]
    if variant in ("chroma", "tavily", "github"):
        channel["source"] = variant
    elif variant == "nameless":
        item["_source_scope_sentences"] = [_SCOPE_MIDDLE]
        item["_seed_target_id"] = "Alpha"
    elif variant == "wrong_product":
        item["_source_scope_sentences"] = ["Gamma persists jobs only when its journal is enabled."]
    elif variant == "oversized":
        item["_source_scope_sentences"] = ["Alpha " + "x" * 401 + "."]
    elif variant in ("public_passages", "private_passages"):
        item["passages" if variant == "public_passages" else "_source_passages"] = [_SCOPE_FIRST]
    elif variant == "navigation":
        item["snippet"] = "Official documentation site for Alpha."
    elif variant == "wrong_seed":
        channel["source"] = "chroma"
        item.update(_seed_source_type="official", _seed_seed_identity_sha256=AUDITED_PRODUCT_SEED_IDENTITY,
                    _seed_target_id="p08-redis-persistence", _seed_verified_chunk=True)
    else:
        channel["source"] = "chroma"
        item.update(url="file:///knowledge/Alpha-vs-Gamma.md", title="Alpha vs Gamma")
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    selector = AsyncMock()
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert output["source_scores"] == []
    selector.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", ["no_manifest", "no_context"])
@pytest.mark.parametrize("source", ["official", "community", "arxiv"])
async def test_scope_only_candidate_preserves_legacy_exclusion(monkeypatch, source, legacy):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None if legacy == "no_context" else object())
    selector = AsyncMock()
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    manifest = None if legacy == "no_manifest" else build_run_manifest({})
    output = await SourceEvaluatorAgent(run_manifest=manifest).run(_scope_only_state(source))
    assert len(output["source_scores"]) == int(source == "official")
    assert output["quality_signals"][0]["candidate_excluded_count"] == int(source != "official")
    selector.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["budget", "lease", "cancel"])
@pytest.mark.parametrize("source", ["official", "community", "arxiv"])
async def test_scope_only_candidate_keeps_authority_failures_visible(monkeypatch, source, failure):
    class LostLease(RuntimeError):
        code = "RUN_LEASE_LOST"

    exc = {"budget": BudgetPersistenceError("store unavailable"), "lease": LostLease("lost"),
           "cancel": asyncio.CancelledError()}[failure]
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    selector = AsyncMock(side_effect=exc)
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    with pytest.raises(type(exc)):
        await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(_scope_only_state(source))
    selector.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["official", "community", "arxiv"])
async def test_unoffered_scope_only_candidate_cannot_gain_admission(monkeypatch, source):
    state = _scope_only_state(source)
    item = state["search_results"][0]["results"][0]
    state["search_results"][0]["results"] = [{**item, "url": f"https://example.org/journal/{index}"} for index in range(9)]
    seen = []

    async def select(messages, **_kwargs):
        payload = json.loads(messages[0]["content"].split("\n")[-1])
        seen.append(payload)
        return {"sources": [{"id": row["id"], "ranges": [[0, 3]]} for row in payload["sources"]]}

    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    monkeypatch.setattr("deepchoice.utils.llm.call_model", select)
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    assert len(seen) == 1 and len(seen[0]["sources"]) == 8
    assert len(output["source_scores"]) == (9 if source == "official" else 8)
    assert output["quality_signals"][0]["candidate_excluded_count"] == int(source != "official")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["official", "community", "arxiv", "chroma", "audited_seed"])
async def test_previously_admitted_source_keeps_selected_nameless_conditions(monkeypatch, source):
    state = _scope_only_state()
    state["search_results"][0]["source"] = source
    state["search_results"][0]["results"][0]["snippet"] = _SCOPE_FIRST
    if source == "audited_seed":
        from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY

        state["task"]["candidate_techs"] = ["Redis"]
        state["search_results"][0]["source"] = "chroma"
        first = _SCOPE_FIRST.replace("Alpha", "Redis")
        state["search_results"][0]["results"][0].update(
            snippet=first, _source_scope_sentences=[first, _SCOPE_MIDDLE, _SCOPE_LAST],
            _seed_source_type="official", _seed_seed_identity_sha256=AUDITED_PRODUCT_SEED_IDENTITY,
            _seed_target_id="p08-redis-persistence", _seed_verified_chunk=True,
        )
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    selector = AsyncMock(return_value={"sources": [{"id": "S1", "ranges": [[1, 3]]}]})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", selector)
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    selector.assert_awaited_once()
    assert len(output["source_scores"]) == 1
    assert output["source_scores"][0]["snippet"] == _SCOPE_MIDDLE + " " + _SCOPE_LAST
    assert output["source_scores"][0]["passages"] == [_SCOPE_MIDDLE + " " + _SCOPE_LAST]
    assert output["quality_signals"][0]["source_scope_proposal"]["accepted"] == 1
    assert output["quality_signals"][0]["candidate_excluded_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["official", "community", "arxiv"])
@pytest.mark.parametrize("failure", ["no_manifest", "no_context", "omitted", "invalid", "provider", "unoffered", "private", "public"])
async def test_blank_proposals_never_score_without_runtime_selection(monkeypatch, failure, source):
    from deepchoice.runtime import context
    from deepchoice.agents import source_evaluator as evaluator
    monkeypatch.setattr(context, "get_run_context", lambda: None if failure == "no_context" else object())
    text = "Acme supports filtering under the documented query conditions. Applications must enforce access separately."
    row = {"url": "https://docs.acme.example/guide/", "title": "Acme docs", "snippet": "  ",
           "_source_scope_sentences": list(scope_sentences(text))}
    if failure in {"private", "public"}:
        row['_source_passages' if failure == 'private' else 'passages'] = [text]
    if failure == 'unoffered':
        monkeypatch.setattr(evaluator, 'MAX_PROPOSAL_MESSAGE_BYTES', 1)
    provider = AsyncMock(return_value={"sources": [] if failure == "omitted" else [{"id": "S1", "ranges": [[0, 99]]}]})
    if failure == 'provider':
        provider.side_effect = RuntimeError('private provider detail')
    monkeypatch.setattr('deepchoice.utils.llm.call_model', provider)
    manifest = None if failure == 'no_manifest' else build_run_manifest({})
    scored = await SourceEvaluatorAgent(run_manifest=manifest).run({
        "task": {"query": "Acme过滤能力", "candidate_techs": ["Acme"]},
        "_supplemental_input": "Supplementary user condition",
        "search_results": [{"source": source, "results": [row]}],
    })
    assert scored['source_scores'] == []
    assert 'private provider detail' not in json.dumps(scored)
    if failure in {'no_manifest', 'no_context', 'unoffered', 'private', 'public'}:
        provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("supplement", [
    "The journal must remain disabled.",
    "补" * 4000,
    ('"\\\n😀' * 1000),
    "😀" * 4000,
], ids=["short", "cjk-4000", "json-escaping-4000", "emoji-4000"])
async def test_scope_supplement_keeps_source_menu_and_stays_untrusted(monkeypatch, supplement):
    from copy import deepcopy
    from deepchoice.agents.source_evaluator import SOURCE_SCOPE_SELECTION_PROMPT
    from deepchoice.utils.source_scope import MAX_PROPOSAL_MESSAGE_BYTES

    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    seen = []

    async def select(messages, **_kwargs):
        content = messages[0]["content"]
        payload = json.loads(content.split("\n")[-1])
        seen.append((content, payload))
        # Stub selection proves delivery/binding, not actual model understanding.
        start = 1 if payload.get("supplemental_context_untrusted") else 0
        return {"sources": [{"id": row["id"], "ranges": [[start, start + 1]]}
                            for row in payload["sources"]]}

    monkeypatch.setattr("deepchoice.utils.llm.call_model", select)
    state = _scoped_source_state()
    # Fill the original source menu beyond its byte limit without changing per-source bounds.
    text = " ".join([f"Alpha condition {i} " + "x" * 275 + "." for i in range(6)])
    sentences = list(scope_sentences(text))
    state["search_results"][0]["results"] = [
        {"url": f"https://example.org/alpha/{i}", "title": "Alpha guide",
         "snippet": sentences[0], "_source_scope_sentences": sentences}
        for i in range(8)
    ]
    agent = SourceEvaluatorAgent(run_manifest=build_run_manifest({}))
    plain = await agent.run(state)
    state["_supplemental_input"] = supplement
    before = deepcopy(state)
    supplemented = await agent.run(state)
    assert state == before
    assert len(seen) == 2
    plain_content, plain_payload = seen[0]
    content, payload = seen[1]
    assert 0 < len(payload["sources"]) < 8
    assert payload["sources"] == plain_payload["sources"]
    assert payload["request"] == plain_payload["request"]
    assert payload.pop("supplemental_context_untrusted") == supplement
    assert "supplemental_context_untrusted" not in plain_payload
    assert len(plain_content.encode("utf-8")) <= MAX_PROPOSAL_MESSAGE_BYTES
    assert SOURCE_SCOPE_SELECTION_PROMPT + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")) == plain_content
    assert len(content.encode("utf-8")) > len(plain_content.encode("utf-8"))
    assert plain["source_scores"][0]["passages"] == [sentences[0]]
    assert supplemented["source_scores"][0]["passages"] == [sentences[1]]
    assert supplement not in json.dumps(supplemented, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("supplement", ["", " \n\t", 1, {}, "x" * 4001, "private\u202e", "private\x00", "\ud800"],
                         ids=["empty", "blank", "int", "dict", "oversize", "bidi", "control", "surrogate"])
async def test_invalid_private_scope_supplement_skips_safely(monkeypatch, supplement):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    model = AsyncMock(return_value={"sources": []})
    monkeypatch.setattr("deepchoice.utils.llm.call_model", model)
    state = _scoped_source_state()
    state["_supplemental_input"] = supplement
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    model.assert_not_awaited()
    assert output["source_scores"][0]["snippet"] == _SCOPE_FIRST
    assert "passages" not in output["source_scores"][0]
    assert output["quality_signals"][0]["source_scope_proposal"] == {
        "offered": 0, "accepted": 0, "status": "invalid_context"}
    assert "private" not in json.dumps(output)


@pytest.mark.asyncio
async def test_supplement_does_not_expand_original_request_allocation(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: object())
    model = AsyncMock()
    monkeypatch.setattr("deepchoice.utils.llm.call_model", model)
    state = _scoped_source_state()
    state["task"]["sub_questions"] = [f"{i:02}" + "问" * 498 for i in range(20)]
    state["_supplemental_input"] = "补" * 4000
    output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
    model.assert_not_awaited()
    assert output["source_scores"][0]["snippet"] == _SCOPE_FIRST
    assert output["quality_signals"][0]["source_scope_proposal"] == {
        "offered": 0, "accepted": 0, "status": "input_too_large"}


@pytest.mark.asyncio
@pytest.mark.parametrize("token_limit", [60000, 10000])
async def test_scope_budget_reserves_complete_supplement_before_dispatch(tmp_path, monkeypatch, token_limit):
    from types import SimpleNamespace
    from deepchoice.budget import BudgetHardLimits, BudgetExceededError, BudgetResource
    from deepchoice.runtime.context import bind_run_context
    from deepchoice.utils import llm
    from tests.test_phase2c_budget_runtime import _running_budget, _context, _count

    connection, _, manager, _, _ = await _running_budget(
        tmp_path, limits=BudgetHardLimits(total_tokens=token_limit))
    state = _scoped_source_state()
    state["_supplemental_input"] = "补" * 4000

    async def create(**kwargs):
        messages = kwargs["messages"]
        payload = json.loads(messages[0]["content"].split("\n")[-1])
        assert payload["supplemental_context_untrusted"] == state["_supplemental_input"]
        assert kwargs["max_tokens"] == 1024
        actual_bytes = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        usage = await manager._usage()
        assert usage[BudgetResource.TOTAL_TOKENS] == actual_bytes + 1024
        assert usage[BudgetResource.LLM_CALLS] == 1
        return SimpleNamespace(model="fixture", usage=SimpleNamespace(
            prompt_tokens=100, completion_tokens=10, total_tokens=110),
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
                {"sources": [{"id": "S1", "ranges": [[0, 1]]}]})))])

    dispatch = AsyncMock(side_effect=create)
    monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=dispatch))))
    try:
        with bind_run_context(_context(manager)):
            if token_limit == 10000:
                with pytest.raises(BudgetExceededError) as caught:
                    await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
                assert caught.value.resource == BudgetResource.TOTAL_TOKENS
                assert caught.value.requested > 12000
                dispatch.assert_not_awaited()
                assert await _count(connection) == 0
            else:
                output = await SourceEvaluatorAgent(run_manifest=build_run_manifest({})).run(state)
                dispatch.assert_awaited_once()
                assert output["source_scores"][0]["passages"] == [_SCOPE_FIRST]
                assert (await manager._usage())[BudgetResource.TOTAL_TOKENS] == 110
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_web_search_proposal_survives_missing_exact_candidate_label():
    from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
    source = {'title': 'Isolation reference', 'url': 'https://docs.example/isolation',
              'snippet': 'Hosted workers run each job in an isolated workspace. Operators manage the private workers.'}
    output = await SourceEvaluatorAgent().run({'task': {'query': 'Compare isolated execution options.',
        'candidate_techs': ['Managed Acme job workers', 'Private Beta agents']},
        'search_results': [{'source': 'tavily', 'status': 'success', 'results': [source]}]})
    assert len(output['source_scores']) == 1
    assert output['source_scores'][0]['snippet'] == source['snippet']
    assert output['source_scores'][0]['evidence_type'] == 'unassessed'
    assert output['quality_signals'][0]['candidate_excluded_count'] == 0


@pytest.mark.asyncio
async def test_documentation_body_with_shorter_product_name_remains_a_proposal():
    from copy import deepcopy
    from deepchoice.agents.evidence_chain import build_evidence_chain
    from deepchoice.utils.fact_selection import selection_view_packet
    source = {"title": "Overview - Example Engine", "url": "https://docs.example.org/overview",
              "snippet": "The engine can run locally on one machine. Distributed execution needs separate configuration."}
    state = {"task": {"query": "Compare local deployment", "candidate_techs": ["Acme Example Engine", "Other Tool"]},
             "search_results": [{"source": "official", "status": "success", "results": [source]}]}
    before = deepcopy(state)
    result = await SourceEvaluatorAgent().run(state)
    assert state == before
    assert result["source_scores"][0]["snippet"] == source["snippet"]
    assert result["source_scores"][0]["source_type"] == "tech_blog"
    assert result["source_scores"][0]["evidence_type"] == "unassessed"
    menu, offered = selection_view_packet(build_evidence_chain(result["source_scores"], []), state["task"]["candidate_techs"])
    assert "run locally on one machine" in menu and offered
    assert "verified" not in result["source_scores"][0]
