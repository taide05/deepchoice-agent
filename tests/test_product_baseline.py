from __future__ import annotations

import csv
import json
from pathlib import Path

import httpx
import pytest

from benchmarks import product_baseline as baseline
from benchmarks.product_baseline import (
    CollectionOptions,
    DurableBaselineCollector,
    build_parser,
    compare_profiles,
    load_dataset,
    load_environment,
    usage_projection,
    write_collection_summary,
)
from benchmarks.product_baseline_server import create_app


DATASET = Path("benchmarks/product-baseline-v1.json")


def test_frozen_dataset_has_twelve_valid_cases_and_candidate_cannot_run(tmp_path):
    dataset, digest = load_dataset(DATASET, require_frozen=True)
    assert len(dataset["cases"]) == 12
    assert len(digest) == 64
    assert [case["id"] for case in dataset["cases"]] == [
        f"P{index:02d}" for index in range(1, 13)
    ]
    assert dataset["version"] == "1.0.0"
    candidate = tmp_path / "candidate.json"
    dataset["status"] = "candidate"
    candidate.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(ValueError, match="requires a frozen dataset"):
        load_dataset(candidate, require_frozen=True)


def test_candidate_environment_manifest_blocks_paid_collection():
    environment, digest = load_environment(
        Path("benchmarks/product-baseline-environment.example.json")
    )
    assert environment["status"] == "candidate"
    assert len(digest) == 64
    with pytest.raises(ValueError, match="requires a ready environment manifest"):
        load_environment(
            Path("benchmarks/product-baseline-environment.example.json"),
            require_ready=True,
        )


