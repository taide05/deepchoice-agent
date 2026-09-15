"""Deterministic, credential-free smoke evaluation for versioned core assets.

This runner intentionally evaluates only fixture-replayed outputs and pure
post-processing/rendering functions.  It must never import the live benchmark
runner, load ``.env``, create an outbound resolver, or call an LLM/judge.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BENCHMARKS_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = BENCHMARKS_DIR / "offline" / "smoke-v1.json"
DEFAULT_BASELINE = BENCHMARKS_DIR / "offline" / "baseline-smoke-v1.json"
EXPECTED_DATASET_ID = "deepchoice-offline-smoke"
EXPECTED_DATASET_VERSION = "smoke-v1"
EXPECTED_CASES_PER_STAGE = 3
EXPECTED_STAGES = (
    "query_analysis",
    "citation_verification",
    "conclusion",
    "report",
)
DEFAULT_RETRIEVAL_SOURCES = (
    "tavily",
    "chroma",
    "github",
    "arxiv",
    "community",
    "official",
)


class OfflineEvalError(ValueError):
    """The checked-in offline evaluation input or baseline is invalid."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        dataset = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineEvalError(f"invalid offline dataset: {path}") from exc
    if not isinstance(dataset, dict):
        raise OfflineEvalError("offline dataset must be a JSON object")
    _validate_dataset(dataset)
    return dataset, _sha256_bytes(raw)


def _validate_dataset(dataset: dict[str, Any]) -> None:
    if dataset.get("dataset_id") != EXPECTED_DATASET_ID:
        raise OfflineEvalError(f"dataset_id must be {EXPECTED_DATASET_ID!r}")
    if dataset.get("version") != EXPECTED_DATASET_VERSION:
        raise OfflineEvalError(f"dataset version must be {EXPECTED_DATASET_VERSION!r}")
    freeze_date = dataset.get("freeze_date")
    if not isinstance(freeze_date, str) or len(freeze_date) != 10:
        raise OfflineEvalError("freeze_date must be an ISO calendar date")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) != 12:
        raise OfflineEvalError("smoke-v1 must contain exactly 12 cases")
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or len(set(ids)) != len(ids) or not all(ids):
        raise OfflineEvalError("every offline case must have a unique non-empty case_id")
    stage_counts = Counter(case.get("stage") for case in cases)
    expected = {stage: EXPECTED_CASES_PER_STAGE for stage in EXPECTED_STAGES}
    if dict(stage_counts) != expected:
        raise OfflineEvalError(f"smoke-v1 stage distribution must be {expected}")


