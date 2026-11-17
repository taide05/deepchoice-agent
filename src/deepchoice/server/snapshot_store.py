import json
import re
from pathlib import Path

OUTPUT_DIR = Path("./outputs")

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _valid_task_id(task_id: str) -> bool:
    return bool(_TASK_ID_RE.match(task_id))


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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


def load_failed_snapshot(task_id: str) -> dict | None:
    """The partial snapshot persisted for a run that ended in failure.

    A failed run is still inspectable: the server saves whatever the checkpoint
    held when the exception ended the run, plus the error that ended it. Returns
    None when the task never failed (or has no persisted failure at all).
    """
    if not _valid_task_id(task_id):
        return None
    snapshot_path = OUTPUT_DIR / task_id / "research_snapshot_failed.json"
    if not snapshot_path.exists():
        return None
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    # Failed snapshots written before this marker existed are still failures: the
    # file itself is the evidence, so the status is not inferred from the caller.
    snapshot.setdefault("_status", "failed")
    return snapshot


def save_failed_snapshot(task_id: str, state: dict, error: str) -> Path:
    task_dir = OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = task_dir / "research_snapshot_failed.json"
    serializable = {k: v for k, v in state.items() if k != "current_phase"}
    serializable["_error"] = error
    serializable["_status"] = "failed"
    _atomic_write_text(
        snapshot_path,
        json.dumps(serializable, ensure_ascii=False, indent=2, default=str),
    )
    return snapshot_path


def save_report(task_id: str, report_md: str) -> Path:
    report_path = OUTPUT_DIR / task_id / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(report_path, report_md)
    return report_path


def list_history() -> list[dict]:
    if not OUTPUT_DIR.exists():
        return []
    history = []
    for task_dir in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not task_dir.is_dir():
            continue
        snapshot = load_snapshot(task_dir.name)
        if snapshot:
            history.append({
                "task_id": task_dir.name,
                "query": snapshot.get("task", {}).get("query", ""),
                "confidence": snapshot.get("confidence", ""),
                "status": "complete",
            })
            continue
        # A failed run is part of the history too: it is inspectable through the
        # same snapshot/status endpoints, so it must not silently disappear.
        failed = load_failed_snapshot(task_dir.name)
        if failed:
            history.append({
                "task_id": task_dir.name,
                "query": failed.get("task", {}).get("query", ""),
                "confidence": failed.get("confidence", ""),
                "status": "failed",
                "error": failed.get("_error", ""),
            })
    return history[:50]
