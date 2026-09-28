"""Machine-bound, initially closed v3 overlay on the reviewed serial collector."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from benchmarks import product_optimization_serial_check_v2 as parent

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v3.json"
PROTOCOL_ID = "product-optimization-serial-check-v3"
PARENT_SHA256 = "47ffb9c66b07039a7c2730103718ad8b30126320152a9d13f1b303b4e6b89975"
CARD_PATH = Path("D:/deepchoice-agent/notes/product-optimization-serial-card-v3-20260928.md")
CARD_SHA256 = "ac65512a302b82820c4a6d70812137d2b7be4a3bf04d8cecba755a3223a955a8"
CLOSED = "closed-pending-independent-review-and-offline-acceptance"
OPEN = parent.OPEN
NEW_CONTROL_PATHS = (
    "scripts/product_optimization_serial_check_v3.py",
    "benchmarks/product_optimization_serial_check_v3.py",
)
SerialCheckProtocolError = parent.SerialCheckProtocolError

_PREDECESSOR_ARTIFACTS = {
    "execution_binding": ("outputs/product-optimization-serial-check-v2-20260927-v1/execution-binding.json", "e45a8383d7c2702c53280201221dfd90877bcdcf662e08818473a09acfd837da"),
    "execution_claim": ("outputs/product-optimization-ledgers/product-optimization-serial-check-v2/execution-claim.json", "044e34476d673d0ac92b25e79b0900fde8df395803f941614546456213005b2f"),
    "run_result": ("outputs/product-optimization-serial-check-v2-20260927-v1/serial-check-run-result.json", "2ab1656b508059a8c54afc2c6a46f68cb6679222091bdeed3cfc4d9ad45dfc80"),
    "cell_p04": ("outputs/product-optimization-ledgers/product-optimization-serial-check-v2/cells/candidate-r1-P04.json", "61c7f811b65954230ea1359e4234b88f6766e5bba29e99969353073452f7df5b"),
    "cell_p01": ("outputs/product-optimization-ledgers/product-optimization-serial-check-v2/cells/candidate-r1-P01.json", "fcb67541b41ca268e6d8a7868b77adbbe6022200b2c59cf10ce70b6623cc947b"),
    "observations": ("outputs/product-optimization-ledgers/product-optimization-serial-check-v2/observations.jsonl", "9b84e4ec0b20ddbeb86ed94184f836afff16e18f8d5dd0fa89b5a8de886c5d3f"),
    "collection_record": ("outputs/product-optimization-serial-check-v2-20260927-v1/collections/candidate-r1/runs.jsonl", "0867fdf751fbbdcebd7094743796de2d9e96c50239ca2cb3cac42617d503f53b"),
    "telemetry": ("outputs/product-optimization-serial-check-v2-20260927-v1/arms/candidate/r1/control/telemetry.jsonl", "15bff9f8dc50513c6c7f856bf37d6a431ab19bbbbebe85d99adab4aa3c871a38"),
}


def _expected_raw() -> dict:
    old = parent.load_serial_check_protocol()
    if old.byte_sha256 != PARENT_SHA256:
        raise SerialCheckProtocolError("v2 protocol identity drift")
    candidate = deepcopy(old.payload["identities"]["candidate"])
    candidate["anchor_commit"] = "13e42c5e932c620c9e8b18736f7fe9b48b95ea13"
    candidate["source_objects"][0]["git_object"] = "ec8f3e7dce8d6550e482246584157a31a3850471"
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "status": "frozen",
        "freeze_date": "2026-09-28",
        "base_protocol": {
            "protocol_id": parent.PROTOCOL_ID,
            "path": "benchmarks/product-optimization-serial-check-v2.json",
            "byte_sha256": PARENT_SHA256,
        },
        "design_card": {"path": CARD_PATH.as_posix(), "sha256": CARD_SHA256},
        "candidate": candidate,
        "controller": {
            "binding_policy": "candidate-only-three-case-over-serial-v1-v2-v3",
            "research_admission": CLOSED,
            "required_files": [
                {"path": path, "sha256": parent.parent._file_sha256(ROOT / path)}
                for path in NEW_CONTROL_PATHS
            ],
        },
        "design": {
            "formal_research_runs": 3,
            "execution_mode": "serial-concurrency-1",
            "case_order": ["P04", "P01", "P08"],
            "holdout_access": "forbidden",
            "historical_baseline_use": "diagnostic-context-only-not-a-same-window-pair",
            "no_ad_hoc_reruns": True,
            "blind_labels": ["SC3-01", "SC3-02", "SC3-03"],
            "hitl_policy": deepcopy(old.payload["design"]["hitl_policy"]),
        },
        "budgets": {"research_ledger": {
            "starting_used": 105, "diagnostic_max": 3, "concurrency_reserve": 0,
            "unallocated": 48, "hard_total": 156,
        }},
        "acceptance": {
            "collection": "all-three-cases-have-queryable-terminal-report-and-complete-observability",
            "p04": "restart-no-silent-loss-authority-record-and-four-checkable-isolated-stages-with-advance-abort-boundaries",
            "p01": "conditional-writer-fts5-backup-choice-with-measurable-migration-boundaries-no-invented-workload",
            "p08": "conditional-choice-preserved-no-paste-evidence-or-title-rebinding",
            "citation": "inspect-source-qualifiers-scene-applicability-and-chinese-usability-no-verified-count-as-quality-pass",
            "interpretation_limit": "diagnostic-product-feedback-only-no-causal-improvement-claim",
        },
        "control_predecessor": {
            "protocol_id": parent.PROTOCOL_ID,
            "protocol_byte_sha256": PARENT_SHA256,
            "artifacts": {
                name: {"path": path, "sha256": digest}
                for name, (path, digest) in _PREDECESSOR_ARTIFACTS.items()
            },
            "accounted_research_runs": 2,
            "disposition": "immutable-no-retry-no-splice",
        },
        "authorization": {
            "status": "approved-existing-cap",
            "decision_date": "2026-09-28",
            "current_hard_total": 156,
            "effective_hard_total": 156,
            "diagnostic_max": 3,
            "concurrency_runs_authorized": 0,
            "deferred_unallocated": 48,
            "preserve_acceptance_thresholds": True,
        },
    }


def _validate_raw(raw: dict) -> None:
    expected = _expected_raw()
    mode = raw.get("controller", {}).get("research_admission") if isinstance(raw, dict) else None
    if mode not in (CLOSED, OPEN):
        raise SerialCheckProtocolError("v3 admission contract drift")
    expected["controller"]["research_admission"] = mode
    if json.dumps(raw, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise SerialCheckProtocolError("v3 frozen protocol contract drift")
    if parent.parent._file_sha256(CARD_PATH) != CARD_SHA256:
        raise SerialCheckProtocolError("v3 local design card drift")


def load_serial_check_protocol(path: Path = PROTOCOL_PATH) -> parent.parent.SerialCheckProtocol:
    if path != PROTOCOL_PATH or not path.is_absolute():
        raise SerialCheckProtocolError("protocol path is not approved")
    try:
        data = path.read_bytes()
        raw = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SerialCheckProtocolError("protocol could not be loaded") from None
    _validate_raw(raw)
    payload = deepcopy(parent.load_serial_check_protocol().payload)
    for key in ("protocol_id", "status", "freeze_date", "design_card", "control_predecessor", "authorization", "acceptance"):
        payload[key] = deepcopy(raw[key])
    payload["identities"]["candidate"] = deepcopy(raw["candidate"])
    payload["controller"] = deepcopy(raw["controller"])
    payload["controller"]["required_files"] += deepcopy(parent.load_serial_check_protocol().payload["controller"]["required_files"])
    payload["budgets"]["research_ledger"] = deepcopy(raw["budgets"]["research_ledger"])
    payload["design"]["hitl_policy"] = deepcopy(raw["design"]["hitl_policy"])
    for row, label in zip(payload["design"]["blind_review_order"], raw["design"]["blind_labels"], strict=True):
        row["blind_label"] = label
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return parent.parent.SerialCheckProtocol(payload, hashlib.sha256(data).hexdigest(), hashlib.sha256(canonical).hexdigest())
