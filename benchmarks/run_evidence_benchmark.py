"""Benchmark: inline multi-turn evidence gathering vs single-pass pro arbitration.

Tests conflict_detector's Stage 2 evidence-gathering loop on hand-crafted
ambiguous conflict pairs, comparing "pro-only" vs "pro+evidence" quality.

Usage:
    cd D:/deepchoice-agent
    python -m benchmarks.run_evidence_benchmark
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from dotenv import load_dotenv
load_dotenv()

from deepchoice.utils.llm import call_model
from deepchoice.agents.conflict_detector import _gather_evidence, ARBITRATION_PROMPT

# ---------------------------------------------------------------------------
# Test cases: deliberately ambiguous conflict pairs
# ---------------------------------------------------------------------------

TEST_CASES = [
    {
        "id": "E001",
        "topic": "Redis vs Memcached for session caching",
        "claim_a": "Redis is better because of persistence and data structures",
        "claim_b": "Memcached is faster and simpler for pure caching workloads",
        "score_a": 8.0, "score_b": 7.5,
        "authority_a": 8, "authority_b": 7,
        "evidence_a": "citation", "evidence_b": "benchmark",
    },
    {
        "id": "E002",
        "topic": "GraphQL vs REST for mobile API backends",
        "claim_a": "GraphQL reduces over-fetching and improves mobile battery life",
        "claim_b": "REST with HTTP/2 is simpler and performs just as well for mobile",
        "score_a": 7.0, "score_b": 8.0,
        "authority_a": 6, "authority_b": 8,
        "evidence_a": "citation", "evidence_b": "citation",
    },
    {
        "id": "E003",
        "topic": "Kafka vs RabbitMQ for event-driven microservices",
        "claim_a": "Kafka's log-based architecture is superior for event sourcing",
        "claim_b": "RabbitMQ's flexible routing is better for most microservice patterns",
        "score_a": 8.5, "score_b": 8.0,
        "authority_a": 9, "authority_b": 7,
        "evidence_a": "citation", "evidence_b": "benchmark",
    },
    {
        "id": "E004",
        "topic": "PostgreSQL vs MongoDB for content management systems",
        "claim_a": "PostgreSQL JSONB matches MongoDB's flexibility with better ACID guarantees",
        "claim_b": "MongoDB's document model is more natural for CMS with faster iteration",
        "score_a": 7.5, "score_b": 7.5,
        "authority_a": 8, "authority_b": 6,
        "evidence_a": "benchmark", "evidence_b": "citation",
    },
    {
        "id": "E005",
        "topic": "Docker Compose vs Kubernetes for staging environments",
        "claim_a": "Docker Compose is simpler and faster for staging with fewer moving parts",
        "claim_b": "Kubernetes provides production parity and avoids staging-prod drift",
        "score_a": 6.5, "score_b": 8.0,
        "authority_a": 5, "authority_b": 9,
        "evidence_a": "citation", "evidence_b": "citation",
    },
]


def _make_prompt(tc: dict, extra_evidence: str = "") -> list[dict]:
    claim_a = tc["claim_a"]
    claim_b = tc["claim_b"]
    if extra_evidence:
        claim_a = f"{tc['claim_a']}\n\n[Additional evidence gathered: {extra_evidence}]"
        claim_b = f"{tc['claim_b']}\n\n[Additional evidence gathered: {extra_evidence}]"
    return [{
        "role": "user",
        "content": ARBITRATION_PROMPT.format(
            topic=tc["topic"],
            score_a=tc["score_a"], authority_a=tc["authority_a"],
            evidence_a=tc["evidence_a"], claim_a=claim_a,
            score_b=tc["score_b"], authority_b=tc["authority_b"],
            evidence_b=tc["evidence_b"], claim_b=claim_b,
        ),
    }]


async def run_baseline(tc: dict) -> dict:
    """Single-pass pro arbitration without evidence gathering."""
    t0 = time.monotonic()
    try:
        result = await call_model(
            _make_prompt(tc), model="qwen-flash",
            response_format="json", timeout=300.0,
        )
    except Exception as e:
        result = {"resolution": "error", "confidence": "low", "reasoning": str(e)}
    elapsed = round(time.monotonic() - t0, 1)

    return {
        "method": "pro-only",
        "case": tc["id"],
        "elapsed_s": elapsed,
        **result,
    }


async def run_evidence(tc: dict) -> dict:
    """Evidence gathering + pro arbitration."""
    t0 = time.monotonic()
    evidence = ""
    evidence_elapsed = 0.0
    try:
        ev_t0 = time.monotonic()
        evidence = await _gather_evidence(
            topic=tc["topic"], claim_a=tc["claim_a"], claim_b=tc["claim_b"],
            max_iterations=3,
        )
        evidence_elapsed = round(time.monotonic() - ev_t0, 1)
    except Exception as e:
        evidence = f"Gathering failed: {e}"

    try:
        result = await call_model(
            _make_prompt(tc, extra_evidence=evidence),
            model="qwen-flash", response_format="json", timeout=300.0,
        )
    except Exception as e:
        result = {"resolution": "error", "confidence": "low", "reasoning": str(e)}
    elapsed = round(time.monotonic() - t0, 1)

    return {
        "method": "pro+evidence",
        "case": tc["id"],
        "elapsed_s": elapsed,
        "evidence_elapsed_s": evidence_elapsed,
        "evidence_summary": evidence[:300],
        **result,
    }


async def main():
    print("=" * 60)
    print("Evidence Gathering Benchmark")
    print(f"Cases: {len(TEST_CASES)}, each run twice (baseline + evidence)")
    print("=" * 60)

    baseline_results = []
    evidence_results = []

    for tc in TEST_CASES:
        print(f"\n[{tc['id']}] {tc['topic']}")
        print(f"  A (score={tc['score_a']}): {tc['claim_a'][:60]}...")
        print(f"  B (score={tc['score_b']}): {tc['claim_b'][:60]}...")

        # Baseline
        print("  Running baseline (pro-only)...")
        b = await run_baseline(tc)
        baseline_results.append(b)
        print(f"    confidence={b['confidence']}, resolution={b['resolution']}, "
              f"elapsed={b['elapsed_s']}s")

        # Evidence
        print("  Running evidence gathering + pro...")
        e = await run_evidence(tc)
        evidence_results.append(e)
        print(f"    confidence={e['confidence']}, resolution={e['resolution']}, "
              f"elapsed={e['elapsed_s']}s (evidence={e.get('evidence_elapsed_s', 0)}s)")

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    print(f"\n{'Case':<8} {'Method':<14} {'Confidence':<12} {'Resolution':<20} {'Elapsed':<10}")
    print("-" * 64)
    for b, e in zip(baseline_results, evidence_results):
        print(f"{b['case']:<8} {b['method']:<14} {b['confidence']:<12} "
              f"{b['resolution']:<20} {b['elapsed_s']:<10.1f}")
        print(f"{'':<8} {e['method']:<14} {e['confidence']:<12} "
              f"{e['resolution']:<20} {e['elapsed_s']:<10.1f}")

    # Aggregate
    def conf_up(r1, r2):
        order = {"low": 0, "medium": 1, "high": 2}
        return order.get(r2["confidence"], 0) > order.get(r1["confidence"], 0)

    improved = sum(1 for b, e in zip(baseline_results, evidence_results) if conf_up(b, e))
    same = sum(1 for b, e in zip(baseline_results, evidence_results)
               if b["confidence"] == e["confidence"] and not conf_up(b, e))
    degraded = len(TEST_CASES) - improved - same

    total_baseline = sum(r["elapsed_s"] for r in baseline_results)
    total_evidence = sum(r["elapsed_s"] for r in evidence_results)
    avg_evidence_time = sum(r.get("evidence_elapsed_s", 0) for r in evidence_results) / len(evidence_results)

    print("\nConfidence changes:")
    print(f"  Improved:   {improved}/{len(TEST_CASES)}")
    print(f"  Same:       {same}/{len(TEST_CASES)}")
    print(f"  Degraded:   {degraded}/{len(TEST_CASES)}")
    print("\nTotal latency:")
    print(f"  Baseline:   {total_baseline:.1f}s")
    print(f"  Evidence:   {total_evidence:.1f}s (avg evidence gathering: {avg_evidence_time:.1f}s)")

    # Save report
    BENCHMARKS_DIR = Path(__file__).resolve().parent
    RUNS_DIR = BENCHMARKS_DIR / "runs" / "evidence-benchmark"
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    report = {
        "timestamp": timestamp,
        "cases": TEST_CASES,
        "baseline": baseline_results,
        "evidence": evidence_results,
        "summary": {
            "improved": improved,
            "same": same,
            "degraded": degraded,
            "total_baseline_s": total_baseline,
            "total_evidence_s": total_evidence,
            "avg_evidence_gathering_s": avg_evidence_time,
        },
    }
    out_path = RUNS_DIR / f"benchmark-{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nReport saved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
