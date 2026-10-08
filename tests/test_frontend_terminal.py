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


@pytest.mark.parametrize("lang", LABELS)
@pytest.mark.parametrize("status,index", [("failed",0),("timed_out",1),("interrupted",2),(None,3)])
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


@pytest.mark.parametrize("operation", ["start", "resume", "stream", "legacy"])
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
        if operation=="stream":
            monkeypatch.setattr(httpx,"stream",fail)
        else:
            monkeypatch.setattr(httpx,"stream",lambda *a,**kw: _RawStream([
                'event: run.progress', 'data: {"node":"__error__","detail":"'+marker+'"}', ''
            ]))
        at.run()
        assert at.session_state["research_connection_lost"] == (operation=="stream")
    assert not at.exception
    assert marker not in " ".join(str(x.value) for group in (at.error,at.warning,at.markdown) for x in group)


@pytest.mark.parametrize("lang,label", [("zh","取消任务"),("en","Cancel task"),("ja","タスクをキャンセル"),("ko","작업 취소")])
@pytest.mark.parametrize("outcome", ["exception", 409, 200])
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
