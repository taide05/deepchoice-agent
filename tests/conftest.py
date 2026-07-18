import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def sample_task():
    return {
        "query": "LangGraph vs CrewAI for building AI agents",
        "scene_context": "solo",
        "constraints": ["python-only", "low-cost"],
        "report_format": "what_why_how",
    }


@pytest.fixture
def sample_state(sample_task):
    return {
        "task": sample_task,
        "sub_questions": [],
        "search_results": [],
        "source_scores": [],
        "conflicts": [],
        "evidence_chains": [],
        "report": "",
        "confidence": "",
        "knowledge_gaps": [],
        "retry_count": 0,
        "partial_failures": [],
        "current_phase": "",
    }


@pytest.fixture
def sample_search_results():
    return [
        {
            "source": "tavily",
            "status": "success",
            "results": [
                {
                    "url": "https://blog.langchain.dev/langgraph-vs-crewai/",
                    "title": "LangGraph vs CrewAI Comparison",
                    "snippet": "LangGraph offers more flexibility while CrewAI provides better DX...",
                    "date": "2026-05-15",
                },
                {
                    "url": "https://reddit.com/r/LangChain/comments/abc123",
                    "title": "CrewAI review after 3 months",
                    "snippet": "CrewAI is great for simple workflows but breaks down at scale...",
                    "date": "2026-04-20",
                },
            ],
            "error": None,
            "latency_ms": 1200,
        },
        {
            "source": "arxiv",
            "status": "success",
            "results": [
                {
                    "url": "https://arxiv.org/abs/2401.12345",
                    "title": "A Survey of Multi-Agent Orchestration Frameworks",
                    "snippet": "We compare LangGraph, CrewAI, AutoGen, and AutoGPT across 12 dimensions...",
                    "date": "2026-01-15",
                }
            ],
            "error": None,
            "latency_ms": 800,
        },
    ]


@pytest.fixture
def mock_call_model():
    mock = AsyncMock()
    mock.return_value = {"result": "mocked"}
    return mock
