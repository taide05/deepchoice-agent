"""DeepChoice Baseline Benchmark Runner.

Runs the full DeepChoice pipeline against annotated test cases, collects
all metrics, and saves timestamped results for trend tracking.

Usage:
    cd D:/deepchoice-agent
    python -m benchmarks.run_baseline              # 50 annotated cases (serial)
    python -m benchmarks.run_baseline --full        # 200 cases (serial)
    python -m benchmarks.run_baseline --full --concurrency 10  # 200 cases (10 concurrent)
    python -m benchmarks.run_baseline --cases 5     # first 5 cases (quick)

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
from typing import Any

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.utils.llm import call_model, set_current_case, set_record_callback

from benchmarks.metrics import (
    compute_all_metrics,
    compute_conflict_detection_rate_llm,
    save_benchmark,
    trend_report,
)
from benchmarks.report_quality import evaluate_batch

# ---------------------------------------------------------------------------
# Outbound health-check helpers (batch 3)
# ---------------------------------------------------------------------------

async def probe_tavily_direct() -> tuple[bool, str]:
    """Tavily stays direct (user decision 2026-09-01): one keypool POST probe."""
    import httpx

    from deepchoice.retrievers.base import error_text
    from deepchoice.retrievers.tavily_keypool import post_with_failover

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            async def post(url, json=None, **kw):
                return await client.post(url, json=json, **kw)

            resp, _ = await post_with_failover(post, {"query": "langgraph", "max_results": 1})
            if resp is None:
                return False, "no available Tavily key"
            return resp.status_code == 200, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, error_text(exc)


async def health_check_report() -> dict[str, Any]:
    """Probe all outbound sources + tavily-direct; returns diagnostics."""
    from deepchoice.outbound import get_resolver

    out = await get_resolver().health_check()
    tav_ok, tav_detail = await probe_tavily_direct()
    out["tavily_direct"] = {"ok": tav_ok, "detail": tav_detail}
    return out


def _print_health_check(hc: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("OUTBOUND HEALTH CHECK")
    print("=" * 60)
    for source, info in hc.get("sources", {}).items():
        ch = info.get("channel") or "-"
        mark = "OK " if info.get("ok") else "XX "
        print(f"  [{mark}] {source:<12} channel={ch}")
    td = hc.get("tavily_direct", {})
    mark = "OK " if td.get("ok") else "XX "
    print(f"  [{mark}] {'tavily':<12} direct={td.get('detail', '-')}")
    if hc.get("degraded_sources"):
        print(f"  DEGRADED SOURCES: {hc['degraded_sources']}")
    print("=" * 60)


async def run_health_check() -> int:
    hc = await health_check_report()
    _print_health_check(hc)
    return 0 if (hc.get("ok") and hc.get("tavily_direct", {}).get("ok")) else 1


def _setup_debug_dump(dump_dir: Path) -> None:
    """Dump every LLM call's raw response to {dump_dir}/{case_id}/{tag}-{seq}.json."""
    import json as _json

    dump_dir.mkdir(parents=True, exist_ok=True)
    seq: dict[tuple[str, str], int] = {}

    async def _dump(entry: dict[str, Any]) -> None:
        cid = entry.get("case_id") or "unknown"
        tag = entry.get("tag") or entry.get("tier") or "llm"
        n = seq.get((cid, tag), 0)
        seq[(cid, tag)] = n + 1
        d = dump_dir / cid
        d.mkdir(parents=True, exist_ok=True)
        data = _json.dumps(entry, ensure_ascii=False, indent=2)
        await asyncio.to_thread((d / f"{tag}-{n:03d}.json").write_text,
                                data, encoding="utf-8")

    set_record_callback(_dump)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BENCHMARKS_DIR = Path(__file__).resolve().parent
RUNS_DIR = BENCHMARKS_DIR / "runs"
ANNOTATED_CASES_PATH = BENCHMARKS_DIR / "annotated_cases.json"
FULL_CASES_PATH = BENCHMARKS_DIR / "cases_200.json"
TIMEOUT_PER_CASE_S = 600  # 10 minutes per case (thinking synthesis adds latency)
DEFAULT_CONCURRENCY = 8


