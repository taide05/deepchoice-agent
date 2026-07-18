import time
import pytest
from deepchoice.clarify.session_manager import SessionManager, SessionState


class TestSessionManagerCreate:
    def test_creates_session_with_id(self):
        sm = SessionManager()
        result = sm.create("我想用FastAPI还是Flask")
        assert result["session_id"].startswith("clarify_")
        assert result["status"] == "clarifying"

    def test_detects_tech_keywords_in_query(self):
        sm = SessionManager()
        result = sm.create("FastAPI vs Flask 哪个好")
        assert "candidate_techs" in result["filled_required"]
        assert "candidate_techs" not in result["missing_required"]

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
    def test_applies_soft_gate_defaults(self):
        sm = SessionManager()
        result = sm.create("做个AI应用")
        sid = result["session_id"]
        sm.finalize(sid)
        state = sm._sessions[sid]
        assert state.scene == "team"
        assert state.complexity == "medium"
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
        sm.finalize(sid)
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

    def test_cleanup_removes_expired(self):
        sm = SessionManager()
        sm.SESSION_TIMEOUT = 0
        sm.create("test1")
        sm.create("test2")
        time.sleep(0.1)
        sm._cleanup_expired()
        assert len(sm._sessions) == 0
