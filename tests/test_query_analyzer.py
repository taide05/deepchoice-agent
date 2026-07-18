import pytest
from unittest.mock import AsyncMock, patch
from deepchoice.agents.query_analyzer import QueryAnalyzerAgent


class TestQueryAnalyzer:
    @pytest.mark.asyncio
    async def test_decomposes_query_into_sub_questions(self):
        state = {
            "task": {
                "query": "FastAPI vs Flask for REST API",
                "scene_context": "solo",
                "constraints": ["python"],
                "report_format": "what_why_how",
            }
        }
        mock_response = {
            "sub_questions": [
                "FastAPI async performance vs Flask sync throughput",
                "FastAPI auto-docs vs Flask plugin ecosystem",
                "FastAPI learning curve vs Flask simplicity for solo developer",
                "FastAPI Pydantic validation vs Flask flexibility",
                "FastAPI vs Flask deployment complexity",
            ],
            "scene_context": "solo",
            "constraints": ["python"],
        }

        agent = QueryAnalyzerAgent()
        with patch("deepchoice.agents.query_analyzer.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent.run(state)

        assert len(result["sub_questions"]) >= 3
        assert result["scene_context"] == "solo"
        assert "python" in result["constraints"]

    @pytest.mark.asyncio
    async def test_defaults_scene_to_team_when_unspecified(self):
        state = {
            "task": {
                "query": "test",
                "scene_context": "unspecified",
                "constraints": [],
                "report_format": "what_why_how",
            }
        }
        mock_response = {"sub_questions": ["q1"], "scene_context": "team", "constraints": []}

        agent = QueryAnalyzerAgent()
        with patch("deepchoice.agents.query_analyzer.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent.run(state)

        assert result["scene_context"] == "team"
