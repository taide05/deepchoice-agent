"""Single-case collection and fail-closed evaluation control, without external calls."""
import json
import csv

import httpx
import pytest

from benchmarks import product_baseline as baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["health_loss", "requeue"])
async def test_collector_stops_future_admission_and_keeps_last_usage(tmp_path, failure):
    cases = baseline.load_dataset(baseline.Path("benchmarks/product-baseline-v1.json"))[0]["cases"][:2]
    posts = task_reads = health_reads = observations = 0
    async def handler(request):
        nonlocal posts, task_reads, health_reads, observations
        path = request.url.path
        if path == "/health":
            health_reads += 1
            lost = failure == "health_loss" and health_reads >= 3
            return httpx.Response(503 if lost else 200,
                json={"status": "unavailable" if lost else "ok", "runtime_instance": "lost" if lost else "active"})
        if request.method == "POST":
            assert path == "/api/v1/tasks"
            posts += 1
            status = "queued"
        elif path.endswith("/observability"):
            observations += 1
            if observations > 1:
                raise httpx.ReadError("fixture disconnected", request=request)
            return httpx.Response(200, json={"availability": "available", "run_id": "r",
                "totals": {"total_tokens": 77, "token_usage_complete": True}})
        else:
            task_reads += 1
            status = "running" if task_reads == 1 else "queued"
        return httpx.Response(202 if request.method == "POST" else 200,
            json={"task": {"task_id": "t", "status": status},
                  "latest_run": {"run_id": "r", "manifest_id": "m"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fixture") as client:
        collector = baseline.DurableBaselineCollector(client, tmp_path,
            experiment_id="fixture", dataset_hash="a" * 64,
            options=baseline.CollectionOptions("serial", 1, 1, 0, 5))
        records = await collector.collect(cases)
    assert posts == 1
    assert records[0]["usage"]["total_tokens"] == 77
    assert records[0]["usage"]["token_usage_complete"] is False
    assert records[0]["usage"]["observation_final"] is False
    assert records[0]["usage"]["observed_at"]
    baseline.write_collection_summary(tmp_path, records)
    csv_rows = list(csv.DictReader((tmp_path / "usage.csv").open(encoding="utf-8-sig")))
    assert csv_rows[0]["total_tokens"] == "77" and csv_rows[0]["token_usage_complete"] == "False"
    assert "Complete token usage: 0/2" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert records[1]["status"] == "not_submitted" and records[1]["run_id"] is None
    assert records[0]["error_code"] == ("RUNTIME_HEALTH_UNAVAILABLE" if failure == "health_loss" else "UNEXPECTED_RUN_REQUEUE")


@pytest.mark.asyncio
async def test_single_command_submits_exactly_one_development_case(tmp_path, monkeypatch):
    environment = json.loads(baseline.Path("benchmarks/product-baseline-environment.example.json").read_text(encoding="utf-8"))
    environment.update(status="ready", retrieval_health="passed", llm_compatibility="passed",
        dependency_snapshot_sha256="a" * 64, knowledge_snapshot_sha256="b" * 64)
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    output = tmp_path / "single"
    args = baseline.build_parser().parse_args(["collect-single", "--case-id", "P06",
        "--environment-file", str(environment_path), "--output-dir", str(output),
        "--api-base", "http://127.0.0.1:8011", "--repetition", "1", "--execute-paid-runs"])
    posts = 0
    async def handler(request):
        nonlocal posts
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "runtime_instance": "active"})
        if request.method == "POST":
            assert path == "/api/v1/tasks"
            posts += 1
            assert json.loads(request.content) == baseline.load_dataset(
                baseline.Path("benchmarks/product-baseline-v1.json"))[0]["cases"][5]["request"]
        elif path.endswith("/observability"):
            return httpx.Response(200, json={"availability": "unavailable"})
        elif path.endswith("/report"):
            return httpx.Response(200, json={"run_id": "r", "report": "# fixture"})
        elif path.endswith("/snapshot"):
            return httpx.Response(200, json={"fixture": True})
        return httpx.Response(202 if request.method == "POST" else 200,
            json={"task": {"task_id": "t", "status": "completed"},
                  "latest_run": {"run_id": "r", "manifest_id": "m"}})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(baseline.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(baseline, "_git_commit", lambda: "offline-fixture")
    assert await baseline._collect(args) == 0
    metadata = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
    assert posts == 1 and metadata["case_denominator"] == 1
    assert metadata["execution_mode"] == "single" and metadata["case_order"] == ["P06"]
    assert metadata["requested_concurrency"] == 1
    assert metadata["admitted_run_denominator"] == 1


def test_single_command_rejects_holdout_and_multiple_cases():
    parser = baseline.build_parser()
    for selection in ("P09", "P06,P07"):
        with pytest.raises(SystemExit):
            parser.parse_args(["collect-single", "--case-id", selection,
                "--environment-file", "fixture", "--output-dir", "fixture", "--repetition", "1"])
