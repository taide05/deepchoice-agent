"""Pre-enable resume audit (M5): read-only classification of the outputs tree."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

from deepchoice.server import snapshot_store

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "resume_audit.py"
SCHEMA = 3


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("resume_audit_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load_audit_module()


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    root.mkdir()
    monkeypatch.setattr(snapshot_store, "OUTPUT_DIR", root)
    return root


def _write_run_state(task_dir: Path, **overrides) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "task_id": task_dir.name,
        "state": "failed",
        "attempt": 1,
        "graph_schema_version": SCHEMA,
        "started_at_epoch": time.time() - 60,
        "wall_clock_max_s": 900,
    }
    record.update(overrides)
    (task_dir / "run_state.json").write_text(json.dumps(record), encoding="utf-8")


def _save_partial(task_id: str, *, status="failed", next_nodes=("evidence_chain",),
                  error="boom") -> None:
    snapshot = {"task": {"query": "q"}, "confidence": "low"}
    if next_nodes is not None:
        snapshot["_resume"] = {"attempt": 1, "max_attempts": 2,
                               "next_nodes": list(next_nodes), "checkpoint_step": 4}
    snapshot_store.save_failed_snapshot(task_id, snapshot, error, attempt=1,
                                        status=status)


def _build_tree(outputs: Path) -> None:
    # complete
    snapshot_store.save_snapshot("done_task", {"task": {"query": "done"}})
    _write_run_state(outputs / "done_task", state="complete")
    # resumable failed
    _save_partial("failed_task", status="failed")
    _write_run_state(outputs / "failed_task", state="failed", attempt=1)
    # resumable cancelled
    _save_partial("cancelled_task", status="cancelled")
    _write_run_state(outputs / "cancelled_task", state="cancelled", attempt=1)
    # attempts exhausted
    _save_partial("exhausted_task")
    _write_run_state(outputs / "exhausted_task", attempt=2)
    # schema mismatch
    _save_partial("schema_task")
    _write_run_state(outputs / "schema_task", graph_schema_version=SCHEMA - 1)
    # failed snapshot but no checkpoint position
    _save_partial("no_ckpt_task", next_nodes=None)
    _write_run_state(outputs / "no_ckpt_task")
    # completed task that still carries an old `running` run record: it must not
    # be reported as a startup-recovery candidate
    snapshot_store.save_snapshot("done_stale_task", {"task": {"query": "done2"}})
    _write_run_state(outputs / "done_stale_task", state="running",
                     started_at_epoch=time.time() - 7200)
    # stale running record (startup recovery candidate)
    _write_run_state(outputs / "stale_task", state="running",
                     started_at_epoch=time.time() - 7200)
    # fresh running record (not stale)
    _write_run_state(outputs / "fresh_task", state="running",
                     started_at_epoch=time.time())


def test_scan_classifies_every_task_without_writing(outputs):
    _build_tree(outputs)
    before = sorted(str(p.relative_to(outputs)) for p in outputs.rglob("*"))

    report = audit.scan(outputs)

    after = sorted(str(p.relative_to(outputs)) for p in outputs.rglob("*"))
    assert before == after, "the audit must not create or modify files"
    summary = report["summary"]
    assert summary["tasks_scanned"] == 9
    assert summary["status_counts"]["complete"] == 2
    assert summary["status_counts"]["failed"] == 4
    assert summary["status_counts"]["cancelled"] == 1
    assert summary["status_counts"]["running"] == 2
    assert summary["resumable_count"] == 2
    assert summary["not_resumable_count"] == 7
    assert summary["reason_counts"] == {
        "already_complete": 2,
        "attempts_exhausted": 1,
        "schema_mismatch": 1,
        "no_checkpoint": 3,
    }
    assert summary["stale_running_count"] == 1
    resumable_ids = {record["task_id"] for record in report["resumable"]}
    assert resumable_ids == {"failed_task", "cancelled_task"}
    stale_ids = {record["task_id"] for record in report["stale_running"]}
    assert stale_ids == {"stale_task"}, "a completed task is not a recovery candidate"
    assert report["checkpoint_db"]["present"] is False
    assert report["attempt_cap"] == 2
    assert report["current_schema_version"] == SCHEMA


def test_scan_reports_a_malformed_task_without_a_run_record(outputs):
    _save_partial("orphan_task")
    report = audit.scan(outputs)
    assert report["summary"]["reason_counts"] == {"no_run_record": 1}
    assert report["summary"]["status_counts"]["failed"] == 1


def test_scan_restores_flag_and_snapshot_store_globals(outputs, monkeypatch):
    monkeypatch.delenv("RESUME_ENABLED", raising=False)
    original_output_dir = snapshot_store.OUTPUT_DIR

    audit.scan(outputs)

    assert "RESUME_ENABLED" not in __import__("os").environ
    assert snapshot_store.OUTPUT_DIR == original_output_dir


def test_cli_json_report_and_limit(outputs, capsys):
    _build_tree(outputs)
    exit_code = audit.main(["--outputs", str(outputs), "--json", "--limit", "1"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["resumable_count"] == 2
    assert len(payload["resumable"]) == 1  # --limit truncates only the listing
    assert payload["summary"]["stale_running_count"] == 1


def test_cli_missing_outputs_returns_2(tmp_path, capsys):
    exit_code = audit.main(["--outputs", str(tmp_path / "missing")])
    assert exit_code == 2
    assert "not found" in capsys.readouterr().err


def test_checkpoint_db_size_is_reported_when_present(outputs):
    (outputs / "checkpoints.db").write_bytes(b"x" * 1024)
    report = audit.scan(outputs)
    assert report["checkpoint_db"]["present"] is True
    assert report["checkpoint_db"]["size_mb"] == pytest.approx(0.0, abs=0.1)
