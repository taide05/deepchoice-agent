"""Resume decisions for the research API (M2 of the checkpoint-resume design).

Kept separate from `app.py` so the decision is a pure function over the persisted
records: the complete snapshot, the failed snapshot (with its `_resume`
metadata) and the task's `run_state.json`. The resume endpoint and `/status`
derive the same answer from the same inputs.

Policy (design D2/D3, internal_docs/fix_plans/CHECKPOINT_RESUME_DESIGN_2026-11-17.md):
  * disabled unless RESUME_ENABLED=1;
  * only a failed task with pending checkpoint nodes is resumable;
  * the task's run record must have been written by the current graph schema;
  * at most RESUME_MAX_ATTEMPTS attempts per task (default 2).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MAX_ATTEMPTS = 2

# Reason codes; app.py maps them to HTTP error codes.
REASON_FEATURE_DISABLED = "feature_disabled"
REASON_ALREADY_COMPLETE = "already_complete"
REASON_NO_RUN_RECORD = "no_run_record"
REASON_SCHEMA_MISMATCH = "schema_mismatch"
REASON_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
REASON_NO_CHECKPOINT = "no_checkpoint"


def resume_enabled() -> bool:
    """Feature flag, read per call so the endpoint can be toggled without a code change."""
    return os.environ.get("RESUME_ENABLED", "0") == "1"


def max_attempts() -> int:
    """Per-task attempt cap. An invalid/zero value falls back to the default."""
    raw = os.environ.get("RESUME_MAX_ATTEMPTS", "")
    try:
        value = int(raw) if raw else DEFAULT_MAX_ATTEMPTS
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return value if value > 0 else DEFAULT_MAX_ATTEMPTS


def read_task_run_state(task_dir: Path) -> dict:
    """The task's run record, or {} when it was never written / is unreadable."""
    path = Path(task_dir) / "run_state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _failed_resume_meta(failed_snapshot: dict | None) -> dict:
    if not isinstance(failed_snapshot, dict):
        return {}
    meta = failed_snapshot.get("_resume")
    return meta if isinstance(meta, dict) else {}


def build_resume_metadata(state, attempt: int) -> dict:
    """Checkpoint position saved into a partial snapshot for a later resume.

    Pure: reads the LangGraph StateSnapshot attributes, nothing else.
    """
    next_nodes = list(getattr(state, "next", None) or ())
    metadata = getattr(state, "metadata", None)
    step = metadata.get("step") if isinstance(metadata, dict) else None
    return {
        "attempt": max(1, int(attempt)),
        "max_attempts": max_attempts(),
        "next_nodes": [str(node) for node in next_nodes],
        "checkpoint_step": step,
    }


def build_resume_info(*, complete_snapshot: dict | None,
                      failed_snapshot: dict | None,
                      run_state: dict,
                      current_schema_version: int) -> dict:
    """Whether this task can be resumed, and why not when it cannot.

    Pure: no I/O, no feature-flag side effects beyond reading the environment.
    """
    attempt = int(run_state.get("attempt") or 0)
    meta = _failed_resume_meta(failed_snapshot)
    next_nodes = [str(node) for node in (meta.get("next_nodes") or [])]
    limit = max_attempts()
    info = {
        "attempt": attempt if attempt > 0 else 1,
        "max_attempts": limit,
        "next_nodes": next_nodes,
        "next_node": next_nodes[0] if next_nodes else None,
        "checkpoint_step": meta.get("checkpoint_step"),
        "resumable": False,
        "reason": None,
    }
    # The capability flag wins first: with resume disabled even a completed task
    # is reported as "feature disabled" by the pure function. (The endpoint checks
    # the flag before calling this, for the same reason.)
    if not resume_enabled():
        info["reason"] = REASON_FEATURE_DISABLED
        return info
    if complete_snapshot:
        info["reason"] = REASON_ALREADY_COMPLETE
        return info
    if not run_state:
        info["reason"] = REASON_NO_RUN_RECORD
        return info
    if run_state.get("graph_schema_version") != current_schema_version:
        info["reason"] = REASON_SCHEMA_MISMATCH
        return info
    if attempt <= 0:
        info["reason"] = REASON_NO_RUN_RECORD
        return info
    if attempt >= limit:
        info["reason"] = REASON_ATTEMPTS_EXHAUSTED
        return info
    if not next_nodes:
        info["reason"] = REASON_NO_CHECKPOINT
        return info
    info["resumable"] = True
    return info
