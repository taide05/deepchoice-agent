import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from deepchoice.agents.multi_retriever import MultiRetrieverAgent
from deepchoice.retrievers import RETRIEVER_REGISTRY
from deepchoice.retrievers.arxiv_api import ArxivSearch
from deepchoice.retrievers.base import BaseRetriever
from deepchoice.retrievers.community import CommunitySearch
from deepchoice.retrievers.github_api import GitHubSearch
from deepchoice.retrievers.official import OfficialSearch
from deepchoice.retrievers.tavily_search import TavilySearch
from deepchoice.outbound import throttle


@pytest.fixture(autouse=True)
def _fast_provider_pacing(monkeypatch):
    # Envelope tests use immediate fake HTTP; dedicated throttle tests retain
    # the real policies and a virtual clock.
    for source in ("github", "arxiv", "community", "official", "official-web"):
        throttle.gate_for(source).interval = 0.0
    from deepchoice.retrievers import tavily_keypool

    monkeypatch.setattr(tavily_keypool, "_KEY_INTERVAL_S", 0.0)


class _FakeClient:
    """Async context-manager client standing in for outbound.make_client."""

    def __init__(self, get_return=None, post_return=None,
                 get_side=None, post_side=None):
        self.get = AsyncMock(return_value=get_return, side_effect=get_side)
        self.post = AsyncMock(return_value=post_return, side_effect=post_side)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_outbound(fake: _FakeClient):
    return patch("deepchoice.outbound.make_client", new_callable=AsyncMock,
                 return_value=fake)


class TestTavilySearch:
    @pytest.fixture(autouse=True)
    def _tavily_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TAVILY_API_KEYS", "tvly-dev-test")
        monkeypatch.setenv("TAVILY_KEY_STATE_PATH", str(tmp_path / "state.json"))
        from deepchoice.retrievers import tavily_keypool
        tavily_keypool._reset_for_tests()
        yield

    @pytest.mark.asyncio
    async def test_returns_uniform_envelope(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [{
                "url": "https://example.com",
                "title": "Test Result",
                "content": "A comprehensive comparison snippet",
                "published_date": "2026-06-15",
            }]
        }
        retriever = TavilySearch()
        client = _FakeClient(post_return=mock_resp)
        with _patch_outbound(client) as make_client:
            result = await retriever.search("test query", [])
        make_client.assert_awaited_once_with("tavily")
        assert client.post.await_count == 2  # key probe + actual search
        assert all(
            call.args[0] == "https://api.tavily.com/search"
            for call in client.post.await_args_list
        )
        assert result["source"] == "tavily"
        assert result["status"] == "success"
        assert result["error"] is None
        assert isinstance(result["latency_ms"], int)
        assert len(result["results"]) > 0
        assert result["results"][0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        retriever = TavilySearch()
        client = _FakeClient(post_side=Exception("API timeout"))
        with _patch_outbound(client) as make_client:
            result = await retriever.search("test query", [])
        make_client.assert_awaited_once_with("tavily")
        assert result["status"] == "failed"
        assert result["error"] is not None
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_searches_sub_questions_too(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}

        retriever = TavilySearch()
        client = _FakeClient(post_return=mock_resp)
        with _patch_outbound(client):
            await retriever.search("main query", ["sq1", "sq2", "sq3"])
        assert client.post.await_count >= 3  # probe + main + sub-questions

    @pytest.mark.asyncio
    async def test_conflict_search_web_uses_tavily_outbound_client(self):
        from deepchoice.agents.conflict_detector import _execute_search

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [{
                "url": "https://example.com/evidence",
                "title": "Evidence",
                "content": "bounded evidence content",
            }]
        }
        client = _FakeClient(post_return=mock_resp)
        with _patch_outbound(client) as make_client:
            output = await _execute_search(
                "search_web", {"query": "claim", "max_results": 2}
            )

        make_client.assert_awaited_once_with("tavily")
        assert client.post.await_count == 2  # key probe + actual search
        assert json.loads(output) == [{
            "title": "Evidence",
            "content": "bounded evidence content",
            "url": "https://example.com/evidence",
        }]

    @pytest.mark.asyncio
    async def test_conflict_search_web_route_unavailable_is_safe_error(self):
        from deepchoice.agents.conflict_detector import _execute_search

        with patch(
            "deepchoice.outbound.make_client",
            new_callable=AsyncMock,
            side_effect=RuntimeError("private route detail"),
        ) as make_client:
            output = await _execute_search("search_web", {"query": "claim"})

        make_client.assert_awaited_once_with("tavily")
        assert json.loads(output) == {"error": "RuntimeError"}
        assert "private route detail" not in output


