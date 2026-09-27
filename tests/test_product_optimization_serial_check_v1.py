from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from benchmarks import product_optimization_serial_check_v1 as contract
from benchmarks.product_baseline import CollectionOptions
from scripts import product_optimization_repair_pair as runner_base
from scripts import product_optimization_serial_check_v1 as runner


def test_serial_check_contract_is_candidate_only_and_open_after_review():
    frozen = contract.load_serial_check_protocol()
    payload = frozen.payload

    assert payload["protocol_id"] == contract.PROTOCOL_ID
    assert payload["status"] == "frozen"
    assert payload["freeze_date"] == "2026-09-27"
    assert payload["controller"]["research_admission"] == (
        "open-after-independent-review-and-offline-acceptance"
    )
    assert payload["design"]["execution_blocks"] == [
        {
            "block": 1,
            "arm": "candidate",
            "repetition": 1,
            "case_order": ["P04", "P01", "P08"],
        }
    ]
    assert payload["design"]["concurrency"] == 1
    assert payload["design"]["holdout_access"] == "forbidden"
    assert payload["design"]["hitl_policy"] == contract.HITL_POLICY
    assert payload["environment"]["hitl_mode"] == contract.HITL_MODE
    assert payload["environment"]["hitl_policy"] == contract.HITL_POLICY
    assert payload["budgets"]["research_ledger"] == {
        "starting_used": 100,
        "diagnostic_max": 3,
        "concurrency_reserve": 0,
        "unallocated": 53,
        "hard_total": 156,
    }
    assert payload["authorization"]["concurrency_runs_authorized"] == 0
    assert payload["acceptance"]["interpretation_limit"] == (
        "diagnostic-product-feedback-only-no-causal-improvement-claim"
    )


def test_serial_check_bootstrap_binds_stopped_v6_evidence():
    frozen = contract.load_serial_check_protocol()

    payload = runner._bootstrap_approved_protocol(frozen.byte_sha256)

    assert payload["control_predecessor"]["accounted_research_runs"] == 3
    assert payload["control_predecessor"]["disposition"] == (
        "immutable-no-retry-no-splice"
    )


def test_frozen_reviewed_card_admits_only_its_exact_contract():
    protocol = contract.load_serial_check_protocol().payload

    runner._require_active_protocol(protocol)

    drifted = json.loads(json.dumps(protocol))
    drifted["controller"]["research_admission"] = (
        "closed-pending-independent-review"
    )
    with pytest.raises(runner.RepairPairControlError, match="not open"):
        runner._require_active_protocol(drifted)


def test_fixed_case_projection_preserves_existing_hitl_policy():
    protocol = contract.load_serial_check_protocol().payload

    cases = runner._load_cases(protocol)

    assert tuple(cases) == ("P01", "P04", "P08")
    assert cases["P04"]["hitl"]["action"] == "limited_report"
    assert cases["P08"]["hitl"]["action"] == "provide_context"
    assert cases["P08"]["hitl"]["repeat_action"] == "limited_report"
    assert cases["P08"]["hitl"]["supplemental_input"]
    assert runner._case_hitl_policy(protocol, "P01") == {
        "stop_at_hitl": True,
        "max_auto_resolutions": 0,
    }
    assert runner._case_hitl_policy(protocol, "P04") == {
        "stop_at_hitl": True,
        "max_auto_resolutions": 0,
    }
    assert runner._case_hitl_policy(protocol, "P08") == {
        "stop_at_hitl": False,
        "max_auto_resolutions": 2,
    }


