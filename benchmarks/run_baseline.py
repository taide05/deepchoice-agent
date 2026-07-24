"""DeepChoice Baseline Benchmark Runner.

Runs the full DeepChoice pipeline against annotated test cases, collects
all metrics, optionally runs LLM-as-Judge evaluation, and saves timestamped
results for trend tracking.

Usage:
    cd D:/deepchoice-agent
    python -m benchmarks.run_baseline              # all 15 cases
    python -m benchmarks.run_baseline --cases 5    # first 5 cases (quick)
    python -m benchmarks.run_baseline --cases 3 --judge  # with LLM-as-Judge

Requires: .env with DEEPSEEK_API_KEY, TAVILY_API_KEY, GITHUB_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.utils.llm import call_model

from benchmarks.metrics import (
    compute_all_metrics,
    save_benchmark,
    trend_report,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BENCHMARKS_DIR = Path(__file__).resolve().parent
RUNS_DIR = BENCHMARKS_DIR / "runs"
ANNOTATED_CASES_PATH = BENCHMARKS_DIR / "annotated_cases.json"
TIMEOUT_PER_CASE_S = 300  # 5 minutes per case


# ---------------------------------------------------------------------------
# LLM-as-Judge (reused from test_eval.py, made standalone)
# ---------------------------------------------------------------------------

EVAL_PROMPT = """You are an impartial evaluator. Score this research report on 5 dimensions (1-5 each).

## Report
{report}

## Original Query
{query}

## Scoring Rubric
1. Factual Consistency (1-5): Are claims consistent with the cited sources? Deduct for hallucinated facts.
2. Evidence Sufficiency (1-5): Does each major claim have at least one source? Deduct for unsourced claims.
3. Reasoning Logic (1-5): Is the reasoning chain coherent? Deduct for logical gaps.
4. Honesty (1-5): Are gaps and uncertainties clearly stated? Deduct for overconfidence.
5. Completeness (1-5): Are all sub-questions answered? Deduct for missing dimensions.

