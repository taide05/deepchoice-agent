from unittest.mock import AsyncMock, patch

import pytest

from deepchoice.clarify.clarification_agent import (
    ClarificationAgent,
    _get_recommendations,
    _match_categories,
)
from deepchoice.clarify.session_manager import SessionState


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

        mock_llm = {"message": "这些是推荐的框架，你看看想比较哪几个？", "action": "recommend",
                    "candidate_techs": ["LangChain", "Dify"]}
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm
            result = await agent._handle_recommend(state)

        assert result["action"] == "recommend"
        assert "candidates" in result["payload"]
        assert len(result["payload"]["candidates"]) > 0
        assert state.candidate_techs == []
        assert "candidate_techs" in state.missing_required
        assert state.messages[0]["content"] in mock_call.await_args.args[0][0]["content"]


class TestClarificationAgentSubQuestions:
    @pytest.mark.asyncio
    async def test_generate_sub_questions_returns_5(self):
        state = SessionState()
        state.candidate_techs = ["FastAPI", "Flask"]
        state.scene = "solo"
        state.complexity = "simple"
        state.constraints = ["No additional server", "Restart recovery is mandatory"]
        state.messages = [{"role": "user", "content": "Choose for durable restart recovery"}]

        mock_llm = {"sub_questions": ["q1", "q2", "q3", "q4", "q5"]}
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm
            result = await agent._generate_sub_questions(state)

        assert len(result) == 5
        prompt = mock_call.await_args.args[0][0]["content"]
        assert state.messages[0]["content"] in prompt
        assert all(constraint in prompt for constraint in state.constraints)
        assert mock_call.await_count == 1

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


@pytest.mark.parametrize("reply,candidates,expected", [
    ("Compare Zephyr and Sable", ["Zephyr", "Sable"], ["Zephyr", "Sable"]),
    ("Compare ZephyrPro", ["Zephyr", "Sable"], []),
    ("Please recommend something", ["Zephyr", "Sable"], []),
    ("Compare Atlas Pro", ["Atlas", "Atlas Pro"], ["Atlas Pro"]),
    ("Compare Atlas Pro and Atlas", ["Atlas", "Atlas Pro"], ["Atlas", "Atlas Pro"]),
])
def test_only_user_candidate_mentions_can_fill_selection(reply, candidates, expected):
    state = SessionState(missing_required=["candidate_techs"], messages=[
        {"role": "user", "content": "Need a routing library"},
        {"role": "assistant", "content": "Perhaps Zephyr or Sable?"},
        {"role": "user", "content": reply},
    ])
    ClarificationAgent()._merge_and_build_response(state, {
        "action": "ask", "message": "Next question", "candidate_techs": candidates,
    })
    assert state.candidate_techs == expected
    assert ("candidate_techs" in state.filled_required) == bool(expected)


def test_distinct_original_requests_and_replies_do_not_share_clarification_prompt():
    first = SessionState(candidate_techs=["Zephyr", "Sable"], messages=[
        {"role": "user", "content": "Choose a routing library for recovery"},
        {"role": "assistant", "content": "OUTDATED QUESTION"},
        {"role": "user", "content": "OLDER REPLY"},
        {"role": "assistant", "content": "Who will maintain this?"},
        {"role": "user", "content": "Personal use, no additional server"},
    ])
    second = first.model_copy(deep=True)
    second.messages = [
        {"role": "user", "content": "Choose a routing library for throughput"},
        {"role": "assistant", "content": "What is the deployment scope?"},
        {"role": "user", "content": "Enterprise deployment with separate services"},
    ]
    agent = ClarificationAgent()
    first_prompt, second_prompt = agent._build_prompt(first), agent._build_prompt(second)
    assert first_prompt != second_prompt
    assert all(first.messages[index]["content"] in first_prompt for index in (0, 3, 4))
    assert "OUTDATED QUESTION" not in first_prompt and "OLDER REPLY" not in first_prompt
    assert all(message["content"] in second_prompt for message in second.messages)


@pytest.mark.parametrize("model_result", [
    RuntimeError("provider error"), ["invalid JSON shape"],
    {"scene": "solo", "complexity": "invalid", "constraints": ["must not commit"]},
    {"message": "x" * 4000},
])
async def test_confirm_failure_is_atomic_and_default_notice_stays_within_message_limit(model_result):
    state = SessionState(candidate_techs=["Zephyr"], constraints=["Keep original constraint"],
        clarify_rounds=3, missing_required=["scene", "complexity"], messages=[
            {"role": "user", "content": "Compare Zephyr for personal use"},
        ])
    with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
        if isinstance(model_result, Exception):
            model.side_effect = model_result
        else:
            model.return_value = model_result
        response = await ClarificationAgent().decide_and_respond(state)
    assert model.await_count == 1 and response["action"] == "confirm"
    assert state.scene == "team" and state.complexity == "medium"
    assert state.constraints == ["Keep original constraint"]
    assert "场景=team" in response["answer"] and "复杂度=medium" in response["answer"]
    assert "推测" in response["answer"] and len(response["answer"]) <= 4000
    state.append_message("assistant", response["answer"])
    assert response["payload"]["clarified_task"]["constraints"] == ["Keep original constraint"]


async def test_confirm_preserves_known_values_and_defaults_only_missing_fields():
    state = SessionState(scene="solo", candidate_techs=["Zephyr"], clarify_rounds=3,
                         missing_required=["complexity"], messages=[
                             {"role": "user", "content": "Compare Zephyr for personal use"}])
    with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
        model.return_value = {"scene": "enterprise", "message": "Confirm this request"}
        response = await ClarificationAgent().decide_and_respond(state)
    assert state.scene == "solo" and state.complexity == "medium"
    assert "复杂度=medium" in response["answer"] and "场景=" not in response["answer"]
    assert model.await_count == 1
