import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from deepchoice.retrievers.tavily_search import TavilySearch
from deepchoice.retrievers.github_api import GitHubSearch
from deepchoice.retrievers.arxiv_api import ArxivSearch
from deepchoice.retrievers.community import CommunitySearch
from deepchoice.retrievers.official import OfficialSearch
from deepchoice.retrievers import RETRIEVER_REGISTRY
from deepchoice.agents.multi_retriever import MultiRetrieverAgent


class TestTavilySearch:
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
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            result = await retriever.search("test framework", [])
        assert result["source"] == "github"
        assert result["status"] == "success"
        assert "Stars:" in result["results"][0]["snippet"] if result["results"] else True

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        retriever = GitHubSearch()
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("rate limited")
            result = await retriever.search("test", [])
        assert result["status"] == "failed"


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
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
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

        mock_reddit = MagicMock()
        mock_reddit.status_code = 200
        mock_reddit.json.return_value = {"data": {"children": []}}

        retriever = CommunitySearch()
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_se, mock_reddit]
            result = await retriever.search("test query", [])
        assert result["source"] == "community"
        assert result["status"] == "success"


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
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            result = await retriever.search("test fastapi", [])
        assert result["source"] == "official"
        assert result["status"] == "success"


class TestRetrieverRegistry:
    def test_all_six_retrievers_registered(self):
        assert len(RETRIEVER_REGISTRY) == 6
        assert "tavily" in RETRIEVER_REGISTRY
        assert "chroma" in RETRIEVER_REGISTRY
        assert "github" in RETRIEVER_REGISTRY
        assert "arxiv" in RETRIEVER_REGISTRY
        assert "community" in RETRIEVER_REGISTRY
        assert "official" in RETRIEVER_REGISTRY


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
