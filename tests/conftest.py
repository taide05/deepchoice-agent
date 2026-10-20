from unittest.mock import AsyncMock

import pytest


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


def _install_network_block():
    """Install a process-level external DNS/TCP block; return originals.

    Loopback remains available for tests that explicitly start a local service.
    Called at session start and re-applied per test so a test's own monkeypatch
    cannot leave the process able to reach the internet.
    """
    import ipaddress
    import socket

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def is_loopback_host(host):
        if host is None:
            return True
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        text = str(host).strip("[]").lower()
        if text in {"localhost", "localhost.localdomain", "0.0.0.0", "::"}:
            return True
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            return False
        return address.is_loopback

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and not is_loopback_host(host):
            raise OSError("external network blocked in tests")
        return original_connect(sock, address)

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and not is_loopback_host(host):
            raise OSError("external network blocked in tests")
        return original_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not is_loopback_host(host):
            raise socket.gaierror("external DNS blocked in tests")
        return original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.create_connection = guarded_create_connection
    socket.getaddrinfo = guarded_getaddrinfo
    return original_connect, original_create_connection, original_getaddrinfo


def _restore_network_block(originals):
    import socket

    (socket.socket.connect, socket.create_connection,
     socket.getaddrinfo) = originals


def pytest_sessionstart(session):
    """External DNS/TCP are blocked from test-session start, not only per test."""
    _install_network_block()


@pytest.fixture(autouse=True)
def _block_external_network():
    originals = _install_network_block()
    yield
    _restore_network_block(originals)
