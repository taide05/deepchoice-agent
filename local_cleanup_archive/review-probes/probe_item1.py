"""Item 1: execute a low-confidence run and prove the review survives, and inspect
the compiled graph's edges for self_reviewer."""
import asyncio, inspect, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\deepchoice-precodex\src")
sys.path.insert(0, r"D:\deepchoice-precodex")

from deepchoice.agents import orchestrator as orch

SENTINEL_GAP = "SENTINEL-GAP-9f3a: the wrong scale was not reconciled"

# 1. Compiled graph edges.
agent = orch.ChiefEditorAgent({"query": "t"})
chain = agent.init_research_team()
g = chain.get_graph()
edges = [(e.source, e.target, getattr(e, "conditional", False)) for e in g.edges]
print("=== graph edges out of self_reviewer ===")
for s, t, c in edges:
    if s == "self_reviewer" or t == "self_reviewer":
        print(f"  {s} -> {t} conditional={c}")
print("  any conditional edge:", any(c for _, _, c in edges))
print("  END in targets:", any(t == "__end__" for _, t, _ in edges))

# 2. Execute.
from tests.test_pipeline import (MOCK_EVIDENCE_CHAINS, MOCK_QUERY_RESULT, MOCK_REPORT,
                                 MOCK_SEARCH_RESULTS, MOCK_SOURCE_SCORES, _make_mock_run)

REVIEW = {"confidence": "low", "knowledge_gaps": [SENTINEL_GAP],
          "quality_signals": [{"agent": "self_reviewer", "note": "low"}]}

calls = {"review": 0, "report": 0, "analyzer": 0, "render": 0}


async def mock_review(*a, **k):
    calls["review"] += 1
    return dict(REVIEW)


async def mock_report(*a, **k):
    calls["report"] += 1
    return {"report": MOCK_REPORT}


async def mock_analyzer(*a, **k):
    calls["analyzer"] += 1
    return MOCK_QUERY_RESULT


task = {"query": "t", "scene_context": "team", "constraints": [], "report_format": "what_why_how"}
a2 = orch.ChiefEditorAgent(task)
orch.QueryAnalyzerAgent.run = _make_mock_run(MOCK_QUERY_RESULT)
orch.MultiRetrieverAgent.run = _make_mock_run({"search_results": MOCK_SEARCH_RESULTS, "partial_failures": []})
orch.SourceEvaluatorAgent.run = _make_mock_run({"source_scores": MOCK_SOURCE_SCORES})
orch.ConflictDetectorAgent.run = _make_mock_run({"conflicts": []})
orch.EvidenceChainAgent.run = _make_mock_run({"evidence_chains": MOCK_EVIDENCE_CHAINS})
orch.ReportGeneratorAgent.run = mock_report
orch.SelfReviewerAgent.run = mock_review

result = asyncio.run(a2.run_research_task())

print("\n=== execution ===")
print("  reviewer calls:", calls["review"])
print("  report_generator calls:", calls["report"])
print("  current_phase:", result.get("current_phase"))
print("  confidence in final state:", result.get("confidence"))
print("  sentinel gap survives into final state:", SENTINEL_GAP in (result.get("knowledge_gaps") or []))
print("  final report is the reviewed report:", result.get("report") == MOCK_REPORT)
print("  review quality signal present:",
      any(s.get("agent") == "self_reviewer" for s in (result.get("quality_signals") or [])))
print("  retry_count:", result.get("retry_count"))
print("  analyzer invocations (1 == no restart):", calls["analyzer"])
