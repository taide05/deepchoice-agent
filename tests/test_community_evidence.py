"""Unit/contract tests for isolated StackExchange evidence packs.

No live network is used here; the HTTP client is a small fake. The feature is
opt-in via COMMUNITY_RETRIEVAL_MODE, so the legacy tests remain the default-path
guard.
"""
import asyncio

import pytest

from deepchoice.retrievers import community_evidence as ce


def _question(**overrides):
    base = {
        "question_id": 79187626,
        "title": "AKS Network Policy Manager vs Azure Cilium Network Policies",
        "link": "https://stackoverflow.com/questions/79187626/aks-network-policy-manager-vs-azure-cilium-network-policies",
        "body": "<p>I am trying to implement network policies in Azure AKS.</p>",
        "score": 1,
        "answer_count": 1,
        "accepted_answer_id": 79191202,
        "favorite_count": 2,
        "creation_date": 1731566342,
        "last_activity_date": 1731648903,
        "tags": ["cilium", "kubernetes-networkpolicy"],
        "owner": {"display_name": "Jatin"},
    }
    base.update(overrides)
    return base


def test_query_variants_are_short_and_english_anchored():
    variants = ce.build_query_variants(
        "我们正在 Cilium 和 Calico 之间做技术选型，重点看审计、权限控制和长期维护",
        ["审计日志粒度", "权限控制模型"],
        [],
        ["Cilium", "Calico"],
    )
    assert 1 <= len(variants) <= ce.MAX_SEARCH_VARIANTS
    assert all(len(v) <= 160 for v in variants)
    assert any("Cilium" in v for v in variants)
    assert any("Calico" in v for v in variants)
    assert all(not any("\u4e00" <= ch <= "\u9fff" for ch in v) for v in variants)


def test_query_variants_empty_without_english_anchor():
    assert ce.build_query_variants("我们该选什么", [], [], []) == []


def test_selection_keeps_relevant_niche_and_drops_unrelated():
    relevant = _question()
    unrelated = _question(question_id=1, title="Python list index out of range",
                          tags=["python"], score=500, answer_count=20,
                          accepted_answer_id=1, favorite_count=100)
    selected = ce.select_questions([unrelated, relevant],
                                   candidate_techs=["Cilium", "Calico"],
                                   dimension_terms=["audit", "permissions"])
    assert selected
    assert selected[0]["question_id"] == 79187626
    assert all("python" not in (q.get("tags") or []) for q in selected)


def test_selection_keeps_one_pack_per_candidate_when_available():
    langgraph_best = _question(
        question_id=11, title="LangGraph deployment issue", tags=["langgraph"],
        score=30, answer_count=5, accepted_answer_id=2)
    langgraph_second = _question(
        question_id=12, title="LangGraph checkpoint question", tags=["langgraph"],
        score=20, answer_count=3, accepted_answer_id=3)
    autogen = _question(
        question_id=21, title="AutoGen agent configuration", tags=["ms-autogen"],
        score=2, answer_count=1, accepted_answer_id=4)
    selected = ce.select_questions(
        [langgraph_best, langgraph_second, autogen],
        candidate_techs=["LangGraph", "AutoGen"],
        dimension_terms=[],
    )
    assert {item["question_id"] for item in selected} >= {11, 21}


def test_build_pack_has_question_answer_comment_and_attribution():
    pack = ce.build_pack(
        _question(),
        [{"body": "<p>Use Cilium for <b>kernel</b> enforcement.</p>",
          "score": 9, "is_accepted": True, "creation_date": 1731648903,
          "owner": {"display_name": "pchaigno"}}],
        [{"body": "Cilium has limitations too.", "score": 2,
          "creation_date": 1731584965, "owner": {"display_name": "Arko"}}],
    )
    text = pack["snippet"]
    assert pack["has_body"] is True
    assert "非官方" in text
    assert "问题正文" in text
    assert "回答1" in text and "pchaigno" in text
    assert "评论1" in text and "Arko" in text
    assert "kernel enforcement" in text


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.paths: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        self.paths.append(url)
        if url.endswith("/search/advanced"):
            return _FakeResponse(payload={"items": [_question()]})
        if url.endswith("/questions/79187626"):
            return _FakeResponse(payload={"items": [_question()]})
        if url.endswith("/questions/79187626/answers"):
            return _FakeResponse(payload={"items": [{
                "question_id": 79187626,
                "body": "<p>Use Cilium.</p>", "score": 5,
                "is_accepted": True, "creation_date": 1731648903,
                "owner": {"display_name": "answerer"}}]})
        if url.endswith("/questions/79187626/comments"):
            return _FakeResponse(payload={"items": [{
                "post_id": 79187626,
                "body": "Cilium limitations exist.", "score": 2,
                "creation_date": 1731584965,
                "owner": {"display_name": "commenter"}}]})
        raise AssertionError(f"unexpected path: {url}")