@pytest.mark.asyncio
async def test_p08_resolution_limit_blocks_before_decision_post(tmp_path: Path):
    class NoRequestClient:
        async def request(self, *_args, **_kwargs):
            raise AssertionError("decision POST must not be sent")

    collector = runner._SerialCheckCollector(
        NoRequestClient(),
        tmp_path,
        experiment_id=contract.PROTOCOL_ID,
        dataset_hash="a" * 64,
        options=CollectionOptions(
            profile="serial-r1",
            repetition=1,
            concurrency=1,
            poll_interval_seconds=1.0,
            case_timeout_seconds=900.0,
        ),
        max_hitl_resolutions=2,
    )

    error = await collector._resolve_decision(
        {"hitl": {"action": "provide_context", "supplemental_input": "x"}},
        {"task": {"task_id": "task", "version": 1}},
        {"decision_id": "decision"},
        resolution_index=2,
    )

    assert error == "HITL_RESOLUTION_LIMIT_REACHED"


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["P01", "P04"])
async def test_non_p08_collector_stops_at_hitl_without_decision_post(
    tmp_path: Path, case_id: str
):
    protocol = contract.load_serial_check_protocol().payload
    case = runner._load_cases(protocol)[case_id]
    policy = runner._case_hitl_policy(protocol, case_id)
    decision_posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal decision_posts
        path = request.url.path
        if path == "/health":
            return httpx.Response(
                200, json={"status": "ok", "runtime_instance": "active"}
            )
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run", "manifest_id": "manifest"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "task_id": "task",
                        "status": "waiting_for_input",
                        "version": 1,
                    },
                    "latest_run": {"run_id": "run", "manifest_id": "manifest"},
                },
            )
        if request.method == "GET" and path.endswith("/decision"):
            return httpx.Response(200, json={"decision_id": "decision"})
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(200, json={"run_id": "run"})
        if request.method == "POST" and "/decisions/" in path:
            decision_posts += 1
            raise AssertionError("non-P08 HITL must not be resolved")
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial-r1",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
        stop_at_hitl=policy["stop_at_hitl"],
    )
    output_dir = tmp_path / case_id
    output_dir.mkdir()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = runner._SerialCheckCollector(
            client,
            output_dir,
            experiment_id=contract.PROTOCOL_ID,
            dataset_hash=protocol["dataset"]["parent_sha256"],
            options=options,
            max_hitl_resolutions=policy["max_auto_resolutions"],
        )
        result = (await collector.collect([case]))[0]

    assert decision_posts == 0
    assert result["status"] == "waiting_for_input"
    assert result["error_code"] == "HITL_REQUIRED_NO_AUTO_RESOLUTION"
    assert result["hitl_resolutions"] == 0


@pytest.mark.asyncio
async def test_p08_collector_stops_before_third_decision_post(tmp_path: Path):
    protocol = contract.load_serial_check_protocol().payload
    case = runner._load_cases(protocol)["P08"]
    policy = runner._case_hitl_policy(protocol, "P08")
    decision_bodies: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(
                200, json={"status": "ok", "runtime_instance": "active"}
            )
        if request.method == "POST" and path == "/api/v1/tasks":
            return httpx.Response(
                202,
                json={
                    "task": {"task_id": "task", "status": "queued", "version": 0},
                    "latest_run": {"run_id": "run", "manifest_id": "manifest"},
                },
            )
        if request.method == "GET" and path == "/api/v1/tasks/task":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "task_id": "task",
                        "status": "waiting_for_input",
                        "version": len(decision_bodies) + 1,
                    },
                    "latest_run": {"run_id": "run", "manifest_id": "manifest"},
                },
            )
        if request.method == "GET" and path.endswith("/decision"):
            return httpx.Response(
                200,
                json={"decision_id": f"decision-{len(decision_bodies) + 1}"},
            )
        if request.method == "POST" and "/decisions/" in path:
            decision_bodies.append(json.loads(request.content))
            return httpx.Response(202, json={"replayed": False})
        if request.method == "GET" and path.endswith("/observability"):
            return httpx.Response(200, json={"run_id": "run"})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    options = CollectionOptions(
        profile="serial-r1",
        repetition=1,
        concurrency=1,
        poll_interval_seconds=0,
        case_timeout_seconds=5,
        stop_at_hitl=policy["stop_at_hitl"],
    )
    output_dir = tmp_path / "P08"
    output_dir.mkdir()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        collector = runner._SerialCheckCollector(
            client,
            output_dir,
            experiment_id=contract.PROTOCOL_ID,
            dataset_hash=protocol["dataset"]["parent_sha256"],
            options=options,
            max_hitl_resolutions=policy["max_auto_resolutions"],
        )
        result = (await collector.collect([case]))[0]

    assert decision_bodies == [
        {
            "action": "provide_context",
            "supplemental_input": case["hitl"]["supplemental_input"],
        },
        {"action": "limited_report"},
    ]
    assert result["error_code"] == "HITL_RESOLUTION_LIMIT_REACHED"
    assert result["hitl_resolutions"] == 2


