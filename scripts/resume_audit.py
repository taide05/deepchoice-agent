"""Read-only pre-enable audit for checkpoint resume (M5).

Before turning RESUME_ENABLED on in a deployment, an operator needs to know what
the existing `outputs/` tree will look like to the resume policy: how many tasks
are resumable, how many attempts they already used, why the others cannot be
resumed, and how many dead `running` records startup recovery would pick up.

This script answers those questions **without writing anything** and without
opening the checkpoint database: it reads `run_state.json` and the per-attempt
partial snapshots only. Classification runs the same pure policy as the API
(`deepchoice.server.resume.build_resume_info`) with the feature flag forced on,
so the numbers describe what would happen if resume were enabled today.

Usage:
    python scripts/resume_audit.py [--outputs outputs] [--limit 20] [--json]

Exit codes: 0 = audit produced (even when nothing is resumable); 2 = outputs
directory missing (nothing to audit).

Design record: internal_docs/fix_plans/CHECKPOINT_RESUME_DESIGN_2026-11-17.md
(M5 rollout/verification).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Runnable as a plain script: `src/` for the package and the repo root for the
# root-level `run_limits.py` module (the server runs with the repo root as cwd).
for _path in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from deepchoice.server import snapshot_store  # noqa: E402
from deepchoice.server.recovery import (  # noqa: E402
    RECOVERY_GRACE_S,
    is_stale_run_record,
)
from deepchoice.server.resume import (  # noqa: E402
    build_resume_info,
    max_attempts,
    read_task_run_state,
)
import run_limits  # noqa: E402


def _status_of(complete: bool, failed: dict | None, run_state: dict) -> str:
    if complete:
        return "complete"
    if failed and failed.get("_status"):
        return str(failed["_status"])
    recorded = str(run_state.get("state") or "").strip()
    return recorded or "unknown"


def scan(outputs_dir: Path, *, now: float | None = None) -> dict:
    """Classify every task under `outputs_dir` as the resume policy would see it."""
    outputs_dir = Path(outputs_dir)
    current_time = time.time() if now is None else float(now)
    current_schema = run_limits.GRAPH_SCHEMA_VERSION
    old_output_dir = snapshot_store.OUTPUT_DIR
    old_flag = os.environ.get("RESUME_ENABLED")
    # Classify as if the feature were on; restored in the finally block so the
    # surrounding process (a shell or another script step) is unaffected.
    os.environ["RESUME_ENABLED"] = "1"
    snapshot_store.OUTPUT_DIR = outputs_dir
    try:
        records = []
        if outputs_dir.exists():
            for task_dir in sorted(path for path in outputs_dir.iterdir()
                                   if path.is_dir()):
                task_id = task_dir.name
                complete = (task_dir / "research_snapshot.json").exists()
                failed = None if complete else snapshot_store.load_failed_snapshot(task_id)
                run_state = read_task_run_state(task_dir)
                info = build_resume_info(
                    complete_snapshot={"task": {}} if complete else None,
                    failed_snapshot=failed,
                    run_state=run_state,
                    current_schema_version=current_schema,
                )
                stale_running = (
                    # A completed task can still carry an old `running` run record
                    # (historical outputs written before the record was finalized);
                    # it cannot need recovery, so it is not a candidate.
                    not complete
                    and str(run_state.get("state") or "") == "running"
                    and is_stale_run_record(run_state, current_time, RECOVERY_GRACE_S)
                )
                records.append({
                    "task_id": task_id,
                    "status": _status_of(complete, failed, run_state),
                    "attempts": int(run_state.get("attempt") or info["attempt"] or 1),
                    "attempt_cap": info["max_attempts"],
                    "resumable": info["resumable"],
                    "reason": info["reason"],
                    "next_nodes": info["next_nodes"],
                    "stale_running": stale_running,
                })
    finally:
        snapshot_store.OUTPUT_DIR = old_output_dir
        if old_flag is None:
            os.environ.pop("RESUME_ENABLED", None)
        else:
            os.environ["RESUME_ENABLED"] = old_flag

    db_path = outputs_dir / "checkpoints.db"
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    status_counts = Counter(record["status"] for record in records)
    reason_counts = Counter(record["reason"] for record in records
                            if not record["resumable"])
    attempt_counts = Counter(record["attempts"] for record in records
                             if not record["resumable"])
    resumable = [record for record in records if record["resumable"]]
    stale = [record for record in records if record["stale_running"]]
    return {
        "generated_at_epoch": current_time,
        "outputs_dir": str(outputs_dir),
        "current_schema_version": current_schema,
        "attempt_cap": max_attempts(),
        "checkpoint_db": {
            "present": db_path.exists(),
            "size_mb": round(db_bytes / (1024 * 1024), 1) if db_bytes else 0.0,
        },
        "summary": {
            "tasks_scanned": len(records),
            "status_counts": dict(status_counts),
            "resumable_count": len(resumable),
            "not_resumable_count": len(records) - len(resumable),
            "reason_counts": dict(reason_counts),
            "not_resumable_attempt_counts": dict(attempt_counts),
            "stale_running_count": len(stale),
        },
        "resumable": resumable,
        "stale_running": stale,
    }


def _human_report(report: dict, limit: int) -> str:
    summary = report["summary"]
    db = report["checkpoint_db"]
    db_text = (f"{db['size_mb']} MB" if db["present"] else "missing")
    lines = [
        "Checkpoint resume pre-enable audit (read-only)",
        f"outputs: {report['outputs_dir']}",
        f"checkpoint db: {db_text}",
        f"graph schema v{report['current_schema_version']}, attempt cap "
        f"{report['attempt_cap']} (flag forced on for classification)",
        "",
        f"tasks scanned: {summary['tasks_scanned']}",
        "status: " + ", ".join(f"{name}={count}"
                               for name, count in sorted(summary["status_counts"].items()))
        if summary["status_counts"] else "status: none",
        f"resumable: {summary['resumable_count']} / "
        f"{summary['tasks_scanned']} partial tasks",
        f"startup-recovery candidates (stale running records): "
        f"{summary['stale_running_count']}",
    ]
    if summary["reason_counts"]:
        lines.append("not resumable reasons: " + ", ".join(
            f"{name}={count}" for name, count in sorted(summary["reason_counts"].items())))
    if summary["not_resumable_attempt_counts"]:
        lines.append("not resumable attempts: " + ", ".join(
            f"{attempts}x={count}" for attempts, count in
            sorted(summary["not_resumable_attempt_counts"].items())))
    if report["resumable"]:
        lines += ["", f"resumable tasks (up to {limit}):"]
        for record in report["resumable"][:limit]:
            lines.append(
                f"  {record['task_id']}: status={record['status']} "
                f"attempts={record['attempts']}/{record['attempt_cap']} "
                f"next={','.join(record['next_nodes']) or '-'}")
        if len(report["resumable"]) > limit:
            lines.append(f"  ... {len(report['resumable']) - limit} more")
    if report["stale_running"]:
        lines += ["", f"startup-recovery candidates (up to {limit}):"]
        for record in report["stale_running"][:limit]:
            lines.append(f"  {record['task_id']}: attempt {record['attempts']}")
    lines += [
        "",
        "Notes:",
        "- resumable = would be accepted by POST /research/{id}/resume if the flag",
        "  were on and the metadata still matches the checkpoint database at request",
        "  time (the endpoint re-probes pending nodes before starting).",
        "- stale running records are those past their own wall-clock limit plus the",
        "  recovery grace; startup recovery checks the checkpoint for pending nodes.",
        "- This audit writes nothing and does not open the checkpoint database.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only pre-enable audit for checkpoint resume.")
    parser.add_argument(
        "--outputs",
        default=os.environ.get("DEEPCHOICE_OUTPUT_DIR") or str(REPO_ROOT / "outputs"),
        help="outputs directory to audit (default: $DEEPCHOICE_OUTPUT_DIR or <repo>/outputs)")
    parser.add_argument("--limit", type=int, default=20,
                        help="max task ids listed per section (default: 20)")
    parser.add_argument("--json", action="store_true",
                        help="print a JSON report instead of the human summary")
    parser.add_argument("--now", type=float, default=None,
                        help="reference epoch for staleness (testing only)")
    args = parser.parse_args(argv)
    outputs_dir = Path(args.outputs)
    if not outputs_dir.exists():
        print(f"outputs directory not found: {outputs_dir}", file=sys.stderr)
        return 2
    report = scan(outputs_dir, now=args.now)
    if args.json:
        report = dict(report)
        report["resumable"] = report["resumable"][:max(args.limit, 0)]
        report["stale_running"] = report["stale_running"][:max(args.limit, 0)]
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_human_report(report, max(args.limit, 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