Return ONLY a JSON object:
{{
  "factual_consistency": N,
  "evidence_sufficiency": N,
  "reasoning_logic": N,
  "honesty": N,
  "completeness": N,
  "total": N.N,
  "notes": "Brief justification"
}}"""


async def judge_report(query: str, report: str) -> dict:
    """Run LLM-as-Judge evaluation on a single report."""
    prompt = EVAL_PROMPT.format(query=query, report=report[:8000])
    try:
        result = await call_model(
            [{"role": "user", "content": prompt}],
            model="deepseek-v4-flash",
            response_format="json",
        )
        return result
    except Exception as exc:
        return {"error": str(exc), "total": 0.0}


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------

def _build_report_from_state(state: dict) -> str:
    """Extract report text from pipeline state."""
    report = state.get("report", "")
    if report:
        return report
    # Fallback: synthesize a minimal report from state
    conclusion = state.get("conclusion", {})
    if isinstance(conclusion, dict):
        parts = []
        ranked = conclusion.get("ranked_options", [])
        if ranked:
            parts.append("## Ranked Options\n")
            for i, opt in enumerate(ranked):
                parts.append(f"{i+1}. **{opt.get('name', 'Unknown')}**")
        tradeoffs = conclusion.get("trade_offs", "")
        if tradeoffs:
            parts.append(f"\n## Trade-offs\n{tradeoffs}")
        return "\n".join(parts)
    return ""


async def run_single_case(case: dict, verbose: bool = False) -> dict:
    """Run DeepChoice pipeline for one annotated case.

    Returns a dict with everything needed for metrics calculation.
    """
    case_id = case["id"]
    t0 = time.monotonic()

    task = {
        "query": case["query"],
        "scene_context": case.get("scene", "solo"),
        "constraints": [],
        "report_format": "what_why_how",
    }

    if verbose:
        print(f"  [{case_id}] Starting: {case['query'][:80]}...")

    try:
        orchestrator = ChiefEditorAgent(task)
        state = await asyncio.wait_for(
            orchestrator.run_research_task(), timeout=TIMEOUT_PER_CASE_S
        )
        elapsed = round(time.monotonic() - t0, 1)
        report = _build_report_from_state(state)

        if verbose:
            n_sources = len(state.get("search_results", []))
            confidence = state.get("confidence", "unknown")
            print(f"  [{case_id}] Done in {elapsed}s | confidence={confidence} | "
                  f"sources={n_sources} | report={len(report)} chars")

        return {
            "case_id": case_id,
            "query": case["query"],
            "state": state,
            "report": report,
            "error": None,
            "elapsed_s": elapsed,
            "retry_count": state.get("retry_count", 0),
            "confidence": state.get("confidence", ""),
            "search_results": state.get("search_results", []),
            "conflicts": state.get("conflicts", []),
            "knowledge_gaps": state.get("knowledge_gaps", []),
        }

    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - t0, 1)
        if verbose:
            print(f"  [{case_id}] TIMEOUT after {elapsed}s")
        return {
            "case_id": case_id,
            "query": case["query"],
            "state": None,
            "report": "",
            "error": f"timeout ({TIMEOUT_PER_CASE_S}s)",
            "elapsed_s": elapsed,
            "retry_count": 0,
            "confidence": "",
        }

    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 1)
        if verbose:
            print(f"  [{case_id}] FAILED: {exc}")
        return {
            "case_id": case_id,
            "query": case["query"],
            "state": None,
            "report": "",
            "error": str(exc),
            "elapsed_s": elapsed,
            "retry_count": 0,
            "confidence": "",
        }


async def run_baseline(
    n_cases: int | None = None,
    verbose: bool = False,
    with_judge: bool = False,
    batch: int = 0,
    batch_size: int = 10,
) -> Path:
    """Run the full benchmark suite.

    Args:
        n_cases: Number of cases to run (None = all).
        verbose: Print per-case progress.
        with_judge: Run LLM-as-Judge evaluation (costs API credits).
        batch: Batch number (1-indexed, 0 = run all).
        batch_size: Cases per batch (default 10).

    Returns:
        Path to the saved benchmark report.
    """
    # Load annotated cases
    cases = json.loads(ANNOTATED_CASES_PATH.read_text(encoding="utf-8"))

    # Handle batching
    batch_label = ""
    if batch > 0:
        start_idx = (batch - 1) * batch_size
        end_idx = start_idx + batch_size
        cases = cases[start_idx:end_idx]
        batch_label = f"-batch{batch:02d}"
        print(f"Batch {batch}: cases {start_idx+1}-{min(end_idx, len(cases))} "
              f"(batch_size={batch_size}, total available={len(json.loads(ANNOTATED_CASES_PATH.read_text(encoding='utf-8')))})")
    elif n_cases and n_cases > 0:
        cases = cases[:n_cases]

    # Validate API keys
    api_status = {
        "deepseek": bool(os.getenv("DEEPSEEK_API_KEY")),
        "tavily": bool(os.getenv("TAVILY_API_KEY")),
        "github": bool(os.getenv("GITHUB_TOKEN")),
    }
    if verbose:
        missing = [k for k, v in api_status.items() if not v]
        if missing:
            print(f"WARNING: Missing API keys: {missing}. Some retrievers will fail.")

    # Phase 1: Run all cases
    print(f"\n{'=' * 60}")
    print(f"PHASE 1: Running {len(cases)} cases through DeepChoice pipeline")
    print(f"{'=' * 60}\n")

    runs = []
    latencies = []
    ok = 0
    fail = 0

    for i, case in enumerate(cases):
        if verbose:
            print(f"[{i+1}/{len(cases)}]", end=" ")
        result = await run_single_case(case, verbose=verbose)
        runs.append(result)
        latencies.append(result["elapsed_s"])
        if result["error"] is None:
            ok += 1
        else:
            fail += 1

    print(f"\nPhase 1 complete: {ok} success / {fail} failure")

    # Phase 2: LLM-as-Judge (optional)
    before_after_pairs = []
    if with_judge:
        print(f"\n{'=' * 60}")
        print("PHASE 2: LLM-as-Judge Evaluation")
        print(f"{'=' * 60}\n")

        judge_results = []
        for i, run in enumerate(runs):
            if run["error"] or not run["report"]:
                continue
            if verbose:
                print(f"[{i+1}/{len(runs)}] Judging {run['case_id']}...")
            scores = await judge_report(run["query"], run["report"])
            run["judge_scores"] = scores
            judge_results.append({
                "case_id": run["case_id"],
                "total": scores.get("total", 0),
            })
            if verbose:
                print(f"  Score: {scores.get('total', 'ERR')}/5")

        avg_judge = (
            sum(j["total"] for j in judge_results) / len(judge_results)
            if judge_results
            else 0
        )
        print(f"\nAverage judge score: {avg_judge:.2f}/5 ({len(judge_results)} reports)")

        # Build retry pairs for runs that triggered retry
        for run in runs:
            if run.get("retry_count", 0) > 0 and "judge_scores" in run:
                before_after_pairs.append({
                    "case_id": run["case_id"],
                    "score_before": 0,  # Would need pre-retry state snapshot
                    "score_after": run["judge_scores"].get("total", 0),
                    "retry_triggered": True,
                    "retry_type": "full" if run.get("knowledge_gaps", 0) > 2 else "small",
                })

    # Phase 3: Compute metrics
    print(f"\n{'=' * 60}")
    print("PHASE 3: Computing Metrics")
    print(f"{'=' * 60}\n")

    report = compute_all_metrics(
        runs=runs,
        annotated_cases=cases,
        latencies_s=latencies,
        before_after_pairs=before_after_pairs,
    )

    # Print summary
    s = report["summary"]
    print("Summary:")
    print(f"  Top-1 Accuracy:         {s['top1_accuracy']:.1%}")
    print(f"  Source Recall:          {s['source_recall']:.1%}")
    print(f"  Claim Grounding Rate:   {s['claim_grounding_rate']:.1%}")
    print(f"  Conflict Detection:     {s['conflict_detection_rate']:.1%}")
    print(f"  Latency P50 / P95:      {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    print(f"  Success Rate:           {s['success_rate']:.1%}")
    print(f"  Retry Score Delta:      {s['retry_mean_delta']:+.2f}")

    # Phase 4: Save
    path = save_benchmark(report, RUNS_DIR, label=batch_label)
    print(f"\nBenchmark saved to: {path}")

    # Save raw runs for later merging (only for batch mode)
    if batch_label:
        runs_path = RUNS_DIR / f"runs{batch_label}.json"
        runs_to_save = []
        for run in runs:
            # Strip heavy state objects to keep files small
            runs_to_save.append({
                "case_id": run["case_id"],
                "query": run["query"],
                "report": run.get("report", ""),
                "error": run.get("error"),
                "elapsed_s": run.get("elapsed_s", 0),
                "search_results": run.get("search_results", []),
                "conflicts": run.get("conflicts", []),
                "retry_count": run.get("retry_count", 0),
                "confidence": run.get("confidence", ""),
                "knowledge_gaps": run.get("knowledge_gaps", []),
                "judge_scores": run.get("judge_scores"),
            })
        runs_path.write_text(json.dumps(runs_to_save, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Raw runs saved to: {runs_path}")

    # Check trend if previous benchmarks exist
    if not batch_label:
        trend = trend_report(RUNS_DIR)
        if trend["status"] == "ok":
            print(f"\nTrend vs previous ({trend['previous_timestamp']}):")
            for metric, delta in trend["deltas"].items():
                sign = "+" if delta > 0 else ""
                print(f"  {metric}: {sign}{delta}")

    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def merge_all_batches(verbose: bool = False) -> dict[str, Any]:
    """Merge all batch runs into final aggregate report."""
    annotated_path = ANNOTATED_CASES_PATH
    annotated_cases = json.loads(annotated_path.read_text(encoding="utf-8"))

    # Load all batch runs files
    runs_files = sorted(RUNS_DIR.glob("runs-batch*.json"))
    if not runs_files:
        print("No batch runs files found. Run --batch N first.")
        return {"status": "no_data"}

    all_runs = []
    for rf in runs_files:
        batch_runs = json.loads(rf.read_text(encoding="utf-8"))
        all_runs.extend(batch_runs)
        if verbose:
            print(f"  Loaded {len(batch_runs)} runs from {rf.name}")

    print(f"Total runs loaded: {len(all_runs)}")

    # Compute aggregate metrics
    latencies = [r.get("elapsed_s", 0) for r in all_runs]
    before_after_pairs = []  # Not available from batch runs without state

    from benchmarks.metrics import compute_all_metrics, save_benchmark
    report = compute_all_metrics(
        runs=all_runs,
        annotated_cases=annotated_cases,
        latencies_s=latencies,
        before_after_pairs=before_after_pairs,
    )

    # Print summary
    s = report["summary"]
    print("\n" + "=" * 60)
    print(f"AGGREGATE BENCHMARK ({len(runs_files)} batches, {len(all_runs)} cases)")
    print("=" * 60)
    print(f"  Top-1 Accuracy:         {s['top1_accuracy']:.1%}")
    print(f"  Source Recall:          {s['source_recall']:.1%}")
    print(f"  Claim Grounding Rate:   {s['claim_grounding_rate']:.1%}")
    print(f"  Conflict Detection:     {s['conflict_detection_rate']:.1%}")
    print(f"  Latency P50 / P95:      {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    print(f"  Success Rate:           {s['success_rate']:.1%}")
    print(f"  Retry Score Delta:      {s['retry_mean_delta']:+.2f}")

    path = save_benchmark(report, RUNS_DIR)
    print(f"\nFinal report saved to: {path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeepChoice Baseline Benchmark")
    parser.add_argument(
        "--cases", type=int, default=0,
        help="Number of cases to run (default: all)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print per-case progress",
    )
    parser.add_argument(
        "--judge", action="store_true",
        help="Run LLM-as-Judge evaluation (costs API credits)",
    )
    parser.add_argument(
        "--batch", type=int, default=0,
        help="Batch number (1-indexed, e.g. --batch 1 runs first N cases)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Cases per batch (default: 10)",
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="Merge all batch results into final aggregate report",
    )
    args = parser.parse_args()

    if args.merge:
        asyncio.run(merge_all_batches(verbose=args.verbose))
    else:
        n = args.cases if args.cases > 0 else None
        path = asyncio.run(
            run_baseline(
                n_cases=n,
                verbose=args.verbose,
                with_judge=args.judge,
                batch=args.batch,
                batch_size=args.batch_size,
            )
        )
        print(f"\nDone. Report: {path}")
