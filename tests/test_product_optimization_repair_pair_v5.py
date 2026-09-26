from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

from benchmarks import product_optimization_repair_pair as protocol_v4
from benchmarks import product_optimization_repair_pair_v5 as protocol_v5
from scripts import o1_pr2b_child_v5 as child_v5
from scripts import product_optimization_repair_pair as runner_v4
from scripts import product_optimization_repair_pair_v5 as runner_v5


def _write_json(root: Path, path: Path, payload: dict) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": runner_v4._file_hash(path),
    }


def _current_predecessor_protocol(root: Path) -> dict:
    protocol = json.loads(protocol_v5.PROTOCOL_PATH.read_text(encoding="utf-8"))
    protocol_id = "product-optimization-repair-pair-v4"
    execution_blocks = protocol["design"]["execution_blocks"]
    cells = [
        {
            "block": block["block"],
            "arm": block["arm"],
            "repetition": block["repetition"],
            "case_id": case_id,
            "status": (
                "completed"
                if (block["block"], block["arm"], block["repetition"], case_id)
                == (1, "baseline", 2, "P04")
                else "not_submitted"
            ),
        }
        for block in execution_blocks
        for case_id in block["case_order"]
    ]
    record = {
        "experiment_id": protocol_id,
        "block": 1,
        "arm": "baseline",
        "repetition": 2,
        "case_id": "P04",
        "status": "completed",
        "error_code": None,
        "task_id": "task-v4",
        "run_id": "run-v4",
        "observability_final": True,
        "usage": {
            "observation_final": True,
            "token_usage_complete": True,
            "total_tokens": 8622,
            "llm_calls": 8,
            "retrieval_calls": 6,
            "external_calls": 14,
            "failed_calls": 0,
        },
        "observability": {
            "totals": {
                "total_tokens": 8622,
                "llm_calls": 8,
                "retrieval_calls": 6,
                "external_calls": 14,
                "failed_calls": 0,
            },
            "calls": [{"status": "succeeded"} for _ in range(14)],
        },
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "planned_cells": 12,
        "started_cells": 1,
        "complete": False,
        "stop_reason": "TELEMETRY_strict_safe_fetch_failure",
        "no_retries_or_splices": True,
        "cells": cells,
        "ledger": {
            "attempted_cells": 1,
            "known_admitted_min": 1,
            "possibly_submitted_max": 1,
            "submission_count_uncertain": False,
            "uncertain_cells": 0,
        },
        "records": [record],
    }
    payloads = {
        "execution_claim": {
            "schema_version": 1,
            "protocol_id": protocol_id,
            "protocol_byte_sha256": "d" * 64,
            "policy": "single-execution-no-resume-or-retry",
        },
        "attempted_cell": {
            "schema_version": 1,
            "protocol_id": protocol_id,
            "arm": "baseline",
            "repetition": 2,
            "case_id": "P04",
            "status": "attempted-before-post",
        },
        "observation": {
            "schema_version": 1,
            "protocol_id": protocol_id,
            "arm": "baseline",
            "repetition": 2,
            "case_id": "P04",
            "status": "completed",
            "error_code": None,
            "task_id": "task-v4",
            "run_id": "run-v4",
        },
        "run_result": result,
    }
    specifications = {
        name: _write_json(root, root / "artifacts" / f"{name}.json", payload)
        for name, payload in payloads.items()
    }
    telemetry_rows = [
        *[
            {
                "event": "safe_fetch_failure",
                "error_type": "UnsafeUrlError",
                "failure": "response_rejected",
                "safe_fetch_phase": "response_received",
            }
            for _ in range(4)
        ],
        *[
            {
                "event": "safe_fetch_failure",
                "error_type": "OtherError",
                "failure": None,
                "safe_fetch_phase": "response_received",
            }
            for _ in range(2)
        ],
        {
            "event": "proxy_tls_success",
            "certificate_required": True,
            "hostname_check_enabled": True,
            "hostname_matches": True,
        },
        {"event": "service_stopped"},
        {"event": "asyncio_runner_returned"},
    ]
    telemetry_path = root / "artifacts" / "telemetry.jsonl"
    telemetry_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in telemetry_rows),
        encoding="utf-8",
    )
    specifications["telemetry"] = {
        "path": telemetry_path.relative_to(root).as_posix(),
        "sha256": runner_v4._file_hash(telemetry_path),
    }
    protocol["current_predecessor"] = {
        "protocol_id": protocol_id,
        "protocol_byte_sha256": "d" * 64,
        "artifacts": specifications,
        "accounted_research_runs": 1,
        "trace_external_calls": 14,
        "disposition": "immutable-no-retry-no-splice",
    }
    return protocol


