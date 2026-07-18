import pytest
from unittest.mock import patch
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
        assert result.get("retry_count", 0) == 0

    @pytest.mark.asyncio
    async def test_pipeline_triggers_retry_on_low_confidence(self):
        task = {"query": "test", "scene_context": "team", "constraints": [], "report_format": "evidence_first"}
        orchestrator = ChiefEditorAgent(task)

        call_count = {"review": 0}

        async def mock_review(*args, **kwargs):
            call_count["review"] += 1
            if call_count["review"] == 1:
                return MOCK_REVIEW_LOW
            return MOCK_REVIEW_MEDIUM

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

        assert call_count["review"] >= 2, "SelfReviewer should be called at least twice (retry after low confidence)"
        assert result["confidence"] == "medium"

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
