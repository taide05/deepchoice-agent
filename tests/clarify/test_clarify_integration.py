from unittest.mock import AsyncMock, patch

import pytest

from tests.clarify import model_snapshot

from deepchoice.clarify.clarification_agent import ClarificationAgent
from deepchoice.clarify.session_manager import SessionManager


class TestFullClarifyFlow:
    @pytest.mark.asyncio
    async def test_vague_query_to_finalize(self):
        sm = SessionManager()
        agent = ClarificationAgent()

        result = sm.create("我想做个AI应用，用什么框架好")
        sid = result["session_id"]
        state = sm._sessions[sid]
        assert state.unknown_techs is True
        assert "candidate_techs" in state.missing_required

        mock_r1 = model_snapshot("个人开发对话机器人，用什么框架好", action="recommend", scene="solo")
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r1
            sm.process_message(sid, "对话机器人")
            state = sm._sessions[sid]
            r1 = await agent.decide_and_respond(state)
            assert r1["action"] == "recommend"

        mock_r2 = model_snapshot("个人开发对话机器人，比较 LangChain 和 Dify", scene="solo",
                                 candidate_techs=["LangChain", "Dify"])
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r2
            sm.process_message(sid, "比较 LangChain 和 Dify")
            r2 = await agent.decide_and_respond(state)
            assert r2["action"] in ("ask", "confirm")

        mock_r3 = model_snapshot("个人开发简单对话机器人，比较 LangChain 和 Dify", action="confirm",
                                 scene="solo", complexity="simple", candidate_techs=["LangChain", "Dify"])
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r3
            sm.process_message(sid, "简单的对话机器人")
            r3 = await agent.decide_and_respond(state)
            assert r3["action"] == "confirm"

        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = AssertionError("Finalize must not call a model")
            final = await agent._handle_finalize(state)
            mock_llm.assert_not_awaited()

        assert final["action"] == "finalize"
        assert final["payload"]["sub_questions"] == []
        assert final["payload"]["clarified_task"]["scene_context"] == "solo"
        assert len(final["payload"]["clarified_task"]["candidate_techs"]) == 2

    @pytest.mark.asyncio
    async def test_initial_skip_keeps_missing_requirements(self):
        sm = SessionManager()
        sm.create("做个项目")
        sid = list(sm._sessions.keys())[0]
        sm.finalize(sid)
        final_state = sm._sessions[sid]
        assert final_state.scene is None
        assert final_state.complexity is None
