"""Control the proposed v6 successor to the immutable v5 stopped root.

V6 keeps the v5 product, observer, and experiment design.  It adds only two
controller guarantees: bounded Chroma runtime drift is accepted after a block
has been attempted, and completed same-root records are reconciled from the
append-only ledger if a later control check stops admission.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import stat
from typing import Any, Iterator

from scripts import product_optimization_repair_pair as _v4


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-repair-pair-v6.json"
CHILD = ROOT / "scripts/o1_pr2b_child_v5.py"
LEDGER_ROOT = ROOT / "outputs/product-optimization-ledgers/product-optimization-repair-pair-v6"
RepairPairControlError = _v4.RepairPairControlError
_BASE_VALIDATE_EXECUTION_BINDING = _v4._validate_execution_binding
_BASE_TREE_HASH = _v4._tree_hash


def _bound_jsonl_artifact(root: Path, specification: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(specification, dict)
        or set(specification) != {"path", "sha256"}
        or not isinstance(specification.get("sha256"), str)
        or len(specification["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in specification["sha256"])
    ):
        raise RepairPairControlError("control predecessor artifact contract is invalid")
    path = _v4._contained_plain_file(root, specification["path"])
    if _v4._file_hash(path) != specification["sha256"]:
        raise RepairPairControlError("control predecessor artifact identity drift")
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("control predecessor artifact is invalid") from None
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise RepairPairControlError("control predecessor artifact is invalid")
    return rows


def _validate_control_predecessor(protocol: dict[str, Any], root: Path = ROOT) -> None:
    predecessor = protocol.get("control_predecessor")
    if not isinstance(predecessor, dict):
        raise RepairPairControlError("control predecessor contract is invalid")
    artifacts = predecessor.get("artifacts")
    expected_artifacts = {
        "execution_binding", "execution_claim", "attempted_cell", "observation",
        "run_result", "collection_record", "telemetry",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise RepairPairControlError("control predecessor artifact contract is invalid")
    binding = _v4._bound_json_artifact(root, artifacts["execution_binding"])
    claim = _v4._bound_json_artifact(root, artifacts["execution_claim"])
    cell = _v4._bound_json_artifact(root, artifacts["attempted_cell"])
    observation = _v4._bound_json_artifact(root, artifacts["observation"])
    result = _v4._bound_json_artifact(root, artifacts["run_result"])
    records = _bound_jsonl_artifact(root, artifacts["collection_record"])
    telemetry = _bound_jsonl_artifact(root, artifacts["telemetry"])
    predecessor_id = "product-optimization-repair-pair-v5"
    if not (
        predecessor.get("protocol_id") == predecessor_id
        and claim.get("schema_version") == 1
        and claim.get("protocol_id") == predecessor_id
        and claim.get("protocol_byte_sha256") == predecessor.get("protocol_byte_sha256")
        and claim.get("policy") == "single-execution-no-resume-or-retry"
        and binding.get("schema_version") == 1
        and binding.get("protocol_byte_sha256") == predecessor.get("protocol_byte_sha256")
        and binding.get("status") == "ready"
    ):
        raise RepairPairControlError("control predecessor identity is invalid")
    if not (
        cell.get("schema_version") == 1
        and cell.get("protocol_id") == predecessor_id
        and (cell.get("arm"), cell.get("repetition"), cell.get("case_id"), cell.get("status"))
        == ("baseline", 2, "P04", "attempted-before-post")
        and observation.get("schema_version") == 1
        and observation.get("protocol_id") == predecessor_id
        and (observation.get("arm"), observation.get("repetition"),
             observation.get("case_id"), observation.get("status"),
             observation.get("error_code"))
        == ("baseline", 2, "P04", "completed", None)
    ):
        raise RepairPairControlError("control predecessor cell evidence is invalid")
    cells = result.get("cells") if isinstance(result.get("cells"), list) else []
    expected_cells = [
        (block["block"], block["arm"], block["repetition"], case_id)
        for block in protocol["design"]["execution_blocks"]
        for case_id in block["case_order"]
    ]
    if not (
        result.get("schema_version") == 1
        and result.get("protocol_id") == predecessor_id
        and result.get("planned_cells") == 12
        and result.get("started_cells") == 0
        and result.get("complete") is False
        and result.get("stop_reason") == "CONTROL_RepairPairControlError"
        and result.get("records") == []
        and result.get("no_retries_or_splices") is True
        and [
            (item.get("block"), item.get("arm"), item.get("repetition"), item.get("case_id"))
            for item in cells if isinstance(item, dict)
        ] == expected_cells
        and all(isinstance(item, dict) and item.get("status") == "not_submitted"
                for item in cells)
        and result.get("ledger") == {
            "attempted_cells": 1,
            "known_admitted_min": 1,
            "possibly_submitted_max": 1,
            "submission_count_uncertain": False,
            "uncertain_cells": 0,
        }
    ):
        raise RepairPairControlError("control predecessor result is invalid")
    if len(records) != 1:
        raise RepairPairControlError("control predecessor completed record is invalid")
    record = records[0]
    usage = record.get("usage") if isinstance(record, dict) else None
    totals = record.get("observability", {}).get("totals") if isinstance(record, dict) else None
    calls = record.get("observability", {}).get("calls") if isinstance(record, dict) else None
    if not (
        record.get("experiment_id") == predecessor_id
        and (record.get("profile"), record.get("repetition"), record.get("case_id"),
             record.get("status"), record.get("error_code"))
        == ("serial-r2", 2, "P04", "completed", None)
        and record.get("observability_final") is True
        and isinstance(usage, dict)
        and usage.get("observation_final") is True
        and usage.get("token_usage_complete") is True
        and (usage.get("total_tokens"), usage.get("llm_calls"),
             usage.get("retrieval_calls"), usage.get("external_calls"),
             usage.get("failed_calls")) == (9372, 10, 6, 16, 0)
        and isinstance(totals, dict)
        and (totals.get("total_tokens"), totals.get("llm_calls"),
             totals.get("retrieval_calls"), totals.get("external_calls"),
             totals.get("failed_calls")) == (9372, 10, 6, 16, 0)
        and isinstance(calls, list) and len(calls) == 16
        and all(isinstance(item, dict) and item.get("status") == "succeeded"
                for item in calls)
        and observation.get("task_id") == record.get("task_id")
        and observation.get("run_id") == record.get("run_id")
        and predecessor.get("accounted_research_runs") == 1
        and predecessor.get("trace_external_calls") == 16
        and predecessor.get("disposition") == "immutable-no-retry-no-splice"
    ):
        raise RepairPairControlError("control predecessor completed record is invalid")
    failures = Counter(
        (row.get("error_type"), row.get("failure"), row.get("safe_fetch_phase"))
        for row in telemetry if row.get("event") == "safe_fetch_failure"
    )
    tls = [row for row in telemetry if row.get("event") == "proxy_tls_success"]
    if not (
        failures == Counter({
            ("UnsafeUrlError", "response_rejected", "response_received"): 7,
        })
        and tls
        and all(row.get("certificate_required") is True
                and row.get("hostname_check_enabled") is True
                and row.get("hostname_matches") is True for row in tls)
        and not any(row.get("event") == "child_failure" for row in telemetry)
        and any(row.get("event") == "service_stopped" for row in telemetry)
        and any(row.get("event") == "asyncio_runner_returned" for row in telemetry)
        and predecessor.get("used_knowledge_tree_sha256")
        == "c5b46ded75fb9fed8ee93a82d8487813a1c193f457626815336347a1e698ccdf"
    ):
        raise RepairPairControlError("control predecessor telemetry is invalid")


def _load_raw_protocol() -> dict[str, Any]:
    try:
        payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("approved protocol could not be loaded") from None
    if not isinstance(payload, dict):
        raise RepairPairControlError("approved protocol is invalid")
    return payload


def _bootstrap_approved_protocol(expected_protocol_byte_sha256: str) -> dict[str, Any]:
    if (
        len(expected_protocol_byte_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_protocol_byte_sha256)
        or _v4._file_hash(PROTOCOL_PATH) != expected_protocol_byte_sha256
    ):
        raise RepairPairControlError("approved protocol identity mismatch")
    raw = _load_raw_protocol()
    required = raw.get("controller", {}).get("required_files")
    if not isinstance(required, list) or not required:
        raise RepairPairControlError("approved controller TCB is invalid")
    for item in required:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise RepairPairControlError("approved controller TCB is invalid")
        relative = Path(item["path"])
        target = (ROOT / relative).resolve()
        if (
            relative.is_absolute() or ".." in relative.parts
            or not target.is_relative_to(ROOT.resolve())
            or _v4._file_hash(target) != item["sha256"]
        ):
            raise RepairPairControlError("approved controller TCB drift")
    _v4._reject_import_shadows(ROOT, [item["path"] for item in required])
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    protocol = frozen.payload
    _v4._validate_predecessor(protocol)
    _v4._validate_immediate_predecessor(protocol)
    _v4._validate_latest_predecessor(protocol)
    from scripts import product_optimization_repair_pair_v5 as v5

    v5._validate_current_predecessor(protocol)
    _validate_control_predecessor(protocol)
    return protocol


def _require_active_protocol(protocol: dict[str, Any]) -> None:
    authorization = protocol.get("authorization")
    controller = protocol.get("controller")
    ledger = protocol.get("budgets", {}).get("research_ledger")
    if not (
        protocol.get("status") == "frozen"
        and isinstance(controller, dict)
        and controller.get("research_admission") == "open-after-offline-runner-acceptance"
        and isinstance(authorization, dict)
        and authorization.get("status") == "approved-existing-cap"
        and authorization.get("current_hard_total") == 156
        and authorization.get("effective_hard_total") == 156
        and authorization.get("local_pair_max") == 12
        and authorization.get("concurrency_runs_authorized") == 0
        and authorization.get("deferred_unallocated") == 47
        and isinstance(ledger, dict)
        and ledger.get("starting_used") == 97
        and ledger.get("local_pair_max") == 12
        and ledger.get("final_concurrency_reserve") == 0
        and ledger.get("hard_total") == 156
        and ledger.get("unallocated") == 47
    ):
        raise RepairPairControlError("research admission is not approved")


def _load_approved_protocol(expected_protocol_byte_sha256: str) -> Any:
    package = importlib.import_module("benchmarks")
    module = importlib.import_module("benchmarks.product_optimization_repair_pair_v6")
    dev_requests = importlib.import_module("benchmarks.product_optimization_dev_requests")
    expected_origins = {
        package: ROOT / "benchmarks/__init__.py",
        module: ROOT / "benchmarks/product_optimization_repair_pair_v6.py",
        dev_requests: ROOT / "benchmarks/product_optimization_dev_requests.py",
    }
    if any(Path(item.__file__).resolve() != path.resolve()
           for item, path in expected_origins.items()):
        raise RepairPairControlError("approved controller import origin drift")
    frozen = module.load_repair_pair_protocol()
    if frozen.byte_sha256 != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol loader mismatch")
    return frozen


def _regular_file_map(root: Path) -> dict[str, tuple[int, str]]:
    root = _v4._validate_plain_directory(root)
    files: dict[str, tuple[int, str]] = {}
    try:
        paths = sorted(root.rglob("*"))
    except OSError:
        raise RepairPairControlError("knowledge tree unavailable") from None
    for path in paths:
        try:
            metadata = path.lstat()
        except OSError:
            raise RepairPairControlError("knowledge tree unavailable") from None
        if stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0) & 0x0400
        ):
            raise RepairPairControlError("knowledge artifact contains link or reparse point")
        if stat.S_ISREG(metadata.st_mode):
            files[path.relative_to(root).as_posix()] = (
                metadata.st_size, _v4._file_hash(path)
            )
        elif not stat.S_ISDIR(metadata.st_mode):
            raise RepairPairControlError("knowledge artifact is not a plain file")
    if not files:
        raise RepairPairControlError("knowledge tree is empty")
    return files


def _validate_used_knowledge_copy(
    pristine: Path, used: Path, allowed_drift_paths: set[str]
) -> None:
    expected = _regular_file_map(pristine)
    observed = _regular_file_map(used)
    if set(expected) != set(observed):
        raise RepairPairControlError("used knowledge inventory drift")
    changed: set[str] = set()
    for relative, (expected_size, expected_hash) in expected.items():
        observed_size, observed_hash = observed[relative]
        if observed_hash != expected_hash:
            changed.add(relative)
            if relative not in allowed_drift_paths or observed_size != expected_size:
                raise RepairPairControlError("used knowledge content drift")
    if not changed.issubset(allowed_drift_paths):
        raise RepairPairControlError("used knowledge runtime drift is invalid")


def _attempted_blocks(protocol: dict[str, Any]) -> set[tuple[str, int]]:
    attempted: set[tuple[str, int]] = set()
    cells_dir = LEDGER_ROOT / "cells"
    if not cells_dir.is_dir():
        return attempted
    for path in cells_dir.glob("*.json"):
        cell = _v4._read_json(path)
        if cell.get("protocol_id") != protocol.get("protocol_id"):
            raise RepairPairControlError("protocol ledger identity drift")
        attempted.add((cell.get("arm"), cell.get("repetition")))
    valid = {
        (block["arm"], block["repetition"])
        for block in protocol["design"]["execution_blocks"]
    }
    if not attempted.issubset(valid):
        raise RepairPairControlError("protocol ledger block drift")
    return attempted


def _validate_execution_binding_allow_used(
    root: Path,
    preflight_dir: Path,
    baseline_root: Path,
    candidate_root: Path,
    env_file: Path,
    expected_protocol_byte_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    arguments = (
        root,
        preflight_dir,
        baseline_root,
        candidate_root,
        env_file,
        expected_protocol_byte_sha256,
    )
    try:
        return _BASE_VALIDATE_EXECUTION_BINDING(*arguments)
    except RepairPairControlError as exc:
        if str(exc) != "prepared block drift":
            raise
    root = Path(root).resolve()
    protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    attempted = _attempted_blocks(protocol)
    if not attempted:
        raise RepairPairControlError("prepared block drift")
    binding = _v4._read_json(root / "execution-binding.json")
    allowed = set(protocol["stopping"]["allowed_chroma_runtime_drift_paths"])
    masked: dict[Path, str] = {}
    for block in binding.get("blocks", []):
        key = (block.get("arm"), block.get("repetition"))
        knowledge = (
            _v4._block_root(root, block["arm"], block["repetition"])
            / block["profile"] / "knowledge"
        ).resolve()
        if key in attempted:
            _validate_used_knowledge_copy(_v4.SEED_ROOT, knowledge, allowed)
            masked[knowledge] = block["knowledge_sha256"]
        elif _BASE_TREE_HASH(knowledge) != block["knowledge_sha256"]:
            raise RepairPairControlError("unattempted knowledge drift")

    def masked_tree_hash(path: Path) -> str:
        resolved = path.resolve()
        if resolved in masked:
            return masked[resolved]
        return _BASE_TREE_HASH(path)

    previous = _v4._tree_hash
    try:
        _v4._tree_hash = masked_tree_hash
        return _BASE_VALIDATE_EXECUTION_BINDING(*arguments)
    finally:
        _v4._tree_hash = previous


def _reconcile_completed_records(
    experiment_root: Path, result: dict[str, Any], protocol_id: str
) -> dict[str, Any]:
    reconciled = json.loads(json.dumps(result))
    records = reconciled.get("records")
    cells = reconciled.get("cells")
    if not isinstance(records, list) or not isinstance(cells, list):
        raise RepairPairControlError("run result structure is invalid")
    known = {
        (item.get("arm"), item.get("repetition"), item.get("case_id"))
        for item in records if isinstance(item, dict)
    }
    observation_path = LEDGER_ROOT / "observations.jsonl"
    try:
        observations = [] if not observation_path.is_file() else [
            json.loads(line)
            for line in observation_path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("protocol observation ledger is invalid") from None
    block_by_key = {
        (cell.get("arm"), cell.get("repetition"), cell.get("case_id")): cell.get("block")
        for cell in cells if isinstance(cell, dict)
    }
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("protocol_id") != protocol_id:
            raise RepairPairControlError("protocol observation identity drift")
        key = (
            observation.get("arm"), observation.get("repetition"),
            observation.get("case_id"),
        )
        if key not in block_by_key:
            raise RepairPairControlError("protocol observation cell drift")
        if key in known or observation.get("status") not in _v4.SUCCESS:
            continue
        collection = experiment_root / "collections" / f"{key[0]}-r{key[1]}"
        runs = _bound_jsonl_artifact(
            experiment_root,
            {
                "path": (collection / "runs.jsonl").relative_to(experiment_root).as_posix(),
                "sha256": _v4._file_hash(collection / "runs.jsonl"),
            },
        )
        matches = [
            item for item in runs
            if item.get("experiment_id") == protocol_id
            and item.get("case_id") == key[2]
            and item.get("task_id") == observation.get("task_id")
            and item.get("run_id") == observation.get("run_id")
        ]
        if len(matches) != 1 or _v4._record_stop_reason(matches[0], collection) is not None:
            raise RepairPairControlError("completed record reconciliation failed")
        record = matches[0]
        record.update(arm=key[0], repetition=key[1], block=block_by_key.get(key))
        records.append(record)
        known.add(key)
        for cell in cells:
            if (cell.get("arm"), cell.get("repetition"), cell.get("case_id")) == key:
                cell["status"] = record["status"]
                cell["error_code"] = record.get("error_code")
                break
    reconciled["started_cells"] = len(records)
    reconciled["ledger"] = _v4._ledger_summary()
    reconciled["complete"] = len(records) == 12 and reconciled.get("stop_reason") is None
    if reconciled != result:
        _v4._write_json(experiment_root / "repair-pair-run-result.json", reconciled)
    return reconciled


@contextmanager
def _configured_base() -> Iterator[None]:
    replacements = {
        "PROTOCOL_PATH": PROTOCOL_PATH,
        "CHILD": CHILD,
        "LEDGER_ROOT": LEDGER_ROOT,
        "_bootstrap_approved_protocol": _bootstrap_approved_protocol,
        "_load_approved_protocol": _load_approved_protocol,
        "_require_active_protocol": _require_active_protocol,
        "_validate_execution_binding": _validate_execution_binding_allow_used,
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
        result = await _v4.run(*args, **kwargs)
        experiment_root = Path(
            args[0] if args else kwargs["experiment_root"]
        )
        return _reconcile_completed_records(
            experiment_root, result, result["protocol_id"]
        )


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