# ---------------------------------------------------------------------------
# LLM Judge for Conflict Detection
# ---------------------------------------------------------------------------

CONFLICT_JUDGE_PROMPT = """You are evaluating a conflict detection system for a tech comparison research tool.

Detected conflicts (from the pipeline):
{conflicts_text}

Known contradiction topic: "{topic}"

Does ANY of the detected conflicts involve the same subject matter as this topic?
Answer "yes" if the detected conflict and the known topic are about the same technology,
performance characteristic, design trade-off, or usage scenario — even if they use different wording.
Only answer "no" if the detected conflicts are clearly about completely different subjects.
Answer ONLY "yes" or "no"."""


async def _judge_conflict_match(detected_conflicts: list[dict], topic: str) -> bool:
    """Ask flash model if any detected conflict relates to the topic."""
    if not detected_conflicts:
        return False
    # Summarize conflicts: claim_a vs claim_b + resolution + reasoning
    parts = []
    for c in detected_conflicts[:5]:  # Cap at 5 to keep prompt small
        parts.append(
            f"- {c.get('claim_a', '')[:80]} vs {c.get('claim_b', '')[:80]}\n"
            f"  resolution={c.get('resolution', '')} reasoning={c.get('reasoning', '')[:120]}"
        )
    conflicts_text = "\n".join(parts)
    try:
        result = await call_model(
            [{"role": "user", "content": CONFLICT_JUDGE_PROMPT.format(
                conflicts_text=conflicts_text, topic=topic)}],
            model="deepseek-flash", tag="conflict_judge",
            response_format="text",
        )
        return "yes" in str(result).strip().lower()
    except Exception:
        return False


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


def _collect_evidence_titles(state: dict) -> list[str]:
    """Source titles shown to the synthesizer (first 4 per chain) — the same
    set the citation sanitizer treats as real."""
    titles: list[str] = []
    for chain in state.get("evidence_chains", []):
        for src in chain.get("sources", [])[:4]:
            t = src.get("title", "")
            if t:
                titles.append(t)
    return titles


def _strip_run(run: dict) -> dict:
    """Strip the heavy state object from a run for checkpoint/persistence,
    keeping the fields metrics recomputation needs (incl. final_recommendation)."""
    return {
        "case_id": run.get("case_id", ""),
        "query": run.get("query", ""),
        "report": run.get("report", ""),
        "error": run.get("error"),
        "elapsed_s": run.get("elapsed_s", 0),
        "search_results": run.get("search_results", []),
        "conflicts": run.get("conflicts", []),
        "retry_count": run.get("retry_count", 0),
        "confidence": run.get("confidence", ""),
        "knowledge_gaps": run.get("knowledge_gaps", []),
        "agent_timing": run.get("agent_timing", {}),
        "final_recommendation": run.get("final_recommendation", {}),
        "evidence_titles": run.get("evidence_titles", []),
        "judge_scores": run.get("judge_scores"),
    }


