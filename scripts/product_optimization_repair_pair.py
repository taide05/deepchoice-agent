"""Control the frozen P01/P04/P08 12-cell repair-package comparison.

The controller consumes only the development request projection. It never
parses holdout cases, auto-resolves HITL, retries a paid cell, or continues
admission after an identity, source, HTTP, budget, lease, or unknown anomaly.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import shutil
import secrets
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from typing import Any, Callable

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-repair-pair-v2.json"
SEED_ROOT = ROOT / "outputs/product-optimization-seeds/product-optimization-knowledge-seed-v1"
CHILD = ROOT / "scripts/o1_pr2b_child.py"
LEDGER_ROOT = ROOT / "outputs/product-optimization-ledgers/product-optimization-repair-pair-v2"
SUCCESS = frozenset({"completed", "completed_with_warnings"})
_TRANSPORT_ENV = {
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
}
_SYSTEM_ENV = {
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "COMSPEC",
} | _TRANSPORT_ENV
_CONFIG_ENV_EXACT = {
    "LOCAL_PROXY", "FWD_BASE", "FWD_KEY", "FWD_TARGETS",
    "GITHUB_TOKEN", "STACKEXCHANGE_API_KEY", "DEEPCHOICE_SYNTH_THINKING",
    "LLM_DS_CONCURRENCY", "HF_HOME", "HF_HUB_CACHE",
}
_CONFIG_ENV_PREFIXES = (
    "DS_FLASH_", "FLASH_", "DEEPSEEK_", "TAVILY_", "OUTBOUND_",
)
_SECRET_ENV = {
    "DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY",
    "TAVILY_API_KEY", "TAVILY_API_KEYS", "FWD_KEY", "GITHUB_TOKEN",
    "STACKEXCHANGE_API_KEY",
}
ARM_PROBE = r"""
import hashlib, json, os, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'src'))
requests = json.load(sys.stdin)
import deepchoice
origin = Path(deepchoice.__file__).resolve()
if not origin.is_relative_to((root / 'src').resolve()):
    raise RuntimeError('product import escaped frozen root')
from deepchoice.outbound.tunnel import proxy_endpoint_identity
os.environ['SAFE_FETCH_TRUSTED_LOCAL_PROXY'] = proxy_endpoint_identity(
    os.environ.get('LOCAL_PROXY', '')
)
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest
from deepchoice.utils.llm import TIERS
import benchmarks as benchmarks_package
import benchmarks.product_baseline_experiment as baseline_experiment
if Path(benchmarks_package.__file__).resolve() != (root / 'benchmarks/__init__.py').resolve():
    raise RuntimeError('benchmark package import escaped frozen root')
if Path(baseline_experiment.__file__).resolve() != (root / 'benchmarks/product_baseline_experiment.py').resolve():
    raise RuntimeError('benchmark helper import escaped frozen root')
RESOURCE_SETTINGS = baseline_experiment.RESOURCE_SETTINGS
manifests = {}
for case_id, request in requests.items():
    value = ResearchRequest.model_validate(request).model_dump(exclude_none=True)
    manifests[case_id] = build_run_manifest(value).manifest_id
