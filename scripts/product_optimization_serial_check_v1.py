"""Control the proposed three-case serial product-effect diagnostic.

The card runs only the current candidate, in the fixed P04/P01/P08 order,
with one in-flight case.  Historical baseline reports are context only: this
run can diagnose current report quality and runtime health, but cannot prove a
paired causal improvement.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
from pathlib import Path
import secrets
import stat
import subprocess
import sys
from typing import Any, Iterator

import httpx

from scripts import product_optimization_repair_pair as _v4
from scripts import product_optimization_repair_pair_v6 as _v6


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v1.json"
BASE_PROTOCOL_SHA256 = (
    "393dd11655b92d8e35683bdcbfdac1fe683f5df63ecc99a59dfdd0a7a0ceb64c"
)
CHILD = ROOT / "scripts/o1_pr2b_child_v5.py"
LEDGER_ROOT = (
    ROOT / "outputs/product-optimization-ledgers/product-optimization-serial-check-v1"
)
RESULT_NAME = "serial-check-run-result.json"
LEGACY_HITL_MODE = "stop-at-hitl-no-auto-resolution"
RepairPairControlError = _v4.RepairPairControlError
_BASE_VALIDATE_EXECUTION_BINDING = _v4._validate_execution_binding
_BASE_TREE_HASH = _v4._tree_hash


class _SerialCheckCollectorMixin:
    def __init__(self, *args: Any, max_hitl_resolutions: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._max_hitl_resolutions = max_hitl_resolutions

    async def _resolve_decision(
        self,
        case: dict[str, Any],
        task: dict[str, Any],
        decision: dict[str, Any],
        *,
        resolution_index: int,
    ) -> str | None:
        if resolution_index >= self._max_hitl_resolutions:
            return "HITL_RESOLUTION_LIMIT_REACHED"
        return await super()._resolve_decision(
            case,
            task,
            decision,
            resolution_index=resolution_index,
        )


def _serial_check_collector(
    *args: Any, max_hitl_resolutions: int, **kwargs: Any
) -> Any:
    # Keep this import after the private environment is installed. Importing the
    # collector at module load can transitively freeze LLM settings too early.
    from benchmarks.product_baseline import DurableBaselineCollector

    class SerialCheckCollector(
        _SerialCheckCollectorMixin, DurableBaselineCollector
    ):
        pass

    return SerialCheckCollector(
        *args, max_hitl_resolutions=max_hitl_resolutions, **kwargs
    )


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
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("control predecessor artifact is invalid") from None
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise RepairPairControlError("control predecessor artifact is invalid")
    return rows


def _validate_control_predecessor(protocol: dict[str, Any]) -> None:
    predecessor = protocol.get("control_predecessor")
    artifacts = predecessor.get("artifacts") if isinstance(predecessor, dict) else None
    if not isinstance(artifacts, dict):
        raise RepairPairControlError("control predecessor contract is invalid")
    binding = _v4._bound_json_artifact(ROOT, artifacts["execution_binding"])
    claim = _v4._bound_json_artifact(ROOT, artifacts["execution_claim"])
    result = _v4._bound_json_artifact(ROOT, artifacts["run_result"])
    cells = {
        case_id: _v4._bound_json_artifact(ROOT, artifacts[f"cell_{case_id.lower()}"])
        for case_id in ("P04", "P01", "P08")
    }
    observations = _bound_jsonl_artifact(ROOT, artifacts["observations"])
    records = _bound_jsonl_artifact(ROOT, artifacts["collection_record"])
    _bound_jsonl_artifact(ROOT, artifacts["telemetry"])
    predecessor_id = "product-optimization-repair-pair-v6"
    if not (
        predecessor.get("protocol_id") == predecessor_id
        and predecessor.get("protocol_byte_sha256") == BASE_PROTOCOL_SHA256
        and predecessor.get("accounted_research_runs") == 3
        and predecessor.get("disposition") == "immutable-no-retry-no-splice"
        and binding.get("protocol_byte_sha256") == BASE_PROTOCOL_SHA256
        and binding.get("status") == "ready"
        and claim.get("protocol_id") == predecessor_id
        and claim.get("policy") == "single-execution-no-resume-or-retry"
    ):
        raise RepairPairControlError("control predecessor identity is invalid")
    if not (
        result.get("protocol_id") == predecessor_id
        and result.get("started_cells") == 3
        and result.get("planned_cells") == 12
        and result.get("complete") is False
        and result.get("stop_reason") == "TELEMETRY_strict_safe_fetch_failure"
        and result.get("no_retries_or_splices") is True
        and result.get("ledger") == {
            "attempted_cells": 3,
            "known_admitted_min": 3,
            "possibly_submitted_max": 3,
            "submission_count_uncertain": False,
            "uncertain_cells": 0,
        }
    ):
        raise RepairPairControlError("control predecessor result is invalid")
    expected_cases = ("P04", "P01", "P08")
    if not all(
        cell.get("protocol_id") == predecessor_id
        and (cell.get("arm"), cell.get("repetition"), cell.get("case_id"))
        == ("baseline", 2, case_id)
        and cell.get("status") == "attempted-before-post"
        for case_id, cell in cells.items()
    ):
        raise RepairPairControlError("control predecessor cell evidence is invalid")
    if not (
        [row.get("case_id") for row in observations] == list(expected_cases)
        and all(
            row.get("protocol_id") == predecessor_id
            and row.get("status") == "completed"
            and row.get("error_code") is None
            for row in observations
        )
        and [row.get("case_id") for row in records] == list(expected_cases)
        and all(
            row.get("experiment_id") == predecessor_id
            and row.get("status") == "completed"
            and row.get("error_code") is None
            and row.get("observability_final") is True
            for row in records
        )
    ):
        raise RepairPairControlError("control predecessor completed evidence is invalid")


def _load_raw_protocol() -> dict[str, Any]:
    try:
        payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("approved protocol could not be loaded") from None
    if not isinstance(payload, dict):
        raise RepairPairControlError("approved protocol is invalid")
    return payload


def _load_approved_protocol(expected_protocol_byte_sha256: str) -> Any:
    package = importlib.import_module("benchmarks")
    module = importlib.import_module(
        "benchmarks.product_optimization_serial_check_v1"
    )
    expected_origins = {
        package: ROOT / "benchmarks/__init__.py",
        module: ROOT / "benchmarks/product_optimization_serial_check_v1.py",
    }
    if any(
        Path(item.__file__).resolve() != path.resolve()
        for item, path in expected_origins.items()
    ):
        raise RepairPairControlError("approved controller import origin drift")
    frozen = module.load_serial_check_protocol()
    if frozen.byte_sha256 != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol loader mismatch")
    return frozen


def _bootstrap_approved_protocol(
    expected_protocol_byte_sha256: str,
) -> dict[str, Any]:
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
            relative.is_absolute()
            or ".." in relative.parts
            or not target.is_relative_to(ROOT.resolve())
            or _v4._file_hash(target) != item["sha256"]
        ):
            raise RepairPairControlError("approved controller TCB drift")
    _v4._reject_import_shadows(ROOT, [item["path"] for item in required])
    _v6._bootstrap_approved_protocol(BASE_PROTOCOL_SHA256)
    protocol = _load_approved_protocol(expected_protocol_byte_sha256).payload
    _validate_control_predecessor(protocol)
    return protocol


def _require_active_protocol(protocol: dict[str, Any]) -> None:
    authorization = protocol.get("authorization")
    controller = protocol.get("controller")
    ledger = protocol.get("budgets", {}).get("research_ledger")
    if not (
        protocol.get("status") == "frozen"
        and protocol.get("freeze_date") == "2026-09-27"
        and isinstance(controller, dict)
        and controller.get("research_admission")
        == "open-after-independent-review-and-offline-acceptance"
        and isinstance(authorization, dict)
        and authorization.get("status") == "approved-existing-cap"
        and authorization.get("current_hard_total") == 156
        and authorization.get("effective_hard_total") == 156
        and authorization.get("diagnostic_max") == 3
        and authorization.get("concurrency_runs_authorized") == 0
        and authorization.get("deferred_unallocated") == 53
        and isinstance(ledger, dict)
        and ledger.get("starting_used") == 100
        and ledger.get("diagnostic_max") == 3
        and ledger.get("concurrency_reserve") == 0
        and ledger.get("unallocated") == 53
        and ledger.get("hard_total") == 156
    ):
        raise RepairPairControlError("research admission is not open")


def _case_hitl_policy(
    protocol: dict[str, Any], case_id: str
) -> dict[str, Any]:
    policy = protocol.get("design", {}).get("hitl_policy")
    cases = policy.get("cases") if isinstance(policy, dict) else None
    selected = cases.get(case_id) if isinstance(cases, dict) else None
    if not (
        isinstance(policy, dict)
        and policy.get("mode") == "case-specific-p01-p04-stop-p08-auto-v1"
        and set(cases) == {"P01", "P04", "P08"}
        and isinstance(selected, dict)
        and set(selected) == {"stop_at_hitl", "max_auto_resolutions"}
        and type(selected.get("stop_at_hitl")) is bool
        and type(selected.get("max_auto_resolutions")) is int
        and selected["max_auto_resolutions"] >= 0
    ):
        raise RepairPairControlError("case HITL policy drift")
    return selected


def _prepared_environment_paths(
    root: Path, protocol: dict[str, Any]
) -> list[Path]:
    return [
        (
            _v4._block_root(root, block["arm"], block["repetition"])
            / "environment.json"
        ).resolve()
        for block in protocol["design"]["execution_blocks"]
    ]


def _validate_prepared_hitl_policy(
    root: Path, protocol: dict[str, Any]
) -> None:
    expected = protocol["design"]["hitl_policy"]
    for environment_path in _prepared_environment_paths(root, protocol):
        environment = _v4._read_json(environment_path)
        notes = environment.get("notes") if isinstance(environment, dict) else None
        if not (
            isinstance(notes, dict)
            and notes.get("hitl_mode") == expected["mode"]
            and notes.get("hitl_policy") == expected
        ):
            raise RepairPairControlError("prepared HITL policy drift")


def _freeze_prepared_hitl_policy(
    root: Path, protocol: dict[str, Any]
) -> None:
    binding_path = root.resolve() / "execution-binding.json"
    binding = _v4._read_json(binding_path)
    blocks = binding.get("blocks") if isinstance(binding, dict) else None
    expected_blocks = protocol["design"]["execution_blocks"]
    if not isinstance(blocks, list) or len(blocks) != len(expected_blocks):
        raise RepairPairControlError("prepared HITL binding drift")
    binding_by_key = {
        (item.get("arm"), item.get("repetition")): item
        for item in blocks
        if isinstance(item, dict)
    }
    if len(binding_by_key) != len(expected_blocks):
        raise RepairPairControlError("prepared HITL binding drift")
    expected_policy = protocol["design"]["hitl_policy"]
    for block, environment_path in zip(
        expected_blocks, _prepared_environment_paths(root, protocol), strict=True
    ):
        key = (block["arm"], block["repetition"])
        binding_block = binding_by_key.get(key)
        environment = _v4._read_json(environment_path)
        notes = environment.get("notes") if isinstance(environment, dict) else None
        if not (
            isinstance(binding_block, dict)
            and isinstance(notes, dict)
            and notes.get("hitl_mode") == LEGACY_HITL_MODE
            and "hitl_policy" not in notes
        ):
            raise RepairPairControlError("prepared HITL binding drift")
        notes["hitl_mode"] = expected_policy["mode"]
        notes["hitl_policy"] = deepcopy(expected_policy)
        _v4._write_json(environment_path, environment)
        binding_block["environment_sha256"] = _v4._file_hash(environment_path)
    _v4._write_json(binding_path, binding)
    _validate_prepared_hitl_policy(root, protocol)


def _base_validate_with_hitl_policy(
    root: Path,
    preflight_dir: Path,
    baseline_root: Path,
    candidate_root: Path,
    env_file: Path,
    expected_protocol_byte_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    _validate_prepared_hitl_policy(root, protocol)
    environment_paths = set(_prepared_environment_paths(root, protocol))
    original_read_json = _v4._read_json

    def compatible_read_json(path: Path) -> Any:
        payload = original_read_json(path)
        if Path(path).resolve() in environment_paths:
            payload = deepcopy(payload)
            payload["notes"]["hitl_mode"] = LEGACY_HITL_MODE
        return payload

    try:
        _v4._read_json = compatible_read_json
        result = _BASE_VALIDATE_EXECUTION_BINDING(
            root,
            preflight_dir,
            baseline_root,
            candidate_root,
            env_file,
            expected_protocol_byte_sha256,
        )
    finally:
        _v4._read_json = original_read_json
    _validate_prepared_hitl_policy(root, protocol)
    return result


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
                metadata.st_size,
                _v4._file_hash(path),
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
    for relative, (expected_size, expected_hash) in expected.items():
        observed_size, observed_hash = observed[relative]
        if observed_hash != expected_hash and (
            relative not in allowed_drift_paths or observed_size != expected_size
        ):
            raise RepairPairControlError("used knowledge content drift")


def _attempted_blocks(protocol: dict[str, Any]) -> set[tuple[str, int]]:
    cells_dir = LEDGER_ROOT / "cells"
    if not cells_dir.is_dir():
        return set()
    attempted: set[tuple[str, int]] = set()
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
        return _base_validate_with_hitl_policy(*arguments)
    except RepairPairControlError as exc:
        if str(exc) != "prepared block drift":
            raise
    protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    attempted = _attempted_blocks(protocol)
    if not attempted:
        raise RepairPairControlError("prepared block drift")
    binding = _v4._read_json(Path(root).resolve() / "execution-binding.json")
    allowed = set(
        protocol["stopping"].get(
            "allowed_chroma_runtime_drift_paths",
            [
                "chroma/chroma.sqlite3",
                "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/data_level0.bin",
                "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/length.bin",
            ],
        )
    )
    masked: dict[Path, str] = {}
    for block in binding.get("blocks", []):
        key = (block.get("arm"), block.get("repetition"))
        knowledge = (
            _v4._block_root(root, block["arm"], block["repetition"])
            / block["profile"]
            / "knowledge"
        ).resolve()
        if key in attempted:
            _validate_used_knowledge_copy(_v4.SEED_ROOT, knowledge, allowed)
            masked[knowledge] = block["knowledge_sha256"]
        elif _BASE_TREE_HASH(knowledge) != block["knowledge_sha256"]:
            raise RepairPairControlError("unattempted knowledge drift")

    def masked_tree_hash(path: Path) -> str:
        resolved = path.resolve()
        return masked.get(resolved, _BASE_TREE_HASH(path))

    previous = _v4._tree_hash
    try:
        _v4._tree_hash = masked_tree_hash
        return _base_validate_with_hitl_policy(*arguments)
    finally:
        _v4._tree_hash = previous


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


def _install_call_environment(
    args: tuple[Any, ...], kwargs: dict[str, Any], index: int
) -> None:
    try:
        env_file = args[index] if len(args) > index else kwargs["env_file"]
    except (IndexError, KeyError):
        raise RepairPairControlError("private environment path is required") from None
    _v4._install_private_environment(Path(env_file))


def audit(*args, **kwargs) -> dict[str, Any]:
    _install_call_environment(args, kwargs, 2)
    with _configured_base():
        return _v4.audit(*args, **kwargs)


def preflight(*args, **kwargs) -> dict[str, Any]:
    _install_call_environment(args, kwargs, 3)
    with _configured_base():
        return _v4.preflight(*args, **kwargs)


def prepare(
    root: Path,
    preflight_dir: Path,
    baseline_root: Path,
    candidate_root: Path,
    env_file: Path,
    expected_protocol_byte_sha256: str,
) -> dict[str, Any]:
    arguments = (
        root,
        preflight_dir,
        baseline_root,
        candidate_root,
        env_file,
        expected_protocol_byte_sha256,
    )
    _install_call_environment(arguments, {}, 4)
    with _configured_base():
        result = _v4.prepare(*arguments)
        protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
        _freeze_prepared_hitl_policy(root, protocol)
    return {**result, "blocks": 1, "planned_cells": 3}


def _load_cases(protocol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from benchmarks.product_baseline import load_dataset

    dataset, digest = load_dataset(
        ROOT / "benchmarks/product-baseline-v1.json", require_frozen=True
    )
    if digest != protocol["dataset"]["parent_sha256"]:
        raise RepairPairControlError("frozen dataset identity drift")
    selected = {
        item["id"]: item
        for item in dataset["cases"]
        if item["id"] in {"P04", "P01", "P08"}
    }
    if tuple(selected) != ("P01", "P04", "P08"):
        raise RepairPairControlError("diagnostic case projection drift")
    return selected


def _record_stop_reason(
    record: dict[str, Any], collection: Path, case_id: str
) -> str | None:
    resolutions = record.get("hitl_resolutions")
    if type(resolutions) is not int or resolutions < 0:
        return "HITL_RESOLUTION_COUNT_INVALID"
    if case_id in {"P04", "P01"} and resolutions != 0:
        return "UNEXPECTED_HITL_RESOLUTION"
    if case_id == "P08" and resolutions > 2:
        return "UNEXPECTED_HITL_RESOLUTION"
    projected = dict(record)
    projected["hitl_resolutions"] = 0
    return _v4._record_stop_reason(projected, collection)


async def _run_candidate_block(
    *,
    experiment_root: Path,
    block: dict[str, Any],
    candidate_root: Path,
    env_file: Path,
    protocol: dict[str, Any],
    expected_manifests: dict[str, str],
    before_admission: Any,
) -> tuple[list[dict[str, Any]], str | None]:
    from benchmarks.product_baseline import CollectionOptions

    arm, repetition = block["arm"], block["repetition"]
    profile = f"serial-r{repetition}"
    block_root = _v4._block_root(experiment_root, arm, repetition)
    control = block_root / "control"
    collection = experiment_root / "collections" / f"{arm}-r{repetition}"
    port = _v4._free_port()
    instance_nonce = secrets.token_hex(16)
    environment, _ = _v4._private_environment(env_file)
    command = [
        sys.executable,
        str(CHILD),
        "--root",
        str(block_root),
        "--port",
        str(port),
        "--profile",
        profile,
        "--frozen-root",
        str(candidate_root),
        "--control-root",
        str(control),
        "--instance-nonce",
        instance_nonce,
    ]
    stdout_handle = (control / "child.stdout.log").open("wb")
    try:
        stderr_handle = (control / "child.stderr.log").open("wb")
    except Exception:
        stdout_handle.close()
        raise
    try:
        process = subprocess.Popen(
            command,
            cwd=candidate_root,
            env=environment,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    except Exception:
        stdout_handle.close()
        stderr_handle.close()
        raise
    records: list[dict[str, Any]] = []
    stop_reason: str | None = None
    graceful = False
    cases = _load_cases(protocol)
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
        ) as client:
            await _v4._wait_ready(
                client, process, control / "telemetry.jsonl", instance_nonce
            )
            for case_id in block["case_order"]:
                hitl_policy = _case_hitl_policy(protocol, case_id)
                before_admission()
                await _v4._require_safe_health(client)
                telemetry = _v4._strict_telemetry_state(
                    control / "telemetry.jsonl"
                )
                if telemetry["anomaly"]:
                    stop_reason = f"TELEMETRY_{telemetry['reason']}"
                    break
                options = CollectionOptions(
                    profile=profile,
                    repetition=repetition,
                    concurrency=1,
                    poll_interval_seconds=1.0,
                    case_timeout_seconds=900.0,
                    stop_at_hitl=hitl_policy["stop_at_hitl"],
                    expected_manifest_id=expected_manifests[case_id],
                )
                collector = _serial_check_collector(
                    client,
                    collection,
                    experiment_id=protocol["protocol_id"],
                    dataset_hash=protocol["dataset"]["parent_sha256"],
                    options=options,
                    max_hitl_resolutions=hitl_policy["max_auto_resolutions"],
                )
                if (
                    process.poll() is not None
                    or not _v4._telemetry_nonce_ready(
                        control / "telemetry.jsonl", instance_nonce
                    )
                ):
                    raise RepairPairControlError(
                        "owned service unavailable before admission"
                    )
                _v4._reserve_cell(arm, repetition, case_id, protocol["protocol_id"])
                [record] = await collector.collect([cases[case_id]])
                record.update(arm=arm, repetition=repetition, block=block["block"])
                _v4._append_ledger_observation(record, protocol["protocol_id"])
                records.append(record)
                stop_reason = _record_stop_reason(record, collection, case_id)
                if stop_reason is not None:
                    break
                await _v4._require_safe_health(client)
                telemetry = _v4._strict_telemetry_state(
                    control / "telemetry.jsonl"
                )
                if telemetry["anomaly"]:
                    stop_reason = f"TELEMETRY_{telemetry['reason']}"
                    break
    finally:
        try:
            (control / "stop-service.flag").touch(exist_ok=True)
            try:
                process.wait(timeout=45)
                graceful = True
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
        finally:
            stdout_handle.close()
            stderr_handle.close()
    final_telemetry = _v4._strict_telemetry_state(
        control / "telemetry.jsonl",
        require_stopped=graceful,
        require_runner_returned=graceful,
    )
    if stop_reason is None and (
        process.returncode != 0 or final_telemetry["anomaly"]
    ):
        stop_reason = "SERVICE_OR_FINAL_TELEMETRY_ANOMALY"
    return records, stop_reason


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
        for item in records
        if isinstance(item, dict)
    }
    observations_path = LEDGER_ROOT / "observations.jsonl"
    try:
        observations = (
            []
            if not observations_path.is_file()
            else [
                json.loads(line)
                for line in observations_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("protocol observation ledger is invalid") from None
    block_by_key = {
        (cell.get("arm"), cell.get("repetition"), cell.get("case_id")): cell.get(
            "block"
        )
        for cell in cells
        if isinstance(cell, dict)
    }
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("protocol_id") != protocol_id
        ):
            raise RepairPairControlError("protocol observation identity drift")
        key = (
            observation.get("arm"),
            observation.get("repetition"),
            observation.get("case_id"),
        )
        if key not in block_by_key:
            raise RepairPairControlError("protocol observation cell drift")
        if key in known or observation.get("status") not in _v4.SUCCESS:
            continue
        collection = experiment_root / "collections" / f"{key[0]}-r{key[1]}"
        runs_path = collection / "runs.jsonl"
        runs = _bound_jsonl_artifact(
            experiment_root,
            {
                "path": runs_path.relative_to(experiment_root).as_posix(),
                "sha256": _v4._file_hash(runs_path),
            },
        )
        matches = [
            item
            for item in runs
            if item.get("experiment_id") == protocol_id
            and item.get("case_id") == key[2]
            and item.get("task_id") == observation.get("task_id")
            and item.get("run_id") == observation.get("run_id")
        ]
        if len(matches) != 1 or _record_stop_reason(
            matches[0], collection, str(key[2])
        ) is not None:
            raise RepairPairControlError("completed record reconciliation failed")
        record = matches[0]
        record.update(arm=key[0], repetition=key[1], block=block_by_key[key])
        records.append(record)
        known.add(key)
        for cell in cells:
            if (
                cell.get("arm"),
                cell.get("repetition"),
                cell.get("case_id"),
            ) == key:
                cell["status"] = record["status"]
                cell["error_code"] = record.get("error_code")
                break
    reconciled["started_cells"] = len(records)
    reconciled["ledger"] = _v4._ledger_summary()
    reconciled["complete"] = (
        len(records) == 3 and reconciled.get("stop_reason") is None
    )
    if reconciled != result:
        _v4._write_json(experiment_root / RESULT_NAME, reconciled)
    return reconciled


async def run(
    experiment_root: Path,
    preflight_dir: Path,
    baseline_root: Path,
    candidate_root: Path,
    env_file: Path,
    expected_protocol_byte_sha256: str,
) -> dict[str, Any]:
    _install_call_environment(
        (
            experiment_root,
            preflight_dir,
            baseline_root,
            candidate_root,
            env_file,
            expected_protocol_byte_sha256,
        ),
        {},
        4,
    )
    with _configured_base():
        protocol, binding = _validate_execution_binding_allow_used(
            experiment_root,
            preflight_dir,
            baseline_root,
            candidate_root,
            env_file,
            expected_protocol_byte_sha256,
        )
        _require_active_protocol(protocol)
        _v4._claim_protocol_execution(
            experiment_root, binding, protocol["protocol_id"]
        )
        block = protocol["design"]["execution_blocks"][0]
        planned = [
            {
                "block": block["block"],
                "arm": block["arm"],
                "repetition": block["repetition"],
                "case_id": case_id,
                "status": "not_submitted",
            }
            for case_id in block["case_order"]
        ]
        records: list[dict[str, Any]] = []
        stop_reason: str | None = None

        def before_admission() -> None:
            _validate_execution_binding_allow_used(
                experiment_root,
                preflight_dir,
                baseline_root,
                candidate_root,
                env_file,
                expected_protocol_byte_sha256,
            )

        try:
            expected = audit(
                baseline_root,
                candidate_root,
                env_file,
                expected_protocol_byte_sha256,
            )["arm_contracts"]["candidate"]["manifests"]
            records, stop_reason = await _run_candidate_block(
                experiment_root=experiment_root,
                block=block,
                candidate_root=candidate_root,
                env_file=env_file,
                protocol=protocol,
                expected_manifests=expected,
                before_admission=before_admission,
            )
        except Exception as exc:
            stop_reason = f"CONTROL_{type(exc).__name__}"
        for record in records:
            key = (record["arm"], record["repetition"], record["case_id"])
            for cell in planned:
                if (cell["arm"], cell["repetition"], cell["case_id"]) == key:
                    cell["status"] = record.get("status", "unknown")
                    cell["error_code"] = record.get("error_code")
                    break
        result = {
            "schema_version": 1,
            "protocol_id": protocol["protocol_id"],
            "started_cells": len(records),
            "planned_cells": 3,
            "complete": len(records) == 3 and stop_reason is None,
            "stop_reason": stop_reason,
            "cells": planned,
            "records": records,
            "no_retries_or_splices": True,
            "ended_at": _v4._stamp(),
            "ledger": _v4._ledger_summary(),
            "interpretation": protocol["acceptance"]["interpretation_limit"],
        }
        _v4._write_json(experiment_root / RESULT_NAME, result)
        return _reconcile_completed_records(
            experiment_root, result, protocol["protocol_id"]
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
            result = audit(
                args.baseline_root,
                args.candidate_root,
                args.env_file.resolve(),
                args.expected_protocol_byte_sha256,
            )
        elif args.command == "preflight":
            if (
                not args.execute_paid_probes
                or not args.trust_current_local_proxy
                or args.output_dir is None
                or args.env_file is None
            ):
                parser.error(
                    "preflight requires explicit paid probe/proxy consent and paths"
                )
            result = preflight(
                args.output_dir.resolve(),
                args.baseline_root,
                args.candidate_root,
                args.env_file.resolve(),
                args.expected_protocol_byte_sha256,
            )
        elif args.command == "prepare":
            if (
                args.experiment_root is None
                or args.preflight_dir is None
                or args.env_file is None
            ):
                parser.error(
                    "prepare requires experiment, preflight, and environment paths"
                )
            result = prepare(
                args.experiment_root.resolve(),
                args.preflight_dir.resolve(),
                args.baseline_root,
                args.candidate_root,
                args.env_file.resolve(),
                args.expected_protocol_byte_sha256,
            )
        else:
            if (
                not args.execute_paid_runs
                or args.experiment_root is None
                or args.preflight_dir is None
                or args.env_file is None
            ):
                parser.error("run requires explicit paid permission and prepared paths")
            result = asyncio.run(
                run(
                    args.experiment_root.resolve(),
                    args.preflight_dir.resolve(),
                    args.baseline_root,
                    args.candidate_root,
                    args.env_file.resolve(),
                    args.expected_protocol_byte_sha256,
                )
            )
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
            if not ledger["submission_count_uncertain"]
            else None
        )
        print(
            json.dumps(
                {
                    "error_type": type(exc).__name__,
                    "research_runs_submitted": exact_submitted,
                    **ledger,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
