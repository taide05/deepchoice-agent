from unittest.mock import AsyncMock, patch

import pytest

from deepchoice.agents.orchestrator import ChiefEditorAgent

MOCK_QUERY_RESULT = {
    "sub_questions": [
        "Async performance and throughput comparison",
        "Ecosystem and community activity comparison",
        "Learning curve and developer experience",
        "Scenario fit for API development",
        "Deployment complexity comparison",
    ],
    "scene_context": "solo",
    "constraints": ["python"],
}

MOCK_SEARCH_RESULTS = [{
    "source": "tavily",
    "status": "success",
    "results": [
        {"url": "https://example.com/1", "title": "A is faster than B in benchmarks", "snippet": "Benchmark results show...", "date": "2026-06-01"},
        {"url": "https://example.com/2", "title": "B has better developer experience", "snippet": "DX comparison...", "date": "2026-05-15"},
    ],
    "error": None,
    "latency_ms": 500,
}]

MOCK_SOURCE_SCORES = [{
    "url": "https://example.com/1",
    "title": "A is faster than B in benchmarks",
    "source_type": "tech_blog",
    "scores": {"authority": 7, "timeliness": 10, "consistency": 6, "verifiability": 8},
    "total_score": 7.5,
    "evidence_type": "benchmark",
    "supporting_sources": [],
    "contradicting_sources": [],
    "rank": 1,
}]

MOCK_EVIDENCE_CHAINS = [{
    "conclusion": "A is faster than B in benchmarks",
    "sources": [{"url": "https://example.com/1", "title": "A vs B benchmark", "snippet": "...", "score": 7.5}],
    "evidence_strength": "moderate",
    "disputed": False,
}]

MOCK_REPORT = "# Test Report\n\nThis is a test report."
MOCK_REVIEW_HIGH = {"confidence": "high", "knowledge_gaps": []}
MOCK_REVIEW_LOW = {"confidence": "low", "knowledge_gaps": ["gap1"]}
MOCK_REVIEW_MEDIUM = {"confidence": "medium", "knowledge_gaps": []}


