"""Joint evaluation: DeepChoice pipeline + Tool Evolution Engine Tracer.

Runs DeepChoice queries with Tracer monkey-patched into BaseRetriever.search(),
collects real traces, and runs the full analysis pipeline on collected data.

Usage:
    cd D:/deepchoice-agent
    python scripts/joint_eval.py --cases 5 --verbose

Requires: .env with DEEPSEEK_API_KEY, TAVILY_API_KEY, GITHUB_TOKEN
"""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Ensure both projects are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tool-evolution-engine" / "src"))

from dotenv import load_dotenv
load_dotenv()

from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.retrievers.base import BaseRetriever
from deepchoice.utils.llm import call_model

from tool_evolution.collection.schemas import TraceReport, ErrorType, TraceType
from tool_evolution.collection.tracer import Tracer
from tool_evolution.collection.store import TraceStore
from tool_evolution.utils.database import get_connection, init_db
from tool_evolution.analysis.classifier import FailureClassifier
from tool_evolution.analysis.distiller import CounterfactualDistiller
from tool_evolution.analysis.kde_analyzer import KDEAnalyzer
from tool_evolution.analysis.dag_miner import DAGMiner
from tool_evolution.knowledge.rule_engine import RuleEngine
from tool_evolution.knowledge.param_template import ParamTemplateManager
from tool_evolution.knowledge.skill_pack import SkillPackManager
from tool_evolution.governance.governor import SkillGovernor

# ---------------------------------------------------------------------------
# Error classification helper
# ---------------------------------------------------------------------------
def classify_error(exc: Exception) -> ErrorType:
    msg = str(exc).lower()
    if any(k in msg for k in ("timeout", "timed out", "deadline")):
        return ErrorType.TIMEOUT
    if any(k in msg for k in ("quota", "ratelimit", "rate limit", "too many")):
        return ErrorType.QUOTA_EXHAUSTED
    if any(k in msg for k in ("permission", "forbidden", "unauthorized", "auth", "401", "403")):
        return ErrorType.PERMISSION_DENIED
    if any(k in msg for k in ("typeerror", "valueerror", "keyerror", "attribute", "param", "invalid")):
        return ErrorType.PARAM_ERROR
    return ErrorType.SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Monkey-patch BaseRetriever.search() with Tracer hooks
# ---------------------------------------------------------------------------
_original_search = BaseRetriever.search
_TRACER: Tracer | None = None
_TRACE_STATS = {"total": 0, "success": 0, "failure": 0, "total_latency_ms": 0, "total_tokens": 0}


async def traced_search(self, query, sub_questions, max_results=7, adapted_queries=None):
    global _TRACER, _TRACE_STATS
    t0 = time.monotonic()

    # Build trace report
    sub_qs = sub_questions if isinstance(sub_questions, list) else []
    adapted = adapted_queries if isinstance(adapted_queries, list) else (adapted_queries or [])
    report = TraceReport(
        trace_id=str(uuid.uuid4()),
        agent_id=self.__class__.__name__,
        tool_name=self.source,
        tool_version="1.0.0",
        trace_type=TraceType.ATOMIC,
        params={"query": query, "sub_questions": sub_qs, "max_results": max_results,
                "adapted_queries": adapted},
        success=False,
        latency_ms=0,
    )

    try:
        result = await _original_search(self, query, sub_questions, max_results, adapted_queries)
        report.success = result["status"] == "success"
        report.latency_ms = result.get("latency_ms", int((time.monotonic() - t0) * 1000))
        report.result = {"result_count": len(result.get("results", [])), "source": result["source"]}
        report.token_count = len(json.dumps(result))
        if not report.success:
            report.error_type = ErrorType.SERVICE_UNAVAILABLE
            report.error_message = result.get("error", "unknown error")
        _TRACE_STATS["success"] += 1
    except Exception as exc:
        report.success = False
        report.latency_ms = int((time.monotonic() - t0) * 1000)
        report.error_type = classify_error(exc)
        report.error_message = str(exc)
        _TRACE_STATS["failure"] += 1
        result = {"source": self.source, "status": "failed", "results": [], "error": str(exc),
                  "latency_ms": report.latency_ms}

    _TRACE_STATS["total"] += 1
    _TRACE_STATS["total_latency_ms"] += report.latency_ms
    _TRACE_STATS["total_tokens"] += report.token_count

    if _TRACER:
        await _TRACER.report(report)

    return result


