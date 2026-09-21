from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import o1_pr2b_child as child
from scripts import o1_pr2b_control as control
from scripts import o1_pr2b_prepare as prepare
from scripts import o1_pr2b_review_pack as review
from scripts import o1_pr2b_round_gate as gate


def _write_collection(root: Path, profile: str) -> Path:
    output = root / "collections" / profile
    output.mkdir(parents=True)
    experiment = f"exp-{profile}"
    metadata = {
        "schema_version": 1,
        "experiment_id": experiment,
        "dataset_hash": review.DATASET_HASH,
        "git_commit": review.EXPECTED_COMMIT,
        "case_denominator": 12,
        "admitted_run_denominator": 12,
        "environment_hash": "e" * 64,
        "core_asset_registry_id": gate.EXPECTED_ASSET,
    }
    (output / "experiment.json").write_text(
        json.dumps(metadata), encoding="utf-8")
    records = []
    for number in range(1, 13):
        case_id = f"P{number:02d}"
        split = "development" if number <= 8 else "holdout"
        report_path = Path(split) / "reports" / f"{case_id}.md"
        snapshot_path = Path(split) / "snapshots" / f"{case_id}.json"
        (output / report_path).parent.mkdir(parents=True, exist_ok=True)
        (output / snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        (output / report_path).write_text(
            f"synthetic report {profile} {case_id}\n", encoding="utf-8")
        (output / snapshot_path).write_text("{}", encoding="utf-8")
        records.append({
            "case_id": case_id,
            "status": "completed",
            "report_path": report_path.as_posix(),
            "snapshot_path": snapshot_path.as_posix(),
            "run_id": f"{profile}-run-{number}",
            "manifest_id": review.EXPECTED_MANIFEST_BY_CASE[case_id],
            "experiment_id": experiment,
            "profile": "serial" if profile.startswith("serial") else "concurrent",
            "requested_concurrency": 1 if profile.startswith("serial") else 12,
            "dataset_hash": review.DATASET_HASH,
            "repetition": int(profile[-1]),
        })
    (output / "runs.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return output


def _complete_review(template: dict, *, finding: bool, independent: bool) -> dict:
    value = dict(template)
    value["review_status"] = "complete"
    value["reviewer_qualification"] = "synthetic-offline-check"
    value["ledger_complete"] = True
    value["claim_occurrences"] = [{
        "occurrence_id": "occ-1",
        "line": 1,
        "atom": "synthetic atom",
        "support": "supported",
        "quality": "eligible",
        "source_refs": ["ref-1"],
        "notes": "synthetic evidence",
    }]
    for field in ("must_answer", "conflict_points"):
        value[field] = [
            {**entry, "score": 2, "notes": "synthetic scoring"}
            for entry in value[field]
        ]
    value["major_errors"] = (
        [{"id": "me-1", "evidence": "synthetic finding"}]
        if finding and not independent else []
    )
    value["disputed_refs"] = []
    value["claimed_improvements"] = []
    if independent:
        value["independent_coverage"] = (
            [{
                "kind": "major_errors",
                "id": "me-1",
                "covered": True,
                "evidence": "independent check",
            }]
            if finding else []
        )
    return value


def _prepare_review(root: Path, repository: Path) -> tuple[Path, Path]:
    serial = _write_collection(root, "serial-r1")
    concurrent = _write_collection(root, "concurrent-r1")
    review_root = root / "review" / "round-1"
    package = review_root / "package"
    mapping = review_root / "mapping.json"
    review.generate(Namespace(
        serial=str(serial),
        concurrent=str(concurrent),
        dataset=str(repository / "benchmarks/product-baseline-v1.json"),
        output=str(package),
        mapping=str(mapping),
        seed=20260919,
    ))
    templates = review.read_json(package / "review-template.json")
    mains = [
        _complete_review(item, finding=index == 0, independent=False)
        for index, item in enumerate(templates)
    ]
    independents = [
        _complete_review(item, finding=index == 0, independent=True)
        for index, item in enumerate(templates)
    ]
    main_path = review_root / "main-review.json"
    independent_path = review_root / "independent-review.json"
    main_path.write_text(json.dumps(mains), encoding="utf-8")
    independent_path.write_text(json.dumps(independents), encoding="utf-8")
    lock = review_root / "review-lock.json"
    review.lock_reviews(Namespace(
        package=str(package),
        main=str(main_path),
        independent=str(independent_path),
        lock=str(lock),
    ))
    joined = review_root / "joined"
    review.join_reviews(Namespace(
        package=str(package),
        mapping=str(mapping),
        lock=str(lock),
        main=str(main_path),
        independent=str(independent_path),
        output=str(joined),
    ))
    return serial, concurrent


def _write_control_evidence(root: Path, profile: str, tool_hashes: dict) -> None:
    destination = root / profile / "control"
    destination.mkdir(parents=True)
    (destination / "profile-control-result.json").write_text(json.dumps({
        "execution_succeeded": True,
        "profile": profile,
        "observed_records": 12,
        "report_count": 12,
        "metrics_complete": True,
        "stop_final_observability_complete": True,
        "active_budget_metrics_complete": True,
        "process_cleanup_unresolved": False,
        "graceful_service_exit": True,
    }), encoding="utf-8")
    (destination / "controller-identity.json").write_text(json.dumps({
        "git_commit": control.EXPECTED_COMMIT,
        "dataset_hash": control.EXPECTED_DATASET,
        "controller_sha256": control.file_hash(
            Path(control.__file__).resolve()),
        "child_sha256": control.file_hash(
            Path(control.__file__).with_name("o1_pr2b_child.py")),
        "pr2_tool_hashes": tool_hashes,
    }), encoding="utf-8")


def test_pr2b_control_chain_is_complete_and_current():
    assert prepare.PR2B_CONTROL_CHAIN == (
        "o1_pr2b_preflight.py",
        "o1_pr2b_prepare.py",
        "o1_pr2b_child.py",
        "o1_pr2b_control.py",
        "o1_pr2b_review_pack.py",
        "o1_pr2b_round_gate.py",
    )


def test_pr2b_blind_review_and_round_gate_reject_tampering(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    tools = repository / "scripts"
    tool_hashes = {
        name: control.file_hash(tools / name)
        for name in prepare.PR2B_CONTROL_CHAIN
    }
    (tmp_path / "environment.json").write_text(json.dumps({
        "notes": {"pr2_tool_hashes": tool_hashes}
    }), encoding="utf-8")
    serial, _ = _prepare_review(tmp_path, repository)
    for profile in ("serial-r1", "concurrent-r1"):
        _write_control_evidence(tmp_path, profile, tool_hashes)

    result = gate.main(tmp_path, repository, 1)
    assert result["passed"] is True
    assert result["completed_report_count"] == 24
    assert result["independent_review_complete"] is True

    (tmp_path / "round-1-gate.json").unlink()
    (tmp_path / "review/round-1/comparison.json").unlink()
    report = serial / "development/reports/P01.md"
    report.write_text("tampered report\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private mapping no longer matches"):
        gate.main(tmp_path, repository, 1)


def _write_telemetry(path: Path, *events: dict) -> None:
    path.write_text(
        "".join(json.dumps({
            "schema_version": 1,
            **event,
        }) + "\n" for event in events),
        encoding="utf-8",
    )


def test_pr2b_safe_fetch_context_marks_dynamic_public_requests():
    request = httpx.Request("GET", "https://example.com/public-citation")
    assert child._observed_operation(request, "api.deepseek.com") == "other"

    token = child._SAFE_FETCH_ACTIVE.set(True)
    try:
        assert (
            child._observed_operation(request, "api.deepseek.com")
            == "safe_fetch_public"
        )
    finally:
        child._SAFE_FETCH_ACTIVE.reset(token)


@pytest.mark.parametrize("status_code", [200, 302, 403, 404, 429])
def test_pr2b_public_safe_fetch_get_accepts_bounded_2xx_through_4xx(
        tmp_path, status_code):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {
            "event": "external_http_response",
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "GET",
            "status_code": status_code,
        },
    )

    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    "event",
    [
        {
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "GET",
            "status_code": 500,
        },
        {
            "operation": "safe_fetch_public",
            "source": "safe_fetch",
            "method": "HEAD",
            "status_code": 403,
        },
        {
            "operation": "safe_fetch_public",
            "source": "other",
            "method": "GET",
            "status_code": 403,
        },
    ],
)
def test_pr2b_safe_fetch_5xx_and_invalid_context_fail_closed(tmp_path, event):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        telemetry,
        {"event": "telemetry_ready"},
        {"event": "external_http_response", **event},
    )

    state = control.telemetry_state(telemetry)
    assert state["anomaly"] is True
    assert state["reason"] == "safe_fetch_public_failed"