async def run_single_case(case: dict, verbose: bool = False,
                           gather_evidence: bool = True,
                           with_clarify: bool = False) -> dict:
    """Run DeepChoice pipeline for one annotated case.

    Returns a dict with everything needed for metrics calculation.
    """
    case_id = case["id"]
    set_current_case(case_id)
    t0 = time.monotonic()

    task = {
        "query": case["query"],
        "scene_context": case.get("scene", "solo"),
        "constraints": [],
        "report_format": "what_why_how",
        "gather_evidence": gather_evidence,
    }

    clarify_used = False
    if with_clarify:
        try:
            from deepchoice.clarify.clarification_agent import ClarificationAgent
            from deepchoice.clarify.session_manager import SessionManager
            sm = SessionManager()
            session = sm.create_session(case["query"])
            agent = ClarificationAgent()
            result = await agent.decide_and_respond(session)
            if result.get("action") == "confirm":
                sub_questions = result.get("payload", {}).get("sub_questions", [])
                if sub_questions:
                    task["sub_questions"] = sub_questions
                    clarify_used = True
                    if verbose:
                        print(f"  [{case_id}] Clarify: generated {len(sub_questions)} sub_questions")
        except Exception as exc:
            if verbose:
                print(f"  [{case_id}] Clarify skipped: {exc}")

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
            agent_timing = state.get("agent_timing", {})
            timing_str = ""
            if agent_timing:
                timing_str = f" | agent_timing={ {k: f'{v}s' for k, v in agent_timing.items()} }"
            print(f"  [{case_id}] Done in {elapsed}s | confidence={confidence} | "
                  f"sources={n_sources} | report={len(report)} chars{timing_str}")

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
            "agent_timing": state.get("agent_timing", {}),
            "final_recommendation": state.get("final_recommendation", {}),
            "evidence_titles": _collect_evidence_titles(state),
            "clarify_used": clarify_used,
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
    batch: int = 0,
    batch_size: int = 10,
    cases_file: Path | None = None,
    gather_evidence: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
    with_clarify: bool = False,
    profile_agents: bool = False,
) -> Path:
    """Run the full benchmark suite.

    Args:
        n_cases: Number of cases to run (None = all).
        verbose: Print per-case progress.
        batch: Batch number (1-indexed, 0 = run all).
        batch_size: Cases per batch (default 10).
        concurrency: Max concurrent cases (default 5). Case execution is I/O-bound
            (API calls + LLM), so parallelism cuts total wall-clock time roughly
            by concurrency factor.

    Returns:
        Path to the saved benchmark report.
    """
    # Load annotated cases
    source_path = cases_file if cases_file else ANNOTATED_CASES_PATH
    cases = json.loads(source_path.read_text(encoding="utf-8"))

    # Handle batching
    batch_label = ""
    if batch > 0:
        start_idx = (batch - 1) * batch_size
        end_idx = start_idx + batch_size
        cases = cases[start_idx:end_idx]
        batch_label = f"-batch{batch:02d}"
        print(f"Batch {batch}: cases running (batch_size={batch_size}, cases in this batch={len(cases)})")
    elif n_cases and n_cases > 0:
        cases = cases[:n_cases]

    # Validate API keys
    api_status = {
        "llm": bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")),
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

    # Phase 1: Run all cases (parallel — each case is fully independent)
    sem = asyncio.Semaphore(concurrency)

    async def _run_with_semaphore(case: dict) -> dict:
        async with sem:
            return await run_single_case(case, verbose=verbose, gather_evidence=gather_evidence,
                                         with_clarify=with_clarify)

    if verbose:
        print(f"  Concurrency: {concurrency}")
    # Process in chunks of 50, saving checkpoint after each chunk
    CHUNK = 50
    all_runs = []
    for chunk_start in range(0, len(cases), CHUNK):
        chunk_cases = cases[chunk_start:chunk_start + CHUNK]
        chunk_idx = chunk_start // CHUNK + 1
        total_chunks = (len(cases) + CHUNK - 1) // CHUNK
        print(f"\n  --- Chunk {chunk_idx}/{total_chunks}: cases {chunk_start+1}-{min(chunk_start+CHUNK, len(cases))} ---")
        tasks = [_run_with_semaphore(case) for case in chunk_cases]
        chunk_runs = await asyncio.gather(*tasks)
        all_runs.extend(chunk_runs)
        chunk_ok = sum(1 for r in chunk_runs if r["error"] is None)
        chunk_fail = len(chunk_runs) - chunk_ok
        print(f"  Chunk {chunk_idx} done: {chunk_ok} success / {chunk_fail} failure")
        # Save checkpoint
        if len(cases) > CHUNK:
            ckpt_path = RUNS_DIR / f"checkpoint-chunk{chunk_idx:02d}.json"
            ckpt_data = {
                "checkpoint_chunk": chunk_idx,
                "cases_so_far": len(all_runs),
                "runs": [_strip_run(r) for r in chunk_runs],
            }
            ckpt_path.write_text(json.dumps(ckpt_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Checkpoint saved: {ckpt_path.name}")

    runs = all_runs
    latencies = [r["elapsed_s"] for r in runs]
    ok = sum(1 for r in runs if r["error"] is None)
    fail = len(runs) - ok

    print(f"\nPhase 1 complete: {ok} success / {fail} failure")

    # Phase 2: Report Quality Checklist (deterministic, no LLM)
    print(f"\n{'=' * 60}")
    print("PHASE 2: Report Quality Checklist")
    print(f"{'=' * 60}\n")

    quality_stats = evaluate_batch(runs)
    qs = quality_stats
    print(f"  Grade distribution: A={qs['grade_distribution']['A']} "
          f"B={qs['grade_distribution']['B']} "
          f"C={qs['grade_distribution']['C']} "
          f"D={qs['grade_distribution']['D']}")
    print(f"  Mean pass count: {qs['mean_pass_count']}/5")
    print("  Check pass rates:")
    for cid, rate in qs['check_pass_rates'].items():
        print(f"    {cid}: {rate:.0f}%")

    # Retry Score Delta requires pre-retry snapshots, which this eval pipeline
    # does not collect — pass no pairs so the metric is honest not_measured
    # instead of fabricated 0/0 deltas (S 终审 B1-O1).
    before_after_pairs = []

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

    # Phase 3.5: LLM-judged conflict detection (replaces keyword metric)
    print("  Running LLM judge on conflict detection...")
    llm_cd = await compute_conflict_detection_rate_llm(
        runs, cases, _judge_conflict_match,
    )
    report["quality"]["conflict_detection"] = llm_cd
    report["summary"]["conflict_detection_rate"] = llm_cd["value"]
    print(f"  LLM judge: {llm_cd['keyword_matched']} keyword + "
          f"{llm_cd['llm_matched']} LLM = {llm_cd['total_detected']}/{llm_cd['total_known']}")

    # Add report quality stats
    report["quality"]["report_quality"] = quality_stats
    report["summary"]["report_quality_grade_a_pct"] = quality_stats["grade_a_pct"]

    # Outbound channel audit (routes actually used by this run)
    try:
        from deepchoice.outbound import get_resolver

        report["outbound"] = get_resolver().summary()
    except Exception as exc:
        report["outbound"] = {"error": str(exc)}

    # Phase 3.6: Source recall by retriever type
    from benchmarks.metrics import compute_source_recall_by_source
    src_split = compute_source_recall_by_source(runs, cases)
    report["quality"]["source_recall_by_source"] = src_split
    print("\n  Source recall by type:")
    for src_type, data in sorted(src_split.items()):
        if src_type == "metric":
            continue
        print(f"    {src_type}: {data['recall']:.1%} ({data['found']}/{data['total']})")

    # Phase 3.7: Agent timing summary (if --profile-agents used)
    agent_timings = []
    for run in runs:
        at = run.get("agent_timing", {})
        if at:
            agent_timings.append(at)
    if agent_timings:
        from collections import defaultdict
        agent_stats = defaultdict(list)
        for at in agent_timings:
            for agent_name, elapsed in at.items():
                agent_stats[agent_name].append(elapsed)
        print(f"\n  Agent timing (avg across {len(agent_timings)} runs):")
        agent_summary = {}
        for agent_name in ["query_analyzer", "query_adapter", "multi_retriever",
                           "source_evaluator", "conflict_detector", "evidence_chain",
                           "conclusion_synthesizer", "report_generator", "self_reviewer"]:
            times = agent_stats.get(agent_name, [])
            if times:
                avg = sum(times) / len(times)
                p95 = sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else max(times)
                agent_summary[agent_name] = {"avg_s": round(avg, 1), "p95_s": round(p95, 1), "n": len(times)}
                print(f"    {agent_name}: avg={avg:.1f}s, p95={p95:.1f}s (n={len(times)})")
        report["efficiency"]["agent_timing"] = agent_summary

    # Print summary
    s = report["summary"]
    print("Summary:")
    print(f"  Top-1 Accuracy:         {s['top1_accuracy']:.1%}")
    print(f"  Source Recall:          {s['source_recall']:.1%}")
    print(f"  Claim Grounding Rate:   {s['claim_grounding_rate']:.1%}")
    print(f"  Conflict Detection:     {s['conflict_detection_rate']:.1%}")
    print(f"  Latency P50 / P95:      {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    print(f"  Success Rate:           {s['success_rate']:.1%}")
    print(f"  Report Quality A/B %:   {quality_stats['grade_a_pct']:.0f}% / {quality_stats['grade_b_pct']:.0f}%")
    if s.get("sources_degraded"):
        print(f"  *** SOURCES DEGRADED: {s['degraded_sources']} — source_recall NOT comparable to healthy runs ***")

    # Phase 4: Save
    path = save_benchmark(report, RUNS_DIR, label=batch_label)
    print(f"\nBenchmark saved to: {path}")

    # Save raw runs (stripped) for metrics recomputation — always, not just
    # batch mode: U3 needs final_recommendation on the 30/300 runs, and CI's
    # lower-bound assertion reads the archived raw runs.
    label_suffix = batch_label if batch_label else "-full"
    runs_path = RUNS_DIR / f"runs{label_suffix}.json"
    runs_to_save = [_strip_run(r) for r in runs]
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

    # Run quality checklist on all reports
    quality_stats = evaluate_batch(all_runs)
    qs = quality_stats
    print("\nReport Quality (aggregate):")
    print(f"  A={qs['grade_distribution']['A']} B={qs['grade_distribution']['B']} "
          f"C={qs['grade_distribution']['C']} D={qs['grade_distribution']['D']}")
    print(f"  Mean pass count: {qs['mean_pass_count']}/5")

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

    report["quality"]["report_quality"] = quality_stats
    report["summary"]["report_quality_grade_a_pct"] = quality_stats["grade_a_pct"]

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
    print(f"  Report Quality A/B %:   {quality_stats['grade_a_pct']:.0f}% / {quality_stats['grade_b_pct']:.0f}%")
    if s.get("sources_degraded"):
        print(f"  *** SOURCES DEGRADED: {s['degraded_sources']} — source_recall NOT comparable to healthy runs ***")

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
    parser.add_argument(
        "--cases-file", type=str, default=None,
        help="Path to custom annotated cases JSON file",
    )
    parser.add_argument(
        "--no-evidence", action="store_true",
        help="Disable multi-turn evidence gathering in Stage 2 arbitration",
    )
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY,
        help=f"Max concurrent cases (default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Use cases_200.json (200 cases) instead of annotated_cases.json (50 cases)",
    )
    parser.add_argument(
        "--with-clarify", action="store_true",
        help="Run clarify module before pipeline to generate scene-aware sub_questions",
    )
    parser.add_argument(
        "--profile-agents", action="store_true",
        help="Record per-agent timing in pipeline state (agent_timing dict)",
    )
    parser.add_argument(
        "--debug-dump-dir", type=str, default=None,
        help="Dump every LLM call's raw response per case into this dir (diagnostics)",
    )
    parser.add_argument(
        "--health-check", action="store_true",
        help="Probe all retrieval sources/channels, print diagnostics, exit (no cases)",
    )
    parser.add_argument(
        "--skip-health-check", action="store_true",
        help="Skip the pre-run outbound health check",
    )
    parser.add_argument(
        "--allow-degraded", action="store_true",
        help="Proceed even when the health check reports degraded sources",
    )
    args = parser.parse_args()

    if args.debug_dump_dir:
        _setup_debug_dump(Path(args.debug_dump_dir))

    if args.health_check:
        sys.exit(asyncio.run(run_health_check()))

    if args.merge:
        asyncio.run(merge_all_batches(verbose=args.verbose))
    else:
        if not args.skip_health_check:
            hc = asyncio.run(health_check_report())
            _print_health_check(hc)
            healthy = hc.get("ok") and hc.get("tavily_direct", {}).get("ok")
            if not healthy and not args.allow_degraded:
                print("Health check FAILED — refusing to run. "
                      "Use --allow-degraded to proceed, or --skip-health-check to bypass.")
                sys.exit(1)
        n = args.cases if args.cases > 0 else None
        cf = Path(args.cases_file) if args.cases_file else None
        if cf is None and args.full:
            cf = FULL_CASES_PATH
            print(f"Using full 200-case benchmark ({cf})")
        path = asyncio.run(
            run_baseline(
                n_cases=n,
                verbose=args.verbose,
                batch=args.batch,
                batch_size=args.batch_size,
                cases_file=cf,
                gather_evidence=not args.no_evidence,
                concurrency=args.concurrency,
                with_clarify=args.with_clarify,
                profile_agents=args.profile_agents,
            )
        )
        print(f"\nDone. Report: {path}")