BaseRetriever.search = traced_search


# ---------------------------------------------------------------------------
# DeepChoice runner
# ---------------------------------------------------------------------------
async def run_deepchoice_query(case: dict, verbose: bool = False) -> dict:
    """Run a single DeepChoice query with 5-minute timeout."""
    task = {
        "query": case["query"],
        "scene_context": case.get("scene", "solo"),
        "constraints": [],
        "report_format": "what_why_how",
    }
    orchestrator = ChiefEditorAgent(task)
    state = await asyncio.wait_for(orchestrator.run_research_task(), timeout=300)
    if verbose:
        agent_steps = len(state.get("agent_log", []))
        search_results = len(state.get("search_results", []))
        print(f"  [{case['id']}] {case['query'][:60]}... "
              f"agents={agent_steps} retrievals={search_results}")
    return state


async def run_joint_eval(n_cases: int = 5, verbose: bool = False, cases_file: str | None = None):
    global _TRACER

    # Load test cases
    if cases_file:
        cases_path = Path(cases_file)
    else:
        cases_path = Path(__file__).resolve().parent.parent / "tests" / "test_cases" / "known_cases.json"
    with open(cases_path) as f:
        cases = json.load(f)
    if n_cases and n_cases > 0:
        cases = cases[:n_cases]

    print("=" * 60)
    print("JOINT EVALUATION: DeepChoice + Tool Evolution Engine")
    print("=" * 60)
    print(f"\nTest cases: {len(cases)}")
    print(f"API check: DEEPSEEK_KEY={'set' if os.getenv('DEEPSEEK_API_KEY') else 'MISSING'}, "
          f"TAVILY_KEY={'set' if os.getenv('TAVILY_API_KEY') else 'MISSING'}")

    # Initialize Tool Evolution Engine DB (use explicit path, not settings relative path)
    engine_db = Path(__file__).resolve().parent.parent.parent / "tool-evolution-engine" / "data" / "joint_eval.db"
    engine_db.parent.mkdir(parents=True, exist_ok=True)
    import aiosqlite
    conn = await aiosqlite.connect(str(engine_db))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await init_db(conn)
    tracer = Tracer(conn, batch_size=100, flush_interval_s=5)
    await tracer.start()
    _TRACER = tracer

    store = TraceStore(conn)
    print(f"Engine DB: {engine_db}")

    # ---- PHASE 1: Run DeepChoice queries with Tracer ----
    print(f"\n{'=' * 40}")
    print("PHASE 1: Collecting traces from DeepChoice")
    print("=" * 40)

    t0_total = time.monotonic()
    results = []
    ok = 0
    fail = 0
    for i, case in enumerate(cases):
        elapsed_so_far = time.monotonic() - t0_total
        avg_per_case = elapsed_so_far / max(i, 1)
        eta_s = avg_per_case * (len(cases) - i)
        eta_str = f"{eta_s/60:.0f}m" if eta_s > 60 else f"{eta_s:.0f}s"
        print(f"[{i+1}/{len(cases)}] {case['id']}: {case['query'][:70]}... (ETA {eta_str})")
        t0 = time.monotonic()
        try:
            state = await run_deepchoice_query(case, verbose=verbose)
            elapsed = time.monotonic() - t0
            ok += 1
            results.append({"case": case, "state": state, "error": None, "elapsed_s": round(elapsed, 1)})
            print(f"  OK ({elapsed:.0f}s) retrievals={len(state.get('search_results', []))} | {ok} ok / {fail} fail")
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            fail += 1
            results.append({"case": case, "state": None, "error": "timeout (300s)", "elapsed_s": round(elapsed, 1)})
            print(f"  TIMEOUT ({elapsed:.0f}s) | {ok} ok / {fail} fail")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            fail += 1
            results.append({"case": case, "state": None, "error": str(exc), "elapsed_s": round(elapsed, 1)})
            print(f"  FAIL ({elapsed:.0f}s) — {exc} | {ok} ok / {fail} fail")

    await tracer.stop()
    total_elapsed = time.monotonic() - t0_total

    # Collect trace stats
    trace_count = len(await store.get_all_traces(limit=max_trace_limit))
    failures = await store.count_failures(None)

    print(f"\nPhase 1 complete in {total_elapsed:.1f}s")
    print(f"  Queries: {len(cases)} ({sum(1 for r in results if r['error'] is None)} success, "
          f"{sum(1 for r in results if r['error'])}) failed")
    print(f"  Traces collected: {trace_count} ({failures} failures, "
          f"{trace_count - failures} success)")

    # ---- PHASE 2: Run analysis pipeline ----
    max_trace_limit = max(len(cases) * 10, 5000)
    print(f"\n{'=' * 40}")
    print("PHASE 2: Analysis Pipeline")
    print("=" * 40)

    # 2a. Failure Classifier
    print("\n[2a] Failure Classifier")
    cursor = await conn.execute("SELECT * FROM trajectories WHERE success=0")
    failed_rows = [dict(r) for r in await cursor.fetchall()]
    if len(failed_rows) >= 10:
        clf = FailureClassifier()
        clf.train(failed_rows)
        importance = clf.feature_importance()
        top5 = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"  Training samples: {len(failed_rows)}")
        print(f"  Top 5 features: {top5[:3]}")

        if len(failed_rows) >= 20:
            import numpy as np
            split = int(len(failed_rows) * 0.7)
            train_set = failed_rows[:split]
            test_set = failed_rows[split:]
            clf2 = FailureClassifier()
            clf2.train(train_set)
            y_true, y_pred = [], []
            for t in test_set:
                try:
                    y_true.append(t["error_type"])
                    y_pred.append(clf2.predict(t).value)
                except Exception:
                    pass
            if y_true:
                acc = sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)
                print(f"  Accuracy (holdout): {acc:.1%} ({len(y_true)} test samples)")

                # Per-class breakdown
                classes = sorted(set(y_true + y_pred))
                for c in classes:
                    tp = sum(1 for a, b in zip(y_true, y_pred) if a == c and b == c)
                    sup = sum(1 for a in y_true if a == c)
                    print(f"    {c}: {tp}/{sup} correct")
    else:
        print(f"  Insufficient failures ({len(failed_rows)}), skipping classifier training")

    # 2b. Distill rules from failures
    print("\n[2b] Rule Distillation")
    distiller = CounterfactualDistiller()
    rules = distiller.distill_batch(failed_rows)
    engine = RuleEngine(conn)
    for rule in rules:
        await engine.add_rule(rule)
    print(f"  Distilled {len(rules)} rules from {len(failed_rows)} failures")
    for r in rules:
        print(f"    - {r['rule_type']}: {r['tool_name']}")

    # 2c. KDE Parameter Analysis
    print("\n[2c] KDE Parameter Analysis")
    mgr = ParamTemplateManager(conn)
    tools_seen = set()
    for trace in await store.get_all_traces(limit=max_trace_limit):
        tools_seen.add((trace["tool_name"], trace["tool_version"]))

    kde_results = {}
    for tool_name, tool_ver in tools_seen:
        tmpl = await mgr.generate(tool_name, tool_ver)
        if tmpl:
            kde_results[tool_name] = len(tmpl)
            print(f"  {tool_name} v{tool_ver}: {len(tmpl)} params discovered")
    if not kde_results:
        print("  Insufficient successful traces for KDE (need >= 30 per tool)")

    # 2d. DAG Mining
    print("\n[2d] DAG Pattern Mining")
    all_traces = await store.get_all_traces(limit=max_trace_limit)
    dag_traces_with_root = [t for t in all_traces if t.get("trace_type") == "task_root"]
    if len(dag_traces_with_root) >= 3:
        miner = DAGMiner(min_support=0.1, max_nodes=10)
        discovered = miner.mine(all_traces)
        skill_mgr = SkillPackManager(conn)
        for d in discovered:
            await skill_mgr.add_discovery(d)
        print(f"  Tasks with DAG structure: {len(dag_traces_with_root)}")
        print(f"  Discovered patterns: {len(discovered)}")
        for d in discovered:
            print(f"    - {d['name'][:70]} (freq={d['frequency']:.1%})")
    else:
        print(f"  Insufficient task-root traces ({len(dag_traces_with_root)}), skipping DAG mining")

    # 2e. Governance Scoring
    print("\n[2e] Skill Governance")
    skill_mgr = SkillPackManager(conn)
    discoveries = await skill_mgr.list_discoveries()
    if discoveries:
        for disc in discoveries[:5]:
            dep_id = await skill_mgr.promote_to_deployed(disc["id"])
            gov = SkillGovernor(conn)
            # Score based on real trace stats
            score = await gov.score_skill(dep_id)
            dep = await skill_mgr.get_deployed(disc["name"])
            print(f"  {disc['name'][:50]}: score={score:.1f} status={dep['status'] if dep else '?'}")
    else:
        print("  No discovered skills to govern")

    # ---- PHASE 3: Before/After estimation ----
    print(f"\n{'=' * 40}")
    print("PHASE 3: Before/After Estimation")
    print("=" * 40)

    # Estimate based on real trace patterns
    total_retrievals = _TRACE_STATS["total"]
    total_failures = _TRACE_STATS["failure"]
    total_latency = _TRACE_STATS["total_latency_ms"]
    total_tokens = _TRACE_STATS["total_tokens"]

    # Optimistic estimate: rules catch ~15% of failures, templates reduce tokens ~10%
    estimated_failure_reduction = min(round(len(rules) / max(total_failures, 1) * 100), 50)
    estimated_token_reduction = min(round(len(kde_results) * 3), 30)

    print(f"  Baseline:")
    print(f"    Retrievals: {total_retrievals} ({_TRACE_STATS['success']} success, {total_failures} failed)")
    print(f"    Avg latency: {total_latency / max(total_retrievals, 1):.0f}ms")
    print(f"    Est. total tokens: {total_tokens:,}")

    post_rules = max(total_failures - len(rules), 0)
    print(f"\n  Estimated after optimization:")
    print(f"    Expected failures (with {len(rules)} rules): ~{post_rules} "
          f"({round((1 - post_rules / max(total_failures, 1)) * 100)}% reduction)")
    print(f"    Expected token savings (with {len(kde_results)} templates): "
          f"~{estimated_token_reduction}%")
    print(f"    Expected latency improvement: ~{estimated_failure_reduction}% "
          f"(fewer retries from prevented failures)")

    # ---- Summary ----
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    pipeline_ok = sum(1 for r in results if r["error"] is None)
    print(f"DeepChoice: {pipeline_ok}/{len(cases)} queries succeeded ({total_elapsed:.0f}s)")
    print(f"Traces: {trace_count} ({failures} failures)")
    print(f"Rules distilled: {len(rules)}")
    print(f"KDE templates: {sum(kde_results.values())} params across {len(kde_results)} tools")
    print(f"DAG patterns: {len(discovered) if 'discovered' in dir() else 0}")

    await conn.close()
    return {
        "deepchoice": {"success": pipeline_ok, "total": len(cases), "elapsed_s": round(total_elapsed, 1)},
        "traces": {"total": trace_count, "failures": failures},
        "analysis": {
            "classifier_samples": len(failed_rows),
            "rules": len(rules),
            "kde_tools": len(kde_results),
            "kde_params": sum(kde_results.values()),
            "dag_patterns": len(discovered) if 'discovered' in dir() else 0,
        },
        "before_after": {
            "failure_reduction_pct": round((1 - post_rules / max(total_failures, 1)) * 100),
            "token_reduction_pct_est": estimated_token_reduction,
        },
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=0, help="Number of test cases to run (default: all from file)")
    parser.add_argument("--cases-file", type=str, default=None, help="Path to JSON test cases file")
    parser.add_argument("--verbose", action="store_true", help="Show per-agent output")
    args = parser.parse_args()

    result = asyncio.run(run_joint_eval(n_cases=args.cases, verbose=args.verbose, cases_file=args.cases_file))
    print(f"\nDone. Full result: {json.dumps(result, indent=2, ensure_ascii=False)}")
