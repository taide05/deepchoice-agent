"""Recover research tasks whose process died before it could persist its state.

A forced stop (launcher guard, crash, OOM) leaves `outputs/{task_id}/run_state.json`
with `state: running` and a checkpoint that may still have pending nodes. Those
tasks used to be invisible to /status and /history and could not be resumed,
because the resume policy needs the checkpoint position that a graceful
failure/cancellation saves into a partial snapshot.

At startup, when the resume feature is enabled, this module sweeps such records:
if the record is clearly past its own deadline and the checkpoint still has
pending nodes, it persists an `interrupted` partial attempt snapshot (with the
usual `_resume` metadata) and marks the run record interrupted. From then on the
normal failed/cancelled endpoints apply — the task is inspectable and resumable.

Design record: internal_docs/fix_plans/CHECKPOINT_RESUME_DESIGN_2026-11-17.md
(review finding R1).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Grace beyond the run's own wall-clock limit before a "running" record is
# considered dead. It covers clock skew and the moment the record is written.
RECOVERY_GRACE_S = float(os.environ.get("RESUME_RECOVERY_GRACE_S", "30"))

INTERRUPTED_STATUS = "interrupted"
INTERRUPTED_ERROR = "research interrupted: the process stopped before the run finished"


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_run_state(task_dir: Path) -> dict:
    try:
        data = json.loads((Path(task_dir) / "run_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_stale_run_record(record: dict, now: float, grace_s: float) -> bool:
    """True when a `running` record is past its own deadline plus the grace.

    The clock is the record's own start and limit, so no pid probing is needed
    (and `os.kill(pid, 0)` is not portable — on Windows it can terminate).
    """
    started = record.get("started_at_epoch")
    if not isinstance(started, (int, float)) or started <= 0:
        return False
    try:
        wall_clock = float(record.get("wall_clock_max_s") or 0.0)
    except (TypeError, ValueError):
        wall_clock = 0.0
    return now > float(started) + max(wall_clock, 0.0) + grace_s


def _mark_interrupted(task_dir: Path, detail: str, now: float) -> None:
    record = read_run_state(task_dir)
    record["state"] = INTERRUPTED_STATUS
    record["detail"] = detail
    record["interrupted_at_epoch"] = now
    _atomic_write_json(task_dir / "run_state.json", record)


async def recover_interrupted_tasks(outputs_dir: Path, *,
                                    now: float | None = None,
                                    grace_s: float | None = None) -> list[str]:
    """Persist an interrupted partial snapshot for every dead `running` task.

    Returns the task ids that were processed (whether or not a checkpoint had
    pending nodes). Never raises for a single broken task; the caller (app
    startup) must not fail because of recovery.
    """
    outputs_dir = Path(outputs_dir)
    if not outputs_dir.exists():
        return []
    current_time = time.time() if now is None else float(now)
    grace = RECOVERY_GRACE_S if grace_s is None else float(grace_s)

    candidates: list[tuple[Path, dict]] = []
    for task_dir in outputs_dir.iterdir():
        if not task_dir.is_dir():
            continue
        # A completed task can still carry an old `running` run record (outputs
        # written before the record was finalized). It cannot need recovery, and
        # probing the checkpoint for it would only delay startup.
        if (task_dir / "research_snapshot.json").exists():
            continue
        record = read_run_state(task_dir)
        if record.get("state") != "running":
            continue
        if not is_stale_run_record(record, current_time, grace):
            continue
        candidates.append((task_dir, record))
    if not candidates:
        return []

    # Imported lazily: this module is only exercised at startup or in tests.
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..agents.orchestrator import ChiefEditorAgent
    from . import snapshot_store
    from .resume import build_resume_metadata

    processed: list[str] = []
    db_path = outputs_dir / "checkpoints.db"
    conn = None
    try:
        if db_path.exists():
            conn = await aiosqlite.connect(str(db_path))
        saver = AsyncSqliteSaver(conn) if conn is not None else None
        for task_dir, record in candidates:
            task_id = task_dir.name
            try:
                attempt = max(1, int(record.get("attempt") or 1))
                detail = "process stopped before the run finished; no checkpoint store"
                if saver is not None:
                    probe = ChiefEditorAgent({}, checkpointer=saver,
                                             thread_id=task_id)
                    state = await probe.get_state()
                    next_nodes = list(getattr(state, "next", None) or ())
                    if state is not None and next_nodes:
                        partial = dict(state.values or {})
                        partial["_resume"] = build_resume_metadata(state, attempt)
                        snapshot_store.save_failed_snapshot(
                            task_id, partial, INTERRUPTED_ERROR,
                            attempt=attempt, status=INTERRUPTED_STATUS)
                        detail = ("process stopped before the run finished; "
                                  "partial checkpoint persisted")
                    else:
                        detail = ("process stopped before the run finished; "
                                  "no pending checkpoint nodes")
                _mark_interrupted(task_dir, detail, current_time)
                processed.append(task_id)
            except Exception:
                # One broken task must not stop the sweep.
                continue
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
    return processed
