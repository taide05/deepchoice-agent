"""Control the v5 decoding-qualified 12-cell repair-package comparison.

V4 remains immutable.  This adapter reuses its reviewed controller while
binding a fresh protocol, child observer, ledger, and v4 predecessor evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
from typing import Any, Iterator

from scripts import product_optimization_repair_pair as _v4


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-repair-pair-v5.json"
CHILD = ROOT / "scripts/o1_pr2b_child_v5.py"
LEDGER_ROOT = ROOT / "outputs/product-optimization-ledgers/product-optimization-repair-pair-v5"
RepairPairControlError = _v4.RepairPairControlError


def _bound_jsonl_artifact(root: Path, specification: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(specification, dict)
        or set(specification) != {"path", "sha256"}
        or not isinstance(specification.get("sha256"), str)
        or len(specification["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in specification["sha256"])
    ):
        raise RepairPairControlError("predecessor artifact contract is invalid")
    path = _v4._contained_plain_file(root, specification["path"])
    if _v4._file_hash(path) != specification["sha256"]:
        raise RepairPairControlError("predecessor artifact identity drift")
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("predecessor artifact is invalid") from None
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise RepairPairControlError("predecessor artifact is invalid")
    return rows


def _validate_current_predecessor(
    protocol: dict[str, Any], root: Path = ROOT
) -> None:
    predecessor = protocol.get("current_predecessor")
    if not isinstance(predecessor, dict):
        raise RepairPairControlError("current predecessor contract is invalid")
    artifacts = predecessor.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "execution_claim", "attempted_cell", "observation", "run_result", "telemetry"
    }:
        raise RepairPairControlError("current predecessor artifact contract is invalid")
    claim = _v4._bound_json_artifact(root, artifacts["execution_claim"])
    cell = _v4._bound_json_artifact(root, artifacts["attempted_cell"])
    observation = _v4._bound_json_artifact(root, artifacts["observation"])
    result = _v4._bound_json_artifact(root, artifacts["run_result"])
    telemetry = _bound_jsonl_artifact(root, artifacts["telemetry"])
    predecessor_id = predecessor.get("protocol_id")
    if not (
        predecessor_id == "product-optimization-repair-pair-v4"
        and claim.get("schema_version") == 1
        and claim.get("protocol_id") == predecessor_id
        and claim.get("protocol_byte_sha256") == predecessor.get("protocol_byte_sha256")
        and claim.get("policy") == "single-execution-no-resume-or-retry"
    ):
        raise RepairPairControlError("current predecessor claim is invalid")
    if not (
        cell.get("schema_version") == 1
        and cell.get("protocol_id") == predecessor_id
        and (cell.get("arm"), cell.get("repetition"), cell.get("case_id"), cell.get("status"))
        == ("baseline", 2, "P04", "attempted-before-post")
    ):
        raise RepairPairControlError("current predecessor cell is invalid")
    cells_value = result.get("cells")
    cells = cells_value if isinstance(cells_value, list) else []
    records = result.get("records")
    expected_cells = [
        (block["block"], block["arm"], block["repetition"], case_id)
        for block in protocol["design"]["execution_blocks"]
        for case_id in block["case_order"]
    ]
    observed_cells = [
        (item.get("block"), item.get("arm"), item.get("repetition"), item.get("case_id"))
        for item in cells
        if isinstance(item, dict)
    ]
    completed = [
        item for item in cells
        if isinstance(item, dict) and item.get("status") == "completed"
    ]
    if not (
        result.get("schema_version") == 1
        and result.get("protocol_id") == predecessor_id
        and result.get("planned_cells") == 12
        and result.get("started_cells") == 1
        and result.get("complete") is False
        and result.get("stop_reason") == "TELEMETRY_strict_safe_fetch_failure"
        and result.get("no_retries_or_splices") is True
        and observed_cells == expected_cells
        and len(completed) == 1
        and sum(
            isinstance(item, dict) and item.get("status") == "not_submitted"
            for item in cells
        ) == 11
        and (completed[0].get("block"), completed[0].get("arm"),
             completed[0].get("repetition"), completed[0].get("case_id"))
        == (1, "baseline", 2, "P04")
        and result.get("ledger") == {
            "attempted_cells": 1,
            "known_admitted_min": 1,
            "possibly_submitted_max": 1,
            "submission_count_uncertain": False,
            "uncertain_cells": 0,
        }
        and isinstance(records, list)
        and len(records) == 1
    ):
        raise RepairPairControlError("current predecessor result is invalid")
    record = records[0]
    usage = record.get("usage") if isinstance(record, dict) else None
    observability = record.get("observability") if isinstance(record, dict) else None
    totals = observability.get("totals") if isinstance(observability, dict) else None
    calls = observability.get("calls") if isinstance(observability, dict) else None
    if not (
        isinstance(record, dict)
        and record.get("experiment_id") == predecessor_id
        and (record.get("block"), record.get("arm"), record.get("repetition"),
             record.get("case_id"), record.get("status"), record.get("error_code"))
        == (1, "baseline", 2, "P04", "completed", None)
        and record.get("observability_final") is True
        and isinstance(usage, dict)
        and usage.get("observation_final") is True
        and usage.get("token_usage_complete") is True
        and (usage.get("total_tokens"), usage.get("llm_calls"),
             usage.get("retrieval_calls"), usage.get("external_calls"),
             usage.get("failed_calls")) == (8622, 8, 6, 14, 0)
        and isinstance(totals, dict)
        and (totals.get("total_tokens"), totals.get("llm_calls"),
             totals.get("retrieval_calls"), totals.get("external_calls"),
             totals.get("failed_calls")) == (8622, 8, 6, 14, 0)
        and isinstance(calls, list)
        and len(calls) == 14
        and all(isinstance(item, dict) and item.get("status") == "succeeded"
                for item in calls)
        and observation.get("schema_version") == 1
        and observation.get("protocol_id") == predecessor_id
        and (observation.get("arm"), observation.get("repetition"),
             observation.get("case_id"), observation.get("status"),
             observation.get("error_code"))
        == ("baseline", 2, "P04", "completed", None)
        and observation.get("task_id") == record.get("task_id")
        and observation.get("run_id") == record.get("run_id")
        and predecessor.get("accounted_research_runs") == 1
        and predecessor.get("trace_external_calls") == 14
        and predecessor.get("disposition") == "immutable-no-retry-no-splice"
    ):
        raise RepairPairControlError("current predecessor completed record is invalid")
    failures = Counter(
        (row.get("error_type"), row.get("failure"), row.get("safe_fetch_phase"))
        for row in telemetry
        if row.get("event") == "safe_fetch_failure"
    )
    tls = [row for row in telemetry if row.get("event") == "proxy_tls_success"]
    if not (
        failures == Counter({
            ("UnsafeUrlError", "response_rejected", "response_received"): 4,
            ("OtherError", None, "response_received"): 2,
        })
        and tls
        and all(row.get("certificate_required") is True
                and row.get("hostname_check_enabled") is True
                and row.get("hostname_matches") is True for row in tls)
        and not any(row.get("event") == "child_failure" for row in telemetry)
        and any(row.get("event") == "service_stopped" for row in telemetry)
        and any(row.get("event") == "asyncio_runner_returned" for row in telemetry)
    ):
        raise RepairPairControlError("current predecessor telemetry is invalid")


def _bootstrap_approved_protocol(expected_protocol_byte_sha256: str) -> dict[str, Any]:
    if (
        len(expected_protocol_byte_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_protocol_byte_sha256)
    ):
        raise RepairPairControlError("approved protocol SHA is invalid")
    if _v4._file_hash(PROTOCOL_PATH) != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol identity mismatch")
    protocol = _v4._read_json(PROTOCOL_PATH)
    try:
        required = protocol["controller"]["required_files"]
    except (KeyError, TypeError):
        raise RepairPairControlError("approved controller TCB is invalid") from None
    if not isinstance(required, list) or not required:
        raise RepairPairControlError("approved controller TCB is invalid")
    for item in required:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise RepairPairControlError("approved controller TCB is invalid")
        relative = Path(item["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(item["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in item["sha256"])
        ):
            raise RepairPairControlError("approved controller TCB is invalid")
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT.resolve()) or _v4._file_hash(target) != item["sha256"]:
            raise RepairPairControlError("approved controller TCB drift")
    _v4._reject_import_shadows(ROOT, [item["path"] for item in required])
    _v4._validate_predecessor(protocol)
    _v4._validate_immediate_predecessor(protocol)
    _v4._validate_latest_predecessor(protocol)
    _validate_current_predecessor(protocol)
    return protocol


def _require_active_protocol(protocol: dict[str, Any]) -> None:
    authorization = protocol.get("authorization")
    controller = protocol.get("controller")
    ledger = protocol.get("budgets", {}).get("research_ledger")
    if not (
        protocol.get("status") == "frozen"
        and protocol.get("freeze_date") == "2026-09-26"
        and isinstance(controller, dict)
        and controller.get("research_admission") == "open-after-offline-runner-acceptance"
        and isinstance(authorization, dict)
        and authorization.get("status") == "approved"
        and authorization.get("decision_date") == "2026-09-26"
        and authorization.get("current_hard_total") == 155
        and authorization.get("proposed_hard_total") == 156
        and authorization.get("effective_hard_total") == 156
        and authorization.get("local_pair_max") == 12
        and authorization.get("final_concurrency_reserve") == 48
        and authorization.get("preserve_acceptance_thresholds") is True
        and isinstance(ledger, dict)
        and ledger.get("starting_used") == 96
        and ledger.get("local_pair_max") == 12
        and ledger.get("final_concurrency_reserve") == 48
        and ledger.get("hard_total") == 156
        and ledger.get("unallocated") == 0
    ):
        raise RepairPairControlError("research admission is not approved")


def _load_approved_protocol(expected_protocol_byte_sha256: str) -> Any:
    protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    package = importlib.import_module("benchmarks")
    module = importlib.import_module("benchmarks.product_optimization_repair_pair_v5")
    dev_requests = importlib.import_module("benchmarks.product_optimization_dev_requests")
    expected_origins = {
        package: ROOT / "benchmarks/__init__.py",
        module: ROOT / "benchmarks/product_optimization_repair_pair_v5.py",
        dev_requests: ROOT / "benchmarks/product_optimization_dev_requests.py",
    }
    if any(Path(item.__file__).resolve() != path.resolve()
           for item, path in expected_origins.items()):
        raise RepairPairControlError("approved controller import origin drift")
    frozen = module.load_repair_pair_protocol()
    if frozen.byte_sha256 != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol loader mismatch")
    if frozen.payload != protocol:
        raise RepairPairControlError("approved protocol payload mismatch")
    return frozen


@contextmanager
def _configured_base() -> Iterator[None]:
    replacements = {
        "PROTOCOL_PATH": PROTOCOL_PATH,
        "CHILD": CHILD,
        "LEDGER_ROOT": LEDGER_ROOT,
        "_bootstrap_approved_protocol": _bootstrap_approved_protocol,
        "_load_approved_protocol": _load_approved_protocol,
        "_require_active_protocol": _require_active_protocol,
    }
    previous = {name: getattr(_v4, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(_v4, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(_v4, name, value)


def audit(*args, **kwargs) -> dict[str, Any]:
    with _configured_base():
        return _v4.audit(*args, **kwargs)


def preflight(*args, **kwargs) -> dict[str, Any]:
    with _configured_base():
        return _v4.preflight(*args, **kwargs)


def prepare(*args, **kwargs) -> dict[str, Any]:
    with _configured_base():
        return _v4.prepare(*args, **kwargs)


async def run(*args, **kwargs) -> dict[str, Any]:
    with _configured_base():
        return await _v4.run(*args, **kwargs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "preflight", "prepare", "run"))
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preflight-dir", type=Path)
    parser.add_argument("--experiment-root", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--expected-protocol-byte-sha256", required=True)
    parser.add_argument("--execute-paid-probes", action="store_true")
    parser.add_argument("--execute-paid-runs", action="store_true")
    parser.add_argument("--trust-current-local-proxy", action="store_true")
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "audit":
            if args.env_file is None:
                parser.error("audit requires the private environment path")
            result = audit(args.baseline_root, args.candidate_root,
                           args.env_file.resolve(), args.expected_protocol_byte_sha256)
        elif args.command == "preflight":
            if (not args.execute_paid_probes or not args.trust_current_local_proxy
                    or args.output_dir is None or args.env_file is None):
                parser.error("preflight requires explicit paid probe/proxy consent and paths")
            result = preflight(args.output_dir.resolve(), args.baseline_root,
                               args.candidate_root, args.env_file.resolve(),
                               args.expected_protocol_byte_sha256)
        elif args.command == "prepare":
            if (args.experiment_root is None or args.preflight_dir is None
                    or args.env_file is None):
                parser.error("prepare requires experiment, preflight, and environment paths")
            result = prepare(args.experiment_root.resolve(), args.preflight_dir.resolve(),
                             args.baseline_root, args.candidate_root,
                             args.env_file.resolve(), args.expected_protocol_byte_sha256)
        else:
            if (not args.execute_paid_runs or args.experiment_root is None
                    or args.preflight_dir is None or args.env_file is None):
                parser.error("run requires explicit paid permission and prepared paths")
            result = asyncio.run(run(args.experiment_root.resolve(),
                                     args.preflight_dir.resolve(),
                                     args.baseline_root, args.candidate_root,
                                     args.env_file.resolve(),
                                     args.expected_protocol_byte_sha256))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if result.get("passed", result.get("complete", True)) else 1
    except Exception as exc:
        with _configured_base():
            try:
                ledger = _v4._ledger_summary()
            except Exception:
                ledger = {
                    "attempted_cells": None,
                    "known_admitted_min": None,
                    "possibly_submitted_max": None,
                    "uncertain_cells": None,
                    "submission_count_uncertain": True,
                }
        exact_submitted = (
            ledger["known_admitted_min"]
            if not ledger["submission_count_uncertain"] else None
        )
        print(json.dumps({"error_type": type(exc).__name__,
                          "research_runs_submitted": exact_submitted,
                          **ledger}, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
