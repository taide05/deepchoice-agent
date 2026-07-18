import pytest
from unittest.mock import AsyncMock, patch
from deepchoice.clarify.session_manager import SessionState
from deepchoice.clarify.clarification_agent import (
    ClarificationAgent,
    _get_recommendations,
    _match_categories,
)


class TestMatchCategories:
    def test_matches_web_keywords(self):
        cats = _match_categories("我想做个网站")
        assert "fc14a2e9" in cats

    def test_matches_ai_keywords(self):
        cats = _match_categories("我要搭一个AI聊天机器人")
        assert "b82c4e6a" in cats

    def test_defaults_to_ai_when_no_match(self):
        cats = _match_categories("asdfghjkl")
        assert cats == ["b82c4e6a"]


class TestGetRecommendations:
    def test_returns_candidates_from_map(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "我想做个AI聊天机器人"}]
        state.unknown_techs = True
        candidates = _get_recommendations(state)
        assert len(candidates) > 0
        names = [c["name"] for c in candidates]
        assert "LangChain" in names or "Dify" in names or "LlamaIndex" in names

    def test_caps_at_7_candidates(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "前端 后端 API 部署"}]
        candidates = _get_recommendations(state)
        assert len(candidates) <= 7


class TestClarificationAgentDecideAction:
    def test_recommend_when_missing_techs_and_unknown(self):
        state = SessionState()
        state.missing_required = ["candidate_techs", "complexity"]
        state.unknown_techs = True
        state.clarify_rounds = 1
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "recommend"

    def test_ask_when_missing_scene(self):
        state = SessionState()
        state.missing_required = ["scene", "candidate_techs"]
        state.unknown_techs = False
        state.candidate_techs = ["FastAPI", "Flask"]
        state.clarify_rounds = 0
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "ask"

    def test_confirm_when_all_filled(self):
        state = SessionState()
        state.missing_required = []
        state.scene = "solo"
        state.complexity = "simple"
        state.candidate_techs = ["FastAPI"]
        state.clarify_rounds = 2
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "confirm"

    def test_confirm_when_rounds_exceeded(self):
        state = SessionState()
        state.missing_required = ["complexity"]
        state.clarify_rounds = 3
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "confirm"


class TestClarificationAgentRecommend:
    @pytest.mark.asyncio
    async def test_handle_recommend_returns_candidates(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "我想做个AI应用"}]
        state.missing_required = ["candidate_techs", "complexity"]
        state.unknown_techs = True
        state.clarify_rounds = 1

        mock_llm = {"message": "这些是推荐的框架，你看看想比较哪几个？", "action": "recommend"}
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm
            result = await agent._handle_recommend(state)

        assert result["action"] == "recommend"
        assert "candidates" in result["payload"]
        assert len(result["payload"]["candidates"]) > 0


class TestClarificationAgentSubQuestions:
    @pytest.mark.asyncio
    async def test_generate_sub_questions_returns_5(self):
        state = SessionState()
        state.candidate_techs = ["FastAPI", "Flask"]
        state.scene = "solo"
        state.complexity = "simple"

        mock_llm = {"sub_questions": ["q1", "q2", "q3", "q4", "q5"]}
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm
            result = await agent._generate_sub_questions(state)

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_generate_sub_questions_fallback_on_error(self):
        state = SessionState()
        state.candidate_techs = ["React", "Vue"]
        state.scene = "team"
        state.complexity = "medium"

        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("API error")
            result = await agent._generate_sub_questions(state)

        assert len(result) == 5
