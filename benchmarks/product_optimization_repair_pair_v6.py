"""Strict delta contract for the proposed repair-pair v6."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks import product_optimization_repair_pair_v5 as _v5


ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-repair-pair-v6.json"
PROTOCOL_ID = "product-optimization-repair-pair-v6"


class RepairPairProtocolError(ValueError):
    """Raised when the proposed v6 delta contract drifts."""


@dataclass(frozen=True, slots=True)
class RepairPairProtocol:
    payload: dict[str, Any]
    byte_sha256: str
    canonical_sha256: str


def _fail(message: str) -> None:
    raise RepairPairProtocolError(message)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise RepairPairProtocolError("required frozen file is unavailable") from None
    return digest.hexdigest()


def _validate_raw(raw: Any) -> None:
    expected_keys = {
        "schema_version", "protocol_id", "status", "freeze_date", "base_protocol",
        "controller", "design", "budgets", "stopping", "control_predecessor",
        "authorization",
    }
    if not isinstance(raw, dict) or set(raw) != expected_keys:
        _fail("protocol fields changed")
    if not (
        raw["schema_version"] == 1
        and raw["protocol_id"] == PROTOCOL_ID
        and raw["status"] == "frozen"
        and raw["freeze_date"] == "2026-09-26"
        and raw["base_protocol"] == {
            "protocol_id": "product-optimization-repair-pair-v5",
            "path": "benchmarks/product-optimization-repair-pair-v5.json",
            "byte_sha256": "13e8bd9ef2e6877c4c8465db22c3ab0bc1b11f3f386e704b7b314a45ef0fd796",
        }
    ):
        _fail("protocol identity changed")
    controller = raw.get("controller")
    expected_paths = [
        "scripts/product_optimization_repair_pair_v6.py",
        "benchmarks/product_optimization_repair_pair_v6.py",
        "scripts/product_optimization_repair_pair_v5.py",
        "benchmarks/product_optimization_repair_pair_v5.py",
        "benchmarks/product-optimization-repair-pair-v5.json",
        "scripts/o1_pr2b_child_v5.py",
    ]
    required = controller.get("required_files") if isinstance(controller, dict) else None
    if not (
        isinstance(required, list)
        and [item.get("path") for item in required if isinstance(item, dict)] == expected_paths
        and controller.get("binding_policy") == "delta-over-v5-control-binding-v1"
        and controller.get("research_admission")
        == "open-after-offline-runner-acceptance"
    ):
        _fail("controller contract changed")
    for item in required:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or len(item["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in item["sha256"])
            or _file_sha256(ROOT / item["path"]) != item["sha256"]
        ):
            _fail("controller file identity changed")
    if raw.get("design") != {
        "blind_labels": [f"RP6-{index:02d}" for index in range(1, 13)],
        "inherits_all_other_fields_from": "product-optimization-repair-pair-v5",
        "execution_mode": "serial-concurrency-1",
        "concurrency_phase": "deferred-until-product-effect-stability",
    }:
        _fail("design delta changed")
    if raw.get("budgets") != {
        "research_ledger": {
            "starting_used": 97,
            "local_pair_max": 12,
            "final_concurrency_reserve": 0,
            "unallocated": 47,
            "hard_total": 156,
        },
    }:
        _fail("budget proposal changed")
    expected_drift = [
        "chroma/chroma.sqlite3",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/data_level0.bin",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/length.bin",
    ]
    if raw.get("stopping") != {
        "used_block_chroma_runtime_drift": (
            "allow-same-inventory-and-size-only-for-listed-paths-after-attempt"
        ),
        "completed_record_reconciliation": (
            "same-root-append-only-observation-and-collection-record-only"
        ),
        "allowed_chroma_runtime_drift_paths": expected_drift,
    }:
        _fail("control stop policy changed")
    predecessor = raw.get("control_predecessor")
    if not (
        isinstance(predecessor, dict)
        and predecessor.get("protocol_id") == "product-optimization-repair-pair-v5"
        and predecessor.get("protocol_byte_sha256")
        == "13e8bd9ef2e6877c4c8465db22c3ab0bc1b11f3f386e704b7b314a45ef0fd796"
        and predecessor.get("accounted_research_runs") == 1
        and predecessor.get("trace_external_calls") == 16
        and predecessor.get("used_knowledge_tree_sha256")
        == "c5b46ded75fb9fed8ee93a82d8487813a1c193f457626815336347a1e698ccdf"
        and predecessor.get("disposition") == "immutable-no-retry-no-splice"
    ):
        _fail("control predecessor changed")
    if raw.get("authorization") != {
        "status": "approved-existing-cap",
        "decision_date": "2026-09-26",
        "current_hard_total": 156,
        "effective_hard_total": 156,
        "local_pair_max": 12,
        "concurrency_runs_authorized": 0,
        "deferred_unallocated": 47,
        "preserve_acceptance_thresholds": True,
    }:
        _fail("measurement authorization changed")


def _materialize(raw: dict[str, Any]) -> dict[str, Any]:
    base = _v5.load_repair_pair_protocol()
    if base.byte_sha256 != raw["base_protocol"]["byte_sha256"]:
        _fail("base protocol identity changed")
    payload = deepcopy(base.payload)
    payload["protocol_id"] = PROTOCOL_ID
    payload["status"] = raw["status"]
    payload["controller"] = deepcopy(raw["controller"])
    for item, label in zip(
        payload["design"]["blind_review_order"], raw["design"]["blind_labels"],
        strict=True,
    ):
        item["blind_label"] = label
    payload["budgets"]["research_ledger"] = deepcopy(
        raw["budgets"]["research_ledger"]
    )
    payload["stopping"].update(deepcopy(raw["stopping"]))
    payload["control_predecessor"] = deepcopy(raw["control_predecessor"])
    payload["authorization"] = deepcopy(raw["authorization"])
    return payload


def load_repair_pair_protocol(path: Path = PROTOCOL_PATH) -> RepairPairProtocol:
    if path != PROTOCOL_PATH or not path.is_absolute():
        _fail("protocol path is not approved")
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairProtocolError("protocol could not be loaded") from None
    _validate_raw(raw)
    payload = _materialize(raw)
    canonical = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return RepairPairProtocol(
        payload=payload,
        byte_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "RepairPairProtocol",
    "RepairPairProtocolError",
    "load_repair_pair_protocol",
]
