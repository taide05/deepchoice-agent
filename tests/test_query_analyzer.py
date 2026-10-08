from unittest.mock import AsyncMock, patch

import pytest

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
        assert "scene_context" not in result
        assert state["task"]["scene_context"] == "solo"
        assert "python" in result["constraints"]

    @pytest.mark.asyncio
    async def test_empty_decomposition_reports_raw_fallback_without_scene_guess(self):
        state = {
            "task": {
                "query": "test",
                "scene_context": "unspecified",
                "constraints": [],
                "report_format": "what_why_how",
            }
        }
        mock_response = {"sub_questions": [], "scene_context": "team", "constraints": []}

        agent = QueryAnalyzerAgent()
        with patch("deepchoice.agents.query_analyzer.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent.run(state)

        assert "scene_context" not in result
        assert result["sub_questions"] == []
        assert result["quality_signals"][0]["fallback_reason"] == "empty_decomposition"
