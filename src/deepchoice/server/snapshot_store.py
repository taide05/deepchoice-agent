"""Persisted research snapshots for one task.

Complete runs keep the single `research_snapshot.json` (the served report state).
Runs that end early (failed or cancelled) persist a *per-attempt* partial
snapshot, because each attempt is inspectable and the latest one is the resume
source: `research_snapshot_failed_attempt{N}.json`. Legacy single-file partial
snapshots (`research_snapshot_failed.json`) are still readable as attempt 1.

Design record: internal_docs/fix_plans/CHECKPOINT_RESUME_DESIGN_2026-11-17.md
(decision D5, milestone M3).
"""
import json
import re
from pathlib import Path

OUTPUT_DIR = Path("./outputs")

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FAILED_SNAPSHOT_RE = re.compile(r"^research_snapshot_failed_attempt(\d+)\.json$")
LEGACY_FAILED_SNAPSHOT_NAME = "research_snapshot_failed.json"


def _valid_task_id(task_id: str) -> bool:
    return bool(_TASK_ID_RE.match(task_id))


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _failed_attempt_numbers(task_id: str) -> list[int]:
    task_dir = OUTPUT_DIR / task_id
    if not task_dir.is_dir():
        return []
    numbers = []
    for path in task_dir.iterdir():
        match = _FAILED_SNAPSHOT_RE.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def failed_snapshot_path(task_id: str, attempt: int) -> Path:
    """Path of one attempt's partial snapshot (per-attempt writes only)."""
    return OUTPUT_DIR / task_id / f"research_snapshot_failed_attempt{max(1, int(attempt))}.json"


def save_snapshot(task_id: str, state: dict) -> Path:
    task_dir = OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = task_dir / "research_snapshot.json"
    serializable = {k: v for k, v in state.items() if k != "current_phase"}
    _atomic_write_text(
        snapshot_path,
        json.dumps(serializable, ensure_ascii=False, indent=2, default=str),
    )
    return snapshot_path


def load_snapshot(task_id: str) -> dict | None:
    if not _valid_task_id(task_id):
        return None
    snapshot_path = OUTPUT_DIR / task_id / "research_snapshot.json"
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def load_failed_snapshot(task_id: str, attempt: int | None = None) -> dict | None:
    """The partial snapshot of one attempt (the latest when `attempt` is None).

    Covers failed and cancelled runs: a run that ended early is inspectable and
    resumable, so its partial state is kept under an attempt-numbered file. When
    no attempt-numbered file exists a legacy single-file partial snapshot is read
    as attempt 1. Returns None when the task never ended early.
    """
    if not _valid_task_id(task_id):
        return None
    if attempt is not None:
        snapshot_path = failed_snapshot_path(task_id, attempt)
        if not snapshot_path.exists() and attempt == 1:
            # A legacy single-file snapshot IS attempt 1; reading it by explicit
            # attempt number must behave the same as the default view.
            legacy_path = OUTPUT_DIR / task_id / LEGACY_FAILED_SNAPSHOT_NAME
            if legacy_path.exists():
                snapshot_path = legacy_path
        if not snapshot_path.exists():
            return None
    else:
        numbers = _failed_attempt_numbers(task_id)
        if numbers:
            snapshot_path = failed_snapshot_path(task_id, numbers[-1])
        else:
            snapshot_path = OUTPUT_DIR / task_id / LEGACY_FAILED_SNAPSHOT_NAME
            if not snapshot_path.exists():
                return None
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    # Snapshots written before the markers existed are still partial attempts:
    # the file itself is the evidence, so the status is not inferred by callers.
    snapshot.setdefault("_status", "failed")
    snapshot.setdefault("_attempt", int(attempt) if attempt is not None else 1)
    return snapshot


def save_failed_snapshot(task_id: str, state: dict, error: str,
                         attempt: int = 1, status: str = "failed") -> Path:
    """Persist one attempt's partial snapshot for inspection and resume.

    `status` is "failed" or "cancelled": both end the run early and both keep the
    checkpoint position needed to resume, but the served status must not lie about
    which one happened. A re-run of the same attempt overwrites its own file.
    """
    attempt = max(1, int(attempt))
    task_dir = OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = failed_snapshot_path(task_id, attempt)
    serializable = {k: v for k, v in state.items() if k != "current_phase"}
    serializable["_error"] = error
    serializable["_status"] = status
    serializable["_attempt"] = attempt
    _atomic_write_text(
        snapshot_path,
        json.dumps(serializable, ensure_ascii=False, indent=2, default=str),
    )
    return snapshot_path


def list_failed_attempts(task_id: str) -> list[dict]:
    """Metadata for every persisted partial attempt, oldest first."""
    attempts = []
    for number in _failed_attempt_numbers(task_id):
        snapshot = load_failed_snapshot(task_id, attempt=number)
        if snapshot is None:
            continue
        attempts.append({
            "attempt": number,
            "status": snapshot.get("_status", "failed"),
            "error": snapshot.get("_error", ""),
        })
    if not attempts:
        legacy = load_failed_snapshot(task_id)
        if legacy is not None:
            attempts.append({
                "attempt": int(legacy.get("_attempt") or 1),
                "status": legacy.get("_status", "failed"),
                "error": legacy.get("_error", ""),
            })
    return attempts


def save_report(task_id: str, report_md: str) -> Path:
    report_path = OUTPUT_DIR / task_id / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(report_path, report_md)
    return report_path


def _task_run_state(task_dir: Path) -> dict:
    """The task's run record (empty when it was never written / unreadable)."""
    try:
        record = json.loads((task_dir / "run_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _task_attempts(task_dir: Path) -> int:
    """Attempts used by the task, from its run record (1 when unreadable)."""
    try:
        return max(1, int(_task_run_state(task_dir).get("attempt") or 1))
    except (TypeError, ValueError):
        return 1


def list_history() -> list[dict]:
    if not OUTPUT_DIR.exists():
        return []
    history = []
    for task_dir in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not task_dir.is_dir():
            continue
        attempts = _task_attempts(task_dir)
        snapshot = load_snapshot(task_dir.name)
        if snapshot:
            history.append({
                "task_id": task_dir.name,
                "query": snapshot.get("task", {}).get("query", ""),
                "confidence": snapshot.get("confidence", ""),
                "status": "complete",
                "attempts": attempts,
            })
            continue
        # A failed/cancelled run is part of the history too: it is inspectable
        # through the same snapshot/status endpoints, so it must not disappear.
        partials = list_failed_attempts(task_dir.name)
        if partials:
            latest = partials[-1]
            latest_snapshot = load_failed_snapshot(task_dir.name,
                                                   latest["attempt"]) or {}
            history.append({
                "task_id": task_dir.name,
                "query": latest_snapshot.get("task", {}).get("query", ""),
                "confidence": latest_snapshot.get("confidence", ""),
                "status": latest["status"],
                "attempts": max(attempts, len(partials)),
                "error": latest["error"],
            })
            continue
        # A run whose process died before it could persist a partial snapshot has
        # only its run record. Show it (as interrupted) instead of vanishing;
        # startup recovery turns it into an inspectable/resumable attempt.
        run_state = _task_run_state(task_dir)
        if run_state:
            recorded_state = str(run_state.get("state") or "unknown")
            history.append({
                "task_id": task_dir.name,
                "query": "",
                "confidence": "",
                "status": ("interrupted" if recorded_state == "running"
                           else recorded_state),
                "attempts": attempts,
                "error": str(run_state.get("detail") or ""),
            })
    return history[:50]
