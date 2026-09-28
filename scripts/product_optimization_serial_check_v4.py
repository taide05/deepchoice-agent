"""V4 serial card adapter; paid entry points remain closed until activation."""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
from typing import Iterator

from scripts import product_optimization_serial_check_v3 as parent

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path("D:/deepchoice-agent")
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v4.json"
PROTOCOL_ID = "product-optimization-serial-check-v4"
PARENT_PATH = ROOT / "benchmarks/product-optimization-serial-check-v3.json"
PARENT_SHA256 = "ecfe3cab6f1efe21ff9d450a6587bc33d9ffa2a105537edf65ab1348fe484107"
LEDGER_ROOT = ROOT / "outputs/product-optimization-ledgers" / PROTOCOL_ID
RepairPairControlError = parent.RepairPairControlError
_base = parent._base


def _load_approved_protocol(expected_protocol_byte_sha256: str):
    package = importlib.import_module("benchmarks")
    module = importlib.import_module("benchmarks.product_optimization_serial_check_v4")
    for loaded, relative in (
        (package, "benchmarks/__init__.py"),
        (module, "benchmarks/product_optimization_serial_check_v4.py"),
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

    def bound(name: str, *, lines: bool = False):
        specification = artifacts[name]
        root = WORKSPACE if specification["root"] == "workspace" else ROOT
        descriptor = {key: specification[key] for key in ("path", "sha256")}
        if lines:
            return parent.parent.parent._bound_jsonl_artifact(root, descriptor)
        return _base._bound_json_artifact(root, descriptor)

    binding = bound("execution_binding")
    claim = bound("execution_claim")
    result = bound("run_result")
    cells = {case: bound("cell_" + case.lower()) for case in ("P04", "P01")}
    observations = bound("observations", lines=True)
    records = bound("collection_record", lines=True)
    bound("telemetry", lines=True)
    if not (
        predecessor["protocol_id"] == "product-optimization-serial-check-v3"
        and predecessor["protocol_byte_sha256"] == PARENT_SHA256
        and predecessor["accounted_research_runs"] == 2
        and predecessor["disposition"] == "immutable-no-retry-no-splice"
        and binding.get("protocol_byte_sha256") == PARENT_SHA256
        and binding.get("status") == "ready"
        and claim.get("protocol_id") == predecessor["protocol_id"]
        and claim.get("protocol_byte_sha256") == PARENT_SHA256
        and claim.get("policy") == "single-execution-no-resume-or-retry"
        and result.get("protocol_id") == predecessor["protocol_id"]
        and result.get("started_cells") == 2
        and result.get("planned_cells") == 3
        and result.get("complete") is False
        and result.get("stop_reason") == "BUDGET_OR_CALL_OBSERVABILITY_ANOMALY"
        and result.get("no_retries_or_splices") is True
        and result.get("ledger") == {
            "attempted_cells": 2, "known_admitted_min": 2,
            "possibly_submitted_max": 2, "submission_count_uncertain": False,
            "uncertain_cells": 0,
        }
        and [row.get("status") for row in result.get("cells", [])]
        == ["completed", "completed", "not_submitted"]
    ):
        raise RepairPairControlError("v3 predecessor identity or accounting drift")
    for case, cell in cells.items():
        if not (
            cell.get("protocol_id") == predecessor["protocol_id"]
            and (cell.get("arm"), cell.get("repetition"), cell.get("case_id"))
            == ("candidate", 1, case)
            and cell.get("status") == "attempted-before-post"
        ):
            raise RepairPairControlError("v3 predecessor cell drift")
    for rows, field in ((observations, "protocol_id"), (records, "experiment_id")):
        if not (
            [row.get("case_id") for row in rows] == ["P04", "P01"]
            and all(row.get(field) == predecessor["protocol_id"]
                    and row.get("status") == "completed"
                    and row.get("error_code") is None for row in rows)
        ):
            raise RepairPairControlError("v3 predecessor completed evidence drift")
    if not all(row.get("observability_final") is True for row in records):
        raise RepairPairControlError("v3 predecessor observability incomplete")


def _bootstrap_approved_protocol(expected_protocol_byte_sha256: str) -> dict:
    checker = parent.parent._check_tcb
    checker(PROTOCOL_PATH, expected_protocol_byte_sha256)
    checker(PARENT_PATH, PARENT_SHA256)
    checker(parent.V2_PROTOCOL_PATH, parent.PARENT_SHA256)
    checker(parent.parent.PARENT_PATH, parent.parent.PARENT_SHA256)
    parent.parent.parent._v6._bootstrap_approved_protocol(
        parent.parent.parent.BASE_PROTOCOL_SHA256
    )
    from benchmarks import product_optimization_serial_check_v1 as v1
    from benchmarks import product_optimization_serial_check_v2 as v2
    from benchmarks import product_optimization_serial_check_v3 as v3
    if any(Path(module.__file__).resolve() != (ROOT / relative).resolve()
           for module, relative in (
               (v1, "benchmarks/product_optimization_serial_check_v1.py"),
               (v2, "benchmarks/product_optimization_serial_check_v2.py"),
               (v3, "benchmarks/product_optimization_serial_check_v3.py"),
           )):
        raise RepairPairControlError("predecessor controller import origin drift")
    parent.parent.parent._validate_control_predecessor(v1.load_serial_check_protocol().payload)
    parent.parent._validate_control_predecessor(v2.load_serial_check_protocol().payload)
    parent._validate_control_predecessor(v3.load_serial_check_protocol().payload)
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    _validate_control_predecessor(frozen.payload)
    return frozen.payload


def _require_active_protocol(protocol: dict) -> None:
    frozen = _load_approved_protocol(_base._file_hash(PROTOCOL_PATH))
    if (protocol.get("protocol_id") != PROTOCOL_ID
            or protocol.get("controller", {}).get("research_admission")
            != "open-after-independent-review-and-offline-acceptance"
            or json.dumps(protocol, sort_keys=True) != json.dumps(frozen.payload, sort_keys=True)):
        raise RepairPairControlError("v4 research admission is not open")


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
    parent.parent.parent._install_call_environment(args, kwargs, environment_index)
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