model = TIERS['deepseek-flash']
print(json.dumps({
    'manifests': manifests,
    'core_asset_registry_id': build_core_asset_registry().registry_id,
    'model_id': model['model'],
    'endpoint_sha256': hashlib.sha256(model['base'].encode()).hexdigest(),
    'resource_settings': RESOURCE_SETTINGS,
}, sort_keys=True))
"""


class RepairPairControlError(ValueError):
    """Fail-closed controller error with no secret-bearing detail."""


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise RepairPairControlError("required file unavailable") from None
    return digest.hexdigest()


def _contained_plain_file(root: Path, relative_value: Any) -> Path:
    if not isinstance(relative_value, str):
        raise RepairPairControlError("predecessor artifact path is invalid")
    relative = Path(relative_value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RepairPairControlError("predecessor artifact path is invalid")
    root = root.resolve()
    current = root
    try:
        for part in relative.parts[:-1]:
            current /= part
            metadata = current.lstat()
            if (not stat.S_ISDIR(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or bool(getattr(metadata, "st_file_attributes", 0) & 0x0400)):
                raise RepairPairControlError(
                    "predecessor artifact parent is not a plain directory"
                )
        target = current / relative.parts[-1]
        metadata = target.lstat()
    except OSError:
        raise RepairPairControlError("predecessor artifact unavailable") from None
    if (not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_file_attributes", 0) & 0x0400)
            or metadata.st_size <= 0):
        raise RepairPairControlError("predecessor artifact is not a plain file")
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        raise RepairPairControlError("predecessor artifact escaped repository")
    return resolved


def _bound_json_artifact(root: Path, specification: Any) -> dict[str, Any]:
    if (not isinstance(specification, dict)
            or set(specification) != {"path", "sha256"}
            or not isinstance(specification.get("sha256"), str)
            or len(specification["sha256"]) != 64
            or any(char not in "0123456789abcdef"
                   for char in specification["sha256"])):
        raise RepairPairControlError("predecessor artifact contract is invalid")
    path = _contained_plain_file(root, specification.get("path"))
    try:
        payload_bytes = path.read_bytes()
    except OSError:
        raise RepairPairControlError("predecessor artifact unavailable") from None
    _contained_plain_file(root, specification.get("path"))
    if _sha256_bytes(payload_bytes) != specification["sha256"]:
        raise RepairPairControlError("predecessor artifact identity drift")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("predecessor artifact is invalid") from None
    if not isinstance(payload, dict):
        raise RepairPairControlError("predecessor artifact is invalid")
    return payload


def _validate_predecessor(protocol: dict[str, Any], root: Path = ROOT) -> None:
    predecessor = protocol.get("predecessor")
    if not isinstance(predecessor, dict):
        raise RepairPairControlError("predecessor contract is invalid")
    artifacts = predecessor.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "execution_claim", "attempted_cell", "run_result"
    }:
        raise RepairPairControlError("predecessor artifact contract is invalid")
    claim = _bound_json_artifact(root, artifacts["execution_claim"])
    cell = _bound_json_artifact(root, artifacts["attempted_cell"])
    result = _bound_json_artifact(root, artifacts["run_result"])
    predecessor_id = predecessor.get("protocol_id")
    if not isinstance(predecessor_id, str) or not predecessor_id:
        raise RepairPairControlError("predecessor contract is invalid")
    if not (
        type(claim.get("schema_version")) is int
        and claim["schema_version"] == 1
        and claim.get("protocol_id") == predecessor_id
        and claim.get("protocol_byte_sha256")
        == predecessor.get("protocol_byte_sha256")
        and claim.get("policy") == "single-execution-no-resume-or-retry"
    ):
        raise RepairPairControlError("predecessor execution claim is invalid")
    if not (
        type(cell.get("schema_version")) is int
        and cell["schema_version"] == 1
        and cell.get("protocol_id") == predecessor_id
        and cell.get("arm") == "baseline"
        and type(cell.get("repetition")) is int
        and cell["repetition"] == 2
        and cell.get("case_id") == "P04"
        and cell.get("status") == "attempted-before-post"
    ):
        raise RepairPairControlError("predecessor attempted cell is invalid")
    cells = result.get("cells")
    records = result.get("records")
    ledger = result.get("ledger")
    expected_cells = [
        (block["block"], block["arm"], block["repetition"], case_id)
        for block in protocol["design"]["execution_blocks"]
        for case_id in block["case_order"]
    ]
    if not (
        type(result.get("schema_version")) is int
        and result["schema_version"] == 1
        and result.get("protocol_id") == predecessor_id
        and type(result.get("planned_cells")) is int
        and result["planned_cells"] == 12
        and type(result.get("started_cells")) is int
        and result["started_cells"] == 1
        and result.get("complete") is False
        and result.get("stop_reason") == "CELL_NOT_SUCCESSFUL"
        and result.get("no_retries_or_splices") is True
        and isinstance(cells, list)
        and len(cells) == 12
        and isinstance(records, list)
        and len(records) == 1
        and ledger == {
            "attempted_cells": 1,
            "known_admitted_min": 1,
            "possibly_submitted_max": 1,
            "submission_count_uncertain": False,
            "uncertain_cells": 0,
        }
    ):
        raise RepairPairControlError("predecessor stopped result is invalid")
    observed_cells = [
        (item.get("block"), item.get("arm"), item.get("repetition"),
         item.get("case_id"))
        for item in cells if isinstance(item, dict)
    ]
    queued = [item for item in cells
              if isinstance(item, dict) and item.get("status") == "queued"]
    if (observed_cells != expected_cells
            or len(queued) != 1
            or any(item.get("status") not in {"queued", "not_submitted"}
                   for item in cells)
            or sum(item.get("status") == "not_submitted" for item in cells) != 11
            or (queued[0].get("block"), queued[0].get("arm"),
                queued[0].get("repetition"), queued[0].get("case_id"),
                queued[0].get("error_code"))
            != (1, "baseline", 2, "P04", "FROZEN_MANIFEST_MISMATCH")):
        raise RepairPairControlError("predecessor stopped cell set is invalid")
    record = records[0]
    usage = record.get("usage") if isinstance(record, dict) else None
    observability = record.get("observability") if isinstance(record, dict) else None
    totals = observability.get("totals") if isinstance(observability, dict) else None
    usage_resources = usage.get("budget_resources") if isinstance(usage, dict) else None
    observed_resources = (
        observability.get("budget", {}).get("resources")
        if isinstance(observability, dict) else None
    )
    if not (
        isinstance(record, dict)
        and record.get("experiment_id") == predecessor_id
        and (record.get("block"), record.get("arm"), record.get("repetition"),
             record.get("case_id"), record.get("status"), record.get("error_code"))
        == (1, "baseline", 2, "P04", "queued", "FROZEN_MANIFEST_MISMATCH")
        and isinstance(usage, dict)
        and isinstance(totals, dict)
        and all(usage.get(name) == 0
                for name in ("external_calls", "llm_calls", "retrieval_calls"))
        and all(totals.get(name) == 0
                for name in ("external_calls", "llm_calls", "retrieval_calls"))
        and isinstance(usage_resources, dict)
        and isinstance(observed_resources, dict)
        and all(
            isinstance(resources.get(name), dict)
            and all(resources[name].get(field) == 0
                    for field in ("reserved", "settled", "unknown_spend"))
            for resources in (usage_resources, observed_resources)
            for name in ("active_milliseconds", "llm_calls",
                         "retrieval_calls", "total_tokens")
        )
        and predecessor.get("accounted_research_runs") == 1
        and predecessor.get("external_calls") == 0
        and predecessor.get("disposition") == "immutable-no-retry-no-splice"
    ):
        raise RepairPairControlError("predecessor stopped record is invalid")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    try:
        for path in root.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or bool(
                getattr(metadata, "st_file_attributes", 0) & 0x0400
            ):
                raise RepairPairControlError("artifact contains link or reparse point")
            if path.is_file():
                files.append(path)
    except OSError:
        raise RepairPairControlError("artifact tree unavailable") from None
    if not files:
        raise RepairPairControlError("artifact tree is empty")
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_hash(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_independent_trees(source: Path, copies: list[Path], expected: str) -> None:
    source_before = _tree_hash(source)
    if source_before != expected or any(_tree_hash(copy) != expected for copy in copies):
        raise RepairPairControlError("knowledge tree identity drift")
    relative_files = sorted(
        path.relative_to(source) for path in source.rglob("*") if path.is_file()
    )
    for relative in relative_files:
        instances = [source / relative, *(copy / relative for copy in copies)]
        for index, left in enumerate(instances):
            if left.stat().st_nlink != 1:
                raise RepairPairControlError("knowledge file is hard-linked")
            for right in instances[index + 1:]:
                if os.path.samefile(left, right):
                    raise RepairPairControlError("knowledge files are not physically distinct")
    if _tree_hash(source) != source_before:
        raise RepairPairControlError("knowledge source changed during copying")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairControlError("required JSON evidence unavailable") from None


def _is_config_key(name: str) -> bool:
    return name in _CONFIG_ENV_EXACT or name.startswith(_CONFIG_ENV_PREFIXES)


def _private_environment(env_file: Path) -> tuple[dict[str, str], str]:
    try:
        metadata = env_file.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
                or bool(getattr(metadata, "st_file_attributes", 0) & 0x0400)):
            raise OSError
        parsed = dotenv_values(env_file)
    except (OSError, UnicodeError, ValueError):
        raise RepairPairControlError("private environment unavailable") from None
    effective = {
        key: value for key, value in os.environ.items()
        if key in _SYSTEM_ENV or _is_config_key(key)
    }
    for key, value in parsed.items():
        if value is not None and _is_config_key(key):
            effective[key] = value
    effective.pop("PYTHONPATH", None)
    effective.pop("PYTHONHOME", None)
    effective["PYTHON_DOTENV_DISABLED"] = "1"
    if effective.get("SSL_CERT_DIR"):
        raise RepairPairControlError("SSL certificate directories are unsupported")
    identity: dict[str, Any] = {"schema_version": 1, "values": {}}
    for key in sorted(effective):
        value = effective[key]
        identity["values"][key] = {
            "present": bool(value),
            "length": len(value),
            "sha256": _sha256_bytes(value.encode("utf-8")),
            "secret": key in _SECRET_ENV,
        }
        if key in {"SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"} and value:
            certificate_file = Path(value)
            try:
                metadata = certificate_file.lstat()
            except OSError:
                raise RepairPairControlError("certificate bundle is unavailable") from None
            if (not certificate_file.is_absolute()
                    or not stat.S_ISREG(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or bool(getattr(metadata, "st_file_attributes", 0) & 0x0400)):
                raise RepairPairControlError("certificate bundle is not a plain file")
            identity["values"][key]["content_sha256"] = _file_hash(certificate_file)
    identity["python_executable_sha256"] = _file_hash(Path(sys.executable))
    return effective, _sha256_bytes(_signature(identity).encode("utf-8"))


def _reject_import_shadows(root: Path, relative_paths: list[str]) -> None:
    for raw in relative_paths:
        relative = Path(raw)
        expected = root / relative
        candidates: list[Path] = []
        if relative.suffix == ".py" and relative.name != "__init__.py":
            candidates.append(expected.with_suffix(""))
            candidates.extend(
                expected.parent / f"{expected.stem}{suffix}"
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
            )
        elif relative.name == "__init__.py":
            package = expected.parent
            candidates.append(package.parent / f"{package.name}.py")
            candidates.extend(
                package.parent / f"{package.name}{suffix}"
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
            )
            candidates.extend(
                package / f"__init__{suffix}"
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
            )
        elif relative.suffix == "":
            candidates.append(expected.with_suffix(".py"))
            candidates.extend(
                expected.parent / f"{expected.name}{suffix}"
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
            )
            candidates.extend(
                expected / f"__init__{suffix}"
                for suffix in importlib.machinery.EXTENSION_SUFFIXES
            )
        for candidate in candidates:
            if candidate.exists() or candidate.is_symlink():
                raise RepairPairControlError("project import shadow detected")


def _bootstrap_approved_protocol(expected_protocol_byte_sha256: str) -> dict[str, Any]:
    """Verify the external protocol root without importing project modules."""
    if (len(expected_protocol_byte_sha256) != 64
            or any(char not in "0123456789abcdef"
                   for char in expected_protocol_byte_sha256)):
        raise RepairPairControlError("approved protocol SHA is invalid")
    if _file_hash(PROTOCOL_PATH) != expected_protocol_byte_sha256:
        raise RepairPairControlError("approved protocol identity mismatch")
    protocol = _read_json(PROTOCOL_PATH)
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
        if (relative.is_absolute() or ".." in relative.parts
                or len(item["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in item["sha256"])):
            raise RepairPairControlError("approved controller TCB is invalid")
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT.resolve()) or _file_hash(target) != item["sha256"]:
            raise RepairPairControlError("approved controller TCB drift")
    _reject_import_shadows(ROOT, [item["path"] for item in required])
    _validate_predecessor(protocol)
    return protocol


def _load_approved_protocol(expected_protocol_byte_sha256: str) -> Any:
    protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    package = importlib.import_module("benchmarks")
    module = importlib.import_module("benchmarks.product_optimization_repair_pair")
    dev_requests = importlib.import_module("benchmarks.product_optimization_dev_requests")
    expected_origins = {
        package: ROOT / "benchmarks/__init__.py",
        module: ROOT / "benchmarks/product_optimization_repair_pair.py",
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


def _install_private_environment(env_file: Path) -> tuple[dict[str, str], str]:
    effective, identity = _private_environment(env_file)
    for key in list(os.environ):
        if (_is_config_key(key) or key in _TRANSPORT_ENV
                or key in {"PYTHONPATH", "PYTHONHOME"}):
            os.environ.pop(key, None)
    os.environ.update(effective)
    return effective, identity


def _dependency_snapshot_sha256() -> str:
    from benchmarks import product_baseline_qualification as qualification

    data = (json.dumps(qualification.dependency_records(), ensure_ascii=False, indent=2)
            + "\n").encode("utf-8")
    return _sha256_bytes(data)


def _ledger_write_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise RepairPairControlError("protocol or cell was already attempted") from None


def _claim_protocol_execution(
    experiment_root: Path, binding: dict[str, Any], protocol_id: str
) -> None:
    _ledger_write_once(
        LEDGER_ROOT / "execution-claim.json",
        {
            "schema_version": 1,
            "protocol_id": protocol_id,
            "claimed_at": _stamp(),
            "execution_binding_sha256": _file_hash(
                experiment_root / "execution-binding.json"
            ),
            "protocol_byte_sha256": binding["protocol_byte_sha256"],
            "policy": "single-execution-no-resume-or-retry",
        },
    )


def _reserve_cell(
    arm: str, repetition: int, case_id: str, protocol_id: str
) -> None:
    _ledger_write_once(
        LEDGER_ROOT / "cells" / f"{arm}-r{repetition}-{case_id}.json",
        {
            "schema_version": 1,
            "protocol_id": protocol_id,
            "arm": arm,
            "repetition": repetition,
            "case_id": case_id,
            "attempted_at": _stamp(),
            "status": "attempted-before-post",
        },
    )


def _append_ledger_observation(
    record: dict[str, Any], protocol_id: str
) -> None:
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    entry = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "observed_at": _stamp(),
        "arm": record.get("arm"),
        "repetition": record.get("repetition"),
        "case_id": record.get("case_id"),
        "task_id": record.get("task_id"),
        "run_id": record.get("run_id"),
        "status": record.get("status"),
        "error_code": record.get("error_code"),
    }
    with (LEDGER_ROOT / "observations.jsonl").open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _ledger_summary() -> dict[str, Any]:
    attempted = len(list((LEDGER_ROOT / "cells").glob("*.json")))
    known_admitted_cells: set[tuple[Any, Any, Any]] = set()
    path = LEDGER_ROOT / "observations.jsonl"
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                if isinstance(entry.get("task_id"), str) and entry["task_id"]:
                    known_admitted_cells.add(
                        (entry.get("arm"), entry.get("repetition"), entry.get("case_id"))
                    )
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RepairPairControlError("protocol ledger is unreadable") from None
    known_min = len(known_admitted_cells)
    possible_max = max(attempted, known_min)
    return {
        "attempted_cells": attempted,
        "known_admitted_min": known_min,
        "possibly_submitted_max": possible_max,
        "uncertain_cells": possible_max - known_min,
        "submission_count_uncertain": possible_max != known_min,
    }


def _run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True,
            text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        raise RepairPairControlError("Git identity unavailable") from None
    return result.stdout.strip()


def _validate_plain_directory(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except OSError:
        raise RepairPairControlError("required directory unavailable") from None
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x0400
    ):
        raise RepairPairControlError("directory is not a plain directory")
    resolved = path.resolve()
    try:
        resolved_metadata = resolved.lstat()
    except OSError:
        raise RepairPairControlError("required directory unavailable") from None
    if (not stat.S_ISDIR(resolved_metadata.st_mode)
            or stat.S_ISLNK(resolved_metadata.st_mode)
            or bool(getattr(resolved_metadata, "st_file_attributes", 0) & 0x0400)):
        raise RepairPairControlError("directory is not a plain directory")
    return resolved


def _validate_product_root(root: Path, arm: str, protocol: dict[str, Any]) -> dict[str, Any]:
    root = _validate_plain_directory(root)
    identity = protocol["identities"][arm]
    head = _run_git(root, "rev-parse", "HEAD")
    if arm == "baseline":
        if head != identity["anchor_commit"]:
            raise RepairPairControlError("baseline checkout drift")
    else:
        try:
            subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", identity["anchor_commit"], head],
                check=True, capture_output=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            raise RepairPairControlError("candidate does not descend from frozen product") from None
    approved_paths = [
        item["path"] for item in identity["source_objects"] + identity["runtime_objects"]
    ]
    if arm == "candidate":
        approved_paths.extend(
            item["path"] for item in protocol["controller"]["required_files"]
        )
    approved_paths = list(dict.fromkeys(approved_paths))
    _reject_import_shadows(
        root,
        [item["path"] for item in identity["source_objects"] + identity["runtime_objects"]],
    )
    try:
        clean = subprocess.run(
            ["git", "-C", str(root), "diff-index", "--quiet", "HEAD", "--",
             *approved_paths],
            check=False, capture_output=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        raise RepairPairControlError("approved-path Git identity unavailable") from None
    if clean.returncode != 0:
        raise RepairPairControlError("approved product paths have tracked changes")
    if _run_git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *approved_paths,
    ):
        raise RepairPairControlError("product import roots contain untracked files")
    for item in identity["source_objects"] + identity["runtime_objects"]:
        if _run_git(root, "rev-parse", f"HEAD:{item['path']}") != item["git_object"]:
            raise RepairPairControlError("product or runtime source identity drift")
    return {"head": head, "anchor_commit": identity["anchor_commit"],
            "source_objects": identity["source_objects"],
            "runtime_objects": identity["runtime_objects"]}


def _seed_evidence(protocol: dict[str, Any], seed: Path = SEED_ROOT) -> dict[str, Any]:
    seed = _validate_plain_directory(seed)
    if list(seed.rglob("*-wal")) or list(seed.rglob("*-shm")):
        raise RepairPairControlError("seed has mutable SQLite sidecars")
    expected = protocol["knowledge_seed"]
    if _tree_hash(seed) != expected["artifact_tree_sha256"]:
        raise RepairPairControlError("seed artifact identity drift")
    record = _read_json(seed / "build-record.json")
    required = {
        "seed_id": expected["seed_id"],
        "seed_identity_sha256": expected["logical_identity_sha256"],
        "manifest_sha256": expected["manifest_sha256"],
        "admission_identity_sha256": expected["admission_identity_sha256"],
        "embedding_sha256": expected["embedding_sha256"],
        "status": "frozen",
    }
    if any(record.get(key) != value for key, value in required.items()):
        raise RepairPairControlError("seed build record drift")
    database = seed / "chroma/chroma.sqlite3"
    try:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RepairPairControlError("seed SQLite integrity failed")
    except sqlite3.Error:
        raise RepairPairControlError("seed SQLite unavailable") from None
    return {"seed_id": expected["seed_id"],
            "artifact_tree_sha256": expected["artifact_tree_sha256"],
            "logical_identity_sha256": expected["logical_identity_sha256"],
            "sqlite_quick_check": "ok"}


def _request_payloads() -> dict[str, dict[str, Any]]:
    from benchmarks.product_optimization_dev_requests import load_dev_requests

    fixture = load_dev_requests()
    return {item.case_id: item.request.model_dump(mode="json", exclude_none=False)
            for item in fixture.cases}


def _probe_arm(root: Path, requests: dict[str, dict[str, Any]],
               environment: dict[str, str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, "-c", ARM_PROBE, str(root)], input=json.dumps(requests),
            text=True, capture_output=True, check=True, timeout=60, cwd=root,
            env=environment,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise RepairPairControlError("arm contract probe failed") from None
    if (set(payload.get("manifests", {})) != set(requests)
            or not isinstance(payload.get("core_asset_registry_id"), str)
            or not isinstance(payload.get("resource_settings"), dict)):
        raise RepairPairControlError("arm contract probe invalid")
    return payload


def _validate_approved_runtime_identity(
    protocol: dict[str, Any], probes: dict[str, dict[str, Any]],
    configuration_sha256: str, safe_fetch_proxy_sha256: str | None,
) -> None:
    environment = protocol["environment"]
    if any(
        probe["model_id"] != environment["model"]
        or probe["endpoint_sha256"] != environment["endpoint_sha256"]
        for probe in probes.values()
    ):
        raise RepairPairControlError("arm model or endpoint drift")
    if (configuration_sha256 != environment["configuration_sha256"]
            or safe_fetch_proxy_sha256 != environment["safe_fetch_proxy_sha256"]):
        raise RepairPairControlError("approved routing or proxy drift")


def audit(baseline_root: Path, candidate_root: Path,
          env_file: Path, expected_protocol_byte_sha256: str) -> dict[str, Any]:
    protocol = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    baseline_root, candidate_root = baseline_root.resolve(), candidate_root.resolve()
    if baseline_root == candidate_root or candidate_root != ROOT.resolve():
        raise RepairPairControlError("arms must use distinct checkouts")
    roots = {"baseline": _validate_product_root(baseline_root, "baseline", protocol),
             "candidate": _validate_product_root(candidate_root, "candidate", protocol)}
    effective, environment_identity = _install_private_environment(env_file)
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    from benchmarks import product_baseline_qualification as qualification

    cfg = qualification.trusted_configuration()
    requests = _request_payloads()
    probes = {"baseline": _probe_arm(baseline_root, requests, effective),
              "candidate": _probe_arm(candidate_root, requests, effective)}
    configuration_sha = qualification.configuration_sha256(cfg)
    _validate_approved_runtime_identity(
        protocol, probes, configuration_sha, cfg.safe_fetch_proxy_sha256
    )
    return {"schema_version": 1, "status": "passed", "audited_at": _stamp(),
            "protocol_id": protocol["protocol_id"],
            "protocol_byte_sha256": frozen.byte_sha256,
            "development_projection_sha256": protocol["dataset"]["development_projection_sha256"],
            "roots": roots, "arm_contracts": probes, "seed": _seed_evidence(protocol),
            "effective_environment_identity_sha256": environment_identity,
            "dependency_snapshot_sha256": _dependency_snapshot_sha256(),
            "configuration_sha256": configuration_sha,
            "safe_fetch_proxy_sha256": cfg.safe_fetch_proxy_sha256,
            "endpoint_sha256": protocol["environment"]["endpoint_sha256"],
            "research_runs_submitted": 0}


def preflight(output_dir: Path, baseline_root: Path, candidate_root: Path,
              env_file: Path, expected_protocol_byte_sha256: str) -> dict[str, Any]:
    if output_dir.exists() or not env_file.is_file():
        raise RepairPairControlError("preflight requires fresh output and private environment")
    audit_result = audit(
        baseline_root, candidate_root, env_file, expected_protocol_byte_sha256
    )
    from benchmarks import product_baseline_qualification as qualification

    cfg = qualification.trusted_configuration()
    anchor = audit_result["roots"]["candidate"]["anchor_commit"]
    result = asyncio.run(qualification.preflight(output_dir, cfg, commit=anchor))
    binding = {
        "schema_version": 1,
        "protocol_byte_sha256": audit_result["protocol_byte_sha256"],
        "audit_sha256": _sha256_bytes(_signature(audit_result).encode("utf-8")),
        "audit": audit_result,
        "effective_environment_identity_sha256":
            audit_result["effective_environment_identity_sha256"],
        "preflight_summary_sha256": _file_hash(output_dir / "preflight-summary.json"),
        "llm_preflight_sha256": _file_hash(output_dir / "llm-preflight.json"),
        "dependencies_sha256": _file_hash(output_dir / "dependencies.json"),
        "research_runs_submitted": 0,
    }
    _write_json(output_dir / "repair-pair-preflight-binding.json", binding)
    return result


def _validate_preflight(preflight_dir: Path, audit_result: dict[str, Any],
                        env_file: Path) -> tuple[dict[str, Any], Any]:
    if not env_file.is_file():
        raise RepairPairControlError("private environment unavailable")
    _, environment_identity = _install_private_environment(env_file)
    from benchmarks import product_baseline_qualification as qualification

    summary = _read_json(preflight_dir / "preflight-summary.json")
    llm = _read_json(preflight_dir / "llm-preflight.json")
    binding = _read_json(preflight_dir / "repair-pair-preflight-binding.json")
    cfg = qualification.trusted_configuration()
    bound_audit = binding.get("audit")
    comparable = (
        "roots", "arm_contracts", "seed", "protocol_byte_sha256",
        "effective_environment_identity_sha256", "dependency_snapshot_sha256",
        "configuration_sha256", "safe_fetch_proxy_sha256", "endpoint_sha256",
    )
    dependency_hash = _dependency_snapshot_sha256()
    expected_binding_keys = {
        "schema_version", "protocol_byte_sha256", "audit_sha256", "audit",
        "effective_environment_identity_sha256", "preflight_summary_sha256",
        "llm_preflight_sha256", "dependencies_sha256", "research_runs_submitted",
    }
    if (not isinstance(binding, dict) or set(binding) != expected_binding_keys
            or binding.get("schema_version") != 1
            or binding.get("research_runs_submitted") != 0
            or summary.get("passed") is not True
            or summary.get("research_runs_submitted") != 0
            or summary.get("git_commit") != audit_result["roots"]["candidate"]["anchor_commit"]
            or summary.get("proxy_sha256") != cfg.safe_fetch_proxy_sha256
            or summary.get("endpoint_sha256") != audit_result["endpoint_sha256"]
            or llm.get("passed") is not True
            or summary.get("dependency_snapshot_sha256") != dependency_hash
            or summary.get("configuration_sha256")
            != qualification.configuration_sha256(cfg)
            or binding.get("protocol_byte_sha256") != audit_result["protocol_byte_sha256"]
            or binding.get("effective_environment_identity_sha256")
            != environment_identity
            or binding.get("preflight_summary_sha256") != _file_hash(
                preflight_dir / "preflight-summary.json")
            or binding.get("llm_preflight_sha256") != _file_hash(
                preflight_dir / "llm-preflight.json")
            or binding.get("dependencies_sha256") != dependency_hash
            or binding.get("dependencies_sha256") != _file_hash(
                preflight_dir / "dependencies.json")
            or not isinstance(bound_audit, dict)
            or any(bound_audit.get(key) != audit_result.get(key) for key in comparable)
            or binding.get("audit_sha256")
            != _sha256_bytes(_signature(bound_audit).encode("utf-8"))):
        raise RepairPairControlError("same-window prerequisite evidence invalid")
    _validate_preflight_window(preflight_dir, 7)
    return summary, cfg


def _validate_preflight_window(preflight_dir: Path, days: int) -> None:
    summary = _read_json(preflight_dir / "preflight-summary.json")
    try:
        started = datetime.fromisoformat(summary["started_at"])
        ended = datetime.fromisoformat(summary["ended_at"])
        now = datetime.now(timezone.utc)
        if (started.tzinfo is None or ended.tzinfo is None or ended < started
                or ended > now or (now - ended).total_seconds() > days * 86400):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise RepairPairControlError("preflight evidence is outside the frozen window") from None


def _block_root(root: Path, arm: str, repetition: int) -> Path:
    return root / "arms" / arm / f"r{repetition}"


def prepare(root: Path, preflight_dir: Path, baseline_root: Path,
            candidate_root: Path, env_file: Path,
            expected_protocol_byte_sha256: str) -> dict[str, Any]:
    if root.exists():
        raise RepairPairControlError("experiment root must be fresh")
    audit_result = audit(
        baseline_root, candidate_root, env_file, expected_protocol_byte_sha256
    )
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    protocol = frozen.payload
    summary, cfg = _validate_preflight(preflight_dir, audit_result, env_file)
    from benchmarks.product_baseline_experiment import embedding_revision
    from benchmarks import product_baseline_qualification as qualification
    from deepchoice.utils.llm import TIERS

    if embedding_revision() != protocol["environment"]["embedding_revision"]:
        raise RepairPairControlError("embedding cache revision drift")
    dependencies = qualification.dependency_records()
    dependency_bytes = (json.dumps(dependencies, ensure_ascii=False, indent=2)
                        + "\n").encode("utf-8")
    dependency_hash = _sha256_bytes(dependency_bytes)
    if (summary.get("dependency_snapshot_sha256") != dependency_hash
            or _file_hash(preflight_dir / "dependencies.json") != dependency_hash
            or summary.get("configuration_sha256")
            != qualification.configuration_sha256(cfg)):
        raise RepairPairControlError("preflight dependency or configuration drift")
    root.mkdir(parents=True)
    (root / "dependencies.json").write_bytes(dependency_bytes)
    model = TIERS["deepseek-flash"]
    copied: list[Path] = []
    block_records: list[dict[str, Any]] = []
    for block in protocol["design"]["execution_blocks"]:
        arm, repetition = block["arm"], block["repetition"]
        block_root = _block_root(root, arm, repetition)
        profile = f"serial-r{repetition}"
        knowledge = block_root / profile / "knowledge"
        shutil.copytree(SEED_ROOT, knowledge)
        if _tree_hash(knowledge) != protocol["knowledge_seed"]["artifact_tree_sha256"]:
            raise RepairPairControlError("knowledge copy identity drift")
        (block_root / profile / "runtime").mkdir(parents=True)
        (block_root / "control").mkdir()
        (root / "collections" / f"{arm}-r{repetition}").mkdir(parents=True)
        copied.append(knowledge)
        probe = audit_result["arm_contracts"][arm]
        settings = {**probe["resource_settings"],
                    "LLM_DS_CONCURRENCY": os.getenv("LLM_DS_CONCURRENCY", "80"),
                    "DEEPCHOICE_SYNTH_THINKING": "0"}
        environment = {
            "schema_version": 1, "status": "ready",
            "model": {"provider": "deepseek-flash", "model_id": model["model"],
                      "thinking": "disabled"},
            "dependency_snapshot_sha256": dependency_hash,
            "knowledge_snapshot_sha256": protocol["knowledge_seed"]["artifact_tree_sha256"],
            "retrieval_health": "passed", "llm_compatibility": "passed",
            "notes": {
                "settings": settings,
                "git_commit": audit_result["roots"][arm]["anchor_commit"],
                "dataset_hash": protocol["dataset"]["parent_sha256"],
                "llm_evidence_sha256": _file_hash(preflight_dir / "llm-preflight.json"),
                "retrieval_evidence_sha256": _file_hash(preflight_dir / "preflight-summary.json"),
                "endpoint_sha256": probe["endpoint_sha256"],
                "safe_fetch_proxy_sha256": cfg.safe_fetch_proxy_sha256,
                "configuration_sha256": qualification.configuration_sha256(cfg),
                "embedding_model": protocol["environment"]["embedding_model"],
                "embedding_revision": protocol["environment"]["embedding_revision"],
                "embedding_startup_mode": "cold-in-research",
                "snapshot_copy_mode": "byte-exact-independent-per-arm-repetition-v1",
                "expected_manifest_by_case": probe["manifests"],
                "core_asset_registry_id": probe["core_asset_registry_id"],
                "price_availability": "unavailable", "auto_recovery": False,
                "hitl_mode": "stop-at-hitl-no-auto-resolution",
                "task_admission_limit": 3,
                "protocol_byte_sha256": frozen.byte_sha256,
                "protocol_id": protocol["protocol_id"],
            },
        }
        _write_json(block_root / "environment.json", environment)
        block_records.append({"block": block["block"], "arm": arm,
                              "repetition": repetition, "profile": profile,
                              "environment_sha256": _file_hash(block_root / "environment.json"),
                              "knowledge_sha256": _tree_hash(knowledge)})
    _validate_independent_trees(
        SEED_ROOT, copied, protocol["knowledge_seed"]["artifact_tree_sha256"]
    )
    binding = {
        "schema_version": 1, "status": "ready", "created_at": _stamp(),
        "protocol_byte_sha256": frozen.byte_sha256,
        "protocol_canonical_sha256": frozen.canonical_sha256,
        "audit": audit_result,
        "preflight_summary_sha256": _file_hash(preflight_dir / "preflight-summary.json"),
        "preflight_binding_sha256": _file_hash(
            preflight_dir / "repair-pair-preflight-binding.json"),
        "controller_sha256": _file_hash(Path(__file__).resolve()),
        "child_sha256": _file_hash(CHILD), "blocks": block_records,
        "effective_environment_identity_sha256":
            audit_result["effective_environment_identity_sha256"],
        "dependency_snapshot_sha256": dependency_hash,
        "research_runs_submitted": 0,
    }
    _write_json(root / "execution-binding.json", binding)
    return {"prepared": True, "blocks": 4, "planned_cells": 12,
            "protocol_byte_sha256": frozen.byte_sha256,
            "research_runs_submitted": 0}


def _validate_execution_binding(root: Path, preflight_dir: Path,
                                baseline_root: Path,
                                candidate_root: Path,
                                env_file: Path,
                                expected_protocol_byte_sha256: str,
                                ) -> tuple[dict[str, Any], dict[str, Any]]:
    bootstrap = _bootstrap_approved_protocol(expected_protocol_byte_sha256)
    _validate_preflight_window(
        preflight_dir, bootstrap["design"]["same_window_days"]
    )
    binding = _read_json(root / "execution-binding.json")
    current_audit = audit(
        baseline_root, candidate_root, env_file, expected_protocol_byte_sha256
    )
    frozen = _load_approved_protocol(expected_protocol_byte_sha256)
    _validate_preflight(preflight_dir, current_audit, env_file)
    expected_binding_keys = {
        "schema_version", "status", "created_at", "protocol_byte_sha256",
        "protocol_canonical_sha256", "audit", "preflight_summary_sha256",
        "preflight_binding_sha256", "controller_sha256", "child_sha256",
        "blocks", "research_runs_submitted",
        "effective_environment_identity_sha256", "dependency_snapshot_sha256",
    }
    if (not isinstance(binding, dict) or set(binding) != expected_binding_keys
            or binding.get("schema_version") != 1
            or binding.get("status") != "ready"
            or binding.get("protocol_byte_sha256") != frozen.byte_sha256
            or binding.get("protocol_canonical_sha256") != frozen.canonical_sha256
            or binding.get("research_runs_submitted") != 0
            or binding.get("effective_environment_identity_sha256")
            != current_audit.get("effective_environment_identity_sha256")
            or binding.get("dependency_snapshot_sha256")
            != current_audit.get("dependency_snapshot_sha256")
            or binding.get("controller_sha256") != _file_hash(Path(__file__).resolve())
            or binding.get("child_sha256") != _file_hash(CHILD)
            or binding.get("preflight_summary_sha256")
            != _file_hash(preflight_dir / "preflight-summary.json")
            or binding.get("preflight_binding_sha256")
            != _file_hash(preflight_dir / "repair-pair-preflight-binding.json")
            or binding.get("audit", {}).get("roots") != current_audit.get("roots")
            or binding.get("audit", {}).get("arm_contracts")
            != current_audit.get("arm_contracts")
            or binding.get("audit", {}).get("seed") != current_audit.get("seed")):
        raise RepairPairControlError("execution binding drift")
    blocks = binding.get("blocks")
    expected_blocks = [
        (item["block"], item["arm"], item["repetition"], f"serial-r{item['repetition']}")
        for item in frozen.payload["design"]["execution_blocks"]
    ]
    if (not isinstance(blocks, list) or len(blocks) != len(expected_blocks)
            or any(not isinstance(item, dict) or set(item) != {
                "block", "arm", "repetition", "profile", "environment_sha256",
                "knowledge_sha256",
            } for item in blocks)
            or [(item.get("block"), item.get("arm"), item.get("repetition"),
                 item.get("profile")) for item in blocks] != expected_blocks
            or any(item.get("knowledge_sha256")
                   != frozen.payload["knowledge_seed"]["artifact_tree_sha256"]
                   for item in blocks)):
        raise RepairPairControlError("execution block binding drift")
    knowledge_copies: list[Path] = []
    for block in blocks:
        knowledge = (_block_root(root, block["arm"], block["repetition"])
                     / block["profile"] / "knowledge")
        knowledge = _validate_plain_directory(knowledge)
        knowledge_copies.append(knowledge)
        environment = (_block_root(root, block["arm"], block["repetition"])
                       / "environment.json")
        if (_tree_hash(knowledge) != block["knowledge_sha256"]
                or _file_hash(environment) != block["environment_sha256"]):
            raise RepairPairControlError("prepared block drift")
        environment_payload = _read_json(environment)
        arm_contract = current_audit["arm_contracts"][block["arm"]]
        notes = environment_payload.get("notes")
        expected_settings = {
            **arm_contract["resource_settings"],
            "LLM_DS_CONCURRENCY": os.getenv("LLM_DS_CONCURRENCY", "80"),
            "DEEPCHOICE_SYNTH_THINKING": "0",
        }
        if (not isinstance(notes, dict)
                or environment_payload.get("knowledge_snapshot_sha256")
                != frozen.payload["knowledge_seed"]["artifact_tree_sha256"]
                or environment_payload.get("dependency_snapshot_sha256")
                != current_audit["dependency_snapshot_sha256"]
                or environment_payload.get("model") != {
                    "provider": "deepseek-flash",
                    "model_id": frozen.payload["environment"]["model"],
                    "thinking": "disabled",
                }
                or environment_payload.get("retrieval_health") != "passed"
                or environment_payload.get("llm_compatibility") != "passed"
                or notes.get("settings") != expected_settings
                or notes.get("dataset_hash") != frozen.payload["dataset"]["parent_sha256"]
                or notes.get("expected_manifest_by_case")
                != arm_contract["manifests"]
                or notes.get("protocol_id") != frozen.payload["protocol_id"]
                or notes.get("core_asset_registry_id")
                != arm_contract["core_asset_registry_id"]
                or notes.get("endpoint_sha256") != arm_contract["endpoint_sha256"]
                or notes.get("configuration_sha256")
                != current_audit["configuration_sha256"]
                or notes.get("safe_fetch_proxy_sha256")
                != current_audit["safe_fetch_proxy_sha256"]
                or notes.get("embedding_revision")
                != frozen.payload["environment"]["embedding_revision"]
                or notes.get("embedding_startup_mode") != "cold-in-research"
                or notes.get("auto_recovery") is not False
                or notes.get("hitl_mode") != "stop-at-hitl-no-auto-resolution"
                or notes.get("task_admission_limit") != 3
                or notes.get("protocol_byte_sha256") != frozen.byte_sha256):
            raise RepairPairControlError("prepared environment semantic drift")
    _validate_independent_trees(
        SEED_ROOT, knowledge_copies,
        frozen.payload["knowledge_seed"]["artifact_tree_sha256"],
    )
    return frozen.payload, binding


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _telemetry_nonce_ready(path: Path, nonce: str) -> bool:
    required = {"telemetry_ready", "service_started"}
    observed: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if (event.get("event") in required
                    and event.get("instance_nonce") == nonce
                    and event.get("status") == "success"):
                observed.add(event["event"])
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return observed == required


async def _wait_ready(client: httpx.AsyncClient, process: subprocess.Popen[Any],
                      telemetry_path: Path, nonce: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RepairPairControlError("service exited before readiness")
        try:
            response = await client.get("/health")
            payload = response.json()
            if (response.status_code == 200 and _health_safe(payload)
                    and _telemetry_nonce_ready(telemetry_path, nonce)):
                return
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(0.5)
    raise RepairPairControlError("service readiness timeout")


def _health_safe(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("runtime_instance") != "active":
        return False
    authority = payload.get("runtime_observations")
    heartbeat = payload.get("run_heartbeat")
    return (
        isinstance(authority, dict)
        and authority.get("authority_valid") is True
        and isinstance(authority.get("lease_remaining_ms"), int)
        and authority["lease_remaining_ms"] > 0
        and isinstance(heartbeat, dict)
        and type(heartbeat.get("failures")) is int
        and heartbeat["failures"] == 0
        and type(heartbeat.get("lease_losses")) is int
        and heartbeat["lease_losses"] == 0
    )


async def _require_safe_health(client: httpx.AsyncClient) -> None:
    try:
        response = await client.get("/health")
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise RepairPairControlError("runtime authority health unavailable") from None
    if response.status_code != 200 or not _health_safe(payload):
        raise RepairPairControlError("runtime authority health unsafe")


def _strict_telemetry_state(path: Path, *, require_stopped: bool = False,
                            require_runner_returned: bool = False) -> dict[str, Any]:
    from scripts.o1_pr2b_control import telemetry_state

    state = telemetry_state(
        path, require_stopped=require_stopped,
        require_runner_returned=require_runner_returned,
    )
    if state["anomaly"]:
        return state
    try:
        raw = path.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise ValueError
        for line in raw.splitlines():
            event = json.loads(line)
            kind = event.get("event") if isinstance(event, dict) else None
            if kind in {"external_http_failure", "safe_fetch_failure", "child_failure"}:
                return {**state, "anomaly": True,
                        "reason": f"strict_{kind}"}
            if kind == "external_http_response":
                status_code = event.get("status_code")
                operation = event.get("operation")
                if (operation == "other" or not isinstance(status_code, int)
                        or status_code == 429 or status_code >= 500):
                    return {**state, "anomaly": True,
                            "reason": "strict_external_http_response"}
    except (OSError, ValueError, json.JSONDecodeError):
        return {**state, "anomaly": True, "reason": "strict_telemetry_parse"}
    return state


def _contained_artifact(root: Path, relative: Any, *, nonempty: bool) -> Path | None:
    if not isinstance(relative, str):
        return None
    candidate_relative = Path(relative)
    if candidate_relative.is_absolute():
        return None
    candidate = (root / candidate_relative).resolve()
    try:
        metadata = candidate.lstat()
        if (not candidate.is_relative_to(root.resolve())
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or bool(getattr(metadata, "st_file_attributes", 0) & 0x0400)
                or (nonempty and metadata.st_size <= 0)):
            return None
    except OSError:
        return None
    return candidate


def _case_payload(case_id: str) -> dict[str, Any]:
    from benchmarks.product_optimization_dev_requests import load_dev_requests

    fixture = load_dev_requests()
    item = next(case for case in fixture.cases if case.case_id == case_id)
    return {"id": item.case_id, "split": "development",
            "request": item.request.model_dump(mode="json", exclude_none=False),
            "rubric": {"must_answer": ["frozen-development-request"]},
            "hitl": {"action": "cancel"}}


def _strict_terminal_usage_anomaly(record: dict[str, Any]) -> bool:
    observation = record.get("observability")
    if not isinstance(observation, dict):
        return True
    totals = observation.get("totals")
    budget = observation.get("budget")
    if (not isinstance(totals, dict)
            or totals.get("token_usage_complete") is not True
            or not isinstance(budget, dict)
            or budget.get("availability") != "available"
            or budget.get("admission_denied") is True
            or not isinstance(budget.get("resources"), dict)):
        return True
    required = {"active_milliseconds", "llm_calls", "retrieval_calls", "total_tokens"}
    resources = budget["resources"]
    if not required.issubset(resources):
        return True
    for name in required:
        resource = resources[name]
        if (not isinstance(resource, dict)
                or resource.get("availability") != "available"
                or resource.get("exhausted") is not False
                or type(resource.get("reserved")) is not int
                or resource["reserved"] != 0
                or type(resource.get("unknown_spend")) is not int
                or resource["unknown_spend"] != 0):
            return True
    return False


def _record_stop_reason(record: dict[str, Any], collection: Path) -> str | None:
    from scripts.o1_pr2b_control import budget_anomaly, call_anomaly, source_anomaly

    if record.get("error_code") or record.get("status") not in SUCCESS:
        return "CELL_NOT_SUCCESSFUL"
    if record.get("hitl_resolutions") != 0:
        return "HITL_AUTO_RESOLUTION_FORBIDDEN"
    if (not record.get("observability_final") or budget_anomaly(record)
            or _strict_terminal_usage_anomaly(record) or call_anomaly(record)):
        return "BUDGET_OR_CALL_OBSERVABILITY_ANOMALY"
    if not _health_safe({"runtime_instance": "active",
                         "runtime_observations": record.get("runtime_observations"),
                         "run_heartbeat": record.get("run_heartbeat")}):
        return "RUNTIME_AUTHORITY_OR_HEARTBEAT_UNKNOWN"
    report, snapshot = record.get("report_path"), record.get("snapshot_path")
    report_path = _contained_artifact(collection, report, nonempty=True)
    snapshot_path = _contained_artifact(collection, snapshot, nonempty=True)
    if report_path is None or snapshot_path is None:
        return "REPORT_OR_SNAPSHOT_MISSING"
    if source_anomaly(_read_json(snapshot_path)):
        return "SOURCE_ENVELOPE_ANOMALY"
    return None


async def _run_block(*, experiment_root: Path, block: dict[str, Any],
                     product_root: Path, env_file: Path,
                     protocol_id: str,
                     expected_manifests: dict[str, str],
                     dataset_hash: str,
                     before_admission: Callable[[], None]
                     ) -> tuple[list[dict[str, Any]], str | None]:
    from benchmarks.product_baseline import CollectionOptions, DurableBaselineCollector
    arm, repetition = block["arm"], block["repetition"]
    profile = f"serial-r{repetition}"
    block_root = _block_root(experiment_root, arm, repetition)
    control = block_root / "control"
    collection = experiment_root / "collections" / f"{arm}-r{repetition}"
    port = _free_port()
    instance_nonce = secrets.token_hex(16)
    environment, _ = _private_environment(env_file)
    command = [sys.executable, str(CHILD), "--root", str(block_root),
               "--port", str(port), "--profile", profile,
               "--frozen-root", str(product_root),
               "--control-root", str(control),
               "--instance-nonce", instance_nonce]
    stdout_handle = (control / "child.stdout.log").open("wb")
    try:
        stderr_handle = (control / "child.stderr.log").open("wb")
    except Exception:
        stdout_handle.close()
        raise
    try:
        process = subprocess.Popen(command, cwd=product_root, env=environment,
                                   stdout=stdout_handle, stderr=stderr_handle)
    except Exception:
        stdout_handle.close()
        stderr_handle.close()
        raise
    records: list[dict[str, Any]] = []
    stop_reason: str | None = None
    graceful = False
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",
                                     timeout=30, trust_env=False) as client:
            await _wait_ready(
                client, process, control / "telemetry.jsonl", instance_nonce
            )
            for case_id in block["case_order"]:
                before_admission()
                await _require_safe_health(client)
                telemetry = _strict_telemetry_state(control / "telemetry.jsonl")
                if telemetry["anomaly"]:
                    stop_reason = f"TELEMETRY_{telemetry['reason']}"
                    break
                options = CollectionOptions(
                    profile=profile, repetition=repetition, concurrency=1,
                    poll_interval_seconds=1.0, case_timeout_seconds=900.0,
                    stop_at_hitl=True,
                    expected_manifest_id=expected_manifests[case_id],
                )
                collector = DurableBaselineCollector(
                    client, collection,
                    experiment_id=protocol_id,
                    dataset_hash=dataset_hash,
                    options=options,
                )
                if (process.poll() is not None
                        or not _telemetry_nonce_ready(
                            control / "telemetry.jsonl", instance_nonce
                        )):
                    raise RepairPairControlError("owned service unavailable before admission")
                _reserve_cell(arm, repetition, case_id, protocol_id)
                [record] = await collector.collect([_case_payload(case_id)])
                record.update(arm=arm, repetition=repetition, block=block["block"])
                _append_ledger_observation(record, protocol_id)
                records.append(record)
                stop_reason = _record_stop_reason(record, collection)
                if stop_reason is not None:
                    break
                await _require_safe_health(client)
                telemetry = _strict_telemetry_state(control / "telemetry.jsonl")
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
    final_telemetry = _strict_telemetry_state(
        control / "telemetry.jsonl", require_stopped=graceful,
        require_runner_returned=graceful,
    )
    if stop_reason is None and (process.returncode != 0
                                or final_telemetry["anomaly"]):
        stop_reason = "SERVICE_OR_FINAL_TELEMETRY_ANOMALY"
    return records, stop_reason


async def run(experiment_root: Path, preflight_dir: Path, baseline_root: Path,
              candidate_root: Path, env_file: Path,
              expected_protocol_byte_sha256: str) -> dict[str, Any]:
    protocol, binding = _validate_execution_binding(
        experiment_root, preflight_dir, baseline_root, candidate_root, env_file,
        expected_protocol_byte_sha256)
    _claim_protocol_execution(experiment_root, binding, protocol["protocol_id"])
    planned = [{"block": block["block"], "arm": block["arm"],
                "repetition": block["repetition"], "case_id": case_id,
                "status": "not_submitted"}
               for block in protocol["design"]["execution_blocks"]
               for case_id in block["case_order"]]
    seen: set[tuple[str, int, str]] = set()
    records: list[dict[str, Any]] = []
    stop_reason: str | None = None

    def before_admission() -> None:
        _validate_execution_binding(experiment_root, preflight_dir,
                                    baseline_root, candidate_root, env_file,
                                    expected_protocol_byte_sha256)

    for block in protocol["design"]["execution_blocks"]:
        if stop_reason is not None:
            break
        arm = block["arm"]
        product_root = baseline_root if arm == "baseline" else candidate_root
        try:
            expected = audit(
                baseline_root, candidate_root, env_file,
                expected_protocol_byte_sha256
            )["arm_contracts"][arm]["manifests"]
            block_records, stop_reason = await _run_block(
                experiment_root=experiment_root, block=block,
                product_root=product_root, env_file=env_file,
                protocol_id=protocol["protocol_id"],
                expected_manifests=expected,
                dataset_hash=protocol["dataset"]["parent_sha256"],
                before_admission=before_admission)
        except Exception as exc:
            block_records = []
            stop_reason = f"CONTROL_{type(exc).__name__}"
        for record in block_records:
            key = (record["arm"], record["repetition"], record["case_id"])
            if key in seen:
                raise RepairPairControlError("duplicate paid cell admission")
            seen.add(key)
            records.append(record)
            for cell in planned:
                if (cell["arm"], cell["repetition"], cell["case_id"]) == key:
                    cell["status"] = record.get("status", "unknown")
                    cell["error_code"] = record.get("error_code")
                    break
    result = {
        "schema_version": 1, "protocol_id": protocol["protocol_id"],
        "started_cells": len(records), "planned_cells": 12,
        "complete": len(records) == 12 and stop_reason is None,
        "stop_reason": stop_reason, "cells": planned, "records": records,
        "no_retries_or_splices": True, "ended_at": _stamp(),
        "ledger": _ledger_summary(),
    }
    _write_json(experiment_root / "repair-pair-run-result.json", result)
    return result


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
                           args.env_file.resolve(),
                           args.expected_protocol_byte_sha256)
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
            result = prepare(args.experiment_root.resolve(),
                             args.preflight_dir.resolve(), args.baseline_root,
                             args.candidate_root, args.env_file.resolve(),
                             args.expected_protocol_byte_sha256)
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
        try:
            ledger = _ledger_summary()
        except Exception:
            ledger = {
                "attempted_cells": None, "known_admitted_min": None,
                "possibly_submitted_max": None, "uncertain_cells": None,
                "submission_count_uncertain": True,
            }
        exact_submitted = (
            ledger["known_admitted_min"]
            if not ledger["submission_count_uncertain"] else None
        )
        print(json.dumps({"error_type": type(exc).__name__,
                          "research_runs_submitted": exact_submitted,
                          **ledger},
                         sort_keys=True),
              flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