@pytest.mark.parametrize(
    "error", (httpx.DecodingError("bad encoding"), httpx.StreamClosed())
)
def test_v5_child_normalizes_only_dispatched_response_consumption(error):
    from deepchoice.security.urls import SafeFetchFailure, UnsafeUrlError

    assert child_v5._bounded_response_failure(error, "before_http") is error
    for phase in ("http_dispatch", "response_received"):
        normalized = child_v5._bounded_response_failure(error, phase)
        assert isinstance(normalized, UnsafeUrlError)
        assert normalized.failure is SafeFetchFailure.RESPONSE_REJECTED


def test_v5_child_preserves_unrelated_request_errors():
    error = httpx.ProxyError("redacted")
    assert child_v5._bounded_response_failure(error, "response_received") is error


def test_v5_protocol_loads_without_changing_frozen_v4():
    frozen_v5 = protocol_v5.load_repair_pair_protocol()
    frozen_v4 = protocol_v4.load_repair_pair_protocol()

    assert frozen_v5.payload["protocol_id"] == protocol_v5.PROTOCOL_ID
    assert frozen_v5.payload["budgets"]["research_ledger"] == {
        "starting_used": 96,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "hard_total": 156,
        "unallocated": 0,
    }
    assert [
        item["blind_label"]
        for item in frozen_v5.payload["design"]["blind_review_order"]
    ] == [f"RP5-{index:02d}" for index in range(1, 13)]
    assert frozen_v4.byte_sha256 == (
        "dd6814e128c9e40b7b4f70b6a2b1e6db2434f4243876e783f5a20a1a25a3a6c6"
    )
    assert frozen_v4.payload["protocol_id"] == "product-optimization-repair-pair-v4"


def test_v5_protocol_has_no_placeholder_controller_hashes():
    payload = json.loads(protocol_v5.PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert all(
        item["sha256"] != "0" * 64
        for item in payload["controller"]["required_files"]
    )


def test_v5_current_predecessor_binds_exact_stop_semantics(tmp_path: Path):
    protocol = _current_predecessor_protocol(tmp_path)
    runner_v5._validate_current_predecessor(protocol, tmp_path)

    telemetry = tmp_path / protocol["current_predecessor"]["artifacts"]["telemetry"]["path"]
    rows = telemetry.read_text(encoding="utf-8").splitlines()
    changed = json.loads(rows[4])
    changed["error_type"] = "TransportError"
    rows[4] = json.dumps(changed, sort_keys=True)
    telemetry.write_text("\n".join(rows) + "\n", encoding="utf-8")
    protocol["current_predecessor"]["artifacts"]["telemetry"]["sha256"] = (
        runner_v4._file_hash(telemetry)
    )

    with pytest.raises(
        runner_v5.RepairPairControlError,
        match="current predecessor telemetry is invalid",
    ):
        runner_v5._validate_current_predecessor(protocol, tmp_path)


def test_v5_current_predecessor_rejects_nonlist_cells(tmp_path: Path):
    protocol = _current_predecessor_protocol(tmp_path)
    specification = protocol["current_predecessor"]["artifacts"]["run_result"]
    result_path = tmp_path / specification["path"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["cells"] = None
    result_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    specification["sha256"] = runner_v4._file_hash(result_path)

    with pytest.raises(
        runner_v5.RepairPairControlError,
        match="current predecessor result is invalid",
    ):
        runner_v5._validate_current_predecessor(protocol, tmp_path)


def test_v5_base_configuration_is_scoped_and_restored():
    names = (
        "PROTOCOL_PATH",
        "CHILD",
        "LEDGER_ROOT",
        "_bootstrap_approved_protocol",
        "_load_approved_protocol",
        "_require_active_protocol",
    )
    before = {name: getattr(runner_v4, name) for name in names}
    with runner_v5._configured_base():
        assert runner_v4.PROTOCOL_PATH == runner_v5.PROTOCOL_PATH
        assert runner_v4.CHILD == runner_v5.CHILD
        assert runner_v4.LEDGER_ROOT == runner_v5.LEDGER_ROOT
    assert {name: getattr(runner_v4, name) for name in names} == before


def test_v5_active_protocol_rejects_budget_drift():
    protocol = json.loads(protocol_v5.PROTOCOL_PATH.read_text(encoding="utf-8"))
    runner_v5._require_active_protocol(protocol)
    changed = copy.deepcopy(protocol)
    changed["budgets"]["research_ledger"]["hard_total"] = 157
    with pytest.raises(
        runner_v5.RepairPairControlError,
        match="research admission is not approved",
    ):
        runner_v5._require_active_protocol(changed)
