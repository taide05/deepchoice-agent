"""Offline validation for the frozen S1 local-effect measurement protocol.

This module performs no network, model, health, or research calls. It binds
the experiment before any paid prerequisite or research admission is allowed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from benchmarks.product_baseline import load_dataset


ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "benchmarks" / "product-optimization-s1-constraint-aware-v1.json"
PROTOCOL_ID = "product-optimization-s1-constraint-aware-v1"
DATASET_SHA256 = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
BASELINE_COMMIT = "d23c9480b9f368f8ec75ec44ee7e25c64146d4be"
CANDIDATE_COMMIT = "bcb4c8732e94b5aac4a3645b7d5d682279e2dad0"
CONTROLLER_COMMIT = "7d16d2892c22ce5e4940caa1ee8009148f76917b"
PRODUCT_PATHS = ("src/deepchoice", "pyproject.toml")
CONTROLLER_PATHS = (
    "benchmarks/product_baseline.py",
    "benchmarks/product_baseline_qualification.py",
    "benchmarks/product_baseline_experiment.py",
    "benchmarks/product_baseline_server.py",
    "benchmarks/product_baseline_preflight.py",
)
CASES = {"P01": "regression", "P04": "target", "P08": "target"}
ARMS = ("baseline", "candidate")
REPETITIONS = (1, 2)
ORDER_SEED = 20260922
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def protocol_sha256(protocol: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(protocol)).hexdigest()


def build_schedule(seed: int = ORDER_SEED) -> list[dict[str, Any]]:
    cells = [
        {"case_id": case_id, "role": role, "arm": arm, "repetition": repetition}
        for repetition in REPETITIONS
        for case_id, role in CASES.items()
        for arm in ARMS
    ]
    cells.sort(
        key=lambda cell: hashlib.sha256(
            f"{seed}:{cell['case_id']}:{cell['arm']}:{cell['repetition']}".encode(
                "ascii"
            )
        ).hexdigest()
    )
    return [
        {**cell, "order": index, "blind_label": f"S1-{index:02d}"}
        for index, cell in enumerate(cells, start=1)
    ]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _git_object(commit: str, path: str) -> str:
    value = _git("rev-parse", f"{commit}:{path}")
    if HEX40.fullmatch(value) is None:
        raise ValueError(f"invalid Git object for {commit}:{path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_identity(
    identity: dict[str, Any],
    *,
    expected_commit: str,
    expected_paths: tuple[str, ...],
    verify_repository: bool,
) -> None:
    _require(
        set(identity) == {"anchor_commit", "source_objects"},
        "identity must contain only anchor_commit and source_objects",
    )
    commit = identity.get("anchor_commit")
    _require(
        commit == expected_commit and HEX40.fullmatch(commit) is not None,
        "identity commit drift",
    )
    objects = identity.get("source_objects")
    _require(isinstance(objects, list), "source_objects must be a list")
    _require(
        [item.get("path") for item in objects if isinstance(item, dict)]
        == list(expected_paths),
        "identity source path drift",
    )
    for item in objects:
        _require(
            set(item) == {"path", "git_object"}
            and HEX40.fullmatch(item.get("git_object", "")) is not None,
            "invalid source object",
        )
        if verify_repository:
            _require(
                _git_object(commit, item["path"]) == item["git_object"],
                f"source object drift: {item['path']}",
            )


def _validate_repository_readiness(
    protocol: dict[str, Any], execution_arm: str, execution_ref: str
) -> None:
    _require(execution_arm in ARMS, "execution arm must be baseline or candidate")
    product = protocol["identities"][execution_arm]
    controller = protocol["identities"]["controller"]
    for item in product["source_objects"]:
        _require(
            _git_object(execution_ref, item["path"]) == item["git_object"],
            f"{execution_ref} product source differs from frozen {execution_arm}: {item['path']}",
        )
    for item in controller["source_objects"]:
        _require(
            _git_object(execution_ref, item["path"]) == item["git_object"],
            f"{execution_ref} controller source differs from frozen controller: {item['path']}",
        )
    if execution_ref == "HEAD":
        guarded_paths = [*PRODUCT_PATHS, *CONTROLLER_PATHS]
        _require(
            not _git(
                "status", "--porcelain", "--untracked-files=all", "--", *guarded_paths
            ),
            "frozen product/controller paths have uncommitted changes",
        )


def load_protocol(
    path: Path = PROTOCOL_PATH,
    *,
    verify_repository: bool = True,
    execution_arm: str = "candidate",
    execution_ref: str = "HEAD",
) -> tuple[dict[str, Any], str]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(protocol, dict), "protocol root must be an object")
    _require(
        set(protocol)
        == {
            "schema_version",
            "protocol_id",
            "status",
            "freeze_date",
            "scope",
            "dataset",
            "identities",
            "qualification",
            "design",
            "environment",
            "budgets",
            "review",
            "acceptance",
            "stopping",
        },
        "protocol top-level fields drift",
    )
    _require(protocol["schema_version"] == 1, "unsupported protocol schema")
    _require(protocol["protocol_id"] == PROTOCOL_ID, "unexpected protocol id")
    _require(protocol["status"] == "frozen", "protocol must be frozen")
    _require(protocol["freeze_date"] == "2026-09-22", "protocol freeze date drift")

    scope = protocol["scope"]
    _require(
        scope
        == {
            "primary_variable": "constraint-aware-conclusion",
            "claim": "three-case-local-effect-only",
            "holdout_reports_or_feedback_accessed": False,
            "excluded_claims": [
                "full-development-set-quality",
                "holdout-quality",
                "human-calibrated-acceptance",
                "concurrency-qualification",
                "global-product-improvement",
            ],
        },
        "scope or excluded claims drift",
    )

    dataset_spec = protocol["dataset"]
    _require(
        dataset_spec
        == {
            "path": "benchmarks/product-baseline-v1.json",
            "dataset_id": "product-baseline-v1",
            "version": "1.0.0",
            "sha256": DATASET_SHA256,
            "cases": [
                {"id": "P01", "role": "regression"},
                {"id": "P04", "role": "target"},
                {"id": "P08", "role": "target"},
            ],
        },
        "dataset identity or case set drift",
    )
    dataset, dataset_hash = load_dataset(
        ROOT / dataset_spec["path"], require_frozen=True
    )
    _require(dataset_hash == DATASET_SHA256, "dataset content drift")
    available = {case["id"]: case["split"] for case in dataset["cases"]}
    _require(
        all(available[case_id] == "development" for case_id in CASES),
        "S1 cases must be development cases",
    )

    identities = protocol["identities"]
    _require(
        set(identities) == {"baseline", "candidate", "controller"},
        "identity roles drift",
    )
    for name, commit, paths in (
        ("baseline", BASELINE_COMMIT, PRODUCT_PATHS),
        ("candidate", CANDIDATE_COMMIT, PRODUCT_PATHS),
        ("controller", CONTROLLER_COMMIT, CONTROLLER_PATHS),
    ):
        _validate_identity(
            identities[name],
            expected_commit=commit,
            expected_paths=paths,
            verify_repository=verify_repository,
        )
    _require(
        identities["baseline"]["source_objects"]
        != identities["candidate"]["source_objects"],
        "baseline and candidate product identities must differ",
    )

    _require(
        protocol["qualification"]
        == {
            "required_for": "candidate",
            "case_id": "P01",
            "max_research_runs": 1,
            "mode": "single-admission-v1",
            "profile": "serial",
            "concurrency": 1,
            "repetition": 1,
            "hitl_mode": "stop-at-hitl",
            "must_pass_before_formal": True,
        },
        "qualification contract drift",
    )

    design = protocol["design"]
    _require(
        design
        == {
            "formal_research_runs": 12,
            "profile": "serial",
            "concurrency": 1,
            "same_window_days": 7,
            "order_seed": ORDER_SEED,
            "no_ad_hoc_reruns": True,
            "schedule": build_schedule(),
        },
        "formal design or schedule drift",
    )

    environment = protocol["environment"]
    _require(
        environment
        == {
            "only_arm_difference": "product_identity",
            "durable_api_only": True,
            "fresh_database_pair_per_cell": True,
            "same_model_dependencies_knowledge_budgets_hitl": True,
            "cache_enabled": True,
            "single_instance_single_worker": True,
            "thinking": "disabled",
            "raw_outputs_local_only": True,
        },
        "paired environment drift",
    )

    budgets = protocol["budgets"]
    _require(
        set(budgets) == {"research_ledger", "per_run", "prerequisite_max"},
        "budget fields drift",
    )
    _require(
        budgets.get("research_ledger")
        == {
            "starting_used": 90,
            "hard_cap": 134,
            "qualification_max": 1,
            "formal": 12,
            "projected_used": 103,
            "reserved_for_s3": 24,
            "unallocated_after_reserve": 7,
        },
        "research ledger drift",
    )
    _require(
        budgets.get("per_run")
        == {
            "total_tokens": 60000,
            "llm_calls": 96,
            "retrieval_calls": 72,
            "active_milliseconds": 900000,
            "soft_warning_fraction": 0.8,
        },
        "per-run budget drift",
    )
    _require(
        budgets.get("prerequisite_max")
        == {
            "research_runs": 0,
            "http_attempts": 20,
            "tavily_posts": 1,
            "llm_attempts": 4,
        },
        "prerequisite budget drift",
    )

    review = protocol["review"]
    _require(
        review
        == {
            "policy": "key-claim-occurrence-v1",
            "blind_labels": True,
            "blind_mapping_access": "execution-controller-only-until-score-lock",
            "lock_scores_before_trace": True,
            "llm_judge": "none",
            "human_calibration": "not_run",
            "holdout_reports_accessed": False,
            "independent_basis_required_for": [
                "major-errors",
                "disputed-citations",
                "claimed-improvements",
            ],
        },
        "review or blinding policy drift",
    )

    acceptance = protocol["acceptance"]
    _require(
        set(acceptance)
        == {
            "primary_metric",
            "targets",
            "regression",
            "result_scope",
            "failure_outcome",
        },
        "acceptance fields drift",
    )
    _require(
        acceptance.get("primary_metric") == "decision_rubric_fraction",
        "primary metric drift",
    )
    _require(
        acceptance.get("targets")
        == {
            "case_ids": ["P04", "P08"],
            "each_repetition_candidate_strictly_better_than_baseline": True,
            "candidate_major_errors": 0,
            "candidate_must_answer_zero_count": 0,
        },
        "target acceptance drift",
    )
    _require(
        acceptance.get("regression")
        == {
            "case_id": "P01",
            "candidate_decision_not_lower": True,
            "candidate_citation_support_not_lower": True,
            "candidate_report_completion_not_lower": True,
            "candidate_no_new_major_errors": True,
        },
        "regression acceptance drift",
    )
    _require(
        acceptance.get("result_scope") == "local-effect-only",
        "result scope drift",
    )
    _require(
        acceptance.get("failure_outcome")
        == "close-or-revise-hypothesis-without-case-switching",
        "failure outcome drift",
    )

    stopping = protocol["stopping"]
    _require(
        stopping
        == {
            "identity_or_environment_drift": "stop-before-admission",
            "qualification_failure": "stop-before-formal",
            "ordinary_citation_http_5xx": "stop-new-admission",
            "safety_budget_lease_rate_limit_unknown": "stop-new-admission",
            "two_paid_stops_without_valid_pair": "revisit-measurement-design",
            "replace_or_splice_stopped_roots": False,
            "finish_already_admitted_runs": True,
            "preserve_all_admitted_denominators": True,
        },
        "stop policy drift",
    )

    if verify_repository:
        _validate_repository_readiness(protocol, execution_arm, execution_ref)
    return protocol, protocol_sha256(protocol)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the frozen S1 measurement protocol offline"
    )
    parser.add_argument("--protocol", default=str(PROTOCOL_PATH))
    parser.add_argument("--execution-arm", choices=ARMS, default="candidate")
    parser.add_argument("--execution-ref", default="HEAD")
    parser.add_argument("--skip-repository-checks", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        protocol, digest = load_protocol(
            Path(args.protocol),
            verify_repository=not args.skip_repository_checks,
            execution_arm=args.execution_arm,
            execution_ref=args.execution_ref,
        )
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        print(f"protocol validation failed: {exc}")
        return 2
    print(
        json.dumps(
            {
                "protocol_id": protocol["protocol_id"],
                "status": protocol["status"],
                "sha256": digest,
                "formal_research_runs": protocol["design"][
                    "formal_research_runs"
                ],
                "qualification_max_research_runs": protocol["qualification"][
                    "max_research_runs"
                ],
                "paid_execution_started": False,
                "execution_arm_checked": args.execution_arm,
                "execution_ref_checked": args.execution_ref,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