def test_experiment_server_factory_isolates_runtime_databases(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    monkeypatch.setenv("DEEPCHOICE_EXPERIMENT_DIR", str(root))
    from deepchoice.server import app as app_module

    monkeypatch.setattr(app_module.app.state, "product_database_path", None, raising=False)
    monkeypatch.setattr(app_module.app.state, "checkpoint_database_path", None, raising=False)
    monkeypatch.setattr(app_module.app.state, "legacy_snapshot_root", None, raising=False)
    monkeypatch.setattr(app_module.app.state, "auto_recovery_enabled", True, raising=False)
    application = create_app()
    assert application.state.product_database_path == root / "product.db"
    assert application.state.checkpoint_database_path == root / "checkpoints.db"
    assert application.state.legacy_snapshot_root == root / "legacy-import-disabled"
    assert application.state.auto_recovery_enabled is False


@pytest.mark.asyncio
@pytest.mark.parametrize("requeue_after_resolution", [False, True])
async def test_collector_handles_hitl_and_preserves_unknown_observability(tmp_path, requeue_after_resolution):
    case = load_dataset(DATASET)[0]["cases"][7]
    task_reads = 0
    decision_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal task_reads, decision_reads
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-1", "status": "queued", "version": 0},
                    "latest_run": {
                        "run_id": "run-1",
                        "manifest_id": "manifest-1",
                    },
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-1":
            task_reads += 1
            statuses = (["running", "waiting_for_input", "queued", "running", "waiting_for_input", "completed"]
                        if requeue_after_resolution else ["waiting_for_input", "waiting_for_input", "completed"])
            status = statuses[min(task_reads - 1, len(statuses) - 1)]
            return httpx.Response(
                200,
                json={
                    "task": {"task_id": "task-1", "status": status, "version": 2},
                    "latest_run": {
                        "run_id": "run-1",
                        "manifest_id": "manifest-1",
                    },
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-1/decision":
            decision_reads += 1
            return httpx.Response(200, json={"decision_id": f"decision-{decision_reads}"})
        if request.method == "POST" and path.endswith("/decisions/decision-1"):
            assert request.headers["if-match"] == "2"
            assert json.loads(request.content) == {
                "action": "provide_context",
                "supplemental_input": case["hitl"]["supplemental_input"],
            }
            return httpx.Response(202, json={"replayed": False})
        if request.method == "POST" and path.endswith("/decisions/decision-2"):
            assert json.loads(request.content) == {"action": "limited_report"}
            return httpx.Response(202, json={"replayed": False})
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={
                    "availability": "available",
                    "totals": {
                        "total_tokens": None,
                        "token_usage_complete": False,
                    },
                },
            )
        if request.method == "GET" and path.endswith("/snapshot"):
            return httpx.Response(200, json={"final_recommendation": "bounded"})
        if request.method == "GET" and path.endswith("/report"):
            return httpx.Response(200, json={"report": "# bounded report"})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-1",
            dataset_hash="a" * 64,
            options=options,
        )
        result = (await collector.collect([case]))[0]

    assert result["status"] == "completed"
    assert result["hitl_resolutions"] == 2
    assert result["observability"]["totals"]["total_tokens"] is None
    assert result["observability"]["totals"]["token_usage_complete"] is False
    assert json.loads((tmp_path / result["snapshot_path"]).read_text(encoding="utf-8")) == {
        "final_recommendation": "bounded"
    }
    assert (tmp_path / result["report_path"]).read_text(encoding="utf-8") == "# bounded report"
    persisted = json.loads((tmp_path / "runs.jsonl").read_text(encoding="utf-8"))
    assert persisted["run_id"] == "run-1"
    assert "supplemental_input" not in persisted
    journal = [json.loads(line) for line in (tmp_path / "admissions.jsonl").read_text().splitlines()]
    assert [entry["event"] for entry in journal] == ["submission_started", "admitted"]
    assert journal[1]["run_id"] == "run-1"
    assert "supplemental_input" not in json.dumps(journal)


@pytest.mark.asyncio
async def test_collector_can_stop_at_public_pending_hitl_without_resolution(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][7]
    decision_posts = 0
    cancel_posts = 0
    task_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal decision_posts, cancel_posts, task_reads
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-stop", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run-stop", "manifest_id": "manifest-stop"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-stop":
            task_reads += 1
            return httpx.Response(
                200,
                json={
                    "task": {"task_id": "task-stop", "status": "waiting_for_input", "version": 7},
                    "latest_run": {"run_id": "run-stop", "manifest_id": "manifest-stop"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-stop/decision":
            return httpx.Response(
                200,
                json={
                    "decision_id": "decision-stop",
                    "kind": "evidence-insufficient",
                    "status": "pending",
                    "reason": "insufficient evidence",
                    "allowed_actions": ["provide_context", "limited_report", "cancel"],
                },
            )
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={
                    "availability": "available",
                    "run_id": "run-stop",
                    "totals": {"total_tokens": None, "token_usage_complete": False},
                },
            )
        if request.method == "POST" and "/decisions/" in path:
            decision_posts += 1
            raise AssertionError("stop-at-hitl must not submit a resolution")
        if request.method == "POST" and path.endswith("/cancel"):
            cancel_posts += 1
            raise AssertionError("stop-at-hitl must not cancel the task")
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
        stop_at_hitl=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-stop",
            dataset_hash="s" * 64,
            options=options,
        )
        result = (await collector.collect([case]))[0]

    assert task_reads == 1
    assert decision_posts == 0
    assert cancel_posts == 0
    assert result["status"] == "waiting_for_input"
    assert result["error_code"] == "HITL_REQUIRED_NO_AUTO_RESOLUTION"
    assert result["hitl_resolutions"] == 0
    assert result["task_id"] == "task-stop"
    assert result["run_id"] == "run-stop"
    assert result["manifest_id"] == "manifest-stop"
    assert result["observability"]["run_id"] == "run-stop"
    assert result["report_path"] is None


@pytest.mark.asyncio
async def test_single_stop_at_hitl_keeps_source_health_and_metadata_identity(tmp_path, monkeypatch):
    environment = json.loads(
        Path("benchmarks/product-baseline-environment.example.json").read_text(encoding="utf-8")
    )
    environment.update(
        status="ready",
        retrieval_health="passed",
        llm_compatibility="passed",
        dependency_snapshot_sha256="a" * 64,
        knowledge_snapshot_sha256="b" * 64,
    )
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    output = tmp_path / "single-stop"
    args = baseline.build_parser().parse_args(
        [
            "collect-single",
            "--case-id",
            "P08",
            "--environment-file",
            str(environment_path),
            "--output-dir",
            str(output),
            "--api-base",
            "http://127.0.0.1:8011",
            "--repetition",
            "1",
            "--execute-paid-runs",
            "--stop-at-hitl",
        ]
    )
    decision_posts = 0
    cancel_posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal decision_posts, cancel_posts
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-cli-stop", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run-cli-stop", "manifest_id": "manifest-cli-stop"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-cli-stop":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "task_id": "task-cli-stop",
                        "status": "waiting_for_input",
                        "version": 3,
                    },
                    "latest_run": {
                        "run_id": "run-cli-stop",
                        "manifest_id": "manifest-cli-stop",
                    },
                },
            )
        if request.method == "GET" and path.endswith("/decision"):
            return httpx.Response(
                200,
                json={"decision_id": "decision-cli-stop", "status": "pending"},
            )
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={
                    "availability": "available",
                    "run_id": "run-cli-stop",
                    "totals": {"total_tokens": None, "token_usage_complete": False},
                },
            )
        if request.method == "POST" and "/decisions/" in path:
            decision_posts += 1
            raise AssertionError("single stop-at-hitl must not resolve")
        if request.method == "POST" and path.endswith("/cancel"):
            cancel_posts += 1
            raise AssertionError("single stop-at-hitl must not cancel")
        raise AssertionError(f"unexpected request: {request.method} {path}")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        baseline.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(baseline, "_git_commit", lambda: "offline-fixture")

    assert await baseline._collect(args) == 0
    metadata = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (output / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decision_posts == 0
    assert cancel_posts == 0
    assert metadata["execution_mode"] == "single"
    assert metadata["source_health"] == "passed"
    assert metadata["collector_stop_reason"] is None
    assert records[0]["error_code"] == "HITL_REQUIRED_NO_AUTO_RESOLUTION"
    assert records[0]["hitl_resolutions"] == 0
    assert records[0]["task_id"] == "task-cli-stop"
    assert records[0]["run_id"] == "run-cli-stop"
    assert records[0]["manifest_id"] == "manifest-cli-stop"


@pytest.mark.asyncio
async def test_stop_at_hitl_timeout_keeps_waiting_task_without_cancellation(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][7]
    decision_posts = 0
    cancel_posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal decision_posts, cancel_posts
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-timeout-stop", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run-timeout-stop", "manifest_id": "manifest-timeout-stop"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-timeout-stop":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "task_id": "task-timeout-stop",
                        "status": "waiting_for_input",
                        "version": 4,
                    },
                    "latest_run": {
                        "run_id": "run-timeout-stop",
                        "manifest_id": "manifest-timeout-stop",
                    },
                },
            )
        if request.method == "GET" and path.endswith("/decision"):
            await __import__("asyncio").sleep(0.3)
            return httpx.Response(
                200,
                json={"decision_id": "decision-timeout-stop", "status": "pending"},
            )
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={
                    "availability": "available",
                    "run_id": "run-timeout-stop",
                    "totals": {"total_tokens": None, "token_usage_complete": False},
                },
            )
        if request.method == "POST" and "/decisions/" in path:
            decision_posts += 1
            raise AssertionError("timeout stop-at-hitl must not resolve")
        if request.method == "POST" and path.endswith("/cancel"):
            cancel_posts += 1
            raise AssertionError("timeout stop-at-hitl must not cancel")
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=0.2,
        stop_at_hitl=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-timeout-stop",
            dataset_hash="t" * 64,
            options=options,
        )
        result = (await collector.collect([case]))[0]

    assert decision_posts == 0
    assert cancel_posts == 0
    assert result["status"] == "waiting_for_input"
    assert result["collector_timeout"] is True
    assert result["error_code"] == "QUALIFICATION_TIMEOUT_NO_AUTO_CANCELLATION"
    assert result["hitl_resolutions"] == 0
    assert result["run_id"] == "run-timeout-stop"
    assert result["manifest_id"] == "manifest-timeout-stop"
    assert result["observability"]["run_id"] == "run-timeout-stop"


