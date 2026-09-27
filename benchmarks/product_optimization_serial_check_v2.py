"""Frozen v2 identity overlay; retain the immutable v1 collector contract."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from benchmarks import product_optimization_serial_check_v1 as parent

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks/product-optimization-serial-check-v2.json"
PROTOCOL_ID = "product-optimization-serial-check-v2"
BASE_SHA256 = "77b2efce9df2a8ed18b40489b7f569d85159b6d1247c976306cc8550af1e55f5"
CLOSED = "closed-after-offline-binding"
OPEN = "open-after-independent-review-and-offline-acceptance"
SerialCheckProtocolError = parent.SerialCheckProtocolError
NEW_CONTROL_PATHS = (
    "scripts/product_optimization_serial_check_v2.py",
    "benchmarks/product_optimization_serial_check_v2.py",
)
# Only these prospective fields differ from the immutable v1 card.
_OVERRIDES = json.loads(r'''{
  "protocol_id": "product-optimization-serial-check-v2",
  "base_protocol": {
    "protocol_id": "product-optimization-serial-check-v1",
    "path": "benchmarks/product-optimization-serial-check-v1.json",
    "byte_sha256": "77b2efce9df2a8ed18b40489b7f569d85159b6d1247c976306cc8550af1e55f5"
  },
  "design_card": {
    "path": "docs/product-optimization-serial-check-v2.md",
    "sha256": "793e84f82e7530a66b3f2931c26e97ad4add7c3fad64129fc0b2febe73939d8d"
  },
  "candidate": {
    "anchor_commit": "c1c43d8df9e8229d970ce78c752bc2e13776c3ff",
    "source_objects": [
      {
        "path": "src/deepchoice",
        "git_object": "97c5c9144a86b7d4e4c09b9e75f23627337b5caf"
      },
      {
        "path": "pyproject.toml",
        "git_object": "72433509ffdfa8d057c6ba21cbe40bf61b55c08d"
      }
    ],
    "runtime_objects": [
      {
        "path": "benchmarks/__init__.py",
        "git_object": "830b6bddff5731d650221c25c60409dfb547d46f"
      },
      {
        "path": "benchmarks/product_baseline.py",
        "git_object": "c68b828df7e73491d3f085d8e1387b2d7dd5fe17"
      },
      {
        "path": "benchmarks/product_baseline_experiment.py",
        "git_object": "d05232c6492e069273347ba7423e94ac8fa6a5f4"
      },
      {
        "path": "benchmarks/product_baseline_server.py",
        "git_object": "819395806e6098fcbf814d590756c80d6c370357"
      }
    ]
  },
  "design": {
    "formal_research_runs": 3,
    "execution_mode": "serial-concurrency-1",
    "case_order": [
      "P04",
      "P01",
      "P08"
    ],
    "holdout_access": "forbidden",
    "historical_baseline_use": "diagnostic-context-only-not-a-same-window-pair",
    "no_ad_hoc_reruns": true,
    "blind_labels": [
      "SC2-01",
      "SC2-02",
      "SC2-03"
    ],
    "hitl_policy": {
      "mode": "case-specific-p01-p04-stop-p08-auto-v1",
      "cases": {
        "P01": {
          "stop_at_hitl": true,
          "max_auto_resolutions": 0
        },
        "P04": {
          "stop_at_hitl": true,
          "max_auto_resolutions": 0
        },
        "P08": {
          "stop_at_hitl": false,
          "max_auto_resolutions": 2
        }
      }
    }
  },
  "budgets": {
    "research_ledger": {
      "starting_used": 103,
      "diagnostic_max": 3,
      "concurrency_reserve": 0,
      "unallocated": 50,
      "hard_total": 156
    }
  },
  "acceptance": {
    "collection": "all-three-cases-have-queryable-terminal-report-and-complete-observability",
    "p04": "four-isolated-stages-with-task-reconciliation-fault-matrix-idempotency-advance-abort-and-no-unsafe-rollback",
    "p01": "conditional-choice-writer-backup-and-measurable-migration-boundaries-no-invented-workload",
    "p08": "conditional-choice-preserved-no-paste-evidence-or-title-rebinding",
    "citation": "inspect-source-language-applicability-and-chinese-usability-no-verified-count-as-quality-pass",
    "interpretation_limit": "diagnostic-product-feedback-only-no-causal-improvement-claim"
  },
  "control_predecessor": {
    "protocol_id": "product-optimization-serial-check-v1",
    "protocol_byte_sha256": "77b2efce9df2a8ed18b40489b7f569d85159b6d1247c976306cc8550af1e55f5",
    "artifacts": {
      "execution_binding": {
        "path": "outputs/product-optimization-serial-check-v1-20260927-v1/execution-binding.json",
        "sha256": "207fd198dfc483ed00ca04ef4fb3684e998844649252ef275cc8c831633ad37f"
      },
      "execution_claim": {
        "path": "outputs/product-optimization-ledgers/product-optimization-serial-check-v1/execution-claim.json",
        "sha256": "2a1d50630371e75639d9954257280e99b8d110dab9ffdf1221b02fd6e83e3edd"
      },
      "cell_p04": {
        "path": "outputs/product-optimization-ledgers/product-optimization-serial-check-v1/cells/candidate-r1-P04.json",
        "sha256": "2635c0bb85ea1afb7fb1148dadd0e51b73670ffafea8d01d04bad68d1becfd69"
      },
      "cell_p01": {
        "path": "outputs/product-optimization-ledgers/product-optimization-serial-check-v1/cells/candidate-r1-P01.json",
        "sha256": "430b88a437621a551974280c983eed52845a994ea99493662a18a116e5540a85"
      },
      "cell_p08": {
        "path": "outputs/product-optimization-ledgers/product-optimization-serial-check-v1/cells/candidate-r1-P08.json",
        "sha256": "6667f02337c68ecad62c32c2ce667c9c995bde1b10bd8a8883a08f4dfa41ccbe"
      },
      "observations": {
        "path": "outputs/product-optimization-ledgers/product-optimization-serial-check-v1/observations.jsonl",
        "sha256": "e9977bed67d44eb0fe6aa08334d2c35c0163cf233087694c35f41d9a90d3960a"
      },
      "run_result": {
        "path": "outputs/product-optimization-serial-check-v1-20260927-v1/serial-check-run-result.json",
        "sha256": "513591b77a49cc9b8b01dab59a71e328b6925b3de7d8f289f990bdf30db89662"
      },
      "collection_record": {
        "path": "outputs/product-optimization-serial-check-v1-20260927-v1/collections/candidate-r1/runs.jsonl",
        "sha256": "460df8ff70cc68c4748e2f58968d798ff221e646bc995a2b38c2d4b43d0efeb8"
      },
      "telemetry": {
        "path": "outputs/product-optimization-serial-check-v1-20260927-v1/arms/candidate/r1/control/telemetry.jsonl",
        "sha256": "dd194678a4f6df930942f6d031cd9558837ad0acdd2f1e9ce70bb363351c74a7"
      }
    },
    "accounted_research_runs": 3,
    "disposition": "immutable-no-retry-no-splice"
  },
  "authorization": {
    "status": "approved-existing-cap",
    "decision_date": "2026-09-27",
    "current_hard_total": 156,
    "effective_hard_total": 156,
    "diagnostic_max": 3,
    "concurrency_runs_authorized": 0,
    "deferred_unallocated": 50,
    "preserve_acceptance_thresholds": true
  }
}''')


def _parent_raw() -> dict:
    if parent._file_sha256(parent.PROTOCOL_PATH) != BASE_SHA256:
        raise SerialCheckProtocolError("parent protocol identity drift")
    return json.loads(parent.PROTOCOL_PATH.read_text(encoding="utf-8"))


def _expected_raw() -> dict:
    raw = _parent_raw()
    raw.update(deepcopy(_OVERRIDES))
    raw["controller"]["binding_policy"] = "candidate-only-three-case-over-serial-v1-v2"
    raw["controller"]["research_admission"] = CLOSED
    raw["controller"]["required_files"] = [
        {"path": path, "sha256": parent._file_sha256(ROOT / path)}
        for path in NEW_CONTROL_PATHS
    ] + raw["controller"]["required_files"]
    return raw


def _validate_raw(raw: dict) -> None:
    # Canonical equality also rejects bool/int substitutions and extra fields.
    expected = _expected_raw()
    mode = raw.get("controller", {}).get("research_admission") if isinstance(raw, dict) else None
    if mode not in (CLOSED, OPEN):
        raise SerialCheckProtocolError("v2 admission contract drift")
    # Activation changes frozen bytes and therefore requires a new external SHA,
    # audit and preflight binding. Merely passing CLI paid flags cannot activate.
    expected["controller"]["research_admission"] = mode
    if json.dumps(raw, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise SerialCheckProtocolError("v2 frozen protocol contract drift")
    card = raw["design_card"]
    if parent._file_sha256(ROOT / card["path"]) != card["sha256"]:
        raise SerialCheckProtocolError("frozen measurement design drift")


def load_serial_check_protocol(path: Path = PROTOCOL_PATH) -> parent.SerialCheckProtocol:
    if path != PROTOCOL_PATH or not path.is_absolute():
        raise SerialCheckProtocolError("protocol path is not approved")
    try:
        data = path.read_bytes()
        raw = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SerialCheckProtocolError("protocol could not be loaded") from None
    _validate_raw(raw)
    base = parent.load_serial_check_protocol()
    payload = deepcopy(base.payload)
    for name in ("protocol_id", "controller", "budgets", "acceptance",
                 "control_predecessor", "authorization", "design_card"):
        if name == "budgets":
            payload[name]["research_ledger"] = deepcopy(raw[name]["research_ledger"])
        else:
            payload[name] = deepcopy(raw[name])
    payload["identities"]["candidate"] = deepcopy(raw["candidate"])
    for row, label in zip(payload["design"]["blind_review_order"],
                          raw["design"]["blind_labels"], strict=True):
        row["blind_label"] = label
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return parent.SerialCheckProtocol(
        payload, hashlib.sha256(data).hexdigest(), hashlib.sha256(canonical).hexdigest(),
    )
