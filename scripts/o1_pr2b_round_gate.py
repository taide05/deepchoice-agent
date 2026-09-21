"""Build one O1-PR2B round gate from locked blind-review evidence."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

EXPECTED_COMMIT = "09f9b66cf114953c09ebe928c1c081667647db16"
EXPECTED_DATASET = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
EXPECTED_ASSET = "15cb66f6602a7f36090c1337f983ecbdbb3c74e77d7c9ca52c6c3c5ba799c850"
EXPECTED_CHECKS = {
    "all_paired_reports_available", "completion_not_lower",
    "decision_mean_drop_at_most_5pp", "citation_mean_drop_at_most_5pp",
    "source_mean_drop_at_most_5pp", "conflict_mean_drop_at_most_10pp",
    "no_new_major_errors", "no_case_decision_drop_over_20pp",
    "at_most_two_case_drops_over_10pp",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(root: Path, frozen_root: Path, round_no: int) -> dict:
    tools = Path(__file__).resolve().parent
    control_module = load_module("o1_pr2_control_gate",
                                  tools / "o1_pr2b_control.py")
    review_module = load_module("o1_pr2_review_gate",
                                 tools / "o1_pr2b_review_pack.py")
    sys.path.insert(0, str(frozen_root))
    from benchmarks import product_baseline as baseline
    from benchmarks import product_baseline_qualification as qualification

    control_module.verify_frozen_tools(root)
    serial_profile = f"serial-r{round_no}"
    concurrent_profile = f"concurrent-r{round_no}"
    review_root = root / "review" / f"round-{round_no}"
    package = review_root / "package"
    main_review = review_root / "main-review.json"
    independent_review = review_root / "independent-review.json"
    review_lock = review_root / "review-lock.json"
    mapping_path = review_root / "mapping.json"
    joined = review_root / "joined"
    comparison_path = review_root / "comparison.json"
    gate_path = root / f"round-{round_no}-gate.json"
    if gate_path.exists() or comparison_path.exists():
        raise ValueError("round gate outputs must be fresh")

    mains, independents = review_module.validate_review_set(
        package, main_review, independent_review)
    lock = review_module.read_json(review_lock)
    package_meta = review_module.read_json(package / "package.json")
    review_items = review_module.read_json(package / "review-items.json")
    review_template = review_module.read_json(package / "review-template.json")
    if (lock.get("schema_version") != 1 or lock.get("status") != "locked"
            or lock.get("review_count") != 24
            or lock.get("human_calibration") != "not_run"
            or lock.get("independent_coverage") != "complete"
            or lock.get("package_sha256") != review_module.sha256_json(package_meta)
            or lock.get("review_items_sha256") != review_module.sha256_json(review_items)
            or lock.get("review_template_sha256") != review_module.sha256_json(review_template)
            or lock.get("main_review_sha256") != review_module.sha256_json(mains)
            or lock.get("independent_review_sha256") !=
                review_module.sha256_json(independents)):
        raise ValueError("locked review evidence changed")

    serial_collection = root / "collections" / serial_profile
    concurrent_collection = root / "collections" / concurrent_profile
    dataset, _ = review_module.load_dataset(
        frozen_root / "benchmarks/product-baseline-v1.json")
    serial_data, concurrent_data = review_module.validate_pair(
        serial_collection, concurrent_collection, dataset)
    actual_manifest_map = serial_data["manifest_by_case"]
    if actual_manifest_map != control_module.EXPECTED_MANIFEST_BY_CASE:
        raise ValueError("actual collection manifest map changed")

    mapping_payload = review_module.read_json(mapping_path)
    mapping_items = mapping_payload.get("items") if isinstance(mapping_payload, dict) else None
    if (not isinstance(mapping_items, list) or len(mapping_items) != 24
            or package_meta.get("mapping_sha256") != review_module.sha256_json(mapping_items)
            or package_meta.get("review_items_sha256") != review_module.sha256_json(review_items)
            or package_meta.get("manifest_map_sha256") !=
                control_module.manifest_map_sha256(actual_manifest_map)):
        raise ValueError("private mapping/package identity changed")
    records_by_profile = {
        "serial": {record["case_id"]: record for record in serial_data["records"]},
        "concurrent": {record["case_id"]: record for record in concurrent_data["records"]},
    }
    dirs_by_profile = {"serial": serial_collection, "concurrent": concurrent_collection}
    seen_pairs = set()
    for mapping in mapping_items:
        profile, case_id = mapping.get("profile"), mapping.get("case_id")
        pair = (profile, case_id)
        if pair in seen_pairs or profile not in records_by_profile or case_id not in records_by_profile[profile]:
            raise ValueError("private mapping coverage is invalid")
        seen_pairs.add(pair)
        record = records_by_profile[profile][case_id]
        report_path = review_module._artifact_under(
            dirs_by_profile[profile], str(record["report_path"]))
        snapshot_path = review_module._artifact_under(
            dirs_by_profile[profile], str(record["snapshot_path"]))
        report_text = report_path.read_text(encoding="utf-8")
        if (mapping.get("run_id") != record.get("run_id")
                or mapping.get("experiment_id") != record.get("experiment_id")
                or mapping.get("manifest_id") != actual_manifest_map[case_id]
                or mapping.get("report_path") != record.get("report_path")
                or mapping.get("snapshot_path") != record.get("snapshot_path")
                or mapping.get("report_sha256") !=
                    hashlib.sha256(report_text.encode("utf-8")).hexdigest()
                or mapping.get("snapshot_sha256") != review_module.sha256_file(snapshot_path)):
            raise ValueError("private mapping no longer matches the collection artifacts")
    if seen_pairs != {(profile, case_id) for profile in ("serial", "concurrent")
                       for case_id in review_module.CASE_IDS}:
        raise ValueError("private mapping does not cover both profiles")

    rebuild_root = Path(tempfile.mkdtemp(prefix=".gate-rejoin-", dir=review_root)).resolve()
    if rebuild_root.parent != review_root.resolve():
        raise ValueError("temporary gate rebuild escaped review root")
    try:
        rebuilt = rebuild_root / "joined"
        review_module.join_reviews(argparse.Namespace(
            package=str(package), mapping=str(mapping_path), lock=str(review_lock),
            main=str(main_review), independent=str(independent_review),
            output=str(rebuilt)))
        if control_module.tree_identity(rebuilt) != control_module.tree_identity(joined):
            raise ValueError("joined scores differ from a fresh locked-input rebuild")
    finally:
        if rebuild_root.parent != review_root.resolve():
            raise ValueError("refusing unsafe temporary cleanup")
        shutil.rmtree(rebuild_root)

    aggregate = review_module.read_json(joined / "aggregate-gate-input.json")
    if (aggregate.get("status") != "ready_for_gate_review"
            or aggregate.get("dataset_hash") != EXPECTED_DATASET
            or aggregate.get("review_count") != 24
            or aggregate.get("human_calibration") != "not_run"
            or aggregate.get("review_lock_sha256") != review_module.sha256_json(lock)
            or aggregate.get("mapping_sha256") != review_module.sha256_json(mapping_items)
            or aggregate.get("review_items_sha256") != review_module.sha256_json(review_items)
            or aggregate.get("main_review_sha256") != review_module.sha256_json(mains)
            or aggregate.get("independent_review_sha256") != review_module.sha256_json(independents)):
        raise ValueError("joined review evidence is incomplete")
    score_hashes = aggregate.get("score_hashes")
    expected_score_hashes = {
        "scores.csv": review_module.sha256_file(joined / "scores.csv"),
        "serial/scores.csv": review_module.sha256_file(joined / "serial/scores.csv"),
        "concurrent/scores.csv": review_module.sha256_file(joined / "concurrent/scores.csv"),
    }
    if score_hashes != expected_score_hashes:
        raise ValueError("joined score hashes changed")
    shutil.copyfile(joined / "serial/scores.csv",
                    serial_collection / "scores.csv")
    shutil.copyfile(joined / "concurrent/scores.csv",
                    concurrent_collection / "scores.csv")
    comparison = baseline.compare_profiles(serial_collection, concurrent_collection)
    checks = comparison.get("checks")
    if (comparison.get("schema_version") != 1
            or comparison.get("dataset_hash") != EXPECTED_DATASET
            or comparison.get("case_count") != 12
            or not isinstance(checks, dict)
            or set(checks) != EXPECTED_CHECKS):
        raise ValueError("comparison output contract changed")
    qualification.write_json(comparison_path, comparison)

    profiles = {}
    blockers = []
    for profile, collection in (
        (serial_profile, serial_collection),
        (concurrent_profile, concurrent_collection),
    ):
        control = root / profile / "control/profile-control-result.json"
        identity = root / profile / "control/controller-identity.json"
        control_payload = json.loads(control.read_text(encoding="utf-8"))
        identity_payload = json.loads(identity.read_text(encoding="utf-8"))
        control_module.verify_frozen_tools(root, identity_payload)
        if (control_payload.get("execution_succeeded") is not True
                or control_payload.get("profile") != profile
                or control_payload.get("observed_records") != 12
                or control_payload.get("report_count") != 12
                or control_payload.get("metrics_complete") is not True
                or control_payload.get("process_cleanup_unresolved") is not False
                or identity_payload.get("git_commit") != EXPECTED_COMMIT
                or identity_payload.get("dataset_hash") != EXPECTED_DATASET):
            blockers.append(profile)
        profiles[profile] = {
            "control_result_sha256": control_module.file_hash(control),
            "controller_identity_sha256": control_module.file_hash(identity),
            "collection_tree_sha256": control_module.tree_identity(collection),
            "controller_sha256": identity_payload.get("controller_sha256"),
            "child_sha256": identity_payload.get("child_sha256"),
        }
    tool_pairs = {
        (value["controller_sha256"], value["child_sha256"])
        for value in profiles.values()
    }
    if len(tool_pairs) != 1:
        blockers.append("profile_tool_identity_mismatch")

    review_tree = control_module.tree_identity(review_root)
    gate = {
        "schema_version": 1,
        "round": round_no,
        "passed": bool(comparison.get("passed") is True and not blockers),
        "candidate_git_commit": EXPECTED_COMMIT,
        "dataset_hash": EXPECTED_DATASET,
        "manifest_map_sha256": control_module.manifest_map_sha256(actual_manifest_map),
        "core_asset_registry_id": EXPECTED_ASSET,
        "completed_report_count": 24,
        "paired_case_count": 12,
        "independent_review_complete": True,
        "human_calibration": "not_run",
        "no_unresolved_blockers": not blockers,
        "blockers": blockers,
        "profiles": profiles,
        "review_lock_sha256": control_module.file_hash(review_lock),
        "comparison_sha256": control_module.file_hash(comparison_path),
        "review_evidence_tree_sha256": review_tree,
        "comparison_checks": checks,
    }
    qualification.write_json(gate_path, gate)
    print(json.dumps({
        "round": round_no,
        "passed": gate["passed"],
        "blocker_count": len(blockers),
        "comparison_checks": checks,
    }, sort_keys=True), flush=True)
    return gate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--round", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    try:
        result = main(args.root.resolve(), args.frozen_root.resolve(), args.round)
        raise SystemExit(0 if result["passed"] else 1)
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__,
                          "gate_written": False}, sort_keys=True), flush=True)
        raise SystemExit(1)
