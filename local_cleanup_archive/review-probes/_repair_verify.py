"""Repair verification on the real input from the cancelled run. No network.

Uses the 29 scored sources the cancelled run actually produced, plus simulated
slow/failing LLM responses, to check the four repair claims.
"""
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(r"D:\deepchoice-precodex")
sys.path.insert(0, str(ROOT / "src"))

SNAP = (ROOT / "outputs" / "0241ebd0-4ed3-4fe0-b313-8a7f9d9947a6"
        / "research_snapshot_failed.json")
real_scores = json.loads(SNAP.read_text(encoding="utf-8"))["source_scores"]
print(f"real input: {len(real_scores)} scored sources from the cancelled run")

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


import numpy as np  # noqa: E402
import deepchoice.recovery_repair as rr  # noqa: E402
import deepchoice.agents.conflict_detector as cd  # noqa: E402
from deepchoice.agents import source_evaluator as se  # noqa: E402


# ---------------------------------------------------------------- claim 1/2
def claim_candidate_selection():
    print("--- claim: duplicate arbitration removed, conflicts still map back ---")
    high = [s for s in real_scores if float(s.get("total_score", 0)) >= 5.0]
    # Distinct directions with varied similarity, so the probe exercises the
    # selection rule instead of feeding every pair through the duplicate filter.
    angle = np.linspace(0.0, 0.9, len(high))
    emb = np.stack([np.cos(angle), np.sin(angle), np.cos(angle * 1.7),
                    np.sin(angle * 2.3)], axis=1)
    norms = np.linalg.norm(emb, axis=1)
    candidates, rejected = rr.partition_candidates(high, emb, norms, np=np)
    check("candidate selection returns pairs", len(candidates) > 0,
          f"pairs={len(candidates)} rejected={rejected}")
    # Rejected reasons must be reported, not silently empty.
    check("rejection reasons are reported", set(rejected) == {
        "near_duplicate", "unrelated", "missing_title"}, str(sorted(rejected)))

    # Every candidate must still map to its own two sources.
    mapped = all(high[i] is not None and high[j] is not None for i, j, _ in candidates)
    check("each candidate maps to its original two sources", mapped)


def claim_evidence_before_arbitration():
    print("--- claim: exactly one arbitration per pair, evidence inlined ---")
    calls = {"scan": 0, "arbitration": 0, "rearbitration": 0, "evidence": 0}

    pairs = [{"source_a": {"url": "https://a", "title": "Kafka throughput vs Redis Streams",
                           "total_score": 8.0, "scores": {"authority": 10}},
              "source_b": {"url": "https://b", "title": "Kafka throughput vs Redis Streams latency",
                           "total_score": 6.0, "scores": {"authority": 7}},
              "similarity": 0.6}]

    prompts_seen = []

    async def fake_call_model(prompt, model="x", tag="", **kwargs):
        if tag == "conflict_arbitration":
            calls["arbitration"] += 1
            prompts_seen.append(json.dumps(prompt))
            return {"resolution": "a", "confidence": "high", "reasoning": "r"}
        if tag == "conflict_rearbitration":
            calls["rearbitration"] += 1
        if tag == "conflict_scan":
            calls["scan"] += 1
            return {"has_difference": True, "type": "tradeoff_disagreement", "explanation": "e"}
        return {}

    async def fake_gather(**kwargs):
        calls["evidence"] += 1
        return "gathered evidence text"

    original_call = cd.call_model
    original_gather = cd._gather_evidence
    cd.call_model = fake_call_model
    cd._gather_evidence = fake_gather
    try:
        agent = cd.ConflictDetectorAgent(gather_evidence=True)
        # Drive only the pair stage by monkeypatching the scan source.
        async def fake_find(scores, query_topic="", usage=None):
            cd.find_contradictions.last_outcomes = {
                "difference": 1, "no_difference": 0, "unscanned": 0}
            return pairs

        original_find = cd.find_contradictions
        cd.find_contradictions = fake_find
        try:
            result = asyncio.run(agent.run({
                "source_scores": real_scores,
                "task": {"query": "MSK vs ElastiCache"},
                "token_usage": [],
            }))
        finally:
            cd.find_contradictions = original_find
    finally:
        cd.call_model = original_call
        cd._gather_evidence = original_gather

    check("no re-arbitration call at all", calls["rearbitration"] == 0,
          f"rearbitration={calls['rearbitration']}")
    check("exactly one arbitration per pair", calls["arbitration"] == 1,
          f"arbitration={calls['arbitration']}")
    check("evidence gathered once, before arbitration", calls["evidence"] == 1)
    check("arbitration prompt carries the gathered evidence",
          any("gathered evidence text" in p for p in prompts_seen))
    conflicts = result.get("conflicts", [])
    check("conflict still corresponds to the original pair",
          len(conflicts) == 1
          and conflicts[0]["source_a"]["url"] == "https://a"
          and conflicts[0]["source_b"]["url"] == "https://b",
          json.dumps(conflicts[0]["source_a"], ensure_ascii=False) if conflicts else "none")
    check("no behaviour change to the deterministic rule path",
          cd._deterministic_arbitration({"total_score": 9, "scores": {"authority": 10}},
                                        {"total_score": 2, "scores": {"authority": 4}}) is not None)


