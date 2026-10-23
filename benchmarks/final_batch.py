"""Minimal durable final-batch collection and review aggregation.

This is an offline-prepared preparation tool, not an authorization. Paid
collection is refused for the current draft dataset (references/expected
outcomes/scoring are not independently frozen) and for any non-admitted status.
The candidate arm calls the final product's durable API through the existing
DurableBaselineCollector; no separate research algorithm is implemented.

Commands
    validate   offline dataset/denominator/calibration checks
    collect    guarded candidate-arm collection (admitted dataset + explicit flag)
    summarize  import reviews and write N/S/R/E + resource/quality summary
    resume-plan report which terminal cases a resume would skip
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import random
import statistics
import subprocess
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from benchmarks.product_baseline import (
    TERMINAL_STATUSES,
    CollectionOptions,
    DurableBaselineCollector,
)
from deepchoice.contracts.api import ResearchRequest

EXPECTED_FINAL = 120
EXPECTED_CALIBRATION = 12
LAYERS = {"A": 30, "B": 24, "C": 18, "D": 16, "E": 16, "F": 16}
SUCCESS_STATUSES = {"completed", "completed_with_warnings"}
ADMITTED_STATUSES = {"admitted", "frozen"}
REVIEW_STATUSES = {"completed", "unavailable", "failed", "needs_review"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pair_key(case: dict) -> str:
    names = sorted(str(value).strip().casefold()
                   for value in (case.get("request") or {}).get("candidate_techs", []))
    return "|".join(names)


def _terminal(record: dict) -> bool:
    return record.get("status") in TERMINAL_STATUSES


def load_batch_dataset(path: Path, *, require_admitted: bool = False) -> tuple[dict, str]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(dataset, dict):
        raise ValueError("dataset root must be an object")
    if dataset.get("dataset_id") != "final-batch-v1":
        raise ValueError("unexpected dataset_id")
    cases = dataset.get("cases")
    calibration = (dataset.get("calibration") or {}).get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_FINAL:
        raise ValueError(f"final cases must be exactly {EXPECTED_FINAL}")
    if not isinstance(calibration, list) or len(calibration) != EXPECTED_CALIBRATION:
        raise ValueError(f"calibration cases must be exactly {EXPECTED_CALIBRATION}")
    seen_ids: set[str] = set()
    groups: set[str] = set()
    pairs: set[str] = set()
    layers: Counter[str] = Counter()
    for case in cases + calibration:
        if not isinstance(case, dict):
            raise ValueError("each case must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case id missing")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        group = case.get("group_id")
        if not isinstance(group, str) or group in groups:
            raise ValueError(f"duplicate/missing group_id: {case_id}")
        groups.add(group)
        pair = _pair_key(case)
        if not pair or pair in pairs:
            raise ValueError(f"duplicate candidate pair: {case_id}")
        pairs.add(pair)
        if case not in cases:
            if case.get("split") != "calibration":
                raise ValueError(f"non-final split on final case: {case_id}")
        else:
            if case.get("split") != "final":
                raise ValueError(f"final case split mismatch: {case_id}")
            layers[str(case.get("layer"))] += 1
        case_ready = case.get("eval_ready")
        if not isinstance(case_ready, bool):
            raise ValueError(f"case eval_ready must be boolean: {case_id}")
        if require_admitted and case_ready is not True:
            raise ValueError(f"admitted dataset has non-ready case: {case_id}")
        reference = case.get("reference_basis") or {}
        if reference.get("must_not_enter_research_input") is not True:
            raise ValueError(f"reference basis isolation missing: {case_id}")
        request = case.get("request")
        ResearchRequest.model_validate(request)
        if request.get("candidate_techs") != (case.get("request") or {}).get("candidate_techs"):
            raise ValueError(f"candidate identity changed: {case_id}")
        if not isinstance(case.get("hitl"), dict):
            raise ValueError(f"missing HITL policy: {case_id}")
    if layers != Counter(LAYERS):
        raise ValueError(f"layer quota mismatch: {dict(layers)}")
    if (dataset.get("calibration") or {}).get("isolated") is not True:
        raise ValueError("calibration set must be isolated")
    if (dataset.get("calibration") or {}).get("never_in_final_denominator") is not True:
        raise ValueError("calibration must never enter the final denominator")
    if len(cases) + len(calibration) != len(seen_ids):
        raise ValueError("final and calibration cases overlap")
    embedded = dataset.get("content_sha256")
    if not isinstance(embedded, str) or not embedded:
        raise ValueError("dataset content_sha256 is required")
    content = {key: value for key, value in dataset.items()
               if key != "content_sha256"}
    if _sha256(content) != embedded:
        raise ValueError("dataset content_sha256 does not match its content")
    if require_admitted:
        if dataset.get("status") not in ADMITTED_STATUSES or dataset.get("eval_ready") is not True:
            blockers = dataset.get("admission_blockers") or []
            raise ValueError("dataset is not admitted: " + ", ".join(map(str, blockers)))
        if not dataset.get("freeze_date"):
            raise ValueError("admitted dataset requires a freeze date")
        if dataset.get("admission_blockers"):
            raise ValueError("admitted dataset still carries admission blockers")
        if (dataset.get("batch_budget") or {}).get("status") != "authorized":
            raise ValueError("batch budget is not authorized")
    return dataset, _path_sha256(path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def terminal_case_ids(records: list[dict]) -> set[str]:
    """Cases whose first terminal record exists must not be redispatched."""
    done = set()
    for record in records:
        case_id = record.get("case_id")
        if isinstance(case_id, str) and _terminal(record):
            done.add(case_id)
    return done


def uncertain_admitted_case_ids(admissions: list[dict],
                                terminal: set[str]) -> set[str]:
    """A submitted but non-terminal admission must be reconciled, not re-sent."""
    uncertain = set()
    for record in admissions:
        case_id = record.get("case_id")
        event = record.get("event")
        if (isinstance(case_id, str) and case_id not in terminal
                and event in {"submission_started", "admitted"}):
            uncertain.add(case_id)
    return uncertain


def resume_plan(dataset: dict, records: list[dict],
                admissions: list[dict] | None = None) -> dict:
    all_ids = {case["id"] for case in dataset["cases"]}
    done = terminal_case_ids(records)
    uncertain = uncertain_admitted_case_ids(admissions or [], done)
    return {
        "planned": len(all_ids),
        "terminal_already_present": sorted(all_ids & done),
        "admitted_unsettled": sorted(all_ids & uncertain),
        "remaining": sorted(all_ids - done - uncertain),
    }


def _git_commit() -> str | None:
    try:
        value = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                        text=True, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def _read_reviews(path: Path | None) -> dict[tuple[str, str], dict]:
    if path is None or not path.exists():
        return {}
    reviews: dict[tuple[str, str], dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = (row.get("case_id") or "").strip()
            arm = (row.get("arm") or "").strip()
            status = (row.get("review_status") or "").strip()
            if not case_id or not arm:
                raise ValueError("review row lacks case_id/arm")
            if status not in REVIEW_STATUSES:
                raise ValueError(f"invalid review_status: {status!r}")
            key = (case_id, arm)
            if key in reviews:
                raise ValueError(f"duplicate review: {key}")
            if not row.get("reviewer"):
                raise ValueError(f"review row lacks reviewer: {key}")
            try:
                major_errors = int(row.get("major_errors") or 0)
            except ValueError as exc:
                raise ValueError(f"invalid major_errors: {key}") from exc
            if major_errors < 0:
                raise ValueError(f"negative major_errors: {key}")
            usable_raw = (row.get("usable") or "").strip().lower()
            if usable_raw not in {"true", "false"}:
                raise ValueError(f"usable must be true/false: {key}")
            reviews[key] = {
                "case_id": case_id, "arm": arm, "reviewer": row["reviewer"],
                "review_status": status,
                "usable": usable_raw == "true",
                "major_errors": major_errors,
                "evidence_notes": (row.get("evidence_notes") or "").strip(),
                "requirement_scores": (row.get("requirement_scores") or "").strip(),
            }
    return reviews


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return ordered[index]


def summarize(dataset: dict, output_dir: Path, reviews_path: Path | None = None) -> dict:
    records = _read_jsonl(output_dir / "runs.jsonl")
    reviews = _read_reviews(reviews_path or output_dir / "reviews.csv")
    cases = {case["id"]: case for case in dataset["cases"]}
    known_case_ids = set(cases)
    for (case_id, arm), review in reviews.items():
        if case_id not in known_case_ids:
            raise ValueError(f"review references unknown final case: {case_id}")
        if arm not in {"candidate", "baseline"}:
            raise ValueError(f"review references unknown arm: {arm}")
    record_by_case_arm: dict[tuple[str, str], dict] = {}
    for record in records:
        case_id = record.get("case_id")
        arm = record.get("profile") or "candidate"
        if case_id not in known_case_ids:
            continue
        record_by_case_arm[(case_id, arm)] = record
    arms = sorted({arm for _, arm in record_by_case_arm}) or ["candidate"]
    by_arm: dict[str, dict] = {}
    for arm in arms:
        arm_records = [record for (case, a), record in record_by_case_arm.items() if a == arm]
        s = [record for record in arm_records if record.get("task_id")]
        r = [record for record in arm_records if record.get("report_path")]
        reviews_for_arm = [review for (case, a), review in reviews.items()
                           if a == arm and case in known_case_ids]
        e = [review for review in reviews_for_arm
             if review["review_status"] == "completed"]
        for review in e:
            bound = record_by_case_arm.get((review["case_id"], arm))
            if not bound or not bound.get("report_path"):
                raise ValueError(
                    f"completed review has no report for {review['case_id']}/{arm}")
        if len(e) > len(r):
            raise ValueError(f"completed reviews exceed reports for arm {arm}")
        usable = sum(review["usable"] for review in e)
        walls = [float(record["wall_time_ms"]) for record in r
                 if isinstance(record.get("wall_time_ms"), (int, float))]
        tokens = [record.get("usage") or {} for record in arm_records]
        known_tokens = [int(u["total_tokens"]) for u in tokens
                        if isinstance(u.get("total_tokens"), int)]
        complete_tokens = sum(u.get("token_usage_complete") is True for u in tokens)
        failures = Counter(record.get("status") for record in arm_records
                           if record.get("status") not in SUCCESS_STATUSES)
        by_layer: dict[str, dict] = {}
        for layer in LAYERS:
            ids = {case_id for case_id in known_case_ids
                   if cases[case_id].get("layer") == layer}
            layer_records = [record for (case_id, a), record in record_by_case_arm.items()
                             if a == arm and case_id in ids]
            layer_reviews = [review for (case_id, a), review in reviews.items()
                             if a == arm and case_id in ids
                             and review["review_status"] == "completed"]
            by_layer[layer] = {
                "N": len(ids), "S": sum(bool(x.get("task_id")) for x in layer_records),
                "R": sum(bool(x.get("report_path")) for x in layer_records),
                "E": len(layer_reviews),
                "usable": sum(review["usable"] for review in layer_reviews),
                "major_errors": sum(review["major_errors"] for review in layer_reviews),
            }
        by_arm[arm] = {
            "N": len(known_case_ids), "S": len(s), "R": len(r), "E": len(e),
            "usable": usable,
            "usable_rate_E": (usable / len(e)) if e else None,
            "review_coverage_E_over_R": (len(e) / len(r)) if r else None,
            "major_errors": sum(review["major_errors"] for review in e),
            "terminal_status_counts": dict(Counter(record.get("status") for record in arm_records)),
            "failures_preserved": dict(failures),
            "report_rate_R_over_S": (len(r) / len(s)) if s else None,
            "wall_ms_p50": _percentile(walls, 50),
            "wall_ms_p95": _percentile(walls, 95),
            "known_total_tokens": sum(known_tokens) if known_tokens else None,
            "token_complete_runs": complete_tokens,
            "token_total_runs": len(arm_records),
            "cost": "unknown",
            "by_layer": by_layer,
        }
    summary = {
        "schema_version": 1,
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("version"),
        "dataset_status": dataset.get("status"),
        "dataset_content_sha256": dataset.get("content_sha256"),
        "dataset_eval_ready": dataset.get("eval_ready"),
        "generated_at": _now(),
        "arms": arms,
        "definitions": {
            "N": "frozen planned final cases",
            "S": "cases with a dispatched first run",
            "R": "cases with an original report",
            "E": "cases with completed semantic review",
            "note": "N is per case set; arm run counts are not added to the case denominator",
        },
        "by_arm": by_arm,
        "admission_blockers": dataset.get("admission_blockers") or [],
        "limitations": [
            "draft dataset: references/expected outcomes/scoring not independently frozen",
            "no real two-arm measurement has been performed",
            "unknown costs remain unknown, never zero",
        ],
    }
    (output_dir / "batch-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = ["# Final batch summary (preparation sample)", "",
             f"- Dataset: `{summary['dataset_id']}` / `{summary['dataset_version']}` / "
             f"status `{summary['dataset_status']}`",
             f"- Dataset SHA-256: `{summary['dataset_content_sha256']}`",
             f"- Arms present: {', '.join(arms)}", ""]
    for arm, data in by_arm.items():
        lines.extend([
            f"## {arm}", "",
            f"- N/S/R/E: {data['N']}/{data['S']}/{data['R']}/{data['E']}",
            f"- Usable reviews: {data['usable']} (rate on E: {data['usable_rate_E']})",
            f"- Major errors: {data['major_errors']}",
            f"- Reports/S: {data['report_rate_R_over_S']}",
            f"- Wall ms P50/P95: {data['wall_ms_p50']}/{data['wall_ms_p95']}",
            f"- Known total tokens: {data['known_total_tokens']} "
            f"(complete {data['token_complete_runs']}/{data['token_total_runs']})",
            f"- Cost: {data['cost']}", "",
        ])
    lines.extend(["## Admission blockers", ""])
    lines.extend(f"- {item}" for item in summary["admission_blockers"])
    (output_dir / "batch-summary.md").write_text("\n".join(lines) + "\n",
                                                 encoding="utf-8")
    return summary


def _collect(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset)
    dataset, dataset_hash = load_batch_dataset(dataset_path, require_admitted=True)
    if args.arm != "candidate":
        raise ValueError("only the candidate arm is integrated; baseline arm is blocked")
    output_dir = Path(args.output_dir)
    if (output_dir / "runs.jsonl").exists() and not args.resume:
        raise ValueError("runs already exist; pass --resume to skip terminal cases")
    output_dir.mkdir(parents=True, exist_ok=True)
    prior = _read_jsonl(output_dir / "runs.jsonl")
    admissions = _read_jsonl(output_dir / "admissions.jsonl")
    done = terminal_case_ids(prior)
    uncertain = uncertain_admitted_case_ids(admissions, done)
    if uncertain:
        raise ValueError(
            "admitted-but-unsettled cases require reconciliation before resume: "
            + ", ".join(sorted(uncertain)))
    cases = [case for case in dataset["cases"]
             if case["id"] not in done and case["id"] not in uncertain]
    if len(cases) > args.max_cases:
        raise ValueError(f"{len(cases)} cases exceed batch max {args.max_cases}")
    if not cases:
        print(json.dumps({"status": "nothing_to_do", "resume_plan":
                          resume_plan(dataset, prior, admissions)}, ensure_ascii=False))
        return 0
    experiment_id = f"final-batch-{uuid.uuid4().hex[:12]}"
    if args.resume and (output_dir / "batch-identity.json").exists():
        previous = json.loads((output_dir / "batch-identity.json").read_text(
            encoding="utf-8"))
        if isinstance(previous.get("experiment_id"), str):
            experiment_id = previous["experiment_id"]
    identity = {
        "schema_version": 1, "experiment_id": experiment_id,
        "created_at": _now(), "dataset": str(dataset_path),
        "dataset_hash": dataset_hash, "dataset_sha256_expected": dataset.get("content_sha256"),
        "arm": args.arm, "api_base": args.api_base, "git_commit": _git_commit(),
        "resume": bool(args.resume), "already_terminal": sorted(done),
        "admitted_unsettled": sorted(uncertain),
        "dispatch_count": len(cases), "max_cases": args.max_cases,
        "batch_wall_max_s": args.max_batch_wall,
    }
    identity_path = output_dir / (
        "batch-identity.json" if not args.resume else
        f"batch-identity-resume-{experiment_id}.json")
    identity_path.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    async def run() -> list[dict]:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(base_url=args.api_base, timeout=timeout) as client:
            health = await client.get("/health")
            if health.status_code != 200:
                raise RuntimeError("durable API health check failed")
            collector = DurableBaselineCollector(
                client, output_dir, experiment_id=experiment_id,
                dataset_hash=dataset_hash,
                options=CollectionOptions(
                    profile=args.arm, repetition=1, concurrency=args.concurrency,
                    poll_interval_seconds=args.poll_interval,
                    case_timeout_seconds=args.case_timeout,
                ),
            )
            return await asyncio.wait_for(
                collector.collect(cases), timeout=args.max_batch_wall)
    records = asyncio.run(run())
    summary = summarize(dataset, output_dir, Path(args.reviews) if args.reviews else None)
    print(json.dumps({"experiment_id": experiment_id, "dispatch_count": len(cases),
                      "summary": {"arms": summary["arms"], "by_arm": summary["by_arm"]}},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--dataset", default="benchmarks/final-batch-v1.json")
    validate.add_argument("--require-admitted", action="store_true")
    resume = sub.add_parser("resume-plan")
    resume.add_argument("--dataset", default="benchmarks/final-batch-v1.json")
    resume.add_argument("--output-dir", required=True)
    summarize_cmd = sub.add_parser("summarize")
    summarize_cmd.add_argument("--dataset", default="benchmarks/final-batch-v1.json")
    summarize_cmd.add_argument("--output-dir", required=True)
    summarize_cmd.add_argument("--reviews")
    collect = sub.add_parser("collect")
    collect.add_argument("--dataset", default="benchmarks/final-batch-v1.json")
    collect.add_argument("--output-dir", required=True)
    collect.add_argument("--api-base", required=True)
    collect.add_argument("--arm", default="candidate", choices=["candidate", "baseline"])
    collect.add_argument("--execute-paid-runs", action="store_true")
    collect.add_argument("--resume", action="store_true")
    collect.add_argument("--reviews")
    collect.add_argument("--concurrency", type=int, default=1)
    collect.add_argument("--max-cases", type=int, default=EXPECTED_FINAL)
    collect.add_argument("--case-timeout", type=float, default=1800.0)
    collect.add_argument("--max-batch-wall", type=float, default=12 * 3600.0)
    collect.add_argument("--poll-interval", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            dataset, digest = load_batch_dataset(Path(args.dataset),
                                                 require_admitted=args.require_admitted)
            print(json.dumps({
                "dataset_id": dataset.get("dataset_id"),
                "version": dataset.get("version"), "status": dataset.get("status"),
                "case_count": len(dataset["cases"]),
                "calibration_count": len(dataset["calibration"]["cases"]),
                "layer_counts": dict(Counter(c["layer"] for c in dataset["cases"])),
                "sha256": digest, "eval_ready": dataset.get("eval_ready"),
                "admission_blockers": dataset.get("admission_blockers"),
            }, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "resume-plan":
            dataset, _ = load_batch_dataset(Path(args.dataset))
            output = Path(args.output_dir)
            records = _read_jsonl(output / "runs.jsonl")
            admissions = _read_jsonl(output / "admissions.jsonl")
            print(json.dumps(resume_plan(dataset, records, admissions),
                             ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "summarize":
            dataset, _ = load_batch_dataset(Path(args.dataset))
            summary = summarize(dataset, Path(args.output_dir),
                                Path(args.reviews) if args.reviews else None)
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if not args.execute_paid_runs:
            raise ValueError("collect requires --execute-paid-runs")
        return _collect(args)
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        print(f"final batch stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
