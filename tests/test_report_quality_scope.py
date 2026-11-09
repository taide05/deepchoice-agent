"""The A/B/C/D checklist is structural only; it must not be described as quality.

The seventh-run quality review and the updated content protocol both reject
treating the five deterministic keyword/structure checks as a deliverable or
production-ready grade. Historical benchmark numbers stay historical; this test
pins the active code's labels and output scope.
"""
import inspect

from benchmarks import merge_checkpoints, report_quality, run_baseline


def test_report_quality_docstring_does_not_claim_production_readiness():
    source = inspect.getsource(report_quality)
    assert "production-ready report" not in source
    assert "structural" in report_quality.__doc__.lower()
    assert "not a content-quality metric" in report_quality.__doc__.lower()


def test_batch_output_declares_structural_scope():
    stats = report_quality.evaluate_batch([])
    assert stats["metric_scope"] == "structural_checklist_only"
    assert "NOT content quality" in stats["metric_interpretation"]
    assert "grade_a_pct" in stats  # historical key kept for old reports


def test_single_output_declares_structural_scope():
    result = report_quality.evaluate_report("short")
    assert result["metric_scope"] == "structural_checklist_only"


def test_active_benchmark_output_calls_it_a_structural_checklist():
    baseline_source = inspect.getsource(run_baseline)
    merge_source = inspect.getsource(merge_checkpoints)
    assert "Structural checklist A/B % (NOT content quality)" in baseline_source
    assert "Structural checklist A/B % (NOT content quality)" in merge_source
    assert "Report Quality A/B %" not in baseline_source
    assert "Report Quality A/B %" not in merge_source

def test_grade_computation_is_unchanged_for_historical_comparability():
    assert report_quality.grade(5) == "A"
    assert report_quality.grade(4) == "B"
    assert report_quality.grade(3) == "C"
    assert report_quality.grade(2) == "D"
    assert report_quality.grade(0) == "D"
