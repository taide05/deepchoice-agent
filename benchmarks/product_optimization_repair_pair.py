"""Strict offline contract for the approved 12-cell repair-package pair.

The loader reads only the tracked protocol, the development-only request
projection, Git object identities, and fixed seed metadata.  It never opens the
full benchmark dataset, reports, snapshots, captures, or holdout material and
performs no network/model/research call.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from benchmarks.product_optimization_dev_requests import (
    EXPECTED_CASE_IDS,
    FIXTURE_BYTES_SHA256,
    FIXTURE_ID,
    load_dev_requests,
)


ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "benchmarks" / "product-optimization-repair-pair-v4.json"
PROTOCOL_ID = "product-optimization-repair-pair-v4"
PARENT_DATASET_SHA256 = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
PARENT_DATASET_BYTES_SHA256 = "d732434d1ae2e01a14b62cfe7b92499dd584703676d0caff17fe4510f647f7ef"
PARENT_DATASET_GIT_OBJECT = "da14cf6d72ed528eef3510f48f78116288c3964a"
BASELINE_COMMIT = "d23c9480b9f368f8ec75ec44ee7e25c64146d4be"
CANDIDATE_COMMIT = "d7e776dffced8d1ddb90d03b924b1217ea766ddb"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")


class RepairPairProtocolError(ValueError):
    """Raised when the frozen local-effect protocol drifts."""


@dataclass(frozen=True, slots=True)
class RepairPairProtocol:
    payload: dict[str, Any]
    byte_sha256: str
    canonical_sha256: str


def _fail(message: str) -> "Any":
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


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _fail(f"{label} fields changed")
    return value


def _git_object(commit: str, path: str, *, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", f"{commit}:{path}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise RepairPairProtocolError("frozen Git object is unavailable") from None
    if _GIT_OBJECT.fullmatch(result) is None:
        _fail("frozen Git object identity is invalid")
    return result


def _validate_product_identity(name: str, value: Any) -> None:
    identity = _exact(
        value,
        {"anchor_commit", "source_objects", "runtime_objects"},
        f"{name} identity",
    )
    expected_commit = BASELINE_COMMIT if name == "baseline" else CANDIDATE_COMMIT
    if identity["anchor_commit"] != expected_commit:
        _fail(f"{name} commit changed")
    objects = identity["source_objects"]
    if not isinstance(objects, list) or [item.get("path") for item in objects] != [
        "src/deepchoice",
        "pyproject.toml",
    ]:
        _fail(f"{name} source object paths changed")
    for item in objects:
        _exact(item, {"path", "git_object"}, f"{name} source object")
        if _GIT_OBJECT.fullmatch(item["git_object"]) is None:
            _fail(f"{name} source object SHA is invalid")
        if _git_object(expected_commit, item["path"]) != item["git_object"]:
            _fail(f"{name} source object changed")
    runtime_objects = identity["runtime_objects"]
    expected_runtime_paths = [
        "benchmarks/__init__.py",
        "benchmarks/product_baseline.py",
        "benchmarks/product_baseline_experiment.py",
        "benchmarks/product_baseline_server.py",
    ]
    if (not isinstance(runtime_objects, list)
            or [item.get("path") for item in runtime_objects]
            != expected_runtime_paths):
        _fail(f"{name} runtime object paths changed")
    for item in runtime_objects:
        _exact(item, {"path", "git_object"}, f"{name} runtime object")
        if (_GIT_OBJECT.fullmatch(item["git_object"]) is None
                or _git_object(expected_commit, item["path"])
                != item["git_object"]):
            _fail(f"{name} runtime object changed")


def _expected_execution_blocks() -> list[dict[str, Any]]:
    return [
        {"block": 1, "arm": "baseline", "repetition": 2, "case_order": ["P04", "P01", "P08"]},
        {"block": 2, "arm": "candidate", "repetition": 2, "case_order": ["P04", "P08", "P01"]},
        {"block": 3, "arm": "candidate", "repetition": 1, "case_order": ["P04", "P08", "P01"]},
        {"block": 4, "arm": "baseline", "repetition": 1, "case_order": ["P04", "P08", "P01"]},
    ]


def _validate_design(value: Any) -> None:
    design = _exact(
        value,
        {
            "formal_research_runs",
            "profile",
            "concurrency",
            "same_window_days",
            "independent_single_case_qualification",
            "paired_p01_replaces_qualification",
            "no_ad_hoc_reruns",
            "execution_blocks",
            "blind_review_order",
        },
        "design",
    )
    if {
        key: design[key]
        for key in (
            "formal_research_runs",
            "profile",
            "concurrency",
            "same_window_days",
            "independent_single_case_qualification",
            "paired_p01_replaces_qualification",
            "no_ad_hoc_reruns",
        )
    } != {
        "formal_research_runs": 12,
        "profile": "serial",
        "concurrency": 1,
        "same_window_days": 7,
        "independent_single_case_qualification": False,
        "paired_p01_replaces_qualification": True,
        "no_ad_hoc_reruns": True,
    } or design["execution_blocks"] != _expected_execution_blocks():
        _fail("execution design changed")
    review = design["blind_review_order"]
    expected_cells = {
        (case_id, arm, repetition)
        for case_id in EXPECTED_CASE_IDS
        for arm in ("baseline", "candidate")
        for repetition in (1, 2)
    }
    if (
        not isinstance(review, list)
        or len(review) != 12
        or {(item.get("case_id"), item.get("arm"), item.get("repetition")) for item in review}
        != expected_cells
        or [item.get("order") for item in review] != list(range(1, 13))
        or [item.get("blind_label") for item in review]
        != [f"RP4-{index:02d}" for index in range(1, 13)]
        or any(
            set(item) != {"case_id", "role", "arm", "repetition", "order", "blind_label"}
            or item.get("role") != ("regression" if item.get("case_id") == "P01" else "target")
            for item in review
        )
    ):
        _fail("blind review order changed")


def _validate_protocol(payload: Any) -> None:
    protocol = _exact(
        payload,
        {
            "schema_version",
            "protocol_id",
            "status",
            "freeze_date",
            "question",
            "interpretation",
            "dataset",
            "identities",
            "knowledge_seed",
            "controller",
            "design",
            "environment",
            "budgets",
            "review",
            "acceptance",
            "stopping",
            "predecessor",
            "immediate_predecessor",
            "latest_predecessor",
            "authorization",
        },
        "protocol",
    )
    if (
        protocol["schema_version"] != 1
        or protocol["protocol_id"] != PROTOCOL_ID
        or protocol["status"] not in {"proposed", "frozen"}
        or (
            protocol["freeze_date"] is not None
            and protocol["freeze_date"] != "2026-09-26"
        )
        or protocol["interpretation"] != "whole-repair-package-local-effect-only"
    ):
        _fail("protocol identity changed")
    dataset = _exact(
        protocol["dataset"],
        {
            "parent_dataset_id",
            "parent_version",
            "parent_sha256",
            "parent_bytes_sha256",
            "parent_git_object",
            "development_projection_id",
            "development_projection_sha256",
            "case_ids",
            "roles",
            "holdout_access",
        },
        "dataset",
    )
    if dataset != {
        "parent_dataset_id": "product-baseline-v1",
        "parent_version": "1.0.0",
        "parent_sha256": PARENT_DATASET_SHA256,
        "parent_bytes_sha256": PARENT_DATASET_BYTES_SHA256,
        "parent_git_object": PARENT_DATASET_GIT_OBJECT,
        "development_projection_id": FIXTURE_ID,
        "development_projection_sha256": FIXTURE_BYTES_SHA256,
        "case_ids": list(EXPECTED_CASE_IDS),
        "roles": {"P01": "regression", "P04": "target", "P08": "target"},
        "holdout_access": "forbidden",
    }:
        _fail("dataset binding changed")
    if (_git_object(CANDIDATE_COMMIT, "benchmarks/product-baseline-v1.json")
            != PARENT_DATASET_GIT_OBJECT):
        _fail("parent dataset Git identity changed")
    fixture = load_dev_requests()
    if fixture.byte_sha256 != FIXTURE_BYTES_SHA256:
        _fail("development projection identity changed")
    identities = _exact(protocol["identities"], {"baseline", "candidate"}, "identities")
    _validate_product_identity("baseline", identities["baseline"])
    _validate_product_identity("candidate", identities["candidate"])
    seed = _exact(
        protocol["knowledge_seed"],
        {
            "seed_id",
            "logical_identity_sha256",
            "artifact_tree_sha256",
            "manifest_sha256",
            "admission_identity_sha256",
            "embedding_sha256",
            "copy_policy",
            "read_only_learned_docs",
            "legacy_seed_access",
        },
        "knowledge seed",
    )
    if (
        any(_SHA256.fullmatch(seed[key]) is None for key in (
            "logical_identity_sha256", "artifact_tree_sha256", "manifest_sha256",
            "admission_identity_sha256", "embedding_sha256"
        ))
        or seed["copy_policy"] != "byte-exact-independent-per-arm-repetition-v1"
        or seed["read_only_learned_docs"] is not True
        or seed["legacy_seed_access"] != "forbidden"
    ):
        _fail("knowledge seed policy changed")
    controller = _exact(
        protocol["controller"],
        {"binding_policy", "required_files", "research_admission"},
        "controller",
    )
    if (
        controller["binding_policy"] != "protocol-plus-execution-binding-v1"
        or controller["research_admission"] not in {
            "closed-pending-hard-cap-approval",
            "open-after-offline-runner-acceptance",
        }
        or not isinstance(controller["required_files"], list)
    ):
        _fail("controller policy changed")
    expected_controller_paths = [
        "scripts/product_optimization_repair_pair.py",
        "scripts/o1_pr2b_child.py",
        "scripts/o1_pr2b_control.py",
        "benchmarks/product_optimization_repair_pair.py",
        "benchmarks/product_optimization_dev_requests.py",
        "benchmarks/product-optimization-dev-requests-v1.json",
        "benchmarks/__init__.py",
        "benchmarks/product_baseline.py",
        "benchmarks/product_baseline_qualification.py",
        "benchmarks/product_baseline_experiment.py",
        "benchmarks/product_baseline_server.py",
    ]
    if [item.get("path") for item in controller["required_files"]] != expected_controller_paths:
        _fail("controller TCB file set changed")
    for item in controller["required_files"]:
        _exact(item, {"path", "sha256"}, "controller file")
        if _SHA256.fullmatch(item["sha256"]) is None:
            _fail("controller file SHA is invalid")
        path = ROOT / item["path"]
        if not path.is_file():
            _fail("required controller file is unavailable")
        if _file_sha256(path) != item["sha256"]:
            _fail("controller file identity changed")
    _validate_design(protocol["design"])
    expected_environment = {
        "provider": "deepseek-flash", "model": "deepseek-v4-flash",
        "endpoint_sha256": "12b8deaccc34b32757dbb1497e029da0c2e7b26ffa86b9c926c08cb4692f4508",
        "configuration_sha256": "4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474",
        "safe_fetch_proxy_sha256": "813477bf51a0efb3b5926c3759f01d02cdf25cd70e6cfc7fa186d9d5e1e1d118",
        "thinking": "disabled", "embedding_model": "BAAI/bge-m3",
        "embedding_revision": "5617a9f61b028005a4858fdac845db406aefb181",
        "durable_api": True, "isolated_product_and_checkpoint_databases": True,
        "auto_recovery": False, "fresh_runtime_per_arm_repetition": True,
        "hitl_mode": "stop-at-hitl-no-auto-resolution",
    }
    if protocol["environment"] != expected_environment:
        _fail("environment contract changed")
    budgets = protocol["budgets"]
    if budgets != {
        "research_ledger": {"starting_used": 95, "local_pair_max": 12,
                            "final_concurrency_reserve": 48, "hard_total": 155,
                            "unallocated": 0},
        "per_run": {"total_tokens": 60000, "llm_calls": 96,
                    "retrieval_calls": 72, "active_milliseconds": 900000},
        "prerequisite_max": {"non_llm_http_attempts": 20,
                             "tavily_post_attempts": 1,
                             "llm_http_attempts": 4, "research_runs": 0},
    }:
        _fail("budget contract changed")
    if protocol["review"] != {
        "mode": "gpt-only-independent-blind-v1", "score_before_trace": True,
        "rubric": "key-claim-occurrence-v1",
        "severity_frozen_from": "product-optimization-s0",
        "major_and_claimed_improvement_second_review": True,
        "human_calibration": "not_required-by-user",
        "do_not_call_human_acceptance": True,
    }:
        _fail("review contract changed")
    if protocol["acceptance"] != {
        "targets": {"case_ids": ["P04", "P08"],
                    "each_repetition_candidate_strictly_better_than_baseline": True,
                    "candidate_major_errors": 0,
                    "candidate_must_answer_zero_count": 0},
        "regression": {"case_id": "P01", "candidate_decision_not_lower": True,
                       "candidate_citation_support_not_lower": True,
                       "candidate_report_completion_not_lower": True,
                       "candidate_no_new_major_errors": True},
        "efficiency_claim": {"minimum_median_reduction_fraction": 0.15,
                             "quality_and_completion_not_lower": True,
                             "complete_usage_required": True},
        "interpretation_limit": "local-three-case-repair-package-effect-only",
    }:
        _fail("acceptance contract changed")
    if protocol["stopping"] != {
        "identity_environment_seed_or_controller_drift": "stop-before-admission",
        "retrieval_rate_limit_safety_budget_lease_or_unknown": "stop-new-admission",
        "known_citation_policy_or_transport_unknown":
            "continue-if-terminal-and-source-gates-pass",
        "bounded_citation_response_stream_unknown":
            "continue-if-dispatch-entered-terminal-and-source-gates-pass",
        "unclassified_external_or_safe_fetch_error": "stop-new-admission",
        "ordinary_citation_http_5xx": "stop-new-admission",
        "finish_already_admitted_run": True,
        "replace_retry_or_splice_stopped_roots": False,
        "next_paid_stop_without_valid_pair": "return-to-measurement-review",
    }:
        _fail("stopping contract changed")
    if protocol["predecessor"] != {
        "protocol_id": "product-optimization-repair-pair-v1",
        "protocol_byte_sha256": "66676f58b19e186cef765481ccc7ac770a316b29511cb9380cccf0ad6bf3e51b",
        "artifacts": {
            "execution_claim": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v1/execution-claim.json",
                "sha256": "d831d9fe7d2bc6a76d2fedebd259e55826a9dc7f452768aaae1fe7505335e331",
            },
            "attempted_cell": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v1/cells/baseline-r2-P04.json",
                "sha256": "0554ea6320700443d17734bbb166130ab2ae39a46607246f1ff4649444aebe7b",
            },
            "run_result": {
                "path": "outputs/product-optimization-repair-pair-20260925-v1/repair-pair-run-result.json",
                "sha256": "c7d92f9ef72b07a6f2f3068736f8ab41be81fc137cd4c704100f95e678770a86",
            },
        },
        "accounted_research_runs": 1,
        "external_calls": 0,
        "disposition": "immutable-no-retry-no-splice",
    }:
        _fail("predecessor execution binding changed")
    authorization = protocol["authorization"]
    if authorization not in ({
        "status": "pending",
        "decision_date": None,
        "current_hard_total": 154,
        "proposed_hard_total": 155,
        "effective_hard_total": 154,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "preserve_acceptance_thresholds": True,
    }, {
        "status": "approved",
        "decision_date": "2026-09-26",
        "current_hard_total": 154,
        "proposed_hard_total": 155,
        "effective_hard_total": 155,
        "local_pair_max": 12,
        "final_concurrency_reserve": 48,
        "preserve_acceptance_thresholds": True,
    }):
        _fail("measurement authorization changed")
    pending = authorization["status"] == "pending"
    if (
        pending
        and (
            protocol["status"] != "proposed"
            or protocol["freeze_date"] is not None
            or controller["research_admission"]
            != "closed-pending-hard-cap-approval"
        )
    ) or (
        not pending
        and (
            protocol["status"] != "frozen"
            or protocol["freeze_date"] != "2026-09-26"
            or controller["research_admission"]
            != "open-after-offline-runner-acceptance"
        )
    ):
        _fail("protocol activation state changed")
    if protocol["immediate_predecessor"] != {
        "protocol_id": "product-optimization-repair-pair-v2",
        "protocol_byte_sha256": "404ff295d0a66fdbaab610f96b6b85a6a0b1bcdebc6c588fd9475975b00e7117",
        "artifacts": {
            "execution_claim": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v2/execution-claim.json",
                "sha256": "4f77600f1e86f9eecf7332cb04249a8b1e65660386ec823ef8589631ae93c270",
            },
            "attempted_cell": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v2/cells/baseline-r2-P04.json",
                "sha256": "bde2aedf88c33d02404ec4b4d9f586e483fbb351a801ee595e9adc8fc009c9a7",
            },
            "observation": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v2/observations.jsonl",
                "sha256": "c991d96d6d6077b2a10fd1d31980b1faeaee7765392a05b4f33abe0b66a25fe6",
            },
            "run_result": {
                "path": "outputs/product-optimization-repair-pair-v2-20260925-v1/repair-pair-run-result.json",
                "sha256": "2c8cfe8facb0b79cabffe78757bee40979e2ae74e3ac82b645ebd5c4042b7f34",
            },
        },
        "accounted_research_runs": 1,
        "trace_external_calls": 14,
        "disposition": "immutable-no-retry-no-splice",
    }:
        _fail("immediate predecessor execution binding changed")
    if protocol["latest_predecessor"] != {
        "protocol_id": "product-optimization-repair-pair-v3",
        "protocol_byte_sha256": "47bfeffa01893b6077a480b06dd6ff4254d6c121d110614747a3fc2f9db9c268",
        "artifacts": {
            "execution_claim": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v3/execution-claim.json",
                "sha256": "97b8ff04d8b8d1d4554625914f07de04617bb9cfef9fff9d0e119941941d1f56",
            },
            "attempted_cell": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v3/cells/baseline-r2-P04.json",
                "sha256": "3468896e934298d49d9db2faeb56d605af318e48fb038da7b9a870daf89ed7fb",
            },
            "observation": {
                "path": "outputs/product-optimization-ledgers/product-optimization-repair-pair-v3/observations.jsonl",
                "sha256": "43fdd654c103b39c7dd05a8daab9fefc6fc6760d82b248861449dc3044040c15",
            },
            "run_result": {
                "path": "outputs/product-optimization-repair-pair-v3-20260925-v1/repair-pair-run-result.json",
                "sha256": "2dcb6d5fcb1d61feff0ef349095ef081ec161bac4f3b970e614abb9c963ead7f",
            },
        },
        "accounted_research_runs": 1,
        "trace_external_calls": 18,
        "disposition": "immutable-no-retry-no-splice",
    }:
        _fail("latest predecessor execution binding changed")


def load_repair_pair_protocol(path: Path = PROTOCOL_PATH) -> RepairPairProtocol:
    if path != PROTOCOL_PATH or not path.is_absolute():
        _fail("protocol path is not approved")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RepairPairProtocolError("protocol could not be loaded") from None
    byte_sha = hashlib.sha256(raw).hexdigest()
    _validate_protocol(payload)
    return RepairPairProtocol(
        payload=payload,
        byte_sha256=byte_sha,
        canonical_sha256=_canonical_sha256(payload),
    )


__all__ = [
    "RepairPairProtocol",
    "RepairPairProtocolError",
    "load_repair_pair_protocol",
]