@pytest.mark.asyncio
async def test_collector_rejects_frozen_manifest_after_admission_without_followup_reads(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][7]
    task_reads = 0
    decision_posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal task_reads, decision_posts
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-manifest", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run-manifest", "manifest_id": "actual-manifest"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-manifest":
            task_reads += 1
            raise AssertionError("manifest mismatch must stop before task polling")
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={
                    "availability": "available",
                    "run_id": "run-manifest",
                    "totals": {"total_tokens": None, "token_usage_complete": False},
                },
            )
        if request.method == "POST" and "/decisions/" in path:
            decision_posts += 1
            raise AssertionError("manifest mismatch must not resolve HITL")
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
        stop_at_hitl=True,
        expected_manifest_id="expected-manifest",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-manifest",
            dataset_hash="m" * 64,
            options=options,
        )
        result = (await collector.collect([case]))[0]

    assert task_reads == 0
    assert decision_posts == 0
    assert result["status"] == "queued"
    assert result["error_code"] == "FROZEN_MANIFEST_MISMATCH"
    assert result["hitl_resolutions"] == 0
    assert result["task_id"] == "task-manifest"
    assert result["run_id"] == "run-manifest"
    assert result["manifest_id"] == "actual-manifest"
    assert result["observability"]["run_id"] == "run-manifest"