@pytest.mark.parametrize(
    ("case_id", "resolutions", "expected"),
    [
        ("P04", 0, None),
        ("P01", 0, None),
        ("P08", 0, None),
        ("P08", 1, None),
        ("P08", 2, None),
        ("P04", 1, "UNEXPECTED_HITL_RESOLUTION"),
        ("P08", 3, "UNEXPECTED_HITL_RESOLUTION"),
    ],
)
def test_hitl_count_policy_is_case_specific(
    monkeypatch, tmp_path: Path, case_id: str, resolutions: int, expected: str | None
):
    monkeypatch.setattr(runner_base, "_record_stop_reason", lambda *_args: None)
    record = {"hitl_resolutions": resolutions}

    assert runner._record_stop_reason(record, tmp_path, case_id) == expected


def test_configured_base_is_scoped_and_restored():
    previous = {
        "PROTOCOL_PATH": runner_base.PROTOCOL_PATH,
        "CHILD": runner_base.CHILD,
        "LEDGER_ROOT": runner_base.LEDGER_ROOT,
        "_require_active_protocol": runner_base._require_active_protocol,
    }

    with runner._configured_base():
        assert runner_base.PROTOCOL_PATH == runner.PROTOCOL_PATH
        assert runner_base.CHILD == runner.CHILD
        assert runner_base.LEDGER_ROOT == runner.LEDGER_ROOT
        assert runner_base._require_active_protocol is runner._require_active_protocol

    for name, value in previous.items():
        assert getattr(runner_base, name) is value or getattr(runner_base, name) == value


