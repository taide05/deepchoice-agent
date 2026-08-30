"""Run baseline strip helper: persist final_recommendation without heavy state."""
from benchmarks.run_baseline import _strip_run


def test_strip_run_keeps_final_recommendation_and_drops_state():
    run = {
        "case_id": "TC-0001",
        "query": "q",
        "state": {"final_recommendation": {"winner": "X"}, "heavy": "data"},
        "report": "r",
        "error": None,
        "elapsed_s": 1.0,
        "search_results": [],
        "conflicts": [],
        "retry_count": 0,
        "confidence": "high",
        "knowledge_gaps": [],
        "agent_timing": {},
        "final_recommendation": {"winner": "X"},
    }
    out = _strip_run(run)
    assert out["final_recommendation"] == {"winner": "X"}
    assert "state" not in out


def test_strip_run_handles_missing_fields():
    run = {"case_id": "TC-0002", "query": "q"}
    out = _strip_run(run)
    assert out["final_recommendation"] == {}
    assert out["report"] == ""
    assert out["error"] is None
    assert "state" not in out
