"""Serial-check-v3 adapter; paid entry points stay closed until frozen activation."""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
from typing import Iterator

from scripts import product_optimization_serial_check_v2 as parent

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v3.json"
PROTOCOL_ID = "product-optimization-serial-check-v3"
PARENT_SHA256 = "47ffb9c66b07039a7c2730103718ad8b30126320152a9d13f1b303b4e6b89975"
LEDGER_ROOT = ROOT / "outputs/product-optimization-ledgers" / PROTOCOL_ID
RepairPairControlError = parent.RepairPairControlError
_base = parent._base
V2_PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v2.json"


def _load_approved_protocol(expected_protocol_byte_sha256: str):
    package = importlib.import_module("benchmarks")
    module = importlib.import_module("benchmarks.product_optimization_serial_check_v3")
    for loaded, relative in (
        (package, "benchmarks/__init__.py"),
        (module, "benchmarks/product_optimization_serial_check_v3.py"),
    ):
        if Path(loaded.__file__).resolve() != (ROOT / relative).resolve():
            raise RepairPairControlError("approved controller import origin drift")
    frozen = module.load_serial_check_protocol()
    if frozen.byte_sha256 != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol loader mismatch")
    return frozen


def _validate_control_predecessor(protocol: dict) -> None:
    predecessor = protocol["control_predecessor"]
    artifacts = predecessor["artifacts"]
    binding = _base._bound_json_artifact(ROOT, artifacts["execution_binding"])
    claim = _base._bound_json_artifact(ROOT, artifacts["execution_claim"])
    result = _base._bound_json_artifact(ROOT, artifacts["run_result"])
    cells = {case: _base._bound_json_artifact(ROOT, artifacts["cell_" + case.lower()])
             for case in ("P04", "P01")}
    observations = parent.parent._bound_jsonl_artifact(ROOT, artifacts["observations"])
    records = parent.parent._bound_jsonl_artifact(ROOT, artifacts["collection_record"])
    parent.parent._bound_jsonl_artifact(ROOT, artifacts["telemetry"])
    predecessor_id = parent.PROTOCOL_ID
    if not (
        predecessor["protocol_id"] == predecessor_id
        and predecessor["protocol_byte_sha256"] == PARENT_SHA256
        and predecessor["accounted_research_runs"] == 2
        and predecessor["disposition"] == "immutable-no-retry-no-splice"
        and binding.get("protocol_byte_sha256") == PARENT_SHA256
        and binding.get("status") == "ready"
        and claim.get("protocol_id") == predecessor_id
        and claim.get("protocol_byte_sha256") == PARENT_SHA256
        and claim.get("policy") == "single-execution-no-resume-or-retry"
        and result.get("protocol_id") == predecessor_id
        and result.get("started_cells") == 2
        and result.get("planned_cells") == 3
        and result.get("complete") is False
        and result.get("stop_reason") == "TELEMETRY_strict_external_http_response"
        and result.get("no_retries_or_splices") is True
        and result.get("ledger") == {
            "attempted_cells": 2, "known_admitted_min": 2,
            "possibly_submitted_max": 2, "submission_count_uncertain": False,
            "uncertain_cells": 0,
        }
        and [row.get("status") for row in result.get("cells", [])]
        == ["completed", "completed", "not_submitted"]
    ):
        raise RepairPairControlError("v2 predecessor identity or accounting drift")
    for case, cell in cells.items():
        if not (
            cell.get("protocol_id") == predecessor_id
            and (cell.get("arm"), cell.get("repetition"), cell.get("case_id"))
            == ("candidate", 1, case)
            and cell.get("status") == "attempted-before-post"
        ):
            raise RepairPairControlError("v2 predecessor cell drift")
    for rows, id_field in ((observations, "protocol_id"), (records, "experiment_id")):
        if not (
            [row.get("case_id") for row in rows] == ["P04", "P01"]
            and all(row.get(id_field) == predecessor_id
                    and row.get("status") == "completed"
                    and row.get("error_code") is None for row in rows)
        ):
            raise RepairPairControlError("v2 predecessor completed evidence drift")
    if not all(row.get("observability_final") is True for row in records):
        raise RepairPairControlError("v2 predecessor observability incomplete")


def _bootstrap_approved_protocol(expected_protocol_byte_sha256: str) -> dict:
    parent._check_tcb(PROTOCOL_PATH, expected_protocol_byte_sha256)
    # The original controller and both predecessor roots remain immutable.
    parent._check_tcb(V2_PROTOCOL_PATH, PARENT_SHA256)
    parent._check_tcb(parent.PARENT_PATH, parent.PARENT_SHA256)
    parent.parent._v6._bootstrap_approved_protocol(parent.parent.BASE_PROTOCOL_SHA256)
    v2 = importlib.import_module("benchmarks.product_optimization_serial_check_v2")
    v1 = importlib.import_module("benchmarks.product_optimization_serial_check_v1")
    if (Path(v2.__file__).resolve()
            != (ROOT / "benchmarks/product_optimization_serial_check_v2.py").resolve()
            or Path(v1.__file__).resolve()
            != (ROOT / "benchmarks/product_optimization_serial_check_v1.py").resolve()):
        raise RepairPairControlError("predecessor controller import origin drift")
    if v2.load_serial_check_protocol().byte_sha256 != PARENT_SHA256:
        raise RepairPairControlError("v2 protocol loader mismatch")
    parent.parent._validate_control_predecessor(v1.load_serial_check_protocol().payload)
    parent._validate_control_predecessor(v2.load_serial_check_protocol().payload)
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    _validate_control_predecessor(frozen.payload)
    return frozen.payload


def _require_active_protocol(protocol: dict) -> None:
    frozen = _load_approved_protocol(_base._file_hash(PROTOCOL_PATH))
    if (protocol.get("protocol_id") != PROTOCOL_ID
            or protocol.get("controller", {}).get("research_admission")
            != "open-after-independent-review-and-offline-acceptance"
            or json.dumps(protocol, sort_keys=True) != json.dumps(frozen.payload, sort_keys=True)):
        raise RepairPairControlError("v3 research admission is not open")


@contextmanager
def _configured_parent() -> Iterator[None]:
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
    parent.parent._install_call_environment(args, kwargs, environment_index)
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
    with _configured_parent():
        return parent.main()


if __name__ == "__main__":
    raise SystemExit(main())