class TestGitHubSearch:
    @pytest.fixture(autouse=True)
    def _throttle_off(self, monkeypatch):
        """These tests assert envelope/error behavior, not throttling; the
        limiter's pacing/backoff would otherwise add real sleeps per request."""
        from deepchoice.retrievers import github_rate
        github_rate._reset_for_tests()

        monkeypatch.setattr(github_rate, "interval_s", lambda: 0.0)
        monkeypatch.setattr(github_rate, "retry_delay", lambda headers: 0.0)
        yield

    @pytest.mark.asyncio
    async def test_returns_repo_results(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{
                "html_url": "https://github.com/test/repo",
                "full_name": "test/repo",
                "stargazers_count": 5000,
                "forks_count": 200,
                "updated_at": "2026-06-01T00:00:00Z",
            }]
        }
        retriever = GitHubSearch()
        with _patch_outbound(_FakeClient(get_return=mock_resp)):
            result = await retriever.search("test framework", [])
        assert result["source"] == "github"
        assert result["status"] == "success"
        assert "Stars:" in result["results"][0]["snippet"] if result["results"] else True

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        retriever = GitHubSearch()
        with _patch_outbound(_FakeClient(get_side=[Exception("rate limited")])):
            result = await retriever.search("test", [])
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_httpx_error_is_failed_not_silent_empty(self):
        """Real failure mode (ConnectError on every attempt) must surface as
        failed — not as success with 0 results (the 300-case regression)."""
        retriever = GitHubSearch()
        with _patch_outbound(_FakeClient(
                get_side=[httpx.ConnectError("all connection attempts failed")] * 4)):
            result = await retriever.search("test framework", [])
        assert result["status"] == "failed"
        assert result["results"] == []
        assert result["error"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_all_non_200_raises(self):
        """HTTP 403 with nothing retrieved must be failed, not empty success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        retriever = GitHubSearch()
        with _patch_outbound(_FakeClient(get_return=mock_resp)):
            result = await retriever.search("test framework", [])
        assert result["status"] == "failed"
        assert "HTTP 403" in result["error"]

    @pytest.mark.asyncio
    async def test_partial_failure_is_not_reported_as_complete_success(self):
        """The v1 envelope cannot express partial results; fail visibly."""
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {
            "items": [{
                "html_url": "https://github.com/test/repo",
                "full_name": "test/repo",
                "stargazers_count": 100,
                "forks_count": 10,
                "updated_at": "2026-06-01T00:00:00Z",
            }]
        }
        bad = MagicMock()
        bad.status_code = 403
        retriever = GitHubSearch()
        with _patch_outbound(_FakeClient(get_side=[ok, bad, bad, bad])):
            result = await retriever.search("test framework", [])
        assert result["status"] == "failed"
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_failure_invalidates_outbound_route(self):
        """A failed search must notify the channel layer so the route can be
        re-probed on the next resolve (runtime re-route path)."""
        retriever = GitHubSearch()
        invalidate = AsyncMock()
        fake_resolver = MagicMock()
        fake_resolver.invalidate = invalidate
        with _patch_outbound(_FakeClient(get_side=[Exception("boom")])), \
             patch("deepchoice.outbound.get_resolver", return_value=fake_resolver):
            result = await retriever.search("test framework", [])
        assert result["status"] == "failed"
        invalidate.assert_awaited_once_with("github")


class TestArxivSearch:
    @pytest.mark.asyncio
    async def test_parses_atom_xml(self):
        xml_response = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345</id>
    <title>A Survey of Multi-Agent Frameworks</title>
    <summary>We compare frameworks across 12 dimensions...</summary>
    <published>2026-01-15T00:00:00Z</published>
  </entry>
</feed>"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = xml_response

        retriever = ArxivSearch()
        with _patch_outbound(_FakeClient(get_return=mock_resp)):
            result = await retriever.search("multi agent frameworks", [])
        assert result["source"] == "arxiv"
        assert result["status"] == "success"
        assert len(result["results"]) == 1
        assert result["results"][0]["url"] == "http://arxiv.org/abs/2401.12345"


class TestCommunitySearch:
    @pytest.mark.asyncio
    async def test_searches_stackexchange_and_reddit(self):
        mock_se = MagicMock()
        mock_se.status_code = 200
        mock_se.json.return_value = {"items": []}

        retriever = CommunitySearch()
        with _patch_outbound(_FakeClient(get_return=mock_se)):
            result = await retriever.search("test query", [])
        assert result["source"] == "community"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_searches_serialized_by_semaphore(self):
        """SO allows one request per IP: two concurrent searches must NOT
        overlap (the semaphore serializes them)."""
        import asyncio as _asyncio

        events = []

        async def slow_get(url, params=None, headers=None, timeout=None):
            assert timeout == 15.0
            events.append("start")
            await _asyncio.sleep(0.15)
            events.append("end")
            return httpx.Response(200, json={"items": []})

        class SlowClient:
            def __init__(self):
                self.get = AsyncMock(side_effect=slow_get)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        # direct test of the semaphore behaviour on the real method:
        # patch make_client to the slow client
        retriever = CommunitySearch()

        async def slow_make_client(source):
            return SlowClient()

        with patch("deepchoice.retrievers.community._outbound.make_client",
                   side_effect=slow_make_client):
            results = await _asyncio.gather(retriever.search("test q", []),
                                            retriever.search("test q2", []))
        assert all(r["status"] == "success" for r in results)
        # never two 'start' without an 'end' between them
        first_end = events.index("end")
        assert events[:first_end] == ["start", "end"] or events == ["start", "end", "start", "end"]

    @pytest.mark.asyncio
    async def test_non_200_raises(self):
        """Non-200 (rate limit/auth) must surface as failed, not empty success."""
        mock_se = MagicMock()
        mock_se.status_code = 429
        mock_se.headers = {"Retry-After": "0"}
        mock_se.text = "quota exceeded"
        retriever = CommunitySearch()
        with _patch_outbound(_FakeClient(get_return=mock_se)):
            result = await retriever.search("test query", [])
        assert result["status"] == "failed"
        assert "HTTP 429" in result["error"]


class TestOfficialSearch:
    @pytest.mark.asyncio
    async def test_fetches_pypi_info(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "info": {
                "package_url": "https://pypi.org/project/test/",
                "version": "1.0.0",
                "summary": "A test package",
            }
        }
        retriever = OfficialSearch()
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("deepchoice.retrievers.official.call_model",
                   new_callable=AsyncMock, return_value={"url": None}):
            mock_get.return_value = mock_resp
            result = await retriever.search("test fastapi", [])
        assert result["source"] == "official"
        assert result["status"] == "success"


class TestErrorReporting:
    """Empty-str exceptions (e.g. httpx.ReadTimeout('')) must not produce empty error fields."""

    class _RaisingRetriever(BaseRetriever):
        source = "raise_test"

        def __init__(self, exc: Exception):
            self._exc = exc

        async def _do_search(self, query, sub_questions, max_results, adapted_queries=None):
            raise self._exc

    @pytest.mark.asyncio
    async def test_empty_message_exception_gets_type_name(self):
        retriever = self._RaisingRetriever(Exception())
        result = await retriever.search("test", [])
        assert result["status"] == "failed"
        assert result["error"] == "Exception()"

    @pytest.mark.asyncio
    async def test_httpx_read_timeout_empty_message(self):
        retriever = self._RaisingRetriever(httpx.ReadTimeout(""))
        result = await retriever.search("test", [])
        assert result["status"] == "failed"
        assert result["error"] == "ReadTimeout()"

    @pytest.mark.asyncio
    async def test_message_exception_keeps_type_prefix(self):
        retriever = self._RaisingRetriever(Exception("API timeout"))
        result = await retriever.search("test", [])
        assert result["error"] == "Exception"

    @pytest.mark.asyncio
    async def test_multi_retriever_gather_error_not_empty(self):
        state = {
            "task": {"query": "test", "scene_context": "solo", "constraints": [], "report_format": "what_why_how"},
            "sub_questions": [],
        }

        class EmptyErrRetriever:
            source = "empty_err"
            async def search(self, query, sub_questions, max_results=7, adapted_queries=None):
                raise httpx.ReadTimeout("")

        agent = MultiRetrieverAgent()
        with patch.dict(
            "deepchoice.agents.multi_retriever.RETRIEVER_REGISTRY",
            {"empty_err": EmptyErrRetriever},
            clear=True,
        ):
            result = await agent.run(state)
        assert result["search_results"][0]["status"] == "failed"
        assert result["search_results"][0]["error"] == "ReadTimeout()"


class TestRetrieverRegistry:
    def test_all_six_retrievers_registered(self):
        assert len(RETRIEVER_REGISTRY) == 6
        assert "tavily" in RETRIEVER_REGISTRY
        assert "chroma" in RETRIEVER_REGISTRY
        assert "github" in RETRIEVER_REGISTRY
        assert "arxiv" in RETRIEVER_REGISTRY
        assert "community" in RETRIEVER_REGISTRY
        assert "official" in RETRIEVER_REGISTRY


class TestSearchKBChromaPath:
    @pytest.mark.parametrize("configured", [None, "experiment/knowledge/chroma"])
    def test_retriever_honors_explicit_path_without_changing_collection(self, monkeypatch, configured):
        import chromadb
        from deepchoice.retrievers.chroma_kb import ChromaKB

        captured = {}

        class FakeClient:
            def get_or_create_collection(self, name):
                captured["collection"] = name
                return object()

        def fake_persistent(path, **_):
            captured["path"] = path
            return FakeClient()

        monkeypatch.setattr(chromadb, "PersistentClient", fake_persistent)
        if configured is None:
            monkeypatch.delenv("CHROMA_PATH", raising=False)
        else:
            monkeypatch.setenv("CHROMA_PATH", configured)
        ChromaKB()
        assert captured == {"path": configured or "./chroma_kb/chroma_db", "collection": "tech_kb"}

    def test_default_path_matches_retriever(self, monkeypatch):
        import asyncio

        import chromadb
        from deepchoice.agents.conflict_detector import _execute_search
        from deepchoice.retrievers.chroma_kb import ChromaKB
        from deepchoice.retrievers.contracts import RetrievalResult

        captured = {}

        class FakeClient:
            def get_or_create_collection(self, name):
                captured["collection"] = name
                return object()

        def fake_persistent(path, **_):
            captured["path"] = path
            return FakeClient()

        monkeypatch.setattr(chromadb, "PersistentClient", fake_persistent)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        retrieve = AsyncMock(return_value=RetrievalResult(source="chroma", status="failed",
            results=[], error="private provider detail", latency_ms=0))
        monkeypatch.setattr(ChromaKB, "retrieve", retrieve)

        out = asyncio.run(_execute_search("search_kb", {"query": "x"}))

        assert captured == {"path": "./chroma_kb/chroma_db", "collection": "tech_kb"}
        assert retrieve.call_args.args[0].query == "x"
        assert json.loads(out) == {"error": "KB collection unavailable", "results": []}

    @pytest.mark.asyncio
    async def test_search_keeps_original_query_and_diversifies_chunked_urls(self, monkeypatch):
        from deepchoice.retrievers import chroma_kb

        encoded = []
        queries = []

        class FakeModel:
            def encode(self, value):
                encoded.append(value)
                return SimpleNamespace(tolist=lambda: [0.1, 0.2])

        class FakeCollection:
            def query(self, **kwargs):
                queries.append(kwargs)
                return {
                    "ids": [["a-1", "a-2", "b-1", "c-1"]],
                    "documents": [["A first", "A second", "B", "C"]],
                    "metadatas": [[
                        {
                            "url": "https://a.example/docs",
                            "title": "A",
                            "target_id": "p01-alpha",
                            "source_type": "official",
                            "seed_identity_sha256": "a" * 64,
                            "private_note": "must not escape",
                        },
                        {"url": "https://a.example/docs", "title": "A"},
                        {"url": "https://b.example/docs", "title": "B"},
                        {"url": "https://c.example/docs", "title": "C"},
                    ]],
                }

        monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: FakeModel())
        retriever = object.__new__(chroma_kb.ChromaKB)
        retriever.collection = FakeCollection()

        results = await retriever._do_search(
            "original comparison",
            ["unused sub-question"],
            max_results=3,
            adapted_queries=["adapted dimension", "original comparison"],
        )

        assert encoded == ["original comparison", "adapted dimension"]
        assert all(call["n_results"] == 30 for call in queries)
        assert [item["url"] for item in results] == [
            "https://a.example/docs",
            "https://b.example/docs",
            "https://c.example/docs",
        ]
        assert results[0]["snippet"] == "A first"
        assert results[0]["_seed_target_id"] == "p01-alpha"
        assert results[0]["_seed_source_type"] == "official"
        assert results[0]["_seed_seed_identity_sha256"] == "a" * 64
        assert "private_note" not in results[0]

    @pytest.mark.asyncio
    async def test_adapted_dimension_receives_reserved_result_capacity(self, monkeypatch):
        from deepchoice.retrievers import chroma_kb

        calls = 0
        monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
            encode=lambda _value: SimpleNamespace(tolist=lambda: [0.1, 0.2])
        ))

        def query(**_kwargs):
            nonlocal calls
            calls += 1
            prefix = "primary" if calls == 1 else "adapted"
            return {
                "ids": [[f"{prefix}-{index}" for index in range(3)]],
                "documents": [[f"{prefix} {index}" for index in range(3)]],
                "metadatas": [[
                    {"url": f"https://{prefix}-{index}.example/docs", "title": prefix}
                    for index in range(3)
                ]],
            }

        retriever = object.__new__(chroma_kb.ChromaKB)
        retriever.collection = SimpleNamespace(query=query)
        results = await retriever._do_search(
            "original", [], max_results=3, adapted_queries=["adapted"]
        )

        assert [item["url"] for item in results] == [
            "https://primary-0.example/docs",
            "https://primary-1.example/docs",
            "https://adapted-0.example/docs",
        ]

    @pytest.mark.asyncio
    async def test_candidate_pool_remains_bounded_for_large_public_limit(self, monkeypatch):
        from deepchoice.retrievers import chroma_kb

        calls = []
        monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
            encode=lambda _value: SimpleNamespace(tolist=lambda: [0.1, 0.2])
        ))
        retriever = object.__new__(chroma_kb.ChromaKB)
        retriever.collection = SimpleNamespace(query=lambda **kwargs: (
            calls.append(kwargs) or {
                "ids": [[]], "documents": [[]], "metadatas": [[]]
            }
        ))

        assert await retriever._do_search("comparison", [], max_results=100) == []
        assert calls[0]["n_results"] == 100

    def test_query_dimensions_cap_deduplicate_and_choose_one_secondary_mode(self):
        from deepchoice.retrievers.chroma_kb import _query_dimensions

        adapted = ["adapted-1", "original", *[f"adapted-{i}" for i in range(2, 12)]]
        assert _query_dimensions("original", ["ignored-subquestion"], adapted) == [
            "original", *[f"adapted-{i}" for i in range(1, 8)]
        ]
        assert _query_dimensions("original", ["sub-1", "sub-2", "sub-3"], None) == [
            "original", "sub-1", "sub-2"
        ]

    def test_dimension_merge_round_robins_adapted_urls_then_falls_back_to_primary(self):
        from deepchoice.retrievers.chroma_kb import _merge_dimensions

        def item(url):
            return {"url": url}

        dimensions = [
            [item("p1"), item("shared"), item("p3"), item("p4")],
            [item("shared"), item("a1"), item("a2")],
            [item("b1"), item("b2")],
        ]

        assert [result["url"] for result in _merge_dimensions(
            dimensions, 7, has_adapted_queries=True
        )] == ["p1", "shared", "p3", "p4", "a1", "b1", "a2"]

    def test_subquestion_dimensions_only_fill_primary_shortfall(self):
        from deepchoice.retrievers.chroma_kb import _merge_dimensions

        def item(url):
            return {"url": url}

        dimensions = [
            [item("p1")],
            [item("p1"), item("s1"), item("s2")],
            [item("t1")],
        ]

        assert [result["url"] for result in _merge_dimensions(
            dimensions, 4, has_adapted_queries=False
        )] == ["p1", "s1", "t1", "s2"]


class TestMultiRetriever:
    @pytest.mark.asyncio
    async def test_aggregates_all_sources(self):
        state = {
            "task": {
                "query": "test",
                "scene_context": "solo",
                "constraints": [],
                "report_format": "what_why_how",
            },
            "sub_questions": [],
        }

        class MockRetriever:
            source = "mock"
            async def search(self, query, sub_questions, max_results=7, adapted_queries=None):
                return {"source": self.source, "status": "success", "results": [], "error": None, "latency_ms": 100}

        agent = MultiRetrieverAgent()
        with patch.dict(
            "deepchoice.agents.multi_retriever.RETRIEVER_REGISTRY",
            {"mock1": MockRetriever, "mock2": MockRetriever},
            clear=True,
        ):
            result = await agent.run(state)
        assert len(result["search_results"]) == 2
        assert result["partial_failures"] == []

    @pytest.mark.asyncio
    async def test_tracks_partial_failures(self):
        state = {
            "task": {"query": "test", "scene_context": "solo", "constraints": [], "report_format": "what_why_how"},
            "sub_questions": [],
        }

        class FailingRetriever:
            source = "fail"
            async def search(self, query, sub_questions, max_results=7, adapted_queries=None):
                raise Exception("broken")

        agent = MultiRetrieverAgent()
        with patch.dict(
            "deepchoice.agents.multi_retriever.RETRIEVER_REGISTRY",
            {"fail1": FailingRetriever},
            clear=True,
        ):
            result = await agent.run(state)
        assert result["partial_failures"] == ["fail1"]
        assert result["search_results"][0]["status"] == "failed"


def test_tech_aliases_target_existing_keys():
    from deepchoice.retrievers.official import _TECH_ALIASES, TECH_DOCS
    for alias, target in _TECH_ALIASES.items():
        assert target in TECH_DOCS, f"alias {alias!r} -> missing target {target!r}"


@pytest.mark.asyncio
async def test_tavily_merges_query_ranks_without_starving_later_targets(monkeypatch):
    async def post(_post, payload):
        i = int(payload["query"].removeprefix("target-"))
        response = MagicMock()
        response.json.return_value = {"results": [
            {"url": f"https://fixture.example/{i}/{j}", "title": f"Target {i}", "content": "Evidence"}
            for j in range(3)]}
        return response, None
    monkeypatch.setattr("deepchoice.retrievers.tavily_search.post_with_failover", post)
    with _patch_outbound(_FakeClient()):
        result = await TavilySearch().search("original", [], max_results=7,
            adapted_queries=[f"target-{i}" for i in range(5)])
    assert [r["url"] for r in result["results"]] == [
        *[f"https://fixture.example/{i}/0" for i in range(5)],
        "https://fixture.example/0/1", "https://fixture.example/1/1"]


@pytest.mark.asyncio
async def test_github_preserves_complete_queries_and_balances_results(monkeypatch):
    queries = ['repo:acme/alpha "transaction recovery" in:readme',
               'org:acme beta language:Python', 'gamma fork:false', 'delta', 'not-dispatched']
    async def get(client, url, *, params, headers):
        i = queries.index(params["q"])
        response = MagicMock(status_code=200)
        response.json.return_value = {"items": [
            {"full_name": f"acme/{i}-{j}", "html_url": f"https://github.com/acme/{i}-{j}"}
            for j in range(3)]}
        return response
    mock_get = AsyncMock(side_effect=get)
    monkeypatch.setattr("deepchoice.retrievers.github_api.github_rate.get_with_throttle", mock_get)
    with _patch_outbound(_FakeClient()):
        result = await GitHubSearch().search("Original Alpha vs Beta", [], max_results=5,
            adapted_queries=queries)
    assert [call.kwargs["params"]["q"] for call in mock_get.await_args_list] == queries[:4]
    assert [r["url"] for r in result["results"]] == [
        *[f"https://github.com/acme/{i}-0" for i in range(4)], "https://github.com/acme/0-1"]


def test_query_merge_skips_shared_urls_and_redistributes_empty_batch_slots():
    from deepchoice.retrievers.query_results import merge_query_results
    def item(name):
        return {"url": f"https://fixture.example/{name}", "title": name}
    assert merge_query_results([
        [item("shared"), item("a")], [],
        [item("shared"), item("shared"), item("b")],
        [{"url": ""}, item("c"), item("d")],
    ], 5) == [item("shared"), item("b"), item("c"), item("a"), item("d")]
    assert merge_query_results([[], []], 7) == []


@pytest.mark.asyncio
async def test_adapter_slots_reach_actual_tavily_dispatch_and_bounded_result(monkeypatch):
    from deepchoice.agents.query_adapter import QueryAdapterAgent
    from deepchoice.agents import query_adapter
    targets = ["Alpha durability", "Beta isolation", "Gamma recovery"]
    monkeypatch.setattr(query_adapter, "call_model", AsyncMock(return_value={"adapted": [
        {"sub_question_index": 2, "tavily": "Gamma recovery guide"},
        {"sub_question_index": 0, "tavily": "Alpha durability guide"}]}))
    adaptation = await QueryAdapterAgent().run({"task": {"query": "Alpha versus Beta"},
                                               "sub_questions": targets})
    dispatched = []
    async def post(_post, payload):
        query = payload["query"]
        dispatched.append(query)
        i = adaptation["adapted_queries"]["tavily"].index(query)
        response = MagicMock()
        response.json.return_value = {"results": [
            {"url": f"https://fixture.example/{i}/{j}", "title": query, "content": "Evidence"}
            for j in range(3)]}
        return response, None
    monkeypatch.setattr("deepchoice.retrievers.tavily_search.post_with_failover", post)
    with _patch_outbound(_FakeClient()):
        result = await TavilySearch().search("Alpha versus Beta", targets, max_results=3,
            adapted_queries=adaptation["adapted_queries"]["tavily"])
    assert dispatched == ["Alpha durability guide", "Beta isolation", "Gamma recovery guide"]
    assert [r["url"] for r in result["results"]] == [f"https://fixture.example/{i}/0" for i in range(3)]


def _target_response(source, query, *, status=200):
    if source == 'arxiv':
        entries = ''.join(
            f'<entry><id>https://arxiv.org/abs/{query.split()[0]}-{i}</id><title>{query}</title>'
            '<summary>Conditional persistence evidence under the documented settings.</summary></entry>'
            for i in range(3))
        return httpx.Response(status, text=f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>',
                              request=httpx.Request('GET', 'https://export.arxiv.org/api/query'))
    return httpx.Response(status, json={'items': [
        {'link': f'https://stackoverflow.com/questions/{query.split()[0]}-{i}', 'title': query,
         'score': 2, 'tags': ['python'],
         'body': '<p>Conditional persistence evidence under the documented settings.</p>'} for i in range(3)]},
        request=httpx.Request('GET', 'https://api.stackexchange.com/2.3/search/advanced'))


@pytest.mark.asyncio
@pytest.mark.parametrize('cls', [ArxivSearch, CommunitySearch])
async def test_native_sources_preserve_later_target_queries_and_bounded_results(cls):
    queries = ['atlas persistence', 'beacon failover', 'cedar batching']
    dispatched = []
    async def get(url, *, params, **kwargs):
        query = params['search_query'].removeprefix('all:') if cls.source == 'arxiv' else params['q']
        dispatched.append(query)
        if cls.source == 'community':
            assert url.endswith('/search/advanced') and params['sort'] == 'relevance'
            assert 'intitle' not in params
        return _target_response(cls.source, query)
    with _patch_outbound(_FakeClient(get_side=get)):
        result = await cls().search('original comparison', [], max_results=3,
                                    adapted_queries=[queries[0], *queries])
    assert result['status'] == 'success'
    assert dispatched == queries
    assert [x['title'] for x in result['results']] == queries


@pytest.mark.asyncio
@pytest.mark.parametrize('cls', [ArxivSearch, CommunitySearch])
async def test_native_source_later_required_query_failure_is_atomic(cls):
    responses = [_target_response(cls.source, 'atlas persistence'),
                 _target_response(cls.source, 'beacon failover', status=400)]
    client = _FakeClient(get_side=responses)
    with _patch_outbound(client):
        result = await cls().search('original comparison', [], adapted_queries=[
            'atlas persistence', 'beacon failover', 'cedar batching'])
    assert result['status'] == 'failed' and result['results'] == []
    assert client.get.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('cls', [ArxivSearch, CommunitySearch])
@pytest.mark.parametrize('mode', ['maximum_targets', 'long_adaptation', 'legacy_fallback', 'short_expression'])
async def test_native_query_boundaries_preserve_expressions_without_enlarging_result_cap(cls, mode):
    original = 'atlas vs beacon ' + 'persistence ' * 30
    if mode == 'maximum_targets':
        adapted = [f'target{i} persistence' for i in range(20)]
    elif mode == 'long_adaptation':
        adapted = ['atlas ' + 'configuration ' * 20 + 'without a shared backend']
    else:
        adapted = None
    if mode == 'short_expression':
        original = 'Alpha vs Beta versus Gamma; 不允许静默丢失条件。'
    expected = adapted or [original]
    dispatched = []
    async def get(url, *, params, **kwargs):
        query = params['search_query'].removeprefix('all:') if cls.source == 'arxiv' else params['q']
        dispatched.append(query)
        return _target_response(cls.source, query)
    with _patch_outbound(_FakeClient(get_side=get)):
        result = await cls().search(original, [], max_results=7, adapted_queries=adapted)
    assert result['status'] == 'success' and dispatched == expected
    assert len(result['results']) <= 7
    if mode == 'maximum_targets':
        # This package preserves the existing capacity limit; dispatch does not
        # mean all twenty targets have material in the seven retained results.
        assert [row['title'] for row in result['results']] == expected[:7]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [ArxivSearch, CommunitySearch])
@pytest.mark.parametrize("language", ["ascii", "chinese"])
async def test_failed_adapter_full_query_reaches_native_dispatch_through_multi_retriever(monkeypatch, cls, language):
    from deepchoice.agents.query_adapter import QueryAdapterAgent
    from deepchoice.retrievers.contracts import RetrievalRequest

    prefix = "Alpha vs Beta; "
    tail = " versus Omega; keep TAIL_CONSTRAINT."
    fill = "x" if language == "ascii" else "界"
    original = prefix + fill * (4000 - len(prefix) - len(tail)) + tail
    state = {"task": {"query": original}, "sub_questions": [], "_supplemental_input": "Clarify the workload."}
    model = AsyncMock(side_effect=RuntimeError("synthetic adaptation failure"))
    monkeypatch.setattr("deepchoice.agents.query_adapter.call_model", model)
    monkeypatch.setattr("deepchoice.agents.multi_retriever.harvest", lambda *a, **k: 0)
    adaptation = await QueryAdapterAgent().run(state)
    assert adaptation["adapted_queries"][cls.source] == []
    requests = []
    real_retrieve = cls.retrieve

    async def retrieve(self, request):
        assert isinstance(request, RetrievalRequest)
        requests.append(request)
        return await real_retrieve(self, request)

    monkeypatch.setattr(cls, "retrieve", retrieve)
    dispatched = []

    async def get(url, *, params, **kwargs):
        value = params["search_query"].removeprefix("all:") if cls.source == "arxiv" else params["q"]
        dispatched.append(value)
        return _target_response(cls.source, "Alpha documented conditions")

    client = _FakeClient(get_side=get)
    with _patch_outbound(client):
        output = await MultiRetrieverAgent(retriever_registry={cls.source: cls}).run({**state, **adaptation})
    assert len(requests) == 1 and requests[0].query == original and requests[0].adapted_queries == ()
    assert dispatched == [original]
    assert output["partial_failures"] == []
    assert output["search_results"][0]["status"] == "success"
    assert len(output["search_results"][0]["results"]) <= 7
    model.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [ArxivSearch, CommunitySearch])
@pytest.mark.parametrize("status", [400, 414])
async def test_native_long_query_rejection_is_visible_atomic_failure(cls, status):
    original = "Alpha vs Beta " + "x" * 3986
    dispatched = []

    async def get(url, *, params, **kwargs):
        value = params["search_query"].removeprefix("all:") if cls.source == "arxiv" else params["q"]
        dispatched.append(value)
        return httpx.Response(status, text="PRIVATE_PROVIDER_DETAIL", request=httpx.Request("GET", url))

    client = _FakeClient(get_side=get)
    with _patch_outbound(client):
        result = await cls().search(original, [])
    assert dispatched == [original] and client.get.await_count == 1
    assert result["status"] == "failed" and result["results"] == []
    expected_error = "HTTPStatusError" if cls.source == "arxiv" else f"RuntimeError: HTTP {status}"
    assert result["error"] == expected_error and "PRIVATE_PROVIDER_DETAIL" not in result["error"]