def test_prepare_projects_dynamic_three_case_counts(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("DS_FLASH_API_KEY=secret\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_install_call_environment", lambda *_args: None)
    protocol = contract.load_serial_check_protocol().payload

    def fake_prepare(root: Path, *_args, **_kwargs):
        environment_path = root / "arms/candidate/r1/environment.json"
        environment_path.parent.mkdir(parents=True)
        runner_base._write_json(
            environment_path,
            {"notes": {"hitl_mode": runner.LEGACY_HITL_MODE}},
        )
        runner_base._write_json(
            root / "execution-binding.json",
            {
                "blocks": [
                    {
                        "arm": "candidate",
                        "repetition": 1,
                        "environment_sha256": runner_base._file_hash(
                            environment_path
                        ),
                    }
                ]
            },
        )
        return {
            "prepared": True,
            "blocks": 4,
            "planned_cells": 12,
            "research_runs_submitted": 0,
        }

    monkeypatch.setattr(runner_base, "prepare", fake_prepare)
    monkeypatch.setattr(
        runner, "_bootstrap_approved_protocol", lambda *_args: protocol
    )

    result = runner.prepare(
        tmp_path / "experiment",
        tmp_path / "preflight",
        tmp_path / "baseline",
        tmp_path / "candidate",
        env_file,
        "a" * 64,
    )

    assert result["blocks"] == 1
    assert result["planned_cells"] == 3
    assert result["research_runs_submitted"] == 0
    environment_path = tmp_path / "experiment/arms/candidate/r1/environment.json"
    environment = runner_base._read_json(environment_path)
    binding = runner_base._read_json(
        tmp_path / "experiment/execution-binding.json"
    )
    assert environment["notes"]["hitl_mode"] == contract.HITL_MODE
    assert environment["notes"]["hitl_policy"] == contract.HITL_POLICY
    assert binding["blocks"][0]["environment_sha256"] == (
        runner_base._file_hash(environment_path)
    )


def test_base_validation_compatibility_does_not_change_frozen_hitl_policy(
    monkeypatch, tmp_path: Path
):
    protocol = contract.load_serial_check_protocol().payload
    environment_path = tmp_path / "arms/candidate/r1/environment.json"
    environment_path.parent.mkdir(parents=True)
    runner_base._write_json(
        environment_path,
        {
            "notes": {
                "hitl_mode": contract.HITL_MODE,
                "hitl_policy": contract.HITL_POLICY,
            }
        },
    )
    monkeypatch.setattr(
        runner, "_bootstrap_approved_protocol", lambda *_args: protocol
    )

    def fake_base_validate(*_args):
        compatible = runner_base._read_json(environment_path)
        assert compatible["notes"]["hitl_mode"] == runner.LEGACY_HITL_MODE
        return protocol, {"status": "ready"}

    monkeypatch.setattr(
        runner, "_BASE_VALIDATE_EXECUTION_BINDING", fake_base_validate
    )

    result = runner._base_validate_with_hitl_policy(
        tmp_path,
        tmp_path / "preflight",
        tmp_path / "baseline",
        tmp_path / "candidate",
        tmp_path / ".env",
        "a" * 64,
    )

    assert result == (protocol, {"status": "ready"})
    assert runner_base._read_json(environment_path)["notes"] == {
        "hitl_mode": contract.HITL_MODE,
        "hitl_policy": contract.HITL_POLICY,
    }


def _result() -> dict:
    return {
        "schema_version": 1,
        "protocol_id": contract.PROTOCOL_ID,
        "started_cells": 0,
        "planned_cells": 3,
        "complete": False,
        "stop_reason": "CONTROL_RepairPairControlError",
        "cells": [
            {
                "block": 1,
                "arm": "candidate",
                "repetition": 1,
                "case_id": case_id,
                "status": "not_submitted",
            }
            for case_id in contract.CASE_ORDER
        ],
        "records": [],
        "no_retries_or_splices": True,
        "ended_at": "2026-09-27T00:00:00+00:00",
        "ledger": {},
        "interpretation": "diagnostic-product-feedback-only-no-causal-improvement-claim",
    }


def test_reconciliation_recovers_only_same_root_completed_record(
    monkeypatch, tmp_path: Path
):
    ledger = tmp_path / "ledger"
    experiment = tmp_path / "experiment"
    collection = experiment / "collections/candidate-r1"
    ledger.mkdir()
    collection.mkdir(parents=True)
    record = {
        "experiment_id": contract.PROTOCOL_ID,
        "case_id": "P04",
        "task_id": "task-1",
        "run_id": "run-1",
        "status": "completed",
        "error_code": None,
        "hitl_resolutions": 0,
    }
    (ledger / "observations.jsonl").write_text(
        json.dumps(
            {
                "protocol_id": contract.PROTOCOL_ID,
                "arm": "candidate",
                "repetition": 1,
                "case_id": "P04",
                "task_id": "task-1",
                "run_id": "run-1",
                "status": "completed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (collection / "runs.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "LEDGER_ROOT", ledger)
    monkeypatch.setattr(runner, "_record_stop_reason", lambda *_args: None)
    monkeypatch.setattr(
        runner_base,
        "_ledger_summary",
        lambda: {
            "attempted_cells": 1,
            "known_admitted_min": 1,
            "possibly_submitted_max": 1,
            "submission_count_uncertain": False,
            "uncertain_cells": 0,
        },
    )

    reconciled = runner._reconcile_completed_records(
        experiment, _result(), contract.PROTOCOL_ID
    )

    assert reconciled["started_cells"] == 1
    assert reconciled["records"][0]["case_id"] == "P04"
    assert reconciled["cells"][0]["status"] == "completed"
    assert reconciled["complete"] is False
    assert (experiment / runner.RESULT_NAME).is_file()


def test_reconciliation_rejects_foreign_observation(monkeypatch, tmp_path: Path):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "observations.jsonl").write_text(
        json.dumps({"protocol_id": "foreign"}) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "LEDGER_ROOT", ledger)

    with pytest.raises(runner.RepairPairControlError, match="identity drift"):
        runner._reconcile_completed_records(
            tmp_path / "experiment", _result(), contract.PROTOCOL_ID
        )
