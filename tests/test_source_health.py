"""Source-health metric: detects quietly-degraded benchmark runs.

Regression guard for the 300-case recall incident: retrievers that fail to
reach their API must be flagged (source status=failed -> failed_rate high),
never silently scored as empty-success.
"""
from benchmarks.metrics import compute_source_health


def _run_with(statuses: list[tuple[str, str]]) -> dict:
    """Build a run dict with one search_results entry per (source, status)."""
    return {
        "case_id": "TC-0001",
        "search_results": [
            {"source": src, "status": st, "results": []}
            for src, st in statuses
        ],
    }


def test_healthy_run_not_degraded():
    runs = [
        _run_with([("github", "success"), ("arxiv", "success"), ("tavily", "success")]),
        _run_with([("github", "success"), ("arxiv", "success"), ("tavily", "success")]),
    ]
    health = compute_source_health(runs)
    assert health["degraded"] is False
    assert health["degraded_sources"] == []
    assert health["sources"]["github"]["failed_rate"] == 0.0


def test_fully_degraded_source_detected():
    runs = [
        _run_with([("github", "failed"), ("arxiv", "failed"), ("tavily", "success")]),
        _run_with([("github", "failed"), ("arxiv", "failed"), ("tavily", "success")]),
        _run_with([("github", "failed"), ("arxiv", "failed"), ("tavily", "success")]),
        _run_with([("github", "failed"), ("arxiv", "failed"), ("tavily", "success")]),
        _run_with([("github", "failed"), ("arxiv", "failed"), ("tavily", "success")]),
    ]
    health = compute_source_health(runs)
    assert health["degraded"] is True
    assert "github" in health["degraded_sources"]
    assert "arxiv" in health["degraded_sources"]
    assert health["sources"]["github"]["failed_rate"] == 1.0


def test_partial_loss_visible_but_not_degraded():
    """One failure in five is visible in the rate table, below the 0.5 gate."""
    runs = [
        _run_with([("arxiv", "success"), ("tavily", "success")]),
        _run_with([("arxiv", "failed"), ("tavily", "success")]),
        _run_with([("arxiv", "success"), ("tavily", "success")]),
        _run_with([("arxiv", "success"), ("tavily", "success")]),
        _run_with([("arxiv", "success"), ("tavily", "success")]),
    ]
    health = compute_source_health(runs)
    assert health["degraded"] is False
    assert health["sources"]["arxiv"]["failed_rate"] == 0.2


def test_small_samples_not_flagged():
    """Fewer than 5 observations of a source never trips the gate."""
    runs = [_run_with([("github", "failed")])]
    health = compute_source_health(runs)
    assert health["degraded"] is False
