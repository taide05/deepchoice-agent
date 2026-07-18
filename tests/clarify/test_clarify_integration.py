import pytest
from unittest.mock import AsyncMock, patch
from deepchoice.clarify.session_manager import SessionManager
from deepchoice.clarify.clarification_agent import ClarificationAgent


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

        mock_r1 = {"action": "recommend", "message": "对话机器人方向，看看这些框架", "scene": "solo"}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r1
            sm.process_message(sid, "对话机器人")
            state = sm._sessions[sid]
            r1 = await agent.decide_and_respond(state)
            assert r1["action"] == "recommend"

        state.candidate_techs = ["LangChain", "Dify"]
        if "candidate_techs" in state.missing_required:
            state.missing_required.remove("candidate_techs")
        if "candidate_techs" not in state.filled_required:
            state.filled_required.append("candidate_techs")

        mock_r2 = {"action": "ask", "message": "这个项目业务逻辑复杂吗？", "complexity": None}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r2
            sm.process_message(sid, "就这两个")
            r2 = await agent.decide_and_respond(state)
            assert r2["action"] in ("ask", "confirm")

        state.complexity = "simple"
        if "complexity" in state.missing_required:
            state.missing_required.remove("complexity")
        if "complexity" not in state.filled_required:
            state.filled_required.append("complexity")

        mock_r3 = {"action": "confirm", "message": "确认：solo开发者，简单对话机器人，LangChain vs Dify。开始研究？"}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r3
            sm.process_message(sid, "简单的对话机器人")
            r3 = await agent.decide_and_respond(state)
            assert r3["action"] == "confirm"

        mock_sub_q = {"sub_questions": [
            "LangChain vs Dify 功能覆盖度对比",
            "LangChain vs Dify 性能基准测试",
            "LangChain vs Dify 社区活跃度与维护频率",
            "LangChain vs Dify 学习曲线与文档质量",
            "LangChain vs Dify 在solo场景下的部署复杂度",
        ]}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_sub_q
            final = await agent._handle_finalize(state)

        assert final["action"] == "finalize"
        assert len(final["payload"]["sub_questions"]) == 5
        assert final["payload"]["clarified_task"]["scene_context"] == "solo"
        assert len(final["payload"]["clarified_task"]["candidate_techs"]) == 2

    @pytest.mark.asyncio
    async def test_forced_finalize_with_defaults(self):
        sm = SessionManager()
        sm.create("做个项目")
        sid = list(sm._sessions.keys())[0]
        state = sm._sessions[sid]
        state.clarify_rounds = 1

        sm.finalize(sid)
        final_state = sm._sessions[sid]
        assert final_state.scene == "team"
        assert final_state.complexity == "medium"