@pytest.mark.asyncio
async def test_pr2b_cleanup_waits_beyond_old_30_second_poll_count(
        tmp_path, monkeypatch):
    state = {"get_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task": {"status": "cancelling"}})
        state["get_count"] += 1
        status = "cancelled" if state["get_count"] > 36 else "cancelling"
        if state["get_count"] == 1:
            status = "running"
        return httpx.Response(200, json={"task": {"status": status}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local.test",
    )
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        control.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            available=control.STOP_MINIMUM_AVAILABLE_BYTES + 1
        ),
    )

    result = await control.settle(
        "http://unused",
        ["task-1"],
        tmp_path / "journal.jsonl",
        True,
        timeout_seconds=5,
        poll_interval_seconds=0.0001,
    )

    assert state["get_count"] > 30
    assert result["attempted"] == 1
    assert result["settled"] == 1
    assert result["unresolved"] == []
    assert result["resource_stop"] is False


@pytest.mark.asyncio
async def test_pr2b_cleanup_keeps_memory_stop_line(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        status = "cancelling" if request.method == "POST" else "running"
        return httpx.Response(200, json={"task": {"status": status}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local.test",
    )
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        control.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            available=control.STOP_MINIMUM_AVAILABLE_BYTES - 1
        ),
    )

    result = await control.settle(
        "http://unused",
        ["task-1"],
        tmp_path / "journal.jsonl",
        True,
        timeout_seconds=5,
        poll_interval_seconds=0.0001,
    )

    assert result["settled"] == 0
    assert result["unresolved"] == ["task-1"]
    assert result["resource_stop"] is True


