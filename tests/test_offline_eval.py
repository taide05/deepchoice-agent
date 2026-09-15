from __future__ import annotations

import copy
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks import run_offline_eval as offline


def test_smoke_dataset_is_frozen_and_balanced():
    dataset, digest = offline.load_dataset(offline.DEFAULT_DATASET)

    assert digest == offline._sha256_bytes(offline.DEFAULT_DATASET.read_bytes())
    assert dataset["dataset_id"] == "deepchoice-offline-smoke"
    assert dataset["version"] == "smoke-v1"
    assert dataset["freeze_date"] == "2026-09-15"
    assert len(dataset["cases"]) == 12
    assert {
        stage: sum(case["stage"] == stage for case in dataset["cases"])
        for stage in offline.EXPECTED_STAGES
    } == {stage: 3 for stage in offline.EXPECTED_STAGES}


def test_offline_eval_meets_contract_and_thresholds():
    artifact = offline.evaluate_dataset()

    assert offline.thresholds_pass(artifact)
    assert artifact["artifact_schema_version"] == 1
    assert artifact["case_count"] == artifact["evaluated_case_count"] == 12
    assert artifact["execution_mode"] == "fixture_replay"
    assert artifact["judge"] == "none"
    assert len(artifact["current_manifest_id"]) == 64
    assert len(artifact["core_asset_registry_id"]) == 64
    assert artifact["source_health"] == {
        "status": "not_run",
        "default_sources": {
            source: "degraded/unmeasured" for source in offline.DEFAULT_RETRIEVAL_SOURCES
        },
    }
    assert artifact["metrics"]["overall"] == {
        "numerator": 12,
        "denominator": 12,
        "rate": 1.0,
    }
    assert artifact["metrics"]["deterministic_replay"]["rate"] == 1.0
    assert all(case["passed"] and case["deterministic"] for case in artifact["cases"])

    for metric in artifact["metrics"].values():
        assert set(metric) == {"numerator", "denominator", "rate"}
    for template in ("what_why_how", "evidence_first", "comparison_matrix"):
        metric = artifact["metrics"][f"report.{template}.quality"]
        assert metric["numerator"] >= 4
        assert metric["denominator"] == 5
    assert artifact["metrics"]["report.structure"]["rate"] == 1.0


def test_fingerprint_excludes_runtime_provenance_metadata():
    artifact = offline.evaluate_dataset()
    changed = copy.deepcopy(artifact)
    changed["evaluated_at"] = "2099-01-01T00:00:00+00:00"
    changed["current_manifest_id"] = "f" * 64
    changed["artifact_fingerprint"] = "not-part-of-input"

    assert offline.artifact_fingerprint(changed) == artifact["artifact_fingerprint"]

    changed["metrics"]["overall"]["numerator"] = 11
    assert offline.artifact_fingerprint(changed) != artifact["artifact_fingerprint"]


def test_checked_in_baseline_is_self_consistent_and_current():
    artifact = offline.evaluate_dataset()
    baseline = json.loads(offline.DEFAULT_BASELINE.read_text(encoding="utf-8"))

    assert baseline["artifact_fingerprint"] == offline.artifact_fingerprint(baseline)
    assert offline._check_baseline(offline.DEFAULT_BASELINE, artifact)
    assert baseline["dataset"]["file_sha256"] == artifact["dataset"]["file_sha256"]


def test_eval_cannot_call_network_llm_dotenv_or_create_outbound_resolver(monkeypatch):
    import dotenv
    import deepchoice.outbound as outbound
    from deepchoice.agents import conclusion_synthesizer, query_analyzer
    from deepchoice.citations import verifier

    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline evaluation crossed a live dependency boundary")

    async def forbidden_async(*_args, **_kwargs):
        forbidden()

    outbound.set_resolver(None)
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(query_analyzer, "call_model", forbidden_async)
    monkeypatch.setattr(conclusion_synthesizer, "call_model", forbidden_async)
    monkeypatch.setattr(verifier, "safe_fetch", forbidden_async)

    artifact = offline.evaluate_dataset()

    assert offline.thresholds_pass(artifact)
    assert outbound._resolver is None


def test_cli_checks_baseline_without_credentials(tmp_path):
    output = tmp_path / "offline-result.json"
    env = {
        key: value
        for key, value in __import__("os").environ.items()
        if not key.endswith("_API_KEY") and key not in {"TAVILY_API_KEYS", "GITHUB_TOKEN"}
    }
    # The manifest records this deployment setting, but fixture results and
    # their checked-in baseline must remain independent from it.
    env["DEEPCHOICE_SYNTH_THINKING"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.run_offline_eval",
            "--check-baseline",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    summary = json.loads(completed.stdout)
    assert summary["passed"] is True
    assert summary["baseline_matches"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["execution_mode"] == "fixture_replay"


def test_dataset_validation_rejects_case_drift():
    dataset, _ = offline.load_dataset(offline.DEFAULT_DATASET)
    dataset["cases"].pop()

    with pytest.raises(offline.OfflineEvalError, match="exactly 12"):
        offline._validate_dataset(dataset)


def test_tampered_baseline_does_not_match(tmp_path):
    artifact = offline.evaluate_dataset()
    tampered = copy.deepcopy(artifact)
    tampered["metrics"]["overall"]["numerator"] = 11
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    assert offline._check_baseline(path, artifact) is False
