"""Closed, machine-bound v4 overlay for three serial product-effect reports."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from benchmarks import product_optimization_serial_check_v3 as parent

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v4.json"
PROTOCOL_ID = "product-optimization-serial-check-v4"
PARENT_SHA256 = "ecfe3cab6f1efe21ff9d450a6587bc33d9ffa2a105537edf65ab1348fe484107"
CARD_PATH = Path("D:/deepchoice-agent/notes/product-optimization-serial-card-v4-20260928.md")
CARD_SHA256 = "12ea22b0c8ef4153592917c807f0e2c64801ca0e44cc131533d4b5f208f61cfc"
CLOSED = "closed-pending-machine-review-and-offline-acceptance"
OPEN = parent.OPEN
NEW_CONTROL_PATHS = (
    "scripts/product_optimization_serial_check_v4.py",
    "benchmarks/product_optimization_serial_check_v4.py",
)
SerialCheckProtocolError = parent.SerialCheckProtocolError

_PREDECESSOR_ARTIFACTS = {
    "execution_binding": ("workspace", "outputs/product-optimization-serial-check-v3-20260928-v1/execution-binding.json", "1e751f2c5959e32d3246eebc144e9a6d5e6e0ad852c1fec29dedb0c7e1ce1dde"),
    "run_result": ("workspace", "outputs/product-optimization-serial-check-v3-20260928-v1/serial-check-run-result.json", "c27c6d11464af8764c4decbb5ccf3b7f15449814ed7a654271c1fe17a4a8abe6"),
    "collection_record": ("workspace", "outputs/product-optimization-serial-check-v3-20260928-v1/collections/candidate-r1/runs.jsonl", "4096ad6d0806ba02af50267b0c0858bb71f63f013736959f604631ae256ae771"),
    "telemetry": ("workspace", "outputs/product-optimization-serial-check-v3-20260928-v1/arms/candidate/r1/control/telemetry.jsonl", "60ff5837ae54976483f77c1c064f4d44a9fdbdcca2e2569516adb5bf77b56f7a"),
    "execution_claim": ("candidate", "outputs/product-optimization-ledgers/product-optimization-serial-check-v3/execution-claim.json", "f0aecd11e7eaf856b488cfd0ec6e6ca17cf63b5de92d6c035abbb6846ea5e613"),
    "observations": ("candidate", "outputs/product-optimization-ledgers/product-optimization-serial-check-v3/observations.jsonl", "8d33e9dedafe9264fdcb40a8384f77d91f5adb59663d11dcada46ea16656c94b"),
    "cell_p04": ("candidate", "outputs/product-optimization-ledgers/product-optimization-serial-check-v3/cells/candidate-r1-P04.json", "2461629d6e3f6b457bc134ac0fab49f7c2c3910539f206fe118369eb5a4f219b"),
    "cell_p01": ("candidate", "outputs/product-optimization-ledgers/product-optimization-serial-check-v3/cells/candidate-r1-P01.json", "a6916eede4f3c08d5cb50d986447ce982d3ead59f3a4756058ac9a39b75733a1"),
}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_raw() -> dict:
    old = parent.load_serial_check_protocol()
    if old.byte_sha256 != PARENT_SHA256:
        raise SerialCheckProtocolError("v3 protocol identity drift")
    candidate = deepcopy(old.payload["identities"]["candidate"])
    candidate["anchor_commit"] = "f0217760a8c620f3f8afd0aa09c1b18dc1bc811a"
    candidate["source_objects"][0]["git_object"] = "c23f03dd5189bedbe72770a194b70562b18c9d4a"
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "status": "frozen",
        "freeze_date": "2026-09-28",
        "base_protocol": {
            "protocol_id": parent.PROTOCOL_ID,
            "path": "benchmarks/product-optimization-serial-check-v3.json",
            "byte_sha256": PARENT_SHA256,
        },
        "design_card": {"path": CARD_PATH.as_posix(), "sha256": CARD_SHA256},
        "candidate": candidate,
        "controller": {
            "binding_policy": "candidate-only-three-case-over-serial-v1-v2-v3-v4",
            "research_admission": CLOSED,
            "required_files": [
                {"path": path, "sha256": _file_sha256(ROOT / path)}
                for path in NEW_CONTROL_PATHS
            ],
        },
        "design": {
            "formal_research_runs": 3,
            "execution_mode": "serial-concurrency-1",
            "case_order": ["P04", "P08", "P01"],
            "holdout_access": "forbidden",
            "historical_baseline_use": "diagnostic-context-only-not-a-same-window-pair",
            "no_ad_hoc_reruns": True,
            "blind_labels": ["SC4-01", "SC4-02", "SC4-03"],
            "hitl_policy": deepcopy(old.payload["design"]["hitl_policy"]),
        },
        "budgets": {"research_ledger": {
            "starting_used": 107, "diagnostic_max": 3, "concurrency_reserve": 0,
            "unallocated": 46, "hard_total": 156,
        }},
        "acceptance": {
            "collection": "three-queryable-terminal-reports-with-partial-source-failures-visible-not-silent-success",
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
                name: {"root": root, "path": path, "sha256": digest}
                for name, (root, path, digest) in _PREDECESSOR_ARTIFACTS.items()
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
            "deferred_unallocated": 46,
            "preserve_acceptance_thresholds": True,
        },
    }


def _validate_raw(raw: dict) -> None:
    expected = _expected_raw()
    mode = raw.get("controller", {}).get("research_admission") if isinstance(raw, dict) else None
    if mode not in (CLOSED, OPEN):
        raise SerialCheckProtocolError("v4 admission contract drift")
    expected["controller"]["research_admission"] = mode
    if json.dumps(raw, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise SerialCheckProtocolError("v4 frozen protocol contract drift")
    try:
        card_hash = _file_sha256(CARD_PATH)
    except OSError:
        raise SerialCheckProtocolError("v4 local design card unavailable") from None
    if card_hash != CARD_SHA256:
        raise SerialCheckProtocolError("v4 local design card drift")


def load_serial_check_protocol(path: Path = PROTOCOL_PATH) -> parent.parent.parent.SerialCheckProtocol:
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
    order = raw["design"]["case_order"]
    payload["design"]["execution_blocks"][0]["case_order"] = order[:]
    by_case = {row["case_id"]: row for row in payload["design"]["blind_review_order"]}
    payload["design"]["blind_review_order"] = [
        {**by_case[case_id], "order": index, "blind_label": raw["design"]["blind_labels"][index - 1]}
        for index, case_id in enumerate(order, start=1)
    ]
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return parent.parent.parent.SerialCheckProtocol(
        payload, hashlib.sha256(data).hexdigest(), hashlib.sha256(canonical).hexdigest(),
    )