@pytest.mark.asyncio
async def test_pr2b_cleanup_cancels_all_tasks_before_polling(tmp_path, monkeypatch):
    sequence = []
    initial_gets = set()

    def handler(request: httpx.Request) -> httpx.Response:
        task_id = request.url.path.split("/")[-1]
        if task_id == "cancel":
            task_id = request.url.path.split("/")[-2]
        sequence.append((request.method, task_id))
        if request.method == "POST":
            return httpx.Response(200, json={"task": {"status": "cancelling"}})
        if task_id not in initial_gets:
            initial_gets.add(task_id)
            return httpx.Response(200, json={"task": {"status": "running"}})
        return httpx.Response(200, json={"task": {"status": "cancelled"}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://local.test",
    )
    monkeypatch.setattr(control.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        control.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            available=control.STOP_MINIMUM_AVAILABLE_BYTES + 1
        ),
    )

    result = await control.settle(
        "http://unused",
        ["task-1", "task-2"],
        tmp_path / "journal.jsonl",
        True,
        timeout_seconds=5,
        poll_interval_seconds=0.0001,
    )

    assert sequence[:4] == [
        ("GET", "task-1"),
        ("POST", "task-1"),
        ("GET", "task-2"),
        ("POST", "task-2"),
    ]
    assert result["attempted"] == 2
    assert result["settled"] == 2
    assert result["unresolved"] == []


def _six_source_snapshot(*, failed_source: str | None = None,
                         partial_failures: list[str] | None = None) -> dict:
    return {
        "partial_failures": partial_failures or [],
        "search_results": [
            {
                "source": source,
                "status": "failed" if source == failed_source else "success",
            }
            for source in sorted(control._EXPECTED_SOURCES)
        ],
    }


def test_pr2b_source_health_allows_non_source_limited_report_marker():
    snapshot = _six_source_snapshot(
        partial_failures=["evidence_insufficient_user_limited"],
    )

    assert control.source_anomaly(snapshot) is False


@pytest.mark.parametrize(
    "snapshot",
    [
        _six_source_snapshot(failed_source="github"),
        {"search_results": []},
        {
            "search_results": [
                {"source": "tavily", "status": "success"},
            ] * 6,
        },
        None,
    ],
)
def test_pr2b_source_health_requires_six_distinct_success_envelopes(snapshot):
    assert control.source_anomaly(snapshot) is True
