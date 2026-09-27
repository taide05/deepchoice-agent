"""Strict contract for the proposed three-case serial product check."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks import product_optimization_repair_pair_v6 as _v6


ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v1.json"
PROTOCOL_ID = "product-optimization-serial-check-v1"
BASE_SHA256 = "393dd11655b92d8e35683bdcbfdac1fe683f5df63ecc99a59dfdd0a7a0ceb64c"
CASE_ORDER = ("P04", "P01", "P08")


class SerialCheckProtocolError(ValueError):
    """Raised when the proposed serial-check contract drifts."""


@dataclass(frozen=True, slots=True)
class SerialCheckProtocol:
    payload: dict[str, Any]
    byte_sha256: str
    canonical_sha256: str


def _fail(message: str) -> None:
    raise SerialCheckProtocolError(message)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise SerialCheckProtocolError("required frozen file is unavailable") from None
    return digest.hexdigest()


def _validate_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_raw(raw: Any) -> None:
    expected_keys = {
        "schema_version", "protocol_id", "status", "freeze_date",
        "base_protocol", "question", "interpretation", "candidate",
        "controller", "design", "budgets", "metrics", "acceptance",
        "stopping", "control_predecessor", "authorization",
    }
    if not isinstance(raw, dict) or set(raw) != expected_keys:
        _fail("protocol fields changed")
    if not (
        raw["schema_version"] == 1
        and raw["protocol_id"] == PROTOCOL_ID
        and raw["status"] == "proposed"
        and raw["freeze_date"] is None
        and raw["base_protocol"] == {
            "protocol_id": "product-optimization-repair-pair-v6",
            "path": "benchmarks/product-optimization-repair-pair-v6.json",
            "byte_sha256": BASE_SHA256,
        }
        and raw["question"]
        == "Can the current candidate produce three usable serial reports for P04, P01, and P08 without runtime, source, budget, citation, or module anomalies?"
        and raw["interpretation"]
        == "three-case-current-candidate-diagnostic-not-paired-effect"
    ):
        _fail("protocol identity changed")
    candidate = raw.get("candidate")
    if not (
        isinstance(candidate, dict)
        and candidate.get("anchor_commit")
        == "4e7ce70e0555c9fc362273d523fe4716a0cfb6f3"
        and candidate.get("source_objects") == [
            {"path": "src/deepchoice", "git_object": "d5559b8c96d24f70899560fe3b81c85482ac050d"},
            {"path": "pyproject.toml", "git_object": "72433509ffdfa8d057c6ba21cbe40bf61b55c08d"},
        ]
        and candidate.get("runtime_objects") == [
            {"path": "benchmarks/__init__.py", "git_object": "830b6bddff5731d650221c25c60409dfb547d46f"},
            {"path": "benchmarks/product_baseline.py", "git_object": "c68b828df7e73491d3f085d8e1387b2d7dd5fe17"},
            {"path": "benchmarks/product_baseline_experiment.py", "git_object": "d05232c6492e069273347ba7423e94ac8fa6a5f4"},
            {"path": "benchmarks/product_baseline_server.py", "git_object": "819395806e6098fcbf814d590756c80d6c370357"},
        ]
    ):
        _fail("candidate identity changed")
    controller = raw.get("controller")
    required = controller.get("required_files") if isinstance(controller, dict) else None
    expected_paths = [
        "scripts/product_optimization_serial_check_v1.py",
        "benchmarks/product_optimization_serial_check_v1.py",
        "scripts/product_optimization_repair_pair_v6.py",
        "benchmarks/product_optimization_repair_pair_v6.py",
        "benchmarks/product-optimization-repair-pair-v6.json",
        "scripts/o1_pr2b_child_v5.py",
    ]
    if not (
        isinstance(required, list)
        and [item.get("path") for item in required if isinstance(item, dict)]
        == expected_paths
        and controller.get("binding_policy")
        == "candidate-only-three-case-over-v6-v1"
        and controller.get("research_admission")
        == "closed-pending-independent-review"
    ):
        _fail("controller contract changed")
    for item in required:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not _validate_hash(item.get("sha256"))
            or _file_sha256(ROOT / item["path"]) != item["sha256"]
        ):
            _fail("controller file identity changed")
    if raw.get("design") != {
        "formal_research_runs": 3,
        "execution_mode": "serial-concurrency-1",
        "case_order": list(CASE_ORDER),
        "holdout_access": "forbidden",
        "historical_baseline_use": "diagnostic-context-only-not-a-same-window-pair",
        "no_ad_hoc_reruns": True,
        "blind_labels": ["SC1-01", "SC1-02", "SC1-03"],
    }:
        _fail("design changed")
    if raw.get("budgets") != {
        "research_ledger": {
            "starting_used": 100,
            "diagnostic_max": 3,
            "concurrency_reserve": 0,
            "unallocated": 53,
            "hard_total": 156,
        }
    }:
        _fail("budget changed")
    if raw.get("metrics") != {
        "runtime": [
            "terminal_status", "wall_time_ms", "timeouts", "retries",
            "partial_failures",
        ],
        "calls": [
            "llm_calls", "retrieval_calls", "failed_calls", "total_tokens",
            "token_usage_complete",
        ],
        "report": [
            "artifact_present", "self_review", "must_answer_coverage",
            "major_errors", "action_safety",
        ],
        "citation": [
            "verified", "unsupported", "unreachable", "unknown",
            "reason_counts",
        ],
        "decision": [
            "winner", "ranked_options", "unresolved_questions",
            "hitl_resolutions",
        ],
        "modules": [
            "source_envelopes", "trace_attempts", "budget_state",
            "telemetry_anomalies",
        ],
    }:
        _fail("metrics changed")
    if raw.get("acceptance") != {
        "collection": "all-three-cases-have-queryable-terminal-report-and-complete-observability",
        "p04": "covers-restart-at-least-once-idempotency-staged-advance-abort-rollback-without-exactly-once-claim",
        "p01": "no-new-major-error-and-keeps-observable-migration-triggers",
        "p08": "no-unconditional-winner-when-critical-context-is-missing-and-hitl-behavior-is-recorded",
        "citation": "verified-total-above-zero-and-no-truncated-prefix-miss-is-labelled-unsupported",
        "interpretation_limit": "diagnostic-product-feedback-only-no-causal-improvement-claim",
    }:
        _fail("acceptance changed")
    expected_drift = [
        "chroma/chroma.sqlite3",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/data_level0.bin",
        "chroma/c29ae142-54e0-4e63-b329-24f1f4af8a53/length.bin",
    ]
    if raw.get("stopping") != {
        "identity_environment_seed_or_controller_drift": "stop-before-admission",
        "retrieval_rate_limit_safety_budget_lease_or_unknown": "stop-new-admission",
        "unclassified_external_or_safe_fetch_error": "stop-new-admission",
        "ordinary_citation_http_5xx": "stop-new-admission",
        "finish_already_admitted_run": True,
        "replace_retry_or_splice_stopped_root": False,
        "used_block_chroma_runtime_drift": (
            "allow-same-inventory-and-size-only-for-listed-paths-after-attempt"
        ),
        "completed_record_reconciliation": (
            "same-root-append-only-observation-and-collection-record-only"
        ),
        "allowed_chroma_runtime_drift_paths": expected_drift,
    }:
        _fail("stopping policy changed")
    predecessor = raw.get("control_predecessor")
    if not (
        isinstance(predecessor, dict)
        and predecessor.get("protocol_id")
        == "product-optimization-repair-pair-v6"
        and predecessor.get("protocol_byte_sha256") == BASE_SHA256
        and predecessor.get("accounted_research_runs") == 3
        and predecessor.get("disposition") == "immutable-no-retry-no-splice"
        and isinstance(predecessor.get("artifacts"), dict)
        and set(predecessor["artifacts"]) == {
            "execution_binding", "execution_claim", "cell_p04", "cell_p01",
            "cell_p08", "observations", "run_result", "collection_record",
            "telemetry",
        }
        and all(
            isinstance(item, dict)
            and set(item) == {"path", "sha256"}
            and _validate_hash(item.get("sha256"))
            for item in predecessor["artifacts"].values()
        )
    ):
        _fail("control predecessor changed")
    if raw.get("authorization") != {
        "status": "approved-existing-cap",
        "decision_date": "2026-09-27",
        "current_hard_total": 156,
        "effective_hard_total": 156,
        "diagnostic_max": 3,
        "concurrency_runs_authorized": 0,
        "deferred_unallocated": 53,
        "preserve_acceptance_thresholds": True,
    }:
        _fail("authorization changed")


def _materialize(raw: dict[str, Any]) -> dict[str, Any]:
    base = _v6.load_repair_pair_protocol()
    if base.byte_sha256 != raw["base_protocol"]["byte_sha256"]:
        _fail("base protocol identity changed")
    payload = deepcopy(base.payload)
    payload.update(
        protocol_id=PROTOCOL_ID,
        status=raw["status"],
        freeze_date=raw["freeze_date"],
        question=raw["question"],
        interpretation=raw["interpretation"],
    )
    payload["identities"]["candidate"] = deepcopy(raw["candidate"])
    payload["controller"] = deepcopy(raw["controller"])
    payload["design"] = {
        "formal_research_runs": 3,
        "profile": "serial",
        "concurrency": 1,
        "same_window_days": 7,
        "independent_single_case_qualification": False,
        "paired_p01_replaces_qualification": False,
        "no_ad_hoc_reruns": True,
        "execution_blocks": [
            {
                "block": 1,
                "arm": "candidate",
                "repetition": 1,
                "case_order": list(CASE_ORDER),
            }
        ],
        "blind_review_order": [
            {
                "case_id": case_id,
                "role": "regression" if case_id == "P01" else "target",
                "arm": "candidate",
                "repetition": 1,
                "order": index,
                "blind_label": raw["design"]["blind_labels"][index - 1],
            }
            for index, case_id in enumerate(CASE_ORDER, start=1)
        ],
        "holdout_access": raw["design"]["holdout_access"],
        "historical_baseline_use": raw["design"]["historical_baseline_use"],
    }
    payload["budgets"]["research_ledger"] = deepcopy(
        raw["budgets"]["research_ledger"]
    )
    payload["metrics"] = deepcopy(raw["metrics"])
    payload["acceptance"] = deepcopy(raw["acceptance"])
    payload["stopping"] = deepcopy(raw["stopping"])
    payload["control_predecessor"] = deepcopy(raw["control_predecessor"])
    payload["authorization"] = deepcopy(raw["authorization"])
    return payload


def load_serial_check_protocol(path: Path = PROTOCOL_PATH) -> SerialCheckProtocol:
    if path != PROTOCOL_PATH or not path.is_absolute():
        _fail("protocol path is not approved")
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SerialCheckProtocolError("protocol could not be loaded") from None
    _validate_raw(raw)
    payload = _materialize(raw)
    canonical = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return SerialCheckProtocol(
        payload=payload,
        byte_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "CASE_ORDER",
    "SerialCheckProtocol",
    "SerialCheckProtocolError",
    "load_serial_check_protocol",
]
