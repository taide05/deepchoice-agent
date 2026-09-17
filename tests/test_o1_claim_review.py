"""Offline regression checks for the manually reviewed O1-A denominators."""
from copy import deepcopy
import hashlib

import pytest

from benchmarks.o1_claim_review import REPORTS, audit, load_review, verify_local


@pytest.fixture
def review():
    return deepcopy(load_review())


def test_recorded_review_has_complete_separate_denominators(review):
    result = audit(*review)
    assert result["aggregate"]["claims"] == 279
    assert result["aggregate"]["supported"] == 79
    assert result["aggregate"]["eligible"] == 8
    assert tuple(result["reports"]) == REPORTS
    assert result["aggregate"]["citation_micro"] != result["aggregate"]["citation_macro"]
    assert result["overall_o1"] == "incomplete"
    assert result["human_calibration"] == "not_run"
    assert result["measured_source_health"] == "degraded"
    assert result["current_source_health"] == "not_run"
    assert result["dataset_hash"] == review[2]["dataset_hash"]
    assert result["measured_candidate_commit"] == review[2]["measured_candidate_commit"]
    assert result["reports"]["P01-r1"]["manifest_id"] == review[2]["rows"][0]["manifest_id"]
    for row in result["reports"].values():
        assert sum(row["support_counts"].values()) == row["claims"]
        assert sum(row["quality_counts"].values()) == row["claims"]


@pytest.mark.parametrize("change", [
    "dataset", "run", "holdout", "duplicate", "order", "support", "quality",
    "citation", "basis", "issue", "uncited", "eligible_partial", "missing_atom", "empty_report",
])
def test_invalid_or_incomplete_review_fails_closed(review, change):
    contract, claims, bindings = review
    if change == "dataset":
        contract["dataset_hash"] = "different"
    elif change == "run":
        contract["reports"]["P01-r1"]["run_id"] = "different"
    elif change == "holdout":
        claims[0]["report"] = "P09-r1"
    elif change == "duplicate":
        claims.insert(1, deepcopy(claims[0]))
    elif change == "order":
        claims.reverse()
    elif change in {"support", "quality", "basis", "issue"}:
        claims[0][change] = "invalid"
    elif change == "citation":
        claims[0]["citations"] = "SQ;NOT_FOUND"
    elif change == "uncited":
        claims[0]["support"] = "uncited"
    elif change == "eligible_partial":
        claims[0]["support"], claims[0]["quality"] = "partial", "eligible"
    elif change == "missing_atom":
        claims.pop(3)
    else:
        claims[:] = [r for r in claims if r["report"] != "P01-r1"]
    with pytest.raises(ValueError):
        audit(contract, claims, bindings)


def test_unknown_and_uncited_are_kept_in_denominator(review):
    result = audit(*review)["reports"]["P01-r1"]
    assert result["support_counts"]["unknown"] == 9
    assert result["support_counts"]["uncited"] == 6
    assert result["citation_support_rate"] == 24 / 54


@pytest.mark.parametrize("path", ["../outside.md", "/outside.md", "outputs/holdout/reports/P01.md"])
def test_local_verification_rejects_unsafe_paths_before_reading(tmp_path, review, path):
    contract, claims, bindings = review
    bindings["rows"][0]["report_path"] = path
    with pytest.raises(ValueError):
        verify_local(tmp_path, bindings, claims, contract)


def test_local_verification_checks_original_and_citation_occurrence(tmp_path, review):
    contract, _, bindings = review
    bindings["rows"] = bindings["rows"][:1]
    path = tmp_path / bindings["rows"][0]["report_path"]
    path.parent.mkdir(parents=True)
    path.write_text("[Source: sqlite-vs-postgresql]\n", encoding="utf-8")
    snapshot = path.parent.parent / "snapshots/P01.json"
    snapshot.parent.mkdir()
    snapshot.write_text("{}", encoding="utf-8")
    for file, field in ((path, "report_sha256"), (snapshot, "snapshot_sha256")):
        bindings["rows"][0][field] = hashlib.sha256(file.read_bytes()).hexdigest()
    claims = [{"report": "P01-r1", "line": "1", "citations": "SQ"}]
    verify_local(tmp_path, bindings, claims, contract)
    claims[0]["citations"] = "TB"
    with pytest.raises(ValueError, match="citation absent"):
        verify_local(tmp_path, bindings, claims, contract)
    claims[0]["citations"] = "SQ"
    snapshot.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_local(tmp_path, bindings, claims, contract)
