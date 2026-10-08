from unittest.mock import AsyncMock, patch

import pytest

from tests.clarify import model_snapshot

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

    def test_unknown_category_does_not_choose_ai(self):
        cats = _match_categories("asdfghjkl")
        assert cats == []


class TestGetRecommendations:
    def test_returns_candidates_from_map(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "我想做个AI聊天机器人"}]
        state.unknown_techs = True
        candidates = _get_recommendations(state)
        assert len(candidates) > 0
        names = [c["name"] for c in candidates]
        assert "LangChain" in names or "Dify" in names or "LlamaIndex" in names
        assert all(set(candidate) == {"name"} for candidate in candidates)

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
    @pytest.mark.parametrize("provider_fails", [False, True])
    async def test_handle_recommend_returns_candidates(self, provider_fails):
        state = SessionState()
        state.messages = [{"role": "user", "content": "我想做个AI应用"}]
        state.missing_required = ["candidate_techs", "complexity"]
        state.unknown_techs = True
        state.clarify_rounds = 1

        mock_llm = model_snapshot(state.messages[0]["content"], action="recommend",
                                  candidate_techs=["LangChain", "Dify"])
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            if provider_fails:
                mock_call.side_effect = RuntimeError("provider error")
            else:
                mock_call.return_value = mock_llm
            result = await agent._handle_recommend(state)

        assert mock_call.await_count == 1
        assert "候选示例" in result["answer"] and "尚未研究" in result["answer"]
        assert result["action"] == "recommend"
        assert "candidates" in result["payload"]
        assert len(result["payload"]["candidates"]) > 0
        assert state.candidate_techs == []
        assert "candidate_techs" in state.missing_required
        assert state.messages[0]["content"] in mock_call.await_args.args[0][0]["content"]


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
    ClarificationAgent()._merge_and_build_response(state, model_snapshot(
        state.messages[0]["content"], candidate_techs=candidates))
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
    first.resolved_round = 1
    second = first.model_copy(deep=True)
    second.resolved_round = 0
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
async def test_confirm_failure_is_atomic_and_does_not_invent_defaults(model_result):
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
    assert model.await_count == 1 and response["action"] == "ask"
    assert state.scene is None and state.complexity is None
    assert state.constraints == ["Keep original constraint"]
    assert len(response["answer"]) <= 4000
    state.append_message("assistant", response["answer"])
    assert state.clarified_task is None



async def test_confirm_preserves_known_values_and_keeps_missing_fields_unknown():
    state = SessionState(scene="solo", candidate_techs=["Zephyr"], clarify_rounds=3,
                         missing_required=["complexity"], messages=[
                             {"role": "user", "content": "Compare Zephyr for personal use"}])
    with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
        model.return_value = model_snapshot(state.messages[0]["content"], scene="solo",
                                            candidate_techs=["Zephyr"])
        response = await ClarificationAgent().decide_and_respond(state)
    assert state.scene == "solo" and state.complexity is None
    assert response["payload"]["clarified_task"]["complexity"] is None
    assert "未知" in response["answer"]
    assert model.await_count == 1


@pytest.mark.parametrize("query,expected", [
    ("rapid", []), ("explain", []), ("happy", []),
    ("use an API", ["a7b31d5f"]),
    ("AI聊天机器人", ["b82c4e6a"]),
    ("mobile APP", ["d04e6a8c"]),
])
def test_category_keywords_respect_ascii_identifier_boundaries(query, expected):
    assert _match_categories(query) == expected


@pytest.mark.parametrize("provider_fails", [False, True])
async def test_unknown_category_asks_without_cards_and_preserves_reply_extraction(provider_fails):
    state = SessionState(missing_required=["candidate_techs", "scene", "complexity"],
        unknown_techs=True, messages=[{"role": "user", "content": "Need rapid explain happy"}])
    with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
        if provider_fails:
            model.side_effect = RuntimeError("provider error")
        else:
            model.return_value = model_snapshot(state.messages[0]["content"], action="recommend",
                                                scene="solo", constraints=["No new server"])
        response = await ClarificationAgent().decide_and_respond(state)
    assert response["action"] == "ask" and response["payload"] == {"reason": "category_unknown"}
    assert "技术方向" in response["answer"] and model.await_count == 1
    assert state.candidate_techs == []
    assert state.scene == (None if provider_fails else "solo")
    assert state.constraints == ([] if provider_fails else ["No new server"])