def test_qualification_environment_rejects_alternate_dataset_before_http_or_output(
    tmp_path, monkeypatch
):
    environment = json.loads(
        Path("benchmarks/product-baseline-environment.example.json").read_text(encoding="utf-8")
    )
    environment.update(
        status="ready",
        retrieval_health="passed",
        llm_compatibility="passed",
        dependency_snapshot_sha256="a" * 64,
        knowledge_snapshot_sha256="b" * 64,
        notes={
            "qualification_mode": "single-admission-v1",
            "dataset_hash": "f" * 64,
        },
    )
    environment_path = tmp_path / "qualification-environment.json"
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    output = tmp_path / "qualification-output"
    dataset = {
        "dataset_id": "product-baseline-v1",
        "version": "1.0.0",
        "freeze_date": "2026-09-16",
        "cases": [],
    }
    monkeypatch.setattr(baseline, "load_dataset", lambda *_args, **_kwargs: (dataset, "a" * 64))

    args = baseline.build_parser().parse_args(
        [
            "collect-single",
            "--case-id",
            "P01",
            "--environment-file",
            str(environment_path),
            "--output-dir",
            str(output),
            "--repetition",
            "1",
            "--execute-paid-runs",
            "--stop-at-hitl",
        ]
    )
    with pytest.raises(ValueError, match="dataset hash"):
        __import__("asyncio").run(baseline._collect(args))
    assert not output.exists()


def test_qualification_environment_rejects_batch_or_non_stop_entrypoint_before_verify(
    tmp_path, monkeypatch
):
    environment = json.loads(
        Path("benchmarks/product-baseline-environment.example.json").read_text(encoding="utf-8")
    )
    environment.update(
        status="ready",
        retrieval_health="passed",
        llm_compatibility="passed",
        dependency_snapshot_sha256="a" * 64,
        knowledge_snapshot_sha256="b" * 64,
        notes={
            "qualification_mode": "single-admission-v1",
            "dataset_hash": "a" * 64,
        },
    )
    environment_path = tmp_path / "qualification-environment.json"
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    output = tmp_path / "qualification-output"
    dataset = {
        "dataset_id": "product-baseline-v1",
        "version": "1.0.0",
        "freeze_date": "2026-09-16",
        "cases": [],
    }
    monkeypatch.setattr(baseline, "load_dataset", lambda *_args, **_kwargs: (dataset, "a" * 64))
    from benchmarks import product_baseline_qualification as qualification

    def unexpected_verify(_environment):
        raise AssertionError("invalid qualification entrypoint must reject before verify")

    monkeypatch.setattr(qualification, "verify_frozen_environment", unexpected_verify)
    args = baseline.build_parser().parse_args(
        [
            "collect",
            "--environment-file",
            str(environment_path),
            "--output-dir",
            str(output),
            "--profile",
            "serial",
            "--repetition",
            "1",
            "--concurrency",
            "1",
            "--execute-paid-runs",
        ]
    )
    with pytest.raises(ValueError, match="qualification environment"):
        __import__("asyncio").run(baseline._collect(args))
    assert not output.exists()


