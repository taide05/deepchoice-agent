"""Phase-A retrieval diversity: an independent-source query per candidate pair.

Limitation 2 (source concentration / single-source): ordinary retrieval favours each
candidate's own docs, so the decisive comparison may rest on vendor material. One
extra Tavily search restricted to independent community domains gives the pair a
chance at a non-owner comparison. Tests fake the HTTP layer; no paid call is made.
"""
import asyncio

from deepchoice.retrievers import tavily_search as ts


def test_diversity_queries_for_a_real_pair():
    queries = ts.diversity_queries(["Gitleaks", "TruffleHog"])
    assert len(queries) == 1
    assert "Gitleaks" in queries[0] and "TruffleHog" in queries[0]


def test_diversity_queries_ignore_generic_placeholders():
    assert ts.diversity_queries(["A", "B"]) == []
    assert ts.diversity_queries(["A", "B", "Candidate A"]) == []
    assert ts.diversity_queries(["Gitleaks"]) == []


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_search_adds_an_independent_source_query(monkeypatch):
    calls = []

    async def fake_post(post, payload=None, **kwargs):
        calls.append(dict(payload or {}))
        return _FakeResponse({"results": [{
            "url": f"https://example.com/{len(calls)}",
            "title": "Result",
            "content": "body",
        }]}), "key"

    monkeypatch.setattr(ts, "post_with_failover", fake_post)
    agent = ts.TavilySearch()
    results = asyncio.run(agent._do_search(
        "Gitleaks vs TruffleHog", [], 6, adapted_queries=["Gitleaks vs TruffleHog"],
        candidate_techs=["Gitleaks", "TruffleHog"]))
    diversity_calls = [call for call in calls if call.get("include_domains")]
    assert len(diversity_calls) == 1
    assert set(diversity_calls[0]["include_domains"]) == set(ts.INDEPENDENT_SOURCE_DOMAINS)
    assert results


def test_search_skips_diversity_for_generic_candidates(monkeypatch):
    calls = []

    async def fake_post(post, payload=None, **kwargs):
        calls.append(dict(payload or {}))
        return _FakeResponse({"results": []}), "key"

    monkeypatch.setattr(ts, "post_with_failover", fake_post)
    agent = ts.TavilySearch()
    asyncio.run(agent._do_search("A vs B", [], 4, adapted_queries=["A vs B"],
                                 candidate_techs=["A", "B"]))
    assert not any(call.get("include_domains") for call in calls)
