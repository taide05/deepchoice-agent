"""Offline preparation tests for the final batch dataset and aggregator."""
import json
from pathlib import Path

import pytest

from benchmarks import final_batch
from benchmarks import prepare_final_batch

ROOT = Path(__file__).resolve().parent.parent


def test_draft_dataset_counts_layers_and_isolation():
    dataset, digest = final_batch.load_batch_dataset(
        ROOT / "benchmarks" / "final-batch-v1.json")
    assert len(dataset["cases"]) == 120
    assert len(dataset["calibration"]["cases"]) == 12
    assert not dataset["eval_ready"]
    assert digest
    assert set(dataset["cases"][0]) >= {"id", "layer", "request", "rubric",
                                       "reference_basis", "hitl"}
    final_ids = {case["id"] for case in dataset["cases"]}
    cal_ids = {case["id"] for case in dataset["calibration"]["cases"]}
    assert final_ids.isdisjoint(cal_ids)
    pairs = {final_batch._pair_key(case) for case in dataset["cases"]}
    cal_pairs = {final_batch._pair_key(case) for case in dataset["calibration"]["cases"]}
    assert pairs.isdisjoint(cal_pairs)


def test_draft_dataset_is_refused_for_paid_collection():
    with pytest.raises(ValueError, match="non-ready|not admitted"):
        final_batch.load_batch_dataset(ROOT / "benchmarks" / "final-batch-v1.json",
                                       require_admitted=True)


def test_resume_skips_terminal_cases_and_preserves_failures():
    dataset, _ = final_batch.load_batch_dataset(
        ROOT / "benchmarks" / "final-batch-v1.json")
    case_id = dataset["cases"][0]["id"]
    failed = dataset["cases"][1]["id"]
    plan = final_batch.resume_plan(dataset, [
        {"case_id": case_id, "status": "completed", "task_id": "t1",
         "report_path": "final/reports/a.md"},
        {"case_id": failed, "status": "failed", "task_id": "t2"},
        {"case_id": failed, "status": "failed", "task_id": "t2"},
    ])
    assert case_id in plan["terminal_already_present"]
    assert failed in plan["terminal_already_present"]
    assert len(plan["remaining"]) == 118


def test_summarize_reports_nsre_failures_tokens_and_unknown_cost(tmp_path):
    dataset, _ = final_batch.load_batch_dataset(
        ROOT / "benchmarks" / "final-batch-v1.json")
    cases = dataset["cases"][:2]
    records = []
    for index, case in enumerate(cases):
        records.append({
            "case_id": case["id"], "profile": "candidate", "task_id": f"t{index}",
            "run_id": f"r{index}", "status": "completed" if index == 0 else "failed",
            "report_path": "final/reports/a.md" if index == 0 else None,
            "wall_time_ms": 1000 + index,
            "usage": {"total_tokens": 10 + index, "token_usage_complete": True},
        })
    records.append({
        "case_id": cases[1]["id"], "profile": "baseline", "task_id": "tb",
        "run_id": "rb", "status": "failed", "report_path": None,
        "wall_time_ms": None, "usage": {},
    })
    out = tmp_path / "batch"
    out.mkdir()
    (out / "runs.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    (out / "reviews.csv").write_text(
        "case_id,arm,reviewer,review_status,usable,major_errors,evidence_notes\n"
        f"{cases[0]['id']},candidate,r1,completed,true,0,ok\n",
        encoding="utf-8")
    summary = final_batch.summarize(dataset, out)
    candidate = summary["by_arm"]["candidate"]
    assert candidate["N"] == 120
    assert candidate["S"] == 2
    assert candidate["R"] == 1
    assert candidate["E"] == 1
    assert candidate["usable_rate_E"] == 1.0
    assert candidate["cost"] == "unknown"
    assert candidate["known_total_tokens"] == 21
    assert candidate["token_complete_runs"] == 2
    assert candidate["failures_preserved"] == {"failed": 1}
    assert summary["by_arm"]["baseline"]["S"] == 1
    assert summary["by_arm"]["baseline"]["R"] == 0
    assert (out / "batch-summary.json").exists()
    assert (out / "batch-summary.md").exists()


def test_dataset_content_hash_is_verified(tmp_path):
    source = json.loads((ROOT / "benchmarks" / "final-batch-v1.json").read_text(
        encoding="utf-8"))
    source["description"] = "tampered"
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="content_sha256"):
        final_batch.load_batch_dataset(target)


def test_uncertain_admission_is_not_redispatched():
    dataset, _ = final_batch.load_batch_dataset(
        ROOT / "benchmarks" / "final-batch-v1.json")
    case_id = dataset["cases"][0]["id"]
    plan = final_batch.resume_plan(
        dataset, [], [{"case_id": case_id, "event": "submission_started"}])
    assert case_id in plan["admitted_unsettled"]
    assert case_id not in plan["remaining"]


def test_review_validation_rejects_bad_values(tmp_path):
    dataset, _ = final_batch.load_batch_dataset(
        ROOT / "benchmarks" / "final-batch-v1.json")
    out = tmp_path / "batch"
    out.mkdir()
    case_id = dataset["cases"][0]["id"]
    (out / "runs.jsonl").write_text(
        json.dumps({"case_id": case_id, "profile": "candidate",
                    "task_id": "t", "report_path": "r", "status": "completed"}) + "\n",
        encoding="utf-8")
    bad = out / "bad-reviews.csv"
    bad.write_text(
        "case_id,arm,reviewer,review_status,usable,major_errors,evidence_notes\n"
        f"{case_id},candidate,r,completed,true,-1,note\n", encoding="utf-8")
    with pytest.raises(ValueError, match="negative major_errors"):
        final_batch.summarize(dataset, out, bad)
    bad.write_text(
        "case_id,arm,reviewer,review_status,usable,major_errors,evidence_notes\n"
        f"{case_id},candidate,r,completed,maybe,0,note\n", encoding="utf-8")
    with pytest.raises(ValueError, match="usable must be"):
        final_batch.summarize(dataset, out, bad)


def test_prepare_is_deterministic():
    first = prepare_final_batch.build()
    second = prepare_final_batch.build()
    assert first["content_sha256"] == second["content_sha256"]
    assert first["cases"] == second["cases"]
    assert first["calibration"]["cases"] == second["calibration"]["cases"]
