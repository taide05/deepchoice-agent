import pytest

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
                assert start.json()["answer"] in prompts[1]
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
                assert start.json()["answer"] in confirmation_prompt
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


class TestActualStaticCandidateBoundary:
    def test_unknown_category_then_user_category_keeps_fields_and_offers_only_names(self):
        sid = None
        try:
            with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
                model.side_effect = [
                    {"action": "recommend", "scene": "solo", "constraints": ["No new server"]},
                    {"action": "recommend", "message": "These are best", "candidate_techs": ["React", "Vue"]},
                ]
                start = client.post("/clarify/start", json={"query": "Need rapid explain happy"})
                assert start.status_code == 200 and start.json()["next_action"] == "ask"
                assert start.json()["payload"] == {"reason": "category_unknown"}
                sid = start.json()["session_id"]
                response = client.post(f"/clarify/{sid}/message", json={"message": "我想做个网站"})
                assert response.status_code == 200 and response.json()["next_action"] == "recommend"
                cards = response.json()["payload"]["candidates"]
                assert [card["name"] for card in cards] == ["React", "Vue", "Angular", "Svelte", "SolidJS"]
                assert all(set(card) == {"name"} for card in cards)
                state = session_manager.get(sid)
                assert state.scene == "solo" and state.constraints == ["No new server"]
                assert state.candidate_techs == [] and model.await_count == 2
        finally:
            if sid is not None:
                session_manager._sessions.pop(sid, None)


@pytest.mark.parametrize("query,scene,complexity,expected", [
    ("Compare Atlas and Borealis for a solo simple project", "solo", "simple", "confirm"),
    ("Compare Atlas and Borealis for a 网站", "team", "medium", "confirm"),
    ("Compare Atlas and Borealis for a 网站", None, None, "ask"),
])
def test_extracted_user_candidates_take_priority_over_static_examples(query, scene, complexity, expected):
    sid = None
    try:
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
            model.return_value = {"action": "confirm", "message": "Please provide the missing scope",
                                  "candidate_techs": ["Atlas", "Borealis"], "scene": scene, "complexity": complexity}
            response = client.post("/clarify/start", json={"query": query})
            assert response.status_code == 200 and response.json()["next_action"] == expected
            sid = response.json()["session_id"]
            payload = response.json().get("payload", {})
            assert "candidates" not in payload and payload.get("reason") != "category_unknown"
            assert session_manager.get(sid).candidate_techs == ["Atlas", "Borealis"]
            if expected == "confirm":
                assert response.json()["answer"] == "需求已整理完毕，确认后开始研究。"
                assert payload["reason"] == "requirements_complete"
                assert payload["clarified_task"]["candidate_techs"] == ["Atlas", "Borealis"]
                assert payload["clarified_task"]["scene_context"] == scene
                assert payload["clarified_task"]["complexity"] == complexity
            assert model.await_count == 1
    finally:
        if sid is not None:
            session_manager._sessions.pop(sid, None)


@pytest.mark.parametrize("model_action", ["ask", "recommend", "confirm"])
def test_named_candidate_ask_can_complete_with_one_call_and_a_queryable_confirmation(model_action):
    sid = None
    query = "Evaluate FastAPI for a personal project with simple processing; No new server"
    try:
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
            model.return_value = {"action": model_action, "message": "Please tell me the scope",
                                  "scene": "solo", "complexity": "simple", "constraints": ["No new server"]}
            response = client.post("/clarify/start", json={"query": query})
            assert response.status_code == 200 and response.json()["next_action"] == "confirm"
            sid = response.json()["session_id"]
            data = response.json()
            assert data["answer"] == "需求已整理完毕，确认后开始研究。"
            assert data["payload"]["reason"] == "requirements_complete"
            task = data["payload"]["clarified_task"]
            assert task["query"] == query and task["candidate_techs"] == ["fastapi"]
            assert task["scene_context"] == "solo" and task["complexity"] == "simple"
            assert task["constraints"] == ["No new server"]
            assert session_manager.get(sid).clarified_task == task
            status = client.get(f"/clarify/{sid}/status")
            assert status.status_code == 200 and status.json()["status"] == "ready"
            assert model.await_count == 1
    finally:
        if sid is not None:
            session_manager._sessions.pop(sid, None)


@pytest.mark.parametrize("model_result", [
    {"action": "confirm", "scene": "solo", "message": "Everything is complete"},
    {"action": "confirm", "scene": "solo", "complexity": "invalid", "constraints": ["must not commit"]},
    RuntimeError("provider error"),
])
def test_named_candidate_ask_keeps_partial_or_failed_extraction_out_of_confirmation(model_result):
    sid = None
    try:
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as model:
            if isinstance(model_result, Exception):
                model.side_effect = model_result
            else:
                model.return_value = model_result
            response = client.post("/clarify/start", json={"query": "Evaluate FastAPI for personal use"})
            assert response.status_code == 200 and response.json()["next_action"] == "ask"
            sid = response.json()["session_id"]
            state = session_manager.get(sid)
            assert state.clarified_task is None and "payload" not in response.json()
            assert state.complexity is None and state.constraints == []
            status = client.get(f"/clarify/{sid}/status")
            assert status.status_code == 200 and status.json()["status"] == "clarifying"
            expected_scene = "solo" if isinstance(model_result, dict) and "complexity" not in model_result else None
            assert state.scene == expected_scene and model.await_count == 1
    finally:
        if sid is not None:
            session_manager._sessions.pop(sid, None)
