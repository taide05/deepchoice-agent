"""Create and validate the blind review pack for one O1-PR2B round.

This tracked offline tool validates two completed collections, copies
only public rubric fields and report text into an opaque package, and writes
the source mapping separately. The lock command validates main and independent
review files. The join command is the only command that reads the private mapping.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATASET_HASH = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
EXPECTED_COMMIT = "09f9b66cf114953c09ebe928c1c081667647db16"
EXPECTED_MANIFEST_BY_CASE = {"P01": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P02": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P03": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P04": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P05": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P06": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P07": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P08": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P09": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P10": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P11": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P12": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a"}
CASE_IDS = tuple(f"P{i:02d}" for i in range(1, 13))
SUCCESS_STATUSES = {"completed", "completed_with_warnings"}
SUPPORT_VALUES = {"supported", "partial", "unsupported", "unknown", "uncited"}
QUALITY_VALUES = {"eligible", "ineligible", "unknown"}
PRIVATE_KEYS = {
    "profile", "repetition", "run_id", "experiment_id", "task_id", "manifest_id",
    "trace", "observability", "runtime_observations", "run_heartbeat", "path",
    "report_path", "snapshot_path", "mapping", "environment", "api_origin",
}
REQUIRED_REVIEW_FIELDS = {
    "review_id", "review_status", "reviewer_qualification", "human_calibration",
    "ledger_complete", "claim_occurrences", "must_answer", "conflict_points",
    "major_errors", "disputed_refs", "claimed_improvements",
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    dataset = read_json(path)
    if not isinstance(dataset, dict) or dataset.get("dataset_id") != "product-baseline-v1":
        raise ValueError("unexpected dataset")
    digest = sha256_json(dataset)
    if digest != DATASET_HASH:
        raise ValueError("dataset hash does not match frozen product-baseline-v1")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) != 12:
        raise ValueError("dataset must contain 12 cases")
    by_id = {case.get("id"): case for case in cases if isinstance(case, dict)}
    if set(by_id) != set(CASE_IDS):
        raise ValueError("dataset case identities are not P01..P12")
    return dataset, digest


def records_in(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = read_json(directory / "experiment.json")
    if not isinstance(metadata, dict):
        raise ValueError(f"{directory}: experiment metadata must be an object")
    records = []
    for line_no, line in enumerate((directory / "runs.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{directory}: invalid runs.jsonl line {line_no}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{directory}: run record is not an object")
        records.append(value)
    if len(records) != 12:
        raise ValueError(f"{directory}: expected exactly 12 records, got {len(records)}")
    return metadata, records


def _artifact_under(directory: Path, relative: str) -> Path:
    root = directory.resolve()
    target = (directory / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"{directory}: artifact escapes collection directory")
    return target


def validate_collection(directory: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    metadata, records = records_in(directory)
    if metadata.get("dataset_hash") != DATASET_HASH or metadata.get("git_commit") != EXPECTED_COMMIT:
        raise ValueError(f"{directory}: frozen dataset/candidate identity mismatch")
    if metadata.get("case_denominator") != 12 or metadata.get("admitted_run_denominator") != 12:
        raise ValueError(f"{directory}: incomplete admitted denominator")
    case_ids = [record.get("case_id") for record in records]
    if sorted(case_ids) != list(CASE_IDS):
        raise ValueError(f"{directory}: case IDs are not exactly P01..P12 once each")
    experiment_id = metadata.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ValueError(f"{directory}: missing experiment_id")
    manifest_by_case, run_ids = {}, set()
    for record in records:
        if record.get("status") not in SUCCESS_STATUSES:
            raise ValueError(f"{directory}: {record.get('case_id')} is not successful")
        if not record.get("report_path") or not record.get("snapshot_path"):
            raise ValueError(f"{directory}: {record.get('case_id')} lacks report/snapshot")
        report = _artifact_under(directory, str(record["report_path"]))
        snapshot = _artifact_under(directory, str(record["snapshot_path"]))
        if not report.is_file() or report.stat().st_size == 0:
            raise ValueError(f"{directory}: report artifact is unavailable")
        if not snapshot.is_file() or snapshot.stat().st_size == 0:
            raise ValueError(f"{directory}: snapshot artifact is unavailable")
        run_id, manifest_id = record.get("run_id"), record.get("manifest_id")
        if not isinstance(run_id, str) or not run_id or not isinstance(manifest_id, str) or not manifest_id:
            raise ValueError(f"{directory}: missing run/manifest identity")
        run_ids.add(run_id)
        manifest_by_case[record["case_id"]] = manifest_id
    if len(run_ids) != 12 or len(manifest_by_case) != 12:
        raise ValueError(f"{directory}: run IDs or per-case manifest identities are incomplete")
    if manifest_by_case != EXPECTED_MANIFEST_BY_CASE:
        raise ValueError(f"{directory}: per-case manifest identities differ from the frozen map")
    return {"metadata": metadata, "records": records, "experiment_id": experiment_id,
            "run_ids": run_ids, "manifest_by_case": manifest_by_case}


def validate_pair(serial: Path, concurrent: Path, dataset: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    left, right = validate_collection(serial, dataset), validate_collection(concurrent, dataset)
    if left["experiment_id"] == right["experiment_id"] or left["run_ids"] & right["run_ids"]:
        raise ValueError("serial/concurrent experiment and run IDs must be globally unique")
    if left["manifest_by_case"] != right["manifest_by_case"]:
        raise ValueError("serial and concurrent per-case manifest IDs must match")
    for key in ("dataset_hash", "environment_hash", "core_asset_registry_id", "git_commit"):
        if left["metadata"].get(key) != right["metadata"].get(key):
            raise ValueError(f"serial and concurrent metadata mismatch: {key}")
    return left, right


class SeededCSPRNG:
    """Deterministic HMAC-SHA256 counter stream with rejection sampling."""
    algorithm = "hmac-sha256-counter-v1"

    def __init__(self, seed: int):
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.seed = seed
        self.key = hashlib.sha256(str(seed).encode("ascii")).digest()
        self.counter = 0

    def bytes(self, size: int) -> bytes:
        output = bytearray()
        while len(output) < size:
            output.extend(hmac.new(self.key, self.counter.to_bytes(16, "big"), hashlib.sha256).digest())
            self.counter += 1
        return bytes(output[:size])

    def below(self, upper: int) -> int:
        width = max(1, (upper - 1).bit_length())
        size, mask = (width + 7) // 8, (1 << width) - 1
        while True:
            value = int.from_bytes(self.bytes(size), "big") & mask
            if value < upper:
                return value

    def shuffle(self, values: list[Any]) -> None:
        for index in range(len(values) - 1, 0, -1):
            swap = self.below(index + 1)
            values[index], values[swap] = values[swap], values[index]

    def token(self, label: str, length: int = 24) -> str:
        return hmac.new(self.key, label.encode("utf-8"), hashlib.sha256).hexdigest()[:length]


def public_rubric(case: dict[str, Any]) -> dict[str, Any]:
    rubric = case.get("rubric")
    if not isinstance(rubric, dict):
        raise ValueError(f"missing rubric for {case.get('id')}")
    must, conflict = rubric.get("must_answer"), rubric.get("conflict_points", [])
    if not isinstance(must, list) or not all(isinstance(item, str) and item for item in must):
        raise ValueError(f"invalid must_answer rubric for {case.get('id')}")
    if not isinstance(conflict, list) or not all(isinstance(item, str) and item for item in conflict):
        raise ValueError(f"invalid conflict rubric for {case.get('id')}")
    return {"must_answer": must, "conflict_points": conflict}


def forbidden_keys(value: Any) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in PRIVATE_KEYS:
                found.add(str(key))
            found |= forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            found |= forbidden_keys(child)
    return found


def blank_review(item: dict[str, Any]) -> dict[str, Any]:
    rubric = item["rubric"]
    return {
        "review_id": item["review_id"], "review_status": "incomplete",
        "reviewer_qualification": "", "human_calibration": "not_run",
        "ledger_complete": False, "claim_occurrences": [],
        "must_answer": [{"id": f"must-{i + 1}", "score": None, "notes": ""} for i, _ in enumerate(rubric["must_answer"])],
        "conflict_points": [{"id": f"conflict-{i + 1}", "score": None, "notes": ""} for i, _ in enumerate(rubric["conflict_points"])],
        "major_errors": [], "disputed_refs": [], "claimed_improvements": [],
        "independent_coverage": [],
    }


def generate(args: argparse.Namespace) -> None:
    dataset, dataset_hash = load_dataset(Path(args.dataset).resolve())
    serial_dir, concurrent_dir = Path(args.serial).resolve(), Path(args.concurrent).resolve()
    serial, concurrent = validate_pair(serial_dir, concurrent_dir, dataset)
    output, mapping_path = Path(args.output).resolve(), Path(args.mapping).resolve()
    if output.exists() or mapping_path.exists():
        raise ValueError("output and mapping paths must be fresh")
    if output == mapping_path or output in mapping_path.parents or mapping_path in output.parents:
        raise ValueError("mapping must be separate from the review package")
    seed = args.seed if args.seed is not None else secrets.randbits(64)
    rng = SeededCSPRNG(seed)
    by_case = {case["id"]: case for case in dataset["cases"]}
    sources = [("serial", record) for record in sorted(serial["records"], key=lambda x: x["case_id"])]
    sources += [("concurrent", record) for record in sorted(concurrent["records"], key=lambda x: x["case_id"])]
    rng.shuffle(sources)
    items, mappings = [], []
    for ordinal, (profile_name, record) in enumerate(sources, 1):
        case = by_case[record["case_id"]]
        label = f"id:{ordinal}:{record['case_id']}:{profile_name}"
        review_id = f"rvw-{rng.token(label, 24)}"
        base = serial_dir if profile_name == "serial" else concurrent_dir
        report_path = _artifact_under(base, str(record["report_path"]))
        snapshot_path = _artifact_under(base, str(record["snapshot_path"]))
        report_text = report_path.read_text(encoding="utf-8")
        item = {"review_id": review_id, "case_id": record["case_id"], "split": case["split"],
                "report": report_text, "rubric": public_rubric(case)}
        if set(item) != {"review_id", "case_id", "split", "report", "rubric"} or forbidden_keys(item):
            raise ValueError("blind item contains private identity fields")
        items.append(item)
        mappings.append({"review_id": review_id, "case_id": record["case_id"], "split": case["split"],
                         "profile": profile_name, "repetition": record.get("repetition"),
                         "experiment_id": record["experiment_id"], "run_id": record["run_id"],
                         "manifest_id": record["manifest_id"], "report_path": record["report_path"],
                         "snapshot_path": record["snapshot_path"],
                         "report_sha256": hashlib.sha256(report_text.encode("utf-8")).hexdigest(),
                         "snapshot_sha256": sha256_file(snapshot_path)})
    if len(items) != 24 or len({item["review_id"] for item in items}) != 24:
        raise ValueError("review IDs are not unique")
    if any(sum(item["case_id"] == case_id for item in items) != 2 for case_id in CASE_IDS):
        raise ValueError("blind package must contain two items for every case")
    templates = [blank_review(item) for item in items]
    package_meta = {
        "schema_version": 1, "package_kind": "o1-pr2-blind-review",
        "dataset_id": dataset["dataset_id"], "dataset_hash": dataset_hash,
        "case_count": 24, "seed": seed, "random_algorithm": rng.algorithm,
        "created_at": now(), "item_order_sha256": sha256_json([x["review_id"] for x in items]),
        "mapping_sha256": sha256_json(mappings),
        "manifest_map_sha256": sha256_json(EXPECTED_MANIFEST_BY_CASE),
        "review_items_sha256": sha256_json(items),
        "review_template_sha256": sha256_json(templates),
        "claim_occurrence_schema": {
            "required_fields": ["occurrence_id", "line", "atom", "support", "quality", "source_refs", "notes"],
            "support_values": sorted(SUPPORT_VALUES), "quality_values": sorted(QUALITY_VALUES),
            "repeated_occurrences_count_separately": True,
        },
        "reviewer_policy": {"human_calibration": "not_run", "main_then_independent": True},
    }
    output.mkdir(parents=True)
    atomic_json(output / "package.json", package_meta)
    atomic_json(output / "review-items.json", items)
    atomic_json(output / "review-template.json", templates)
    atomic_json(mapping_path, {"schema_version": 1, "package_sha256": sha256_json(package_meta), "items": mappings})
    print(json.dumps({"generated": True, "items": 24, "package": str(output),
                      "mapping": str(mapping_path), "mapping_sha256": package_meta["mapping_sha256"]}, sort_keys=True))


def load_reviews(path: Path) -> list[dict[str, Any]]:
    value = read_json(path)
    if not isinstance(value, list):
        raise ValueError(f"{path}: review file must be a JSON list")
    return value


def validate_occurrence(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise ValueError("claim occurrence must be an object")
    required = {"occurrence_id", "line", "atom", "support", "quality", "source_refs", "notes"}
    if not required <= set(entry):
        raise ValueError("claim occurrence is incomplete")
    if not isinstance(entry["occurrence_id"], str) or not entry["occurrence_id"]:
        raise ValueError("claim occurrence ID is required")
    if not isinstance(entry["line"], (int, str)) or not isinstance(entry["atom"], str) or not entry["atom"].strip():
        raise ValueError("claim occurrence line/atom is invalid")
    if entry["support"] not in SUPPORT_VALUES or entry["quality"] not in QUALITY_VALUES:
        raise ValueError("claim occurrence support/quality value is invalid")
    if not isinstance(entry["source_refs"], list) or not all(isinstance(ref, str) for ref in entry["source_refs"]):
        raise ValueError("claim occurrence source_refs is invalid")


def validate_review(review: Any, item: dict[str, Any], role: str) -> None:
    if not isinstance(review, dict) or not REQUIRED_REVIEW_FIELDS <= set(review):
        raise ValueError(f"{role}: review is missing required fields")
    if review.get("review_id") != item["review_id"] or review.get("review_status") != "complete":
        raise ValueError(f"{role}: review identity/status is invalid")
    if not isinstance(review.get("reviewer_qualification"), str) or not review["reviewer_qualification"].strip():
        raise ValueError(f"{role}: reviewer qualification is required")
    if review.get("human_calibration") != "not_run" or review.get("ledger_complete") is not True:
        raise ValueError(f"{role}: calibration/ledger declaration is invalid")
    if not isinstance(review.get("claim_occurrences"), list):
        raise ValueError(f"{role}: claim occurrence ledger must be a list")
    for entry in review["claim_occurrences"]:
        validate_occurrence(entry)
    rubric = item["rubric"]
    for field, expected, prefix in (("must_answer", rubric["must_answer"], "must"), ("conflict_points", rubric["conflict_points"], "conflict")):
        values = review.get(field)
        if not isinstance(values, list) or len(values) != len(expected):
            raise ValueError(f"{role}: {field} count mismatch")
        for index, value in enumerate(values, 1):
            if not isinstance(value, dict) or value.get("id") != f"{prefix}-{index}" or value.get("score") not in {0, 1, 2}:
                raise ValueError(f"{role}: invalid {field} score")
            if not isinstance(value.get("notes"), str) or not value["notes"].strip():
                raise ValueError(f"{role}: {field} notes are required")
    for field in ("major_errors", "disputed_refs", "claimed_improvements"):
        values = review.get(field)
        if not isinstance(values, list):
            raise ValueError(f"{role}: {field} must be a list")
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"] or not isinstance(value.get("evidence"), str) or not value["evidence"].strip():
                raise ValueError(f"{role}: {field} entries need IDs and evidence")


def validate_review_set(package: Path, main_path: Path, independent_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items = read_json(package / "review-items.json")
    if not isinstance(items, list) or len(items) != 24 or len({item.get("review_id") for item in items}) != 24:
        raise ValueError("package must contain 24 unique review items")
    mains, independents = load_reviews(main_path), load_reviews(independent_path)
    expected = {item["review_id"] for item in items}
    for name, reviews in (("main", mains), ("independent", independents)):
        if len(reviews) != 24 or {review.get("review_id") for review in reviews} != expected:
            raise ValueError(f"{name} review set must cover all 24 items exactly once")
        by_id = {review["review_id"]: review for review in reviews}
        for item in items:
            validate_review(by_id[item["review_id"]], item, name)
    main_by_id = {review["review_id"]: review for review in mains}
    independent_by_id = {review["review_id"]: review for review in independents}
    for review_id, main in main_by_id.items():
        required = [(field, entry["id"]) for field in ("major_errors", "disputed_refs", "claimed_improvements") for entry in main[field]]
        covered = {(entry.get("kind"), entry.get("id"), entry.get("covered")) for entry in independent_by_id[review_id].get("independent_coverage", []) if isinstance(entry, dict)}
        if any((field, identifier, True) not in covered for field, identifier in required):
            raise ValueError(f"independent review lacks coverage for {review_id}")
    return mains, independents


def lock_reviews(args: argparse.Namespace) -> None:
    package = Path(args.package).resolve()
    meta = read_json(package / "package.json")
    if not isinstance(meta, dict) or meta.get("dataset_hash") != DATASET_HASH:
        raise ValueError("package metadata is invalid")
    items = read_json(package / "review-items.json")
    template = read_json(package / "review-template.json")
    if (meta.get("review_items_sha256") != sha256_json(items)
            or meta.get("review_template_sha256") != sha256_json(template)
            or meta.get("manifest_map_sha256") != sha256_json(EXPECTED_MANIFEST_BY_CASE)):
        raise ValueError("package items/template/manifest identity changed")
    mains, independents = validate_review_set(package, Path(args.main).resolve(), Path(args.independent).resolve())
    atomic_json(Path(args.lock).resolve(), {
        "schema_version": 1, "status": "locked", "locked_at": now(),
        "package_sha256": sha256_json(meta),
        "review_items_sha256": sha256_json(items),
        "review_template_sha256": sha256_json(template),
        "main_review_sha256": sha256_json(mains),
        "independent_review_sha256": sha256_json(independents), "review_count": 24,
        "human_calibration": "not_run", "independent_coverage": "complete",
    })
    print(json.dumps({"locked": True, "review_count": 24}, sort_keys=True))


def join_reviews(args: argparse.Namespace) -> None:
    package, mapping_path, lock_path = Path(args.package).resolve(), Path(args.mapping).resolve(), Path(args.lock).resolve()
    meta, mapping_payload, lock = read_json(package / "package.json"), read_json(mapping_path), read_json(lock_path)
    if lock.get("status") != "locked" or lock.get("review_count") != 24 or lock.get("package_sha256") != sha256_json(meta):
        raise ValueError("review set is not locked for this package")
    items = read_json(package / "review-items.json")
    template = read_json(package / "review-template.json")
    if (lock.get("review_items_sha256") != sha256_json(items)
            or lock.get("review_template_sha256") != sha256_json(template)
            or meta.get("review_items_sha256") != sha256_json(items)
            or meta.get("review_template_sha256") != sha256_json(template)
            or meta.get("manifest_map_sha256") != sha256_json(EXPECTED_MANIFEST_BY_CASE)):
        raise ValueError("locked package evidence changed")
    mapping_items = mapping_payload.get("items") if isinstance(mapping_payload, dict) else None
    if not isinstance(mapping_items, list) or len(mapping_items) != 24 or mapping_payload.get("package_sha256") != sha256_json(meta):
        raise ValueError("mapping is invalid")
    if meta.get("mapping_sha256") != sha256_json(mapping_items):
        raise ValueError("mapping content hash does not match package")
    mappings = {item["review_id"]: item for item in mapping_items}
    item_by_id = {item["review_id"]: item for item in items}
    if set(mappings) != set(item_by_id):
        raise ValueError("mapping does not cover package")
    for review_id, mapping in mappings.items():
        item = item_by_id[review_id]
        if (mapping.get("case_id") != item.get("case_id")
                or mapping.get("split") != item.get("split")
                or mapping.get("manifest_id") != EXPECTED_MANIFEST_BY_CASE[item["case_id"]]
                or mapping.get("report_sha256") !=
                    hashlib.sha256(item["report"].encode("utf-8")).hexdigest()
                or not isinstance(mapping.get("snapshot_sha256"), str)
                or len(mapping["snapshot_sha256"]) != 64):
            raise ValueError("mapping identity/content does not match the blind item")
    mains, independents = load_reviews(Path(args.main).resolve()), load_reviews(Path(args.independent).resolve())
    if sha256_json(mains) != lock.get("main_review_sha256") or sha256_json(independents) != lock.get("independent_review_sha256"):
        raise ValueError("reviews changed after lock")
    reviews = {review["review_id"]: review for review in mains}
    rows = []
    for item in items:
        review, mapping = reviews[item["review_id"]], mappings[item["review_id"]]
        occurrences = review["claim_occurrences"]
        support_counts = {v: sum(entry["support"] == v for entry in occurrences) for v in sorted(SUPPORT_VALUES)}
        quality_counts = {v: sum(entry["quality"] == v for entry in occurrences) for v in sorted(QUALITY_VALUES)}
        rows.append({
            "review_id": item["review_id"], "case_id": mapping["case_id"], "split": mapping["split"],
            "profile": mapping["profile"], "repetition": mapping["repetition"],
            "experiment_id": mapping["experiment_id"], "run_id": mapping["run_id"],
            "decision_score_total": sum(value["score"] for value in review["must_answer"]),
            "decision_score_max": 2 * len(review["must_answer"]),
            "conflict_score_total": sum(value["score"] for value in review["conflict_points"]),
            "conflict_score_max": 2 * len(review["conflict_points"]),
            "claim_occurrence_count": len(occurrences),
            **{f"support_{k}_count": v for k, v in support_counts.items()},
            **{f"quality_{k}_count": v for k, v in quality_counts.items()},
            "major_error_count": len(review["major_errors"]), "disputed_ref_count": len(review["disputed_refs"]),
            "claimed_improvement_count": len(review["claimed_improvements"]),
            "decision_correctness": sum(value["score"] for value in review["must_answer"]) / (2 * len(review["must_answer"])),
            "citation_support": support_counts.get("supported", 0) / len(occurrences),
            "source_quality": quality_counts.get("eligible", 0) / len(occurrences),
            "conflict_handling": sum(value["score"] for value in review["conflict_points"]) / (2 * len(review["conflict_points"])),
            "reviewer": review["reviewer_qualification"],
            "evidence_notes": f"locked blind ledger {item['review_id']}; occurrences={len(occurrences)}",
        })
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    gate_fields = [
        "case_id", "run_id", "experiment_id", "decision_correctness",
        "citation_support", "source_quality", "conflict_handling",
        "major_errors", "reviewer", "evidence_notes",
    ]
    for profile in ("serial", "concurrent"):
        profile_dir = destination / profile
        profile_dir.mkdir()
        profile_rows = []
        for row in rows:
            if row["profile"] != profile:
                continue
            profile_rows.append({
                "case_id": row["case_id"],
                "run_id": row["run_id"],
                "experiment_id": row["experiment_id"],
                "decision_correctness": row["decision_correctness"],
                "citation_support": row["citation_support"],
                "source_quality": row["source_quality"],
                "conflict_handling": row["conflict_handling"],
                "major_errors": row["major_error_count"],
                "reviewer": row["reviewer"],
                "evidence_notes": row["evidence_notes"],
            })
        if len(profile_rows) != 12:
            raise ValueError("joined scores must contain 12 rows per profile")
        with (profile_dir / "scores.csv").open(
                "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=gate_fields)
            writer.writeheader()
            writer.writerows(profile_rows)
    score_hashes = {
        "scores.csv": sha256_file(destination / "scores.csv"),
        "serial/scores.csv": sha256_file(destination / "serial/scores.csv"),
        "concurrent/scores.csv": sha256_file(destination / "concurrent/scores.csv"),
    }
    atomic_json(destination / "aggregate-gate-input.json", {
        "schema_version": 1, "status": "ready_for_gate_review", "dataset_hash": DATASET_HASH,
        "review_count": 24, "human_calibration": "not_run", "scores_csv": "scores.csv",
        "review_locked_at": lock.get("locked_at"),
        "review_lock_sha256": sha256_json(lock),
        "mapping_sha256": sha256_json(mapping_items),
        "review_items_sha256": sha256_json(items),
        "main_review_sha256": sha256_json(mains),
        "independent_review_sha256": sha256_json(independents),
        "score_hashes": score_hashes,
    })
    print(json.dumps({"joined": True, "rows": 24, "output": str(destination)}, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    for name in ("serial", "concurrent"):
        generate_parser.add_argument(f"--{name}", required=True)
    generate_parser.add_argument("--dataset", default="benchmarks/product-baseline-v1.json")
    generate_parser.add_argument("--output", required=True)
    generate_parser.add_argument("--mapping", required=True)
    generate_parser.add_argument("--seed", type=int)
    generate_parser.set_defaults(func=generate)
    lock_parser = sub.add_parser("lock")
    for name in ("package", "main", "independent", "lock"):
        lock_parser.add_argument(f"--{name}", required=True)
    lock_parser.set_defaults(func=lock_reviews)
    join_parser = sub.add_parser("join")
    for name in ("package", "mapping", "lock", "main", "independent", "output"):
        join_parser.add_argument(f"--{name}", required=True)
    join_parser.set_defaults(func=join_reviews)
    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
