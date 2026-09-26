"""Strict offline contract for the decoding-qualified repair-pair v5."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks import product_optimization_repair_pair as _v4


ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-repair-pair-v5.json"
PROTOCOL_ID = "product-optimization-repair-pair-v5"


class RepairPairProtocolError(ValueError):
    """Raised when the frozen v5 protocol drifts."""


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


def _validate_protocol(payload: Any) -> None:
    expected_keys = {
        "schema_version", "protocol_id", "status", "freeze_date", "question",
        "interpretation", "dataset", "identities", "knowledge_seed", "controller",
        "design", "environment", "budgets", "review", "acceptance", "stopping",
        "predecessor", "immediate_predecessor", "latest_predecessor",
        "current_predecessor", "authorization",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        _fail("protocol fields changed")
    if (
        payload["schema_version"] != 1
        or payload["protocol_id"] != PROTOCOL_ID
        or payload["status"] != "frozen"
        or payload["freeze_date"] != "2026-09-26"
    ):
        _fail("protocol identity changed")
    controller = payload.get("controller")
    expected_paths = [
        "scripts/product_optimization_repair_pair_v5.py",
        "scripts/product_optimization_repair_pair.py",
        "scripts/o1_pr2b_child_v5.py",
        "scripts/o1_pr2b_child.py",
        "scripts/o1_pr2b_control.py",
        "benchmarks/product_optimization_repair_pair_v5.py",
        "benchmarks/product_optimization_repair_pair.py",
        "benchmarks/product_optimization_dev_requests.py",
        "benchmarks/product-optimization-dev-requests-v1.json",
        "benchmarks/__init__.py",
        "benchmarks/product_baseline.py",
        "benchmarks/product_baseline_qualification.py",
        "benchmarks/product_baseline_experiment.py",
        "benchmarks/product_baseline_server.py",
    ]
    required = controller.get("required_files") if isinstance(controller, dict) else None
    if (
        not isinstance(required, list)
        or [item.get("path") for item in required if isinstance(item, dict)] != expected_paths
        or controller.get("binding_policy") != "protocol-plus-execution-binding-v1"
        or controller.get("research_admission") != "open-after-offline-runner-acceptance"
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
    design = payload.get("design")
    if (
        not isinstance(design, dict)
        or [item.get("blind_label") for item in design.get("blind_review_order", [])]
        != [f"RP5-{index:02d}" for index in range(1, 13)]
    ):
        _fail("blind review order changed")
    if payload.get("budgets") != {
        "research_ledger": {
            "starting_used": 96,
            "local_pair_max": 12,
            "final_concurrency_reserve": 48,
            "hard_total": 156,
            "unallocated": 0,
        },
        "per_run": {
            "total_tokens": 60000,
            "llm_calls": 96,
            "retrieval_calls": 72,
            "active_milliseconds": 900000,
        },
        "prerequisite_max": {
            "non_llm_http_attempts": 20,
            "tavily_post_attempts": 1,
            "llm_http_attempts": 4,
            "research_runs": 0,
        },
    }:
        _fail("budget contract changed")
    if payload.get("authorization") != {
        "status": "approved",
        "decision_date": "2026-09-26",
        "current_hard_total": 155,
        "proposed_hard_total": 156,
        "effective_hard_total": 156,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "preserve_acceptance_thresholds": True,
    }:
        _fail("measurement authorization changed")
    stopping = payload.get("stopping")
    if (
        not isinstance(stopping, dict)
        or stopping.get("bounded_citation_decoding_unknown")
        != "continue-if-response-received-terminal-and-source-gates-pass"
    ):
        _fail("decoding stop policy changed")
    expected_current = {
        "protocol_id": "product-optimization-repair-pair-v4",
        "protocol_byte_sha256": "dd6814e128c9e40b7b4f70b6a2b1e6db2434f4243876e783f5a20a1a25a3a6c6",
        "artifacts": {
            "execution_claim": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v4/execution-claim.json",
                "sha256": "9f64d2ab4427abb6dcf5411a1dd72e6ef09c460c9cda913da364913d25cbbfee",
            },
            "attempted_cell": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v4/cells/baseline-r2-P04.json",
                "sha256": "8cfc11218b0853e2e9d049710f1ff8c08c04fa267c85d894ddd9042d5ff6b5ff",
            },
            "observation": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v4/observations.jsonl",
                "sha256": "086a9e1fdfca42d43347085dbcbd30cb6ec2af9bcab101fc379cc7a5583490b2",
            },
            "run_result": {
                "path": "outputs/product-optimization-repair-pair-v4-20260926-v1/repair-pair-run-result.json",
                "sha256": "c9ae68174c9382332b92dec2f44831647da597d5f6d4d529368dd06a2c116ab1",
            },
            "telemetry": {
                "path": "outputs/product-optimization-repair-pair-v4-20260926-v1/arms/baseline/r2/control/telemetry.jsonl",
                "sha256": "5b85c3f6cab8f2917a732fb65001a107b4365d26c107ce5169706211efd59e10",
            },
        },
        "accounted_research_runs": 1,
        "trace_external_calls": 14,
        "disposition": "immutable-no-retry-no-splice",
    }
    if payload.get("current_predecessor") != expected_current:
        _fail("current predecessor execution binding changed")

    projected = deepcopy(payload)
    projected.pop("current_predecessor")
    projected["protocol_id"] = _v4.PROTOCOL_ID
    for index, item in enumerate(projected["design"]["blind_review_order"], start=1):
        item["blind_label"] = f"RP4-{index:02d}"
    projected["controller"]["required_files"] = json.loads(
        _v4.PROTOCOL_PATH.read_text(encoding="utf-8")
    )["controller"]["required_files"]
    projected["budgets"]["research_ledger"] = {
        "starting_used": 95,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "hard_total": 155,
        "unallocated": 0,
    }
    projected["stopping"].pop("bounded_citation_decoding_unknown")
    projected["authorization"] = {
        "status": "approved",
        "decision_date": "2026-09-26",
        "current_hard_total": 154,
        "proposed_hard_total": 155,
        "effective_hard_total": 155,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "preserve_acceptance_thresholds": True,
    }
    try:
        _v4._validate_protocol(projected)
    except _v4.RepairPairProtocolError as exc:
        raise RepairPairProtocolError(str(exc)) from None


def load_repair_pair_protocol(path: Path = PROTOCOL_PATH) -> RepairPairProtocol:
    if path != PROTOCOL_PATH or not path.is_absolute():
        _fail("protocol path is not approved")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairProtocolError("protocol could not be loaded") from None
    _validate_protocol(payload)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return RepairPairProtocol(
        payload=payload,
        byte_sha256=hashlib.sha256(raw).hexdigest(),
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "RepairPairProtocol",
    "RepairPairProtocolError",
    "load_repair_pair_protocol",
]