@pytest.mark.asyncio
async def test_collector_times_out_through_public_cancel_and_records_failure(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][0]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-timeout", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run-timeout", "manifest_id": "m"},
                },
            )
        if request.method == "POST" and path.endswith("/cancel"):
            return httpx.Response(
                200,
                json={
                    "task": {
                        "task_id": "task-timeout",
                        "status": "cancelled",
                        "version": 1,
                    },
                    "latest_run": {"run_id": "run-timeout", "manifest_id": "m"},
                },
            )
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={"availability": "unavailable", "unavailable_reason": "trace_not_recorded"},
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=0,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-timeout",
            dataset_hash="b" * 64,
            options=options,
        )
        result = (await collector.collect([case]))[0]
    assert result["collector_timeout"] is True
    assert result["status"] == "cancelled"
    assert result["report_path"] is None


@pytest.mark.asyncio
async def test_collector_keeps_terminal_failure_and_unknown_usage(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][1]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task-failed", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run-failed", "manifest_id": "m"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task-failed":
            return httpx.Response(
                200,
                json={
                    "task": {"task_id": "task-failed", "status": "failed", "version": 1},
                    "latest_run": {"run_id": "run-failed", "manifest_id": "m"},
                },
            )
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(
                200,
                json={
                    "availability": "available",
                    "totals": {"total_tokens": None, "token_usage_complete": False},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-failed",
            dataset_hash="e" * 64,
            options=options,
        )
        result = (await collector.collect([case]))[0]
    assert result["status"] == "failed"
    assert result["observability"]["totals"]["total_tokens"] is None
    assert result["report_path"] is None


@pytest.mark.asyncio
async def test_collector_enforces_whole_case_concurrency_limit(tmp_path):
    cases = load_dataset(DATASET)[0]["cases"][:3]
    active_posts = 0
    maximum_posts = 0
    release = __import__("asyncio").Event()
    ids: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_posts, maximum_posts
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/tasks":
            payload = json.loads(request.content)
            task_id = f"task-{len(ids) + 1}"
            ids[task_id] = payload["query"]
            active_posts += 1
            maximum_posts = max(maximum_posts, active_posts)
            if active_posts == 2:
                release.set()
            await release.wait()
            active_posts -= 1
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": task_id, "status": "queued", "version": 0},
                    "latest_run": {"run_id": f"run-{task_id}", "manifest_id": "m"},
                },
            )
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(200, json={"availability": "unavailable"})
        if request.method == "GET" and path.endswith("/snapshot"):
            return httpx.Response(200, json={"final_recommendation": "ok"})
        if request.method == "GET" and path.endswith("/report"):
            return httpx.Response(200, json={"report": "# report"})
        if request.method == "GET" and path.startswith("/api/v1/tasks/"):
            task_id = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "task": {"task_id": task_id, "status": "completed", "version": 1},
                    "latest_run": {"run_id": f"run-{task_id}", "manifest_id": "m"},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="test",
        repetition=1,
        concurrency=2,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = DurableBaselineCollector(
            client,
            tmp_path,
            experiment_id="experiment-concurrency",
            dataset_hash="c" * 64,
            options=options,
        )
        results = await collector.collect(cases)
    assert len(results) == 3
    assert maximum_posts == 2
    assert collector.peak_in_flight == 2