def _evaluate_query_case(case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    from deepchoice.agents.query_analyzer import _detect_scene

    fixture = copy.deepcopy(case["fixture_output"])
    actual_scene = _detect_scene(case["query"], case.get("scene_context", "unspecified"))
    sub_questions = fixture.get("sub_questions")
    constraints = fixture.get("constraints")
    fixture_valid = (
        isinstance(sub_questions, list)
        and len(sub_questions) == case["expected_sub_question_count"]
        and all(isinstance(item, str) and item.strip() for item in sub_questions)
        and isinstance(constraints, list)
        and all(isinstance(item, str) and item.strip() for item in constraints)
    )
    passed = actual_scene == case["expected_scene"] and fixture_valid
    return passed, {
        "scene": actual_scene,
        "fixture_valid": fixture_valid,
        "sub_question_count": len(sub_questions) if isinstance(sub_questions, list) else 0,
    }


def _evaluate_citation_case(case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    # _support_status is the same deterministic lexical/numeric/cross-language
    # decision used after a bounded live fetch.  Supplying fixture text here
    # deliberately avoids verify_citations() and therefore all fetch/budget paths.
    from deepchoice.citations.verifier import _support_status

    status, reason = _support_status(case["claim"], case["fixture_evidence_text"])
    actual = {"status": status.value, "reason": reason.value}
    passed = actual == {
        "status": case["expected_status"],
        "reason": case["expected_reason"],
    }
    return passed, actual


def _evaluate_conclusion_case(case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    from deepchoice.agents.conclusion_synthesizer import (
        _bind_citations,
        _sanitize_citations,
        _summarize_chains,
        _validate_constraint_fit,
        _validate_winner,
    )

    result = copy.deepcopy(case["fixture_llm_output"])
    chains = copy.deepcopy(case["evidence_chains"])
    _, citation_map = _summarize_chains(chains)
    _validate_winner(result)
    _validate_constraint_fit(result)
    _sanitize_citations(result, chains)
    _bind_citations(result, citation_map)
    serialized = _canonical_json(result)
    passed = (
        result.get("winner") == case["expected_winner"]
        and all(marker in serialized for marker in case.get("required_markers", []))
        and all(marker not in serialized for marker in case.get("forbidden_markers", []))
    )
    return passed, {
        "winner": result.get("winner"),
        "result_sha256": _sha256_json(result),
    }


def _evaluate_report_case(case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    from benchmarks.report_quality import evaluate_report
    from deepchoice.agents.report_generator import FORMAT_RENDERERS

    template = case["template"]
    state = copy.deepcopy(case["state"])
    state.setdefault("task", {})["report_format"] = template
    report = FORMAT_RENDERERS[template](state)
    quality = evaluate_report(report, case["tech_a"], case["tech_b"])
    markers_ok = all(marker in report for marker in case["required_markers"])
    passed = quality["pass_count"] >= 4 and markers_ok
    return passed, {
        "template": template,
        "quality_pass_count": quality["pass_count"],
        "quality_denominator": 5,
        "structure_passed": markers_ok,
        "report_sha256": _sha256_bytes(report.encode("utf-8")),
    }


_STAGE_EVALUATORS = {
    "query_analysis": _evaluate_query_case,
    "citation_verification": _evaluate_citation_case,
    "conclusion": _evaluate_conclusion_case,
    "report": _evaluate_report_case,
}


def _metric(numerator: int, denominator: int) -> dict[str, int | float]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else 0.0,
    }


def _fingerprint_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    # Paths are intentionally never recorded.  The current manifest remains in
    # the artifact as provenance, but its identity also freezes deployment
    # configuration (models, endpoints and synthesis settings) that this
    # fixture-only evaluation does not exercise.  Excluding it keeps the
    # checked-in result baseline stable across correctly configured runtimes;
    # core code/assets remain covered by the deterministic registry identity.
    return {
        key: value
        for key, value in artifact.items()
        if key not in {
            "evaluated_at",
            "current_manifest_id",
            "artifact_fingerprint",
        }
    }


def artifact_fingerprint(artifact: dict[str, Any]) -> str:
    return _sha256_json(_fingerprint_payload(artifact))


def evaluate_dataset(dataset_path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    dataset, dataset_sha256 = load_dataset(dataset_path)

    from deepchoice.contracts.manifest import build_core_asset_registry, build_run_manifest

    manifest = build_run_manifest({"report_format": "what_why_how"})
    asset_registry = build_core_asset_registry()

    case_results: list[dict[str, Any]] = []
    deterministic_matches = 0
    fixtures = dataset.get("fixtures", {})
    for stored_case in dataset["cases"]:
        case = copy.deepcopy(stored_case)
        fixture_ref = case.pop("fixture_ref", None)
        if fixture_ref is not None:
            if not isinstance(fixtures, dict) or fixture_ref not in fixtures:
                raise OfflineEvalError(f"unknown fixture_ref: {fixture_ref!r}")
            case["state"] = copy.deepcopy(fixtures[fixture_ref])
        evaluator = _STAGE_EVALUATORS[case["stage"]]
        passed, output = evaluator(case)
        repeated_passed, repeated_output = evaluator(case)
        deterministic = passed == repeated_passed and output == repeated_output
        deterministic_matches += int(deterministic)
        case_results.append({
            "case_id": case["case_id"],
            "stage": case["stage"],
            "passed": passed,
            "deterministic": deterministic,
            "output": output,
        })

    metrics: dict[str, dict[str, int | float]] = {}
    for stage in EXPECTED_STAGES:
        selected = [result for result in case_results if result["stage"] == stage]
        metrics[f"{stage}.cases_passed"] = _metric(
            sum(bool(result["passed"]) for result in selected),
            len(selected),
        )
    report_results = [item for item in case_results if item["stage"] == "report"]
    metrics["report.structure"] = _metric(
        sum(bool(item["output"]["structure_passed"]) for item in report_results),
        len(report_results),
    )
    for result in report_results:
        template = result["output"]["template"]
        metrics[f"report.{template}.quality"] = _metric(
            result["output"]["quality_pass_count"],
            result["output"]["quality_denominator"],
        )
    metrics["deterministic_replay"] = _metric(deterministic_matches, len(case_results))
    metrics["overall"] = _metric(
        sum(bool(result["passed"]) for result in case_results),
        len(case_results),
    )

    artifact: dict[str, Any] = {
        "artifact_schema_version": 1,
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "version": dataset["version"],
            "freeze_date": dataset["freeze_date"],
            "file_sha256": dataset_sha256,
        },
        "evaluated_at": datetime.now(UTC).isoformat(),
        "case_count": len(dataset["cases"]),
        "evaluated_case_count": len(case_results),
        "execution_mode": "fixture_replay",
        "judge": "none",
        "current_manifest_id": manifest.manifest_id,
        "core_asset_registry_id": asset_registry.registry_id,
        "source_health": {
            "status": "not_run",
            "default_sources": {
                source: "degraded/unmeasured" for source in DEFAULT_RETRIEVAL_SOURCES
            },
        },
        "metrics": metrics,
        "cases": case_results,
    }
    artifact["artifact_fingerprint"] = artifact_fingerprint(artifact)
    return artifact


def thresholds_pass(artifact: dict[str, Any]) -> bool:
    metrics = artifact["metrics"]
    if artifact["case_count"] != 12 or artifact["evaluated_case_count"] != 12:
        return False
    if metrics["overall"]["numerator"] != 12:
        return False
    if metrics["deterministic_replay"]["rate"] != 1.0:
        return False
    if metrics["report.structure"]["rate"] != 1.0:
        return False
    return all(
        metrics[f"report.{template}.quality"]["numerator"] >= 4
        and metrics[f"report.{template}.quality"]["denominator"] == 5
        for template in ("what_why_how", "evidence_first", "comparison_matrix")
    )


def _write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _check_baseline(path: Path, artifact: dict[str, Any]) -> bool:
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfflineEvalError(f"invalid offline baseline: {path}") from exc
    recorded = baseline.get("artifact_fingerprint")
    return (
        isinstance(recorded, str)
        and recorded == artifact_fingerprint(baseline)
        and recorded == artifact["artifact_fingerprint"]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the credential-free DeepChoice offline smoke evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, help="write the generated artifact to this path")
    parser.add_argument("--write-baseline", action="store_true", help="replace the checked-in baseline artifact")
    parser.add_argument("--check-baseline", action="store_true", help="compare with the checked-in baseline fingerprint")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.write_baseline and args.check_baseline:
        raise OfflineEvalError("--write-baseline and --check-baseline are mutually exclusive")
    artifact = evaluate_dataset(args.dataset)
    if args.write_baseline:
        _write_artifact(DEFAULT_BASELINE, artifact)
    if args.output is not None:
        _write_artifact(args.output, artifact)
    baseline_matches = True
    if args.check_baseline:
        baseline_matches = _check_baseline(DEFAULT_BASELINE, artifact)
    print(json.dumps({
        "passed": thresholds_pass(artifact) and baseline_matches,
        "artifact_fingerprint": artifact["artifact_fingerprint"],
        "metrics": artifact["metrics"],
        "baseline_matches": baseline_matches if args.check_baseline else None,
    }, ensure_ascii=False, indent=2))
    return 0 if thresholds_pass(artifact) and baseline_matches else 1


if __name__ == "__main__":  # pragma: no cover - exercised by CLI subprocess tests
    sys.exit(main())
