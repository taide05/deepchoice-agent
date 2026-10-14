"""Actual Streamlit terminal/recovery UI; all HTTP calls are test doubles."""
import httpx
import pytest
from streamlit.testing.v1 import AppTest
from tests.test_frontend_obs import APP_PATH, _enter_research_phase, _FakeResp, _RawStream

LABELS = {
    "en": ("Research failed", "Research timed out", "Research was interrupted", "Research outcome is unconfirmed", "Retry research", "Attempt recovery", "Reconnect"),
    "zh": ("研究失败", "研究超时", "研究已中断", "研究结果尚未确认", "重试研究", "尝试恢复", "重新连接"),
    "ja": ("調査に失敗しました", "調査がタイムアウトしました", "調査が中断されました", "調査結果を確認できません", "調査を再試行", "復旧を試みる", "再接続"),
    "ko": ("연구 실패", "연구 시간 초과", "연구가 중단되었습니다", "연구 결과가 확인되지 않았습니다", "연구 재시도", "복구 시도", "다시 연결"),
}


def prepare(monkeypatch, status, lang="en"):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected HTTP call")
    for name in ("get", "post", "stream"):
        monkeypatch.setattr(httpx, name, forbidden)
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    _enter_research_phase(at)
    at.session_state["lang"] = lang
    at.session_state["research_running"] = False
    at.session_state["research_failed"] = status != "connection_lost"
    at.session_state["research_connection_lost"] = status == "connection_lost"
    at.session_state["research_terminal_status"] = status if status in {"failed", "timed_out", "interrupted"} else None
    at.session_state["research_task_version"] = 7
    return at


# Status transitions and translation lookup are independent dimensions.
@pytest.mark.parametrize("lang,status,index", [
    ("en", "failed", 0), ("en", "timed_out", 1), ("en", "interrupted", 2), ("en", None, 3),
    ("zh", "failed", 0), ("ja", "failed", 0), ("ko", "failed", 0),
])
def test_terminal_projection_and_action_are_localized(monkeypatch, lang, status, index):
    at = prepare(monkeypatch, status, lang).run()
    assert not at.exception
    messages = at.error if index < 2 else at.warning
    assert any(LABELS[lang][index] in x.value for x in messages)
    assert not any("connection" in x.value.lower() for x in at.error)
    buttons = {x.key:x.label for x in at.button}
    if status:
        assert buttons["resume_durable_task"] == LABELS[lang][5 if status == "interrupted" else 4]
    else:
        assert "resume_durable_task" not in buttons
    assert "reconnect_durable_task" not in buttons


@pytest.mark.parametrize("lang", LABELS)
def test_connection_loss_retains_separate_reconnect(monkeypatch, lang):
    at = prepare(monkeypatch, "connection_lost", lang).run()
    assert not at.exception
    assert at.warning and not at.error
    assert at.button(key="reconnect_durable_task").label == LABELS[lang][6]
    assert "resume_durable_task" not in {x.key for x in at.button}


@pytest.mark.parametrize("status", ["failed", "timed_out", "interrupted"])
def test_resume_keeps_endpoint_cas_and_accepts_server_new_run(monkeypatch, status):
    at = prepare(monkeypatch, status).run()
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResp({"task":{"task_id":"t1","version":8,"status":"queued","latest_run_id":"new-run"}},202)
    monkeypatch.setattr(httpx,"post",post)
    monkeypatch.setattr(httpx,"stream",lambda *a,**kw: _RawStream([]))
    monkeypatch.setattr(httpx,"get",lambda *a,**kw: _FakeResp({"task":{"task_id":"t1","version":9,"status":"interrupted"}}))
    at.button(key="resume_durable_task").click().run()
    assert not at.exception
    assert len(calls)==1 and calls[0][0].endswith("/api/v1/tasks/t1/resume")
    assert calls[0][1]["headers"] == {"If-Match":"7"}
    assert at.session_state["research_task_version"] == 9
    assert at.session_state["research_terminal_status"] == "interrupted"


@pytest.mark.parametrize("operation", ["start", "resume", "stream"])
def test_request_failures_do_not_expose_private_details_or_resubmit(monkeypatch, operation):
    at = prepare(monkeypatch, "failed")
    marker="PRIVATE_SECRET_SENTINEL"
    calls=[]
    def fail(*a,**kw):
        calls.append(a)
        raise RuntimeError(marker)
    if operation=="start":
        at.session_state["research_started"]=False
        at.session_state["research_task_id"]=None
        at.session_state["research_terminal_status"]=None
        monkeypatch.setattr(httpx,"post",fail)
        at.run()
        assert marker not in " ".join(str(x.value) for x in at.error)
        at.run()
        assert len(calls)==1
        assert "resume_durable_task" not in {x.key for x in at.button}
    elif operation=="resume":
        at.run()
        monkeypatch.setattr(httpx,"post",fail)
        at.button(key="resume_durable_task").click().run()
        assert len(calls)==1
        assert at.session_state["research_terminal_status"]=="failed"
    else:
        at.session_state["research_failed"]=False
        at.session_state["research_running"]=True
        at.session_state["research_terminal_status"]=None
        monkeypatch.setattr(httpx,"stream",fail)
        at.run()
        assert at.session_state["research_connection_lost"] == (operation=="stream")
    assert not at.exception
    assert marker not in " ".join(str(x.value) for group in (at.error,at.warning,at.markdown) for x in group)


