import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from deepchoice.retrievers.base import BaseRetriever
from deepchoice.retrievers.tavily_search import TavilySearch
from deepchoice.retrievers.github_api import GitHubSearch
from deepchoice.retrievers.arxiv_api import ArxivSearch
from deepchoice.retrievers.community import CommunitySearch
from deepchoice.retrievers.official import OfficialSearch
from deepchoice.retrievers import RETRIEVER_REGISTRY
from deepchoice.agents.multi_retriever import MultiRetrieverAgent


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
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await retriever.search("test query", [])
        assert result["source"] == "tavily"
        assert result["status"] == "success"
        assert result["error"] is None
        assert isinstance(result["latency_ms"], int)
        assert len(result["results"]) > 0
        assert result["results"][0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        retriever = TavilySearch()
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = Exception("API timeout")
            result = await retriever.search("test query", [])
        assert result["status"] == "failed"
        assert result["error"] is not None
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_searches_sub_questions_too(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}

        retriever = TavilySearch()
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            await retriever.search("main query", ["sq1", "sq2", "sq3"])
        assert mock_post.call_count >= 2  # main + at least 1 sub-question


class TestGitHubSearch:
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
        assert "ConnectError" in result["error"]

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
    async def test_partial_failure_keeps_results(self):
        """If at least one search succeeded, keep results (no raise)."""
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
        assert result["status"] == "success"
        assert len(result["results"]) == 1


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
    async def test_non_200_raises(self):
        """Non-200 (rate limit/auth) must surface as failed, not empty success."""
        mock_se = MagicMock()
        mock_se.status_code = 429
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
        assert result["error"] == "Exception: API timeout"

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
    def test_default_path_matches_retriever(self, monkeypatch):
        import asyncio
        import chromadb
        from deepchoice.agents.conflict_detector import _execute_search

        captured = {}

        class FakeClient:
            def get_collection(self, name):
                raise Exception("missing")

        def fake_persistent(path, settings):
            captured["path"] = path
            return FakeClient()

        monkeypatch.setattr(chromadb, "PersistentClient", fake_persistent)
        monkeypatch.delenv("CHROMA_PATH", raising=False)

        out = asyncio.run(_execute_search("search_kb", {"query": "x"}))

        assert captured["path"] == "./chroma_kb/chroma_db"
        assert "KB collection not found" in out


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