@pytest.mark.asyncio
async def test_fetch_evidence_packs_contract_with_fake_client():
    client = _FakeClient()

    async def factory():
        return client

    packs = await ce.fetch_evidence_packs(
        "Cilium vs Calico for network policy",
        ["audit", "permissions"],
        max_results=2,
        candidate_techs=["Cilium", "Calico"],
        client_factory=factory,
        budget=ce.RequestBudget(),
        search_cache={},
        pack_cache={},
    )
    assert len(packs) == 1
    pack = packs[0]
    assert pack["community_question_id"] == "79187626"
    assert pack["has_body"] is True
    assert pack["source_owner"] is None
    assert "Stack Overflow" in pack["title"]
    assert "answerer" in pack["snippet"] and "commenter" in pack["snippet"]
    assert len(client.paths) <= 5  # up to 2 searches + 3 batched detail requests


@pytest.mark.asyncio
async def test_community_search_uses_evidence_pack_when_enabled(monkeypatch):
    from deepchoice.retrievers.community import CommunitySearch

    called = {}

    async def fake_fetch(*args, **kwargs):
        called.update(kwargs)
        return [{"url": "https://stackoverflow.com/q/1", "title": "pack",
                 "snippet": "body", "has_body": True}]

    monkeypatch.setattr(ce, "fetch_evidence_packs", fake_fetch)
    monkeypatch.setenv("COMMUNITY_RETRIEVAL_MODE", "evidence_pack")
    results = await CommunitySearch()._do_search(
        "Cilium vs Calico", ["audit"], 2, adapted_queries=[], candidate_techs=["Cilium", "Calico"])
    assert results[0]["title"] == "pack"
    assert called["candidate_techs"] == ["Cilium", "Calico"]


@pytest.mark.asyncio
async def test_community_search_defaults_to_evidence_pack(monkeypatch):
    from deepchoice.retrievers.community import CommunitySearch

    called = {}

    async def fake_fetch(*args, **kwargs):
        called["yes"] = True
        return [{"url": "https://stackoverflow.com/q/1", "title": "default pack",
                 "snippet": "body", "has_body": True}]

    monkeypatch.delenv("COMMUNITY_RETRIEVAL_MODE", raising=False)
    monkeypatch.setattr(ce, "fetch_evidence_packs", fake_fetch)
    results = await CommunitySearch()._do_search(
        "Cilium vs Calico", ["audit"], 2, adapted_queries=[], candidate_techs=["Cilium"])
    assert results[0]["title"] == "default pack"
    assert called["yes"] is True


@pytest.mark.asyncio
async def test_request_retries_retryable_status(monkeypatch):
    calls = {"n": 0}

    class RetryClient:
        async def get(self, url, params=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(status_code=503, payload={})
            return _FakeResponse(payload={"items": [], "quota_remaining": 9000})

    async def no_backoff():
        return None

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(ce, "_wait_for_backoff", no_backoff)
    monkeypatch.setattr(ce.asyncio, "sleep", no_sleep)
    body = await ce._request_json(
        RetryClient(), "/search/advanced", {"q": "x"},
        budget=ce.RequestBudget(), key="")
    assert calls["n"] == 2
    assert body["quota_remaining"] == 9000

def test_stackoverflow_authority_reaches_evidence_chain_threshold():
    from deepchoice.agents.source_evaluator import AUTHORITY_MAP, score_authority
    assert AUTHORITY_MAP["stackoverflow"] >= 6
    assert score_authority("stackoverflow") >= 6