def _write_profile(path: Path, *, profile: str, decision_delta: float = 0) -> None:
    path.mkdir()
    records = []
    for index in range(1, 13):
        records.append(
            {
                "case_id": f"P{index:02d}",
                "dataset_hash": "d" * 64,
                "status": "completed",
                "profile": profile,
                "repetition": 1,
                "requested_concurrency": 1 if profile == "serial" else 12,
                "report_path": f"reports/P{index:02d}.md",
                "run_id": f"run-{profile}-{index}",
                "experiment_id": profile,
                "manifest_id": "m",
            }
        )
    (path / "runs.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    (path / "experiment.json").write_text(json.dumps({"environment_hash": "a" * 64,
        "dataset_hash": "d" * 64, "git_commit": "b" * 40}))
    fields = ["case_id", "run_id", "experiment_id", "reviewer", "evidence_notes", *(
        "decision_correctness",
        "citation_support",
        "source_quality",
        "conflict_handling",
    ), "major_errors"]
    with (path / "scores.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "case_id": record["case_id"],
                    "decision_correctness": 0.9 + decision_delta,
                    "citation_support": 0.9,
                    "source_quality": 0.9,
                    "conflict_handling": 0.9,
                    "major_errors": 0,
                    "run_id": record["run_id"],
                    "experiment_id": record["experiment_id"],
                    "reviewer": "fixture-reviewer",
                    "evidence_notes": "fixture evidence",
                }
            )


def test_serial_concurrent_comparison_applies_quality_tolerance(tmp_path):
    serial = tmp_path / "serial"
    concurrent = tmp_path / "concurrent"
    _write_profile(serial, profile="serial")
    _write_profile(concurrent, profile="concurrent", decision_delta=-0.04)
    result = compare_profiles(serial, concurrent)
    assert result["passed"] is True
    assert result["metric_deltas"]["decision_correctness"] == pytest.approx(-0.04)

    degraded = tmp_path / "degraded"
    _write_profile(degraded, profile="concurrent", decision_delta=-0.06)
    result = compare_profiles(serial, degraded)
    assert result["passed"] is False
    assert result["checks"]["decision_mean_drop_at_most_5pp"] is False