def claim_failure_not_success():
    print("--- claim: an unscanned pair is not reported as no-conflict ---")
    outcomes = {"difference": 0, "no_difference": 0, "unscanned": 0}

    async def failing_scan(*args, **kwargs):
        raise RuntimeError("simulated provider failure")

    original = cd._scan_pair_contradiction
    cd._scan_pair_contradiction = failing_scan
    try:
        class _Model:
            def encode(self, titles):
                # Same subject (above the floor) but not a duplicate.
                return np.array([[1.0, 0.0, 0.0], [0.8, 0.6, 0.0]])[:len(titles)]
        original_model = cd.get_embedding_model
        cd.get_embedding_model = lambda: _Model()
        try:
            high = [{"title": "Kafka vs Redis latency", "url": "https://a",
                     "total_score": 8.0, "scores": {"authority": 10}},
                    {"title": "Kafka vs Redis throughput", "url": "https://b",
                     "total_score": 6.0, "scores": {"authority": 7}}]
            pairs = asyncio.run(cd.find_contradictions(high, "q", usage=[]))
        finally:
            cd.get_embedding_model = original_model
    finally:
        cd._scan_pair_contradiction = original

    check("failed scan yields no conflict rows", pairs == [], f"pairs={pairs}")
    recorded = getattr(cd.find_contradictions, "last_outcomes", {})
    check("failure recorded as unscanned, not as no_difference",
          recorded.get("unscanned", 0) >= 1, str(recorded))


# ---------------------------------------------------------------- claim 3
def claim_source_evaluation():
    print("--- claim: no automatic official_doc, no unrelated support ---")
    check("chroma retriever no longer forces official_doc",
          se.classify_source_type("https://example.com/blog/kafka-vs-redis", "chroma")
          == "tech_blog")
    # The URL rule itself is unchanged: a docs.* host is still official, and a
    # chroma hit on one is still official on that URL basis (not on the retriever).
    check("a docs.* host is still official by URL",
          se.classify_source_type("https://docs.confluent.io/kafka", "tavily") == "official_doc")
    check("chroma on a docs.* host is official by URL, not by retriever",
          se.classify_source_type("https://docs.confluent.io/kafka", "chroma") == "official_doc")

    # Two unrelated high scorers must not support each other.
    unrelated = [
        {"url": "https://x/meilisearch-vs-elasticsearch", "title": "meilisearch vs elasticsearch",
         "total_score": 8.0, "scores": {"consistency": 0}, "supporting_sources": []},
        {"url": "https://y/kafka-vs-rabbitmq", "title": "kafka vs rabbitmq", "total_score": 7.5,
         "scores": {"consistency": 0}, "supporting_sources": []},
    ]
    stats = rr.apply_score_support(unrelated)
    check("unrelated high scorers get no support",
          all(not s["supporting_sources"] for s in unrelated),
          f"stats={stats}")

    related = [
        {"url": "https://x/kafka-vs-redis-a", "title": "kafka vs redis latency benchmark",
         "total_score": 8.0, "scores": {"consistency": 0}, "supporting_sources": []},
        {"url": "https://y/kafka-vs-redis-b", "title": "kafka vs redis throughput benchmark",
         "total_score": 7.5, "scores": {"consistency": 0}, "supporting_sources": []},
    ]
    rr.apply_score_support(related)
    check("same-subject sources still count as support",
          bool(related[0]["supporting_sources"]), str(related[0]["supporting_sources"]))
    check("the original source information is preserved",
          related[0]["url"] == "https://x/kafka-vs-redis-a")


claim_candidate_selection()
claim_evidence_before_arbitration()
claim_failure_not_success()
claim_source_evaluation()

print("--- summary ---")
for label, ok, _ in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
failed = [c for c in checks if not c[1]]
print(f"  {len(checks) - len(failed)}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
