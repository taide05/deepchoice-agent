import time

import pytest

from deepchoice.clarify.session_manager import SessionManager


class TestSessionManagerCreate:
    def test_creates_session_with_id(self):
        sm = SessionManager()
        result = sm.create("我想用FastAPI还是Flask")
        assert result["session_id"].startswith("clarify_")
        assert result["status"] == "clarifying"

    def test_tech_mentions_do_not_preselect_candidates(self):
        sm = SessionManager()
        result = sm.create("FastAPI vs Flask 哪个好")
        assert "candidate_techs" not in result["filled_required"]
        assert "candidate_techs" in result["missing_required"]
        assert sm.get(result["session_id"]).unknown_techs is False

    def test_no_tech_keywords_marks_unknown(self):
        sm = SessionManager()
        result = sm.create("我想做个网站")
        assert "candidate_techs" in result["missing_required"]
        state = sm._sessions[result["session_id"]]
        assert state.unknown_techs is True


class TestSessionManagerProcessMessage:
    def test_increments_round_on_message(self):
        sm = SessionManager()
        result = sm.create("测试问题")
        sid = result["session_id"]
        sm.process_message(sid, "我想比较技术")
        state = sm._sessions[sid]
        assert state.clarify_rounds == 1

    def test_raises_on_unknown_session(self):
        sm = SessionManager()
        with pytest.raises(KeyError):
            sm.process_message("nonexistent", "hello")


class TestSessionManagerFinalize:
    def test_skip_keeps_unknown_requirements(self):
        sm = SessionManager()
        result = sm.create("做个AI应用")
        sid = result["session_id"]
        sm.finalize(sid)
        state = sm._sessions[sid]
        assert state.scene is None
        assert state.complexity is None
        assert state.status == "ready"

    def test_preserves_existing_values_on_finalize(self):
        sm = SessionManager()
        result = sm.create("Flask vs FastAPI for enterprise API")
        sid = result["session_id"]
        state = sm._sessions[sid]
        state.scene = "enterprise"
        state.complexity = "complex"
        state.filled_required = ["candidate_techs", "scene", "complexity"]
        state.missing_required = []
        sm._sessions[sid] = state
        sm.finalize(sid, review_only=True)
        final_state = sm._sessions[sid]
        assert final_state.scene == "enterprise"
        assert final_state.complexity == "complex"


class TestSessionManagerTimeout:
    def test_expired_session_raises(self):
        sm = SessionManager()
        sm.SESSION_TIMEOUT = 0
        result = sm.create("test")
        sid = result["session_id"]
        time.sleep(0.1)
        with pytest.raises(KeyError):
            sm.get_status(sid)


@pytest.mark.parametrize("length", [2001, 4000])
def test_original_request_uses_full_entry_limit_but_replies_remain_bounded(length):
    sm = SessionManager()
    query = "x" * length
    sid = sm.create(query)["session_id"]
    state = sm.get(sid)
    assert state.messages[0]["content"] == query
    before = state.model_dump()
    with pytest.raises(ValueError):
        sm.process_message(sid, "y" * 2001)
    assert state.model_dump() == before
    sm.process_message(sid, "y" * 2000)
    assert len(state.messages[-1]["content"]) == 2000


def test_original_request_over_limit_rejected_without_creating_session():
    sm = SessionManager()
    with pytest.raises(ValueError):
        sm.create("x" * 4001)
    assert sm._sessions == {}