def test_usage_export_preserves_unknown_and_separates_budget_charges(tmp_path):
    observation = {"availability": "available", "totals": {
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
        "token_usage_complete": False, "llm_calls": 2},
        "calls": [{"kind": "llm", "retry_no": 1}, {"kind": "http"}],
        "budget": {"resources": {"total_tokens": {"unknown_spend": 4096}}}}
    projected = usage_projection(observation)
    assert projected["total_tokens"] == 120
    assert projected["token_usage_complete"] is False
    assert projected["llm_retries"] == 1
    assert usage_projection(None)["total_tokens"] is None
    write_collection_summary(tmp_path, [{"case_id": "P01", "status": "failed",
        "wall_time_ms": 1, "observability": observation},
        {"case_id": "P02", "status": "failed", "wall_time_ms": 2, "observability": None}])
    with (tmp_path / "usage.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["total_tokens"] == "120"
    assert rows[1]["total_tokens"] == ""


def test_missing_reports_cannot_pass_concurrency_gate(tmp_path):
    serial, concurrent = tmp_path / "serial", tmp_path / "concurrent"
    _write_profile(serial, profile="serial")
    _write_profile(concurrent, profile="concurrent")
    for folder in (serial, concurrent):
        records = [json.loads(line) for line in (folder / "runs.jsonl").read_text().splitlines()]
        for record in records:
            record["report_path"] = None
            record["status"] = "failed"
        (folder / "runs.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    assert compare_profiles(serial, concurrent)["passed"] is False


@pytest.mark.asyncio
async def test_preflight_uses_supported_shared_json_helper_contract(monkeypatch):
    from benchmarks.product_baseline_preflight import probe
    from deepchoice.utils import llm

    async def fake_call(prompt, *, response_format, usage, **_):
        assert isinstance(prompt, list)
        assert response_format == "json"
        usage.append({"total_tokens": 25})
        return {"ok": False}

    monkeypatch.setattr(llm, "call_model", fake_call)
    result = await probe()
    assert result["passed"] is False
    assert result["research_runs_submitted"] == 0
    assert result["results"][0]["usage"] == [{"total_tokens": 25}]


def test_comparison_rejects_environment_drift_and_stale_score_identity(tmp_path):
    serial, concurrent = tmp_path / "serial", tmp_path / "concurrent"
    _write_profile(serial, profile="serial")
    _write_profile(concurrent, profile="concurrent")
    metadata_path = concurrent / "experiment.json"
    original = metadata_path.read_text()
    changed = json.loads(original)
    changed["environment_hash"] = "f" * 64
    metadata_path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="experiment identities"):
        compare_profiles(serial, concurrent)
    metadata_path.write_text(original)
    score_path = concurrent / "scores.csv"
    score_path.write_text(score_path.read_text(encoding="utf-8-sig").replace("run-concurrent-1,", "stale-run,"),
                         encoding="utf-8-sig")
    with pytest.raises(ValueError, match="score identity"):
        compare_profiles(serial, concurrent)


@pytest.mark.asyncio
async def test_collector_does_not_silently_follow_a_replaced_run(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][0]
    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        if request.method == "POST":
            return httpx.Response(202, json={"task": {"task_id": "t", "status": "queued"},
                "latest_run": {"run_id": "original", "manifest_id": "m"}})
        if request.url.path.endswith("/observability"):
            return httpx.Response(200, json={"availability": "available", "run_id": "replacement"})
        return httpx.Response(200, json={"task": {"task_id": "t", "status": "running"},
            "latest_run": {"run_id": "replacement", "manifest_id": "m"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        collector = DurableBaselineCollector(client, tmp_path, experiment_id="e", dataset_hash="a" * 64,
            options=CollectionOptions("serial", 1, 1, 0, 5))
        record = (await collector.collect([case]))[0]
    assert record["run_id"] == "original"
    assert record["error_code"] in {"RUN_IDENTITY_CHANGED", "OBSERVABILITY_RUN_MISMATCH"}
    assert record["report_path"] is None
    assert record["observability"] is None


@pytest.mark.asyncio
async def test_timeout_observes_cancel_completion_without_new_research_run(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][0]
    submissions = 0
    async def handler(request):
        nonlocal submissions
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        if request.method == "POST" and request.url.path == "/api/v1/tasks":
            submissions += 1
            status, code = "queued", 202
        elif request.method == "POST":
            status, code = "cancelling", 200
        elif request.url.path.endswith("/observability"):
            return httpx.Response(200, json={"availability": "unavailable"})
        else:
            status, code = "cancelled", 200
        return httpx.Response(code, json={"task": {"task_id": "t", "status": status},
            "latest_run": {"run_id": "r", "manifest_id": "m"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        collector = DurableBaselineCollector(client, tmp_path, experiment_id="e", dataset_hash="a" * 64,
            options=CollectionOptions("serial", 1, 1, 0, 0))
        record = (await collector.collect([case]))[0]
    assert submissions == 1
    assert record["status"] == "cancelled"
    assert record["collector_timeout"] is True


@pytest.mark.asyncio
async def test_route_preflight_retains_only_allowlisted_fields(monkeypatch):
    from benchmarks.product_baseline_preflight import probe_routes
    from deepchoice import outbound
    class FakeResolver:
        async def health_check(self):
            return {"ok": True, "sources": {"tavily": {"ok": True, "channel": "direct",
                "detail": "sensitive provider detail"}}}
    monkeypatch.setattr(outbound, "get_resolver", lambda: FakeResolver())
    result = await probe_routes()
    assert result["sources"] == {"tavily": {"ok": True, "channel": "direct"}}
    assert result["tavily_credential_probe"] == "not_run"
    assert "sensitive" not in json.dumps(result)


def test_stop_at_hitl_is_exposed_only_by_single_case_cli():
    parser = build_parser()
    single = parser.parse_args(
        [
            "collect-single",
            "--case-id",
            "P08",
            "--environment-file",
            "fixture",
            "--output-dir",
            "fixture",
            "--repetition",
            "1",
            "--stop-at-hitl",
        ]
    )
    assert single.stop_at_hitl is True
    batch = parser.parse_args(
        [
            "collect",
            "--environment-file",
            "fixture",
            "--output-dir",
            "fixture",
            "--profile",
            "serial",
            "--repetition",
            "1",
            "--concurrency",
            "1",
        ]
    )
    assert not hasattr(batch, "stop_at_hitl")
