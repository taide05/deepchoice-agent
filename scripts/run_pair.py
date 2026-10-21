"""Paired comparison entry: simple baseline vs candidate tail.

Default is offline and refuses to call external models. A caller with explicit
budget authorization may pass --allow-external after freezing the state. This
script reuses the existing retrieval/source-scoring state; it does not retrieve
or evaluate sources itself.
"""
import argparse
import asyncio
import json
import pathlib
import sys

from deepchoice.evaluation.simple_baseline import (
    OfflineGateError,
    default_evidence_budget,
    run_pair,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True,
                        help="JSON state snapshot after retrieval + source scoring")
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-external", action="store_true",
                        help="allow real LLM calls; requires external budget authorization")
    parser.add_argument("--budget-chars", type=int, default=default_evidence_budget())
    args = parser.parse_args(argv)
    state = json.loads(pathlib.Path(args.state).read_text(encoding="utf-8"))
    try:
        result = asyncio.run(run_pair(
            state, budget_chars=args.budget_chars,
            allow_external=args.allow_external))
    except OfflineGateError as exc:
        print(f"OFFLINE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "baseline": {
            "report": result["baseline"]["report"],
            "final_recommendation": result["baseline"]["final_recommendation"],
            "quality_signals": result["baseline"]["quality_signals"],
            "token_usage": result["baseline"]["token_usage"],
            "evidence_package": result["baseline"]["evidence_package"],
            "coverage": result["baseline"]["coverage"],
            "incremental_calls": result["baseline_incremental_calls"],
        },
        "candidate": {
            "report": result["candidate"]["report"],
            "final_recommendation": result["candidate"]["final_recommendation"],
            "quality_signals": result["candidate"]["quality_signals"],
            "token_usage": result["candidate"]["token_usage"],
            "coverage": result["candidate"]["coverage"],
            "incremental_calls": result["candidate_incremental_calls"],
        },
        "evidence_equal": result["evidence_equal"],
        "actual_evidence_package_count": result["actual_evidence_package_count"],
        "baseline_actual_package_count": result["baseline_actual_package_count"],
        "candidate_actual_package_count": result["candidate_actual_package_count"],
        "actual_evidence_entries_mismatch": result["actual_evidence_entries_mismatch"],
        "shared_retrieval_requests": result["shared_retrieval_requests"],
        "shared_evidence": {
            "budget_chars": result["shared_evidence"].package["budget_chars"],
            "full_included": result["shared_evidence"].package["full_included"],
            "sources": result["shared_evidence"].package["sources"],
            "coverage": result["shared_evidence"].coverage,
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "evidence_equal": result["evidence_equal"],
                      "baseline_calls": result["baseline_incremental_calls"],
                      "candidate_calls": result["candidate_incremental_calls"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