@pytest.mark.parametrize("lang,label,outcome", [
    ("en", "Cancel task", "exception"), ("en", "Cancel task", 409), ("en", "Cancel task", 200),
    ("zh", "取消任务", 200), ("ja", "タスクをキャンセル", 200), ("ko", "작업 취소", 200),
])
def test_cancel_preserves_cas_and_never_projects_unconfirmed_cancellation(monkeypatch, lang, label, outcome):
    at=prepare(monkeypatch,"connection_lost",lang)
    at.session_state["research_running"]=True
    at.session_state["research_connection_lost"]=False
    def offline(*a,**kw):
        raise RuntimeError("PRIVATE_CANCEL_SENTINEL")
    monkeypatch.setattr(httpx,"stream",offline)
    at.run()
    assert at.button(key="cancel_durable_task").label == label
    calls=[]
    def post(url,**kw):
        calls.append((url,kw))
        if outcome=="exception":
            raise RuntimeError("PRIVATE_CANCEL_SENTINEL")
        return _FakeResp({"task":{"task_id":"t1","status":"cancelled","version":8}},outcome)
    monkeypatch.setattr(httpx,"post",post)
    at.session_state["research_running"]=True
    at.button(key="cancel_durable_task").click().run()
    assert not at.exception
    assert len(calls)==1 and calls[0][0].endswith("/api/v1/tasks/t1/cancel")
    assert calls[0][1]["headers"]=={"If-Match":"7"}
    assert "PRIVATE_CANCEL_SENTINEL" not in " ".join(str(x.value) for g in (at.error,at.warning) for x in g)
    assert (at.session_state["research_terminal_status"]=="cancelled") == (outcome==200)
    if outcome==200:
        assert at.session_state["research_task_version"]==8
    else:
        assert at.error


# Each entry point preserves its own state; shared parsing failures need one entry.
@pytest.mark.parametrize("operation,outcome", [
    ("start", "timeout"), ("message", "timeout"), ("skip", "timeout"), ("finalize", "timeout"),
    ("message", "json"), ("message", "shape"), ("message", "http"),
    ("message", "reason"), ("message", "duplicates"),
    ("skip", "nested"), ("finalize", "nested"),
])
def test_clarification_failure_is_atomic_visible_and_never_replayed(monkeypatch, operation, outcome):
    import copy
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.session_state["lang"] = "en"
    original = [{"role": "assistant", "content": "Review the current request", "action": "confirm",
                 "payload": {"clarify_rounds": 2, "clarified_task": {
                     "query": "Current request", "constraints": ["Offline"], "candidate_techs": ["Acme"]}}}]
    if operation != "start":
        at.session_state["clarify_session_id"] = "clarify_test"
        at.session_state["clarify_messages"] = copy.deepcopy(original)
    at.run()
    calls = []
    marker = "PRIVATE_CLARIFY_SENTINEL"
    def post(url, **kwargs):
        calls.append((url, kwargs))
        if outcome == "timeout":
            raise httpx.ReadTimeout(marker)
        if outcome == "http":
            return _FakeResp({"detail": marker}, 500)
        if outcome == "json":
            class BadJson:
                status_code = 200
                def json(self):
                    raise ValueError(marker)
            return BadJson()
        if outcome == "shape":
            return _FakeResp({"session_id": "clarify_test"})
        if outcome in {"reason", "duplicates"}:
            return _FakeResp({"session_id": "clarify_test", "answer": "Reply", "action": "recommend",
                              "payload": {"reason": []} if outcome == "reason" else {
                                  "candidates": [{"name": "Acme"}, {"name": "Acme"}]}})
        return _FakeResp({"session_id": "clarify_test", "answer": "Review",
                          "action": "finalize" if operation == "finalize" else "confirm",
                          "payload": {"clarify_rounds": 2, "clarified_task": {"query": "New", "constraints": None}}})
    monkeypatch.setattr(httpx, "post", post)
    if operation in {"start", "message"}:
        at.chat_input(key="hero_chat" if operation == "start" else "clarify_chat").set_value("Retain this correction").run()
    elif operation == "skip":
        at.button(key="clarify_skip_btn").click().run()
    else:
        next(button for button in at.button if button.proto.type == "primary").click().run()
    assert not at.exception
    assert at.error
    assert marker not in " ".join(str(x.value) for group in (at.error, at.warning, at.markdown, at.text) for x in group)
    assert at.session_state["clarify_error"] is True
    assert at.session_state["phase"] == "clarify"
    assert at.session_state["clarified_data"] is None
    assert at.session_state["clarify_session_id"] == (None if operation == "start" else "clarify_test")
    assert at.session_state["clarify_messages"] == ([] if operation == "start" else original)
    if operation in {"start", "message"}:
        assert "Retain this correction" in " ".join(x.value for x in at.text)
        assert not any(button.proto.type == "primary" for button in at.button)
    at.run()
    assert not at.exception and len(calls) == 1
    if operation == "skip":
        assert calls[0][1]["json"] == {"review_only": True}
    if operation == "finalize":
        assert calls[0][1]["json"] == {"clarify_rounds": 2}