def _make_mock_run(return_value):
    async def _mock(*args, **kwargs):
        return return_value
    return _mock


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_completes_with_high_confidence(self):
        task = {
            "query": "TestA vs TestB for API development",
            "scene_context": "solo",
            "constraints": ["python"],
            "report_format": "what_why_how",
        }
        orchestrator = ChiefEditorAgent(task)

        with (
            patch("deepchoice.agents.orchestrator.QueryAnalyzerAgent.run", new=_make_mock_run(MOCK_QUERY_RESULT)),
            patch("deepchoice.agents.orchestrator.MultiRetrieverAgent.run", new=_make_mock_run({"search_results": MOCK_SEARCH_RESULTS, "partial_failures": []})),
            patch("deepchoice.agents.orchestrator.SourceEvaluatorAgent.run", new=_make_mock_run({"source_scores": MOCK_SOURCE_SCORES})),
            patch("deepchoice.agents.orchestrator.ConflictDetectorAgent.run", new=_make_mock_run({"conflicts": []})),
            patch("deepchoice.agents.orchestrator.EvidenceChainAgent.run", new=_make_mock_run({"evidence_chains": MOCK_EVIDENCE_CHAINS})),
            patch("deepchoice.agents.orchestrator.ReportGeneratorAgent.run", new=_make_mock_run({"report": MOCK_REPORT})),
            patch("deepchoice.agents.orchestrator.SelfReviewerAgent.run", new=_make_mock_run(MOCK_REVIEW_HIGH)),
        ):
            result = await orchestrator.run_research_task()

        assert result["confidence"] == "high"
        assert result["report"] == MOCK_REPORT
        assert len(result["evidence_chains"]) == 1
        assert "retry_count" not in result, "the removed retry state must not come back"
        assert result["current_phase"] == "self_reviewer"
        all_nodes = {
            "query_analyzer", "query_adapter", "multi_retriever", "source_evaluator",
            "conflict_detector", "evidence_chain", "conclusion_synthesizer",
            "report_generator", "self_reviewer",
        }
        assert all_nodes <= set(result["agent_timing"].keys())

    @pytest.mark.asyncio
    async def test_pipeline_ends_after_review_without_discarding_it(self):
        """A low-confidence review ends the run instead of restarting the graph.

        The restart entered at query_analyzer and overwrote the reviewer's own
        output, so the run served a pre-review report while having paid for the
        review, and the loop could repeat because the restart reset the pass
        counter. The reviewed result is terminal; confidence and knowledge_gaps
        already record that it is provisional.
        """
        task = {"query": "test", "scene_context": "team", "constraints": [], "report_format": "evidence_first"}
        orchestrator = ChiefEditorAgent(task)

        call_count = {"review": 0, "analyzer": 0}

        async def mock_review(*args, **kwargs):
            call_count["review"] += 1
            return MOCK_REVIEW_LOW

        async def mock_analyzer(*args, **kwargs):
            call_count["analyzer"] += 1
            return MOCK_QUERY_RESULT

        with (
            patch("deepchoice.agents.orchestrator.QueryAnalyzerAgent.run", new=_make_mock_run(MOCK_QUERY_RESULT)),
            patch("deepchoice.agents.orchestrator.MultiRetrieverAgent.run", new=_make_mock_run({"search_results": MOCK_SEARCH_RESULTS, "partial_failures": []})),
            patch("deepchoice.agents.orchestrator.SourceEvaluatorAgent.run", new=_make_mock_run({"source_scores": MOCK_SOURCE_SCORES})),
            patch("deepchoice.agents.orchestrator.ConflictDetectorAgent.run", new=_make_mock_run({"conflicts": []})),
            patch("deepchoice.agents.orchestrator.EvidenceChainAgent.run", new=_make_mock_run({"evidence_chains": MOCK_EVIDENCE_CHAINS})),
            patch("deepchoice.agents.orchestrator.ReportGeneratorAgent.run", new=_make_mock_run({"report": MOCK_REPORT})),
            patch("deepchoice.agents.orchestrator.SelfReviewerAgent.run", new=mock_review),
        ):
            result = await orchestrator.run_research_task()

        assert call_count["review"] == 1, "the reviewer must not be asked to redo its own work"
        assert result["confidence"] == "low"
        assert result["current_phase"] == "self_reviewer"

    @pytest.mark.asyncio
    async def test_clarify_integration_skips_query_analyzer(self):
        task = {
            "query": "FastAPI vs Flask",
            "scene_context": "solo",
            "constraints": [],
            "report_format": "what_why_how",
            "sub_questions": ["q1", "q2", "q3", "q4", "q5"],
        }
        orchestrator = ChiefEditorAgent(task)

        qa_called = {"called": False}

        async def mock_qa(*args, **kwargs):
            qa_called["called"] = True
            return MOCK_QUERY_RESULT

        with (
            patch("deepchoice.agents.orchestrator.QueryAnalyzerAgent.run", new=mock_qa),
            patch("deepchoice.agents.orchestrator.MultiRetrieverAgent.run", new=_make_mock_run({"search_results": MOCK_SEARCH_RESULTS, "partial_failures": []})),
            patch("deepchoice.agents.orchestrator.SourceEvaluatorAgent.run", new=_make_mock_run({"source_scores": MOCK_SOURCE_SCORES})),
            patch("deepchoice.agents.orchestrator.ConflictDetectorAgent.run", new=_make_mock_run({"conflicts": []})),
            patch("deepchoice.agents.orchestrator.EvidenceChainAgent.run", new=_make_mock_run({"evidence_chains": MOCK_EVIDENCE_CHAINS})),
            patch("deepchoice.agents.orchestrator.ReportGeneratorAgent.run", new=_make_mock_run({"report": MOCK_REPORT})),
            patch("deepchoice.agents.orchestrator.SelfReviewerAgent.run", new=_make_mock_run(MOCK_REVIEW_HIGH)),
        ):
            await orchestrator.run_research_task()

        assert not qa_called["called"], "QueryAnalyzer should be skipped when sub_questions exist"


PIPELINE_ORDER = [
    "query_analyzer", "query_adapter", "multi_retriever", "source_evaluator",
    "conflict_detector", "evidence_chain", "conclusion_synthesizer",
    "report_generator", "self_reviewer",
]


def _signal(agent_name: str) -> dict:
    return {"agent": agent_name, "count": 1}


