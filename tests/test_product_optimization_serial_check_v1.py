from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import product_optimization_serial_check_v1 as contract
from scripts import product_optimization_repair_pair as runner_base
from scripts import product_optimization_serial_check_v1 as runner


def test_serial_check_contract_is_candidate_only_and_closed_pending_review():
    frozen = contract.load_serial_check_protocol()
    payload = frozen.payload

    assert payload["protocol_id"] == contract.PROTOCOL_ID
    assert payload["status"] == "proposed"
    assert payload["controller"]["research_admission"] == (
        "closed-pending-independent-review"
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


def test_proposed_card_cannot_admit_research():
    protocol = contract.load_serial_check_protocol().payload

    with pytest.raises(runner.RepairPairControlError, match="not open"):
        runner._require_active_protocol(protocol)


def test_fixed_case_projection_preserves_existing_hitl_policy():
    protocol = contract.load_serial_check_protocol().payload

    cases = runner._load_cases(protocol)

    assert tuple(cases) == ("P01", "P04", "P08")
    assert cases["P04"]["hitl"]["action"] == "limited_report"
    assert cases["P08"]["hitl"]["action"] == "provide_context"
    assert cases["P08"]["hitl"]["repeat_action"] == "limited_report"
    assert cases["P08"]["hitl"]["supplemental_input"]


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
    monkeypatch.setattr(
        runner_base,
        "prepare",
        lambda *_args, **_kwargs: {
            "prepared": True,
            "blocks": 4,
            "planned_cells": 12,
            "research_runs_submitted": 0,
        },
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
