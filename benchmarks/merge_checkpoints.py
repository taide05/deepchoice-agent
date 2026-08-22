"""Merge checkpoint runs from interrupted 200-case runs into one final benchmark.

Sources (deduped by case_id, error-free run wins):
- checkpoint-g1-*  : first run, 66 successful cases (50 TC + 16 TC)
- checkpoint-g2-*  : retry run chunk01, 50 successful cases (34 TC + 16 OS)
- checkpoint-chunk*: today's 84-case OS run (chunk01 = 50, chunk02 = 34)

Usage: python -m benchmarks.merge_checkpoints
"""
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
RUNS_DIR = BENCH_DIR / "runs"
sys.path.insert(0, str(BENCH_DIR.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from benchmarks.metrics import (
    compute_all_metrics,
    compute_conflict_detection_rate_llm,
    compute_source_recall_by_source,
    save_benchmark,
)
from benchmarks.report_quality import evaluate_batch
from benchmarks.run_baseline import _judge_conflict_match

AGENT_NAMES = ["query_analyzer", "query_adapter", "multi_retriever",
               "source_evaluator", "conflict_detector", "evidence_chain",
               "conclusion_synthesizer", "report_generator", "self_reviewer"]


def load_runs(paths: list[Path]) -> list[dict]:
    runs = []
    for p in paths:
        if not p.exists():
            print(f"WARNING: missing source {p.name}")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        runs.extend(data["runs"])
    return runs


async def main() -> None:
    cases = json.loads((BENCH_DIR / "cases_eval_200.json").read_text(encoding="utf-8"))
    sources = [
        RUNS_DIR / "checkpoint-g1-chunk01.json",
        RUNS_DIR / "checkpoint-g1-chunk02.json",
        RUNS_DIR / "checkpoint-g2-chunk01.json",
        RUNS_DIR / "checkpoint-chunk01.json",
        RUNS_DIR / "checkpoint-chunk02.json",
    ]
    by_id: dict[str, dict] = {}
    for r in load_runs(sources):
        cur = by_id.get(r["case_id"])
        if cur is None or (cur.get("error") is not None and r.get("error") is None):
            by_id[r["case_id"]] = r

    runs = [by_id[c["id"]] for c in cases if c["id"] in by_id]
    missing = [c["id"] for c in cases if c["id"] not in by_id]
    errors = [r["case_id"] for r in runs if r.get("error") is not None]
    print(f"Merged runs: {len(runs)} (expected 200)")
    print(f"Missing: {len(missing)} {missing[:10]}")
    print(f"With errors: {len(errors)} {errors[:10]}")
    if len(runs) != len(cases) or missing or errors:
        print("ABORT: coverage or error check failed — fix sources and retry")
        return

    quality_stats = evaluate_batch(runs)
    latencies = [r["elapsed_s"] for r in runs]
    before_after_pairs = []
    for run in runs:
        if run.get("retry_count", 0) > 0:
            before_after_pairs.append({
                "case_id": run["case_id"],
                "score_before": 0,
                "score_after": 0,
                "retry_triggered": True,
                "retry_type": "full" if len(run.get("knowledge_gaps", [])) > 2 else "small",
            })

    report = compute_all_metrics(
        runs=runs,
        annotated_cases=cases,
        latencies_s=latencies,
        before_after_pairs=before_after_pairs,
    )

    print("  Running LLM judge on conflict detection...")
    llm_cd = await compute_conflict_detection_rate_llm(runs, cases, _judge_conflict_match)
    report["quality"]["conflict_detection"] = llm_cd
    report["summary"]["conflict_detection_rate"] = llm_cd["value"]
    print(f"  LLM judge: {llm_cd['keyword_matched']} keyword + "
          f"{llm_cd['llm_matched']} LLM = {llm_cd['total_detected']}/{llm_cd['total_known']}")

    report["quality"]["report_quality"] = quality_stats
    report["summary"]["report_quality_grade_a_pct"] = quality_stats["grade_a_pct"]

    src_split = compute_source_recall_by_source(runs, cases)
    report["quality"]["source_recall_by_source"] = src_split
    print("\n  Source recall by type:")
    for src_type, data in sorted(src_split.items()):
        if src_type != "metric":
            print(f"    {src_type}: {data['recall']:.1%} ({data['found']}/{data['total']})")

    agent_stats: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        for name, elapsed in r.get("agent_timing", {}).items():
            agent_stats[name].append(elapsed)
    agent_summary = {}
    for name in AGENT_NAMES:
        times = agent_stats.get(name, [])
        if times:
            avg = sum(times) / len(times)
            p95 = sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else max(times)
            agent_summary[name] = {"avg_s": round(avg, 1), "p95_s": round(p95, 1), "n": len(times)}
    report["efficiency"]["agent_timing"] = agent_summary

    s = report["summary"]
    print("\nSummary:")
    print(f"  Top-1 Accuracy:         {s['top1_accuracy']:.1%}")
    print(f"  Source Recall:          {s['source_recall']:.1%}")
    print(f"  Claim Grounding Rate:   {s['claim_grounding_rate']:.1%}")
    print(f"  Conflict Detection:     {s['conflict_detection_rate']:.1%}")
    print(f"  Latency P50 / P95:      {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    print(f"  Success Rate:           {s['success_rate']:.1%}")
    print(f"  Report Quality A/B %:   {quality_stats['grade_a_pct']:.0f}% / {quality_stats['grade_b_pct']:.0f}%")

    path = save_benchmark(report, RUNS_DIR, label="-merged200")
    print(f"\nBenchmark saved to: {path}")


if __name__ == "__main__":
    asyncio.run(main())
