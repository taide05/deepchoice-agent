from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import o1_pr2a_control as control
from scripts import o1_pr2b_prepare as prepare
from scripts import o1_pr2b_review_pack as review
from scripts import o1_pr2b_round_gate as gate


def _write_collection(root: Path, profile: str) -> Path:
    output = root / "collections" / profile
    output.mkdir(parents=True)
    experiment = f"exp-{profile}"
    metadata = {
        "schema_version": 1,
        "experiment_id": experiment,
        "dataset_hash": review.DATASET_HASH,
        "git_commit": review.EXPECTED_COMMIT,
        "case_denominator": 12,
        "admitted_run_denominator": 12,
        "environment_hash": "e" * 64,
        "core_asset_registry_id": gate.EXPECTED_ASSET,
    }
    (output / "experiment.json").write_text(
        json.dumps(metadata), encoding="utf-8")
    records = []
    for number in range(1, 13):
        case_id = f"P{number:02d}"
        split = "development" if number <= 8 else "holdout"
        report_path = Path(split) / "reports" / f"{case_id}.md"
        snapshot_path = Path(split) / "snapshots" / f"{case_id}.json"
        (output / report_path).parent.mkdir(parents=True, exist_ok=True)
        (output / snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        (output / report_path).write_text(
            f"synthetic report {profile} {case_id}\n", encoding="utf-8")
        (output / snapshot_path).write_text("{}", encoding="utf-8")
        records.append({
            "case_id": case_id,
            "status": "completed",
            "report_path": report_path.as_posix(),
            "snapshot_path": snapshot_path.as_posix(),
            "run_id": f"{profile}-run-{number}",
            "manifest_id": review.EXPECTED_MANIFEST_BY_CASE[case_id],
            "experiment_id": experiment,
            "profile": "serial" if profile.startswith("serial") else "concurrent",
            "requested_concurrency": 1 if profile.startswith("serial") else 12,
            "dataset_hash": review.DATASET_HASH,
            "repetition": int(profile[-1]),
        })
    (output / "runs.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return output


def _complete_review(template: dict, *, finding: bool, independent: bool) -> dict:
    value = dict(template)
    value["review_status"] = "complete"
    value["reviewer_qualification"] = "synthetic-offline-check"
    value["ledger_complete"] = True
    value["claim_occurrences"] = [{
        "occurrence_id": "occ-1",
        "line": 1,
        "atom": "synthetic atom",
        "support": "supported",
        "quality": "eligible",
        "source_refs": ["ref-1"],
        "notes": "synthetic evidence",
    }]
    for field in ("must_answer", "conflict_points"):
        value[field] = [
            {**entry, "score": 2, "notes": "synthetic scoring"}
            for entry in value[field]
        ]
    value["major_errors"] = (
        [{"id": "me-1", "evidence": "synthetic finding"}]
        if finding and not independent else []
    )
    value["disputed_refs"] = []
    value["claimed_improvements"] = []
    if independent:
        value["independent_coverage"] = (
            [{
                "kind": "major_errors",
                "id": "me-1",
                "covered": True,
                "evidence": "independent check",
            }]
            if finding else []
        )
    return value


def _prepare_review(root: Path, repository: Path) -> tuple[Path, Path]:
    serial = _write_collection(root, "serial-r1")
    concurrent = _write_collection(root, "concurrent-r1")
    review_root = root / "review" / "round-1"
    package = review_root / "package"
    mapping = review_root / "mapping.json"
    review.generate(Namespace(
        serial=str(serial),
        concurrent=str(concurrent),
        dataset=str(repository / "benchmarks/product-baseline-v1.json"),
        output=str(package),
        mapping=str(mapping),
        seed=20260919,
    ))
    templates = review.read_json(package / "review-template.json")
    mains = [
        _complete_review(item, finding=index == 0, independent=False)
        for index, item in enumerate(templates)
    ]
    independents = [
        _complete_review(item, finding=index == 0, independent=True)
        for index, item in enumerate(templates)
    ]
    main_path = review_root / "main-review.json"
    independent_path = review_root / "independent-review.json"
    main_path.write_text(json.dumps(mains), encoding="utf-8")
    independent_path.write_text(json.dumps(independents), encoding="utf-8")
    lock = review_root / "review-lock.json"
    review.lock_reviews(Namespace(
        package=str(package),
        main=str(main_path),
        independent=str(independent_path),
        lock=str(lock),
    ))
    joined = review_root / "joined"
    review.join_reviews(Namespace(
        package=str(package),
        mapping=str(mapping),
        lock=str(lock),
        main=str(main_path),
        independent=str(independent_path),
        output=str(joined),
    ))
    return serial, concurrent


def _write_control_evidence(root: Path, profile: str, tool_hashes: dict) -> None:
    destination = root / profile / "control"
    destination.mkdir(parents=True)
    (destination / "profile-control-result.json").write_text(json.dumps({
        "execution_succeeded": True,
        "profile": profile,
        "observed_records": 12,
        "report_count": 12,
        "metrics_complete": True,
        "stop_final_observability_complete": True,
        "active_budget_metrics_complete": True,
        "process_cleanup_unresolved": False,
        "graceful_service_exit": True,
    }), encoding="utf-8")
    (destination / "controller-identity.json").write_text(json.dumps({
        "git_commit": control.EXPECTED_COMMIT,
        "dataset_hash": control.EXPECTED_DATASET,
        "controller_sha256": control.file_hash(
            Path(control.__file__).resolve()),
        "child_sha256": control.file_hash(
            Path(control.__file__).with_name("o1_pr2a_child.py")),
        "pr2_tool_hashes": tool_hashes,
    }), encoding="utf-8")


def test_pr2b_control_chain_is_complete_and_current():
    assert prepare.PR2B_CONTROL_CHAIN == (
        "o1_pr2b_preflight.py",
        "o1_pr2b_prepare.py",
        "o1_pr2a_child.py",
        "o1_pr2a_control.py",
        "o1_pr2b_review_pack.py",
        "o1_pr2b_round_gate.py",
    )


def test_pr2b_blind_review_and_round_gate_reject_tampering(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    tools = repository / "scripts"
    tool_hashes = {
        name: control.file_hash(tools / name)
        for name in prepare.PR2B_CONTROL_CHAIN
    }
    (tmp_path / "environment.json").write_text(json.dumps({
        "notes": {"pr2_tool_hashes": tool_hashes}
    }), encoding="utf-8")
    serial, _ = _prepare_review(tmp_path, repository)
    for profile in ("serial-r1", "concurrent-r1"):
        _write_control_evidence(tmp_path, profile, tool_hashes)

    result = gate.main(tmp_path, repository, 1)
    assert result["passed"] is True
    assert result["completed_report_count"] == 24
    assert result["independent_review_complete"] is True

    (tmp_path / "round-1-gate.json").unlink()
    (tmp_path / "review/round-1/comparison.json").unlink()
    report = serial / "development/reports/P01.md"
    report.write_text("tampered report\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private mapping no longer matches"):
        gate.main(tmp_path, repository, 1)