@pytest.mark.parametrize("lang,expected", [
    ("zh", "请求结果尚未确认"), ("en", "Request outcome is unconfirmed"),
    ("ja", "リクエストの結果を確認できません"), ("ko", "요청 결과가 확인되지 않았습니다"),
])
def test_clarification_error_is_visible_on_welcome_in_each_language(monkeypatch, lang, expected):
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.session_state["lang"] = lang
    at.run()
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout("PRIVATE_CLARIFY_SENTINEL")
    monkeypatch.setattr(httpx, "post", fail)
    at.chat_input(key="hero_chat").set_value("Keep original input").run()
    assert not at.exception and any(expected in x.value for x in at.error)
    assert "Keep original input" in " ".join(x.value for x in at.text)


@pytest.mark.parametrize("resolution", ["resend", "discard"])
def test_pending_correction_survives_old_server_confirmation(monkeypatch, resolution):
    import copy
    task = {"query": "Online allowed", "constraints": [], "candidate_techs": ["Acme"]}
    response = {"answer": "Review", "action": "confirm", "clarify_rounds": 2,
                "payload": {"clarify_rounds": 2, "clarified_task": task}}
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.session_state["clarify_session_id"] = "clarify_test"
    at.session_state["clarify_messages"] = [{"role": "assistant", "content": "Review", "action": "confirm",
                                            "payload": copy.deepcopy(response["payload"])}]
    at.run()
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        if len(calls) == 1:
            raise httpx.ReadTimeout("PRIVATE_CLARIFY_SENTINEL")
        if url.endswith("/message"):
            return _FakeResp({"session_id": "clarify_test", "answer": "Received correction", "next_action": "ask"})
        return _FakeResp(copy.deepcopy(response))
    monkeypatch.setattr(httpx, "post", post)
    at.chat_input(key="clarify_chat").set_value("Must work offline").run()
    assert not at.exception and at.chat_input(key="clarify_chat").disabled
    at.button(key="clarify_skip_btn").click().run()
    assert not at.exception and len(calls) == 2
    assert at.session_state["clarify_pending_input"] == "Must work offline"
    assert "Online allowed" in " ".join(x.value for x in at.text)
    assert "Must work offline" in " ".join(x.value for x in at.text)
    assert not any(button.proto.type == "primary" for button in at.button)
    at.run()
    assert len(calls) == 2
    at.button(key="clarify_" + resolution).click().run()
    assert not at.exception and at.session_state["clarify_pending_input"] is None
    assert not at.session_state["clarify_error"]
    assert not at.chat_input(key="clarify_chat").disabled
    if resolution == "resend":
        assert len(calls) == 3 and calls[-1][1] == {"message": "Must work offline"}
        assert at.session_state["clarify_messages"][-2] == {"role": "user", "content": "Must work offline"}
    else:
        assert len(calls) == 2
        assert any(button.proto.type == "primary" for button in at.button)
    assert at.session_state["phase"] == "clarify"


def test_valid_clarification_finalize_keeps_durable_request_and_revision(monkeypatch):
    task = {"query": "Compare Acme and Beta offline", "constraints": ["No external writes"],
            "candidate_techs": ["Acme", "Beta"], "scene_context": None, "complexity": None}
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.session_state["clarify_session_id"] = "clarify_test"
    at.session_state["clarify_messages"] = [{"role": "assistant", "content": "Review", "action": "confirm",
                                            "payload": {"clarify_rounds": 3, "clarified_task": task}}]
    at.run()
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        if url.endswith("/finalize"):
            return _FakeResp({"action": "finalize", "answer": "Confirmed", "payload": {
                "clarified_task": task, "sub_questions": []}})
        assert url.endswith("/api/v1/tasks")
        # Stop the downstream fake transport after proving the exact request handoff.
        return _FakeResp({}, 503)
    monkeypatch.setattr(httpx, "post", post)
    next(button for button in at.button if button.proto.type == "primary").click().run()
    assert not at.exception and at.session_state["phase"] == "research"
    assert not at.session_state["clarify_error"]
    assert at.session_state["clarified_data"] == {"clarified_task": task, "sub_questions": []}
    assert calls[0][1] == {"clarify_rounds": 3}
    assert calls[1][1] == {**task, "sub_questions": []}
    at.run()
    assert not at.exception and len(calls) == 2
