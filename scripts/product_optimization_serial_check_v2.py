"""Run serial-check-v2 through the unchanged, reviewed v1 execution path.

Importing this entry point must not load LLM configuration before the private
environment is installed. No provider or network calls are made by audit.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
from typing import Iterator

from scripts import product_optimization_serial_check_v1 as parent

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v2.json"
PROTOCOL_ID = "product-optimization-serial-check-v2"
PARENT_PATH = ROOT / "benchmarks/product-optimization-serial-check-v1.json"
PARENT_SHA256 = "77b2efce9df2a8ed18b40489b7f569d85159b6d1247c976306cc8550af1e55f5"
LEDGER_ROOT = ROOT / "outputs/product-optimization-ledgers" / PROTOCOL_ID
RepairPairControlError = parent.RepairPairControlError
_base = parent._v4


def _load_approved_protocol(expected_protocol_byte_sha256: str):
    package = importlib.import_module("benchmarks")
    module = importlib.import_module("benchmarks.product_optimization_serial_check_v2")
    for loaded, relative in (
        (package, "benchmarks/__init__.py"),
        (module, "benchmarks/product_optimization_serial_check_v2.py"),
    ):
        if Path(loaded.__file__).resolve() != (ROOT / relative).resolve():
            raise RepairPairControlError("approved controller import origin drift")
    frozen = module.load_serial_check_protocol()
    if frozen.byte_sha256 != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol loader mismatch")
    return frozen


def _check_tcb(path: Path, digest: str) -> dict:
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or _base._file_hash(path) != digest):
        raise RepairPairControlError("approved protocol identity mismatch")
    raw = _base._read_json(path)
    required = raw.get("controller", {}).get("required_files")
    if not isinstance(required, list) or not required:
        raise RepairPairControlError("approved controller TCB is invalid")
    for item in required:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item["path"], str)
                or not isinstance(item["sha256"], str)):
            raise RepairPairControlError("approved controller TCB is invalid")
        target = _base._contained_plain_file(ROOT, item["path"])
        if _base._file_hash(target) != item["sha256"]:
            raise RepairPairControlError("approved controller TCB drift")
    _base._reject_import_shadows(ROOT, [item["path"] for item in required])
    return raw


def _validate_control_predecessor(protocol: dict) -> None:
    predecessor = protocol["control_predecessor"]
    artifacts = predecessor["artifacts"]
    binding = _base._bound_json_artifact(ROOT, artifacts["execution_binding"])
    claim = _base._bound_json_artifact(ROOT, artifacts["execution_claim"])
    result = _base._bound_json_artifact(ROOT, artifacts["run_result"])
    cells = {case: _base._bound_json_artifact(ROOT, artifacts["cell_" + case.lower()])
             for case in ("P04", "P01", "P08")}
    observations = parent._bound_jsonl_artifact(ROOT, artifacts["observations"])
    records = parent._bound_jsonl_artifact(ROOT, artifacts["collection_record"])
    parent._bound_jsonl_artifact(ROOT, artifacts["telemetry"])
    predecessor_id = "product-optimization-serial-check-v1"
    if not (
        predecessor["protocol_id"] == predecessor_id
        and predecessor["protocol_byte_sha256"] == PARENT_SHA256
        and predecessor["accounted_research_runs"] == 3
        and predecessor["disposition"] == "immutable-no-retry-no-splice"
        and binding.get("protocol_byte_sha256") == PARENT_SHA256
        and binding.get("status") == "ready"
        and claim.get("protocol_id") == predecessor_id
        and claim.get("policy") == "single-execution-no-resume-or-retry"
        and result.get("protocol_id") == predecessor_id
        and result.get("started_cells") == result.get("planned_cells") == 3
        and result.get("complete") is False
        and result.get("stop_reason") == "TELEMETRY_strict_safe_fetch_failure"
        and result.get("no_retries_or_splices") is True
        and result.get("ledger") == {
            "attempted_cells": 3, "known_admitted_min": 3, "possibly_submitted_max": 3,
            "submission_count_uncertain": False, "uncertain_cells": 0,
        }
    ):
        raise RepairPairControlError("v1 predecessor identity or accounting drift")
    for case, cell in cells.items():
        if not (
            cell.get("protocol_id") == predecessor_id
            and (cell.get("arm"), cell.get("repetition"), cell.get("case_id"))
            == ("candidate", 1, case)
            and cell.get("status") == "attempted-before-post"
        ):
            raise RepairPairControlError("v1 predecessor cell drift")
    for rows, id_field in ((observations, "protocol_id"), (records, "experiment_id")):
        if not (
            [row.get("case_id") for row in rows] == ["P04", "P01", "P08"]
            and all(row.get(id_field) == predecessor_id
                    and row.get("status") == "completed"
                    and row.get("error_code") is None for row in rows)
        ):
            raise RepairPairControlError("v1 predecessor completed evidence drift")
    if not all(row.get("observability_final") is True for row in records):
        raise RepairPairControlError("v1 predecessor observability incomplete")


def _bootstrap_approved_protocol(expected_protocol_byte_sha256: str) -> dict:
    _check_tcb(PROTOCOL_PATH, expected_protocol_byte_sha256)
    _check_tcb(PARENT_PATH, PARENT_SHA256)
    # The historical v6 chain remains independently checked, not rewritten as v2.
    parent._v6._bootstrap_approved_protocol(parent.BASE_PROTOCOL_SHA256)
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    module = importlib.import_module("benchmarks.product_optimization_serial_check_v1")
    parent._validate_control_predecessor(module.load_serial_check_protocol().payload)
    _validate_control_predecessor(frozen.payload)
    return frozen.payload


def _require_active_protocol(protocol: dict) -> None:
    # Enforce the whole materialized contract, including counts/order/HITL/budget.
    frozen = _load_approved_protocol(_base._file_hash(PROTOCOL_PATH))
    if (protocol.get("protocol_id") != PROTOCOL_ID
            or protocol.get("controller", {}).get("research_admission")
            != "open-after-independent-review-and-offline-acceptance"
            or json.dumps(protocol, sort_keys=True) != json.dumps(frozen.payload, sort_keys=True)):
        raise RepairPairControlError("v2 research admission is not open")


@contextmanager
def _configured_parent() -> Iterator[None]:
    # These adapters are single-process CLI scopes, not concurrent worker APIs.
    replacements = {
        "PROTOCOL_PATH": PROTOCOL_PATH,
        "LEDGER_ROOT": LEDGER_ROOT,
        "_load_approved_protocol": _load_approved_protocol,
        "_bootstrap_approved_protocol": _bootstrap_approved_protocol,
        "_require_active_protocol": _require_active_protocol,
    }
    previous = {name: getattr(parent, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(parent, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(parent, name, value)


def audit(*args, **kwargs) -> dict:
    with _configured_parent():
        return parent.audit(*args, **kwargs)


def _admit_call(args, kwargs, environment_index: int) -> None:
    parent._install_call_environment(args, kwargs, environment_index)
    index = environment_index + 1
    try:
        digest = args[index] if len(args) > index else kwargs["expected_protocol_byte_sha256"]
    except (IndexError, KeyError):
        raise RepairPairControlError("external protocol SHA is required") from None
    _require_active_protocol(_bootstrap_approved_protocol(digest))


def preflight(*args, **kwargs) -> dict:
    _admit_call(args, kwargs, 3)
    with _configured_parent():
        return parent.preflight(*args, **kwargs)


def prepare(*args, **kwargs) -> dict:
    _admit_call(args, kwargs, 4)
    with _configured_parent():
        return parent.prepare(*args, **kwargs)


async def run(*args, **kwargs) -> dict:
    _admit_call(args, kwargs, 4)
    with _configured_parent():
        return await parent.run(*args, **kwargs)


def main() -> int:
    # Retains explicit paid flags, environment-before-import, and v2 error ledger.
    # CLI calls parent entry points, whose preflight/prepare/run gates also use
    # _require_active_protocol through the scoped configuration below.
    with _configured_parent():
        return parent.main()


if __name__ == "__main__":
    raise SystemExit(main())
