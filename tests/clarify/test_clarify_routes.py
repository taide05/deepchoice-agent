from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deepchoice.server.clarify_routes import clarify_agent, router, session_manager

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestClarifyStart:
    def test_start_returns_session_and_question(self):
        mock_response = {
            "action": "ask",
            "answer": "你这个AI应用主要用来做什么？",
            "clarity_score": 0.15,
            "filled_required": [],
            "missing_required": ["scene", "candidate_techs", "complexity"],
            "clarify_rounds": 0,
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_response
            resp = client.post("/clarify/start", json={"query": "我想做个AI应用"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"].startswith("clarify_")
        assert data["next_action"] == "ask"
        assert len(data["answer"]) > 0

    def test_start_with_tech_keywords_detects_candidates(self):
        mock_response = {
            "action": "ask",
            "answer": "你是个人开发还是团队使用？",
            "clarity_score": 0.43,
            "filled_required": ["candidate_techs"],
            "missing_required": ["scene", "complexity"],
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_response
            resp = client.post("/clarify/start", json={"query": "FastAPI vs Flask"})

        assert resp.status_code == 200
        data = resp.json()
        assert "candidate_techs" in data["filled_required"]


class TestClarifyMessage:
    def test_message_returns_agent_response(self):
        mock_start = {
            "action": "ask",
            "answer": "你好，想选什么技术？",
            "clarity_score": 0.15,
            "filled_required": [],
            "missing_required": ["scene", "candidate_techs", "complexity"],
        }
        mock_message = {
            "action": "recommend",
            "answer": "对话机器人方向，看看这些框架",
            "clarity_score": 0.40,
            "filled_required": ["scene"],
            "missing_required": ["candidate_techs", "complexity"],
            "payload": {"candidates": [{"name": "LangChain", "stars": "90k+", "desc": "灵活度高"}]},
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.side_effect = [mock_start, mock_message]
            start_resp = client.post("/clarify/start", json={"query": "做个AI应用"})
            sid = start_resp.json()["session_id"]
            msg_resp = client.post(f"/clarify/{sid}/message", json={"message": "对话机器人"})

        assert msg_resp.status_code == 200
        data = msg_resp.json()
        assert data["next_action"] == "recommend"
        assert "candidates" in data.get("payload", {})

    def test_message_404_on_bad_session(self):
        resp = client.post("/clarify/nonexistent/message", json={"message": "hello"})
        assert resp.status_code == 404


class TestClarifyStatus:
    def test_status_returns_state(self):
        mock_response = {
            "action": "ask",
            "answer": "你的项目场景是什么？",
            "clarity_score": 0.43,
            "filled_required": ["candidate_techs"],
            "missing_required": ["scene", "complexity"],
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_response
            start_resp = client.post("/clarify/start", json={"query": "FastAPI vs Flask"})
            sid = start_resp.json()["session_id"]
            status_resp = client.get(f"/clarify/{sid}/status")

        assert status_resp.status_code == 200
        data = status_resp.json()
        assert "clarity_score" in data
        assert "missing_required" in data


class TestClarifyFinalize:
    def test_finalize_returns_sub_questions(self):
        mock_start = {
            "action": "confirm",
            "answer": "为solo开发者选择API框架，确认无误？",
            "clarity_score": 1.0,
            "filled_required": ["candidate_techs", "scene", "complexity"],
            "missing_required": [],
            "payload": {
                "summary": "...",
                "clarified_task": {
                    "query": "FastAPI vs Flask for solo dev",
                    "scene_context": "solo",
                    "constraints": ["python"],
                    "candidate_techs": ["FastAPI", "Flask"],
                    "complexity": "simple",
                    "report_format": "what_why_how",
                },
                "candidate_techs": ["FastAPI", "Flask"],
                "scene": "solo",
                "complexity": "simple",
            },
        }
        mock_finalize = {
            "action": "finalize",
            "answer": "需求已确认，开始研究。",
            "payload": {
                "summary": "...",
                "clarified_task": {},
                "sub_questions": ["q1", "q2", "q3", "q4", "q5"],
            },
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_start
            start_resp = client.post("/clarify/start", json={"query": "FastAPI vs Flask"})
            sid = start_resp.json()["session_id"]
            session_manager._sessions[sid].scene = "solo"
            session_manager._sessions[sid].complexity = "simple"
            session_manager._sessions[sid].candidate_techs = ["FastAPI", "Flask"]
            session_manager._sessions[sid].filled_required = ["candidate_techs", "scene", "complexity"]
            session_manager._sessions[sid].missing_required = []

        with patch.object(clarify_agent, "_handle_finalize", new_callable=AsyncMock) as mock_fin:
            mock_fin.return_value = mock_finalize
            resp = client.post(f"/clarify/{sid}/finalize")

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "finalize"
        assert "sub_questions" in data["payload"]


class TestActualClarificationInput:
    def test_pending_reply_reaches_model_and_selected_task(self):
        original = "Need to compare routing libraries for restart recovery"
        reply = "Compare Zephyr and Sable for personal use, no additional server"
        sid = None
        try:
            with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
                model.side_effect = [
                    {"action": "ask", "message": "Which candidates and deployment scope?",
                     "candidate_techs": ["Zephyr", "Sable"]},
                    {"action": "ask", "message": "Ready to confirm",
                     "candidate_techs": ["Zephyr", "Sable"], "scene": "solo",
                     "complexity": "simple", "constraints": ["no additional server"]},
                    {"sub_questions": ["What changes after restart?"]},
                ]
                start = client.post("/clarify/start", json={"query": original})
                assert start.status_code == 200
                sid = start.json()["session_id"]
                assert session_manager.get(sid).candidate_techs == []
                response = client.post(f"/clarify/{sid}/message", json={"message": reply})
                assert response.status_code == 200
                prompts = [call.args[0][0]["content"] for call in model.await_args_list]
                assert original in prompts[0] and prompts[0].count(original) == 1
                assert original in prompts[1] and reply in prompts[1]
                assert "Which candidates and deployment scope?" in prompts[1]
                finalized = client.post(f"/clarify/{sid}/finalize")
                assert finalized.status_code == 200
                task = finalized.json()["payload"]["clarified_task"]
                assert task["query"] == original and task["candidate_techs"] == ["Zephyr", "Sable"]
                assert task["scene_context"] == "solo" and task["constraints"] == ["no additional server"]
                assert model.await_count == 3
        finally:
            if sid is not None:
                session_manager._sessions.pop(sid, None)

    def test_original_request_limit_is_consistent_at_api_and_session(self):
        sid = None
        try:
            with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
                model.return_value = {"message": "Please describe your requirements", "action": "ask"}
                query = "x" * 4000
                response = client.post("/clarify/start", json={"query": query})
                assert response.status_code == 200
                sid = response.json()["session_id"]
                assert session_manager.get(sid).messages[0]["content"] == query
                assert query in model.await_args.args[0][0]["content"]
                rejected = client.post("/clarify/start", json={"query": query + "x"})
                assert rejected.status_code == 422 and model.await_count == 1
        finally:
            if sid is not None:
                session_manager._sessions.pop(sid, None)


class TestActualLastRoundConfirmation:
    def test_third_reply_is_extracted_before_defaults_and_reaches_child_questions(self):
        original = "Need a routing library for restart recovery"
        reply = "Compare Zephyr and Sable for enterprise use with complex processing; no new server"
        sid = None
        try:
            with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
                model.side_effect = [
                    {"action": "ask", "message": "What is the scope and complexity?"},
                    {"action": "confirm", "message": "Confirm the enterprise recovery requirement",
                     "scene": "enterprise", "complexity": "complex",
                     "candidate_techs": ["Zephyr", "Sable"], "constraints": ["no new server"]},
                    {"sub_questions": ["How is restart recovery preserved without a new server?"]},
                ]
                start = client.post("/clarify/start", json={"query": original})
                assert start.status_code == 200
                sid = start.json()["session_id"]
                session_manager.get(sid).clarify_rounds = 2
                response = client.post(f"/clarify/{sid}/message", json={"message": reply})
                assert response.status_code == 200 and response.json()["next_action"] == "confirm"
                assert response.json()["clarify_rounds"] == 3
                state = session_manager.get(sid)
                assert state.scene == "enterprise" and state.complexity == "complex"
                assert state.candidate_techs == ["Zephyr", "Sable"] and state.constraints == ["no new server"]
                assert "推测" not in response.json()["answer"]
                confirmation_prompt = model.await_args_list[1].args[0][0]["content"]
                assert original in confirmation_prompt and reply in confirmation_prompt
                assert "What is the scope and complexity?" in confirmation_prompt
                assert "业务/落地场景：未知" in confirmation_prompt
                finalized = client.post(f"/clarify/{sid}/finalize")
                assert finalized.status_code == 200
                task = finalized.json()["payload"]["clarified_task"]
                assert task["query"] == original and task["scene_context"] == "enterprise"
                assert task["complexity"] == "complex" and task["constraints"] == ["no new server"]
                child_prompt = model.await_args_list[2].args[0][0]["content"]
                assert original in child_prompt and "no new server" in child_prompt
                assert model.await_count == 3
        finally:
            if sid is not None:
                session_manager._sessions.pop(sid, None)