def _pipeline_patches(overrides: dict | None = None):
    """Patch all nine nodes so each returns exactly its own quality signal.

    `overrides` maps a node name to an explicit patch value: a plain dict becomes
    that node's return value (modelling a node that reports no signals), and a
    Mock is installed as-is (for capturing the state the node receives).
    """
    overrides = overrides or {}
    payloads = {
        "query_analyzer": MOCK_QUERY_RESULT,
        "query_adapter": {"adapted_queries": {}},
        "multi_retriever": {"search_results": MOCK_SEARCH_RESULTS,
                            "partial_failures": []},
        "source_evaluator": {"source_scores": MOCK_SOURCE_SCORES},
        "conflict_detector": {"conflicts": [], "conflict_check": {}},
        "evidence_chain": {"evidence_chains": MOCK_EVIDENCE_CHAINS},
        "conclusion_synthesizer": {"final_recommendation": {},
                                   "confidence": "medium"},
        "report_generator": {"report": MOCK_REPORT},
        "self_reviewer": MOCK_REVIEW_HIGH,
    }
    class_names = {
        "query_analyzer": "QueryAnalyzerAgent",
        "query_adapter": "QueryAdapterAgent",
        "multi_retriever": "MultiRetrieverAgent",
        "source_evaluator": "SourceEvaluatorAgent",
        "conflict_detector": "ConflictDetectorAgent",
        "evidence_chain": "EvidenceChainAgent",
        "conclusion_synthesizer": "ConclusionSynthesizerAgent",
        "report_generator": "ReportGeneratorAgent",
        "self_reviewer": "SelfReviewerAgent",
    }
    patches = []
    for agent_name in PIPELINE_ORDER:
        target = f"deepchoice.agents.orchestrator.{class_names[agent_name]}.run"
        override = overrides.get(agent_name)
        if override is not None:
            new_value = (AsyncMock(return_value=override)
                         if isinstance(override, dict) else override)
        else:
            new_value = AsyncMock(return_value={
                **payloads[agent_name],
                "quality_signals": [_signal(agent_name)],
            })
        patches.append(patch(target, new=new_value))
    return patches


class TestQualitySignalAccumulation:
    @pytest.mark.asyncio
    async def test_quality_signals_accumulate_across_nodes(self):
        """Each node's signal must survive into the final state.

        quality_signals has no LangGraph reducer: a plain node return replaces
        the whole list, so the final state used to keep only the last writer's
        signal and the self-reviewer read one agent instead of the pipeline.
        """
        task = {"query": "TestA vs TestB for API development",
                "scene_context": "solo", "constraints": ["python"],
                "report_format": "what_why_how"}
        orchestrator = ChiefEditorAgent(task)
        seen_by_reviewer: dict = {}

        async def _capturing_reviewer(state):
            seen_by_reviewer["quality_signals"] = list(
                state.get("quality_signals") or [])
            return {**MOCK_REVIEW_HIGH,
                    "quality_signals": [_signal("self_reviewer")]}

        patches = _pipeline_patches(overrides={
            "self_reviewer": AsyncMock(side_effect=_capturing_reviewer),
        })

        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8]:
            result = await orchestrator.run_research_task()

        agents = [s.get("agent") for s in result["quality_signals"]]
        assert agents == PIPELINE_ORDER, agents
        assert len(agents) == len(set(agents)), "a node's signal was duplicated"
        # The reviewer sees every upstream node, not only the last writer.
        upstream = [s.get("agent") for s in seen_by_reviewer["quality_signals"]]
        assert upstream == PIPELINE_ORDER[:-1], upstream

    @pytest.mark.asyncio
    async def test_a_node_without_signals_does_not_erase_prior_ones(self):
        """A node that returns no quality_signals leaves the existing list alone."""
        task = {"query": "TestA vs TestB", "scene_context": "solo",
                "constraints": [], "report_format": "what_why_how"}
        orchestrator = ChiefEditorAgent(task)

        # report_generator returns no quality_signals at all.
        patches = _pipeline_patches(overrides={
            "report_generator": {"report": MOCK_REPORT},
        })
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8]:
            result = await orchestrator.run_research_task()

        agents = [s.get("agent") for s in result["quality_signals"]]
        expected = [name for name in PIPELINE_ORDER if name != "report_generator"]
        assert agents == expected, agents
