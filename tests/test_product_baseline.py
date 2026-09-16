from __future__ import annotations

import csv
import json
from pathlib import Path

import httpx
import pytest

from benchmarks.product_baseline import (
    CollectionOptions,
    DurableBaselineCollector,
    compare_profiles,
    load_dataset,
    load_environment,
    usage_projection,
    write_collection_summary,
)
from benchmarks.product_baseline_server import create_app


DATASET = Path("benchmarks/product-baseline-v1.json")


def test_candidate_dataset_has_twelve_valid_cases_and_paid_run_requires_freeze():
    dataset, digest = load_dataset(DATASET)
    assert len(dataset["cases"]) == 12
    assert len(digest) == 64
    assert [case["id"] for case in dataset["cases"]] == [
        f"P{index:02d}" for index in range(1, 13)
    ]
    with pytest.raises(ValueError, match="requires a frozen dataset"):
        load_dataset(DATASET, require_frozen=True)


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
    application = create_app()
    assert application.state.product_database_path == root / "product.db"
    assert application.state.checkpoint_database_path == root / "checkpoints.db"
    assert application.state.legacy_snapshot_root == root / "legacy-import-disabled"


@pytest.mark.asyncio
async def test_collector_handles_hitl_and_preserves_unknown_observability(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][7]
    task_reads = 0
    decision_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal task_reads, decision_reads
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
            status = "waiting_for_input" if task_reads <= 2 else "completed"
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
async def test_collector_times_out_through_public_cancel_and_records_failure(tmp_path):
    case = load_dataset(DATASET)[0]["cases"][0]

    async def handler(request: httpx.Request) -> httpx.Response:
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
