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


def save_failed_snapshot(task_id: str, state: dict, error: str) -> Path:
    task_dir = OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = task_dir / "research_snapshot_failed.json"
    serializable = {k: v for k, v in state.items() if k != "current_phase"}
    serializable["_error"] = error
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
    for task_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if task_dir.is_dir():
            snapshot = load_snapshot(task_dir.name)
            if snapshot:
                history.append({
                    "task_id": task_dir.name,
                    "query": snapshot.get("task", {}).get("query", ""),
                    "confidence": snapshot.get("confidence", ""),
                })
    return history[:50]
