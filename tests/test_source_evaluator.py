import pytest
from datetime import datetime, timedelta
from deepchoice.agents.source_evaluator import (
    SourceEvaluatorAgent,
    score_authority,
    score_timeliness,
    score_consistency,
    score_verifiability,
    compute_total_score,
    classify_source_type,
    classify_evidence_type,
)


class TestScoreAuthority:
    def test_official_docs_get_10(self):
        assert score_authority("official_doc") == 10

    def test_paper_gets_10(self):
        assert score_authority("arxiv_paper") == 10

    def test_well_known_blog_gets_7(self):
        assert score_authority("tech_blog") == 7

    def test_github_gets_6(self):
        assert score_authority("github") == 6

    def test_stackoverflow_gets_5(self):
        assert score_authority("stackoverflow") == 5

    def test_reddit_gets_4(self):
        assert score_authority("reddit") == 4

    def test_anonymous_gets_2(self):
        assert score_authority("anonymous") == 2

    def test_unknown_gets_4_default(self):
        assert score_authority("something_unknown") == 4


class TestScoreTimeliness:
    def test_less_than_3_months(self):
        recent = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        assert score_timeliness(recent) == 10

    def test_3_to_6_months(self):
        mid = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
        assert score_timeliness(mid) == 8

    def test_6_to_12_months(self):
        older = (datetime.now() - timedelta(days=270)).strftime("%Y-%m-%d")
        assert score_timeliness(older) == 6

    def test_1_to_2_years(self):
        old = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
        assert score_timeliness(old) == 4

    def test_over_2_years(self):
        ancient = (datetime.now() - timedelta(days=800)).strftime("%Y-%m-%d")
        assert score_timeliness(ancient) == 2

    def test_missing_date_defaults_5(self):
        assert score_timeliness(None) == 5
        assert score_timeliness("") == 5


class TestScoreConsistency:
    def test_two_sources_agree(self):
        assert score_consistency(["source_a", "source_b"]) == 10

    def test_one_source_only(self):
        assert score_consistency(["source_a"]) == 6

    def test_isolated_no_others(self):
        assert score_consistency([]) == 4

    def test_contradiction(self):
        assert score_consistency([], has_contradiction=True) == 2


class TestScoreVerifiability:
    def test_runnable_code(self):
        assert score_verifiability("code") == 10

    def test_benchmark_data(self):
        assert score_verifiability("benchmark") == 8

    def test_has_citations(self):
        assert score_verifiability("citation") == 6

    def test_pure_opinion(self):
        assert score_verifiability("opinion") == 2

    def test_unknown_default(self):
        assert score_verifiability("something_else") == 4


class TestComputeTotalScore:
    def test_weighted_formula(self):
        scores = {"authority": 10, "timeliness": 10, "consistency": 10, "verifiability": 10}
        total = compute_total_score(scores)
        assert total == 10.0

    def test_zero_scores(self):
        scores = {"authority": 0, "timeliness": 0, "consistency": 0, "verifiability": 0}
        total = compute_total_score(scores)
        assert total == 0.0


class TestClassifySourceType:
    def test_arxiv_url(self):
        assert classify_source_type("https://arxiv.org/abs/2401.12345", "unknown") == "arxiv_paper"

    def test_github_url(self):
        assert classify_source_type("https://github.com/langchain-ai/langgraph", "unknown") == "github"

    def test_readthedocs_url(self):
        assert classify_source_type("https://langchain.readthedocs.io/en/latest/", "unknown") == "official_doc"

    def test_chroma_source(self):
        assert classify_source_type("some-internal-id", "chroma") == "official_doc"


class TestClassifyEvidenceType:
    def test_code_block_is_code(self):
        assert classify_evidence_type("here is a ```python\nimport foo\n``` example") == "code"

    def test_benchmark_data(self):
        assert classify_evidence_type("throughput was 500 rps with 20ms latency") == "benchmark"

    def test_opinion_is_opinion(self):
        assert classify_evidence_type("in my opinion this is the best framework") == "opinion"

    def test_default_is_citation(self):
        assert classify_evidence_type("A general description of the framework") == "citation"


class TestSourceEvaluatorAgent:
    @pytest.mark.asyncio
    async def test_scores_and_ranks_results(self):
        state = {
            "search_results": [
                {
                    "source": "tavily",
                    "status": "success",
                    "results": [
                        {
                            "url": "https://docs.python.org/3/library/asyncio.html",
                            "title": "asyncio - Official Python docs",
                            "snippet": "This module provides infrastructure for writing concurrent code using the async/await syntax.",
                            "date": "2026-06-01",
                        },
                        {
                            "url": "https://www.reddit.com/r/Python/comments/xyz",
                            "title": "Python async is the worst, here's why",
                            "snippet": "in my opinion async programming in Python is overcomplicated for most projects",
                            "date": "2024-03-15",
                        },
                    ],
                    "error": None,
                    "latency_ms": 800,
                }
            ]
        }

        agent = SourceEvaluatorAgent()
        result = await agent.run(state)

        scores = result["source_scores"]
        assert len(scores) == 2
        assert scores[0]["rank"] == 1
        assert scores[1]["rank"] == 2
        assert scores[0]["total_score"] > scores[1]["total_score"]
        assert all("authority" in s["scores"] for s in scores)
        assert all("timeliness" in s["scores"] for s in scores)

    @pytest.mark.asyncio
    async def test_empty_results(self):
        agent = SourceEvaluatorAgent()
        result = await agent.run({"search_results": []})
        assert result["source_scores"] == []
