"""Smoke tests for the supported API/UI dependency combination."""

from pathlib import Path


def test_api_and_ui_dependencies_import_together():
    import fastapi
    import pyarrow
    import starlette
    import streamlit

    assert fastapi.__version__
    assert pyarrow.__version__
    assert starlette.__version__
    assert streamlit.__version__


def test_compose_persists_tavily_key_state_under_outputs_volume():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "- outputs:/app/outputs" in compose
    assert (
        "- TAVILY_KEY_STATE_PATH=${TAVILY_KEY_STATE_PATH:-/app/outputs/"
        "tavily_key_state.json}"
    ) in compose
    assert (
        "- OUTBOUND_CHANNELS_TAVILY=${OUTBOUND_CHANNELS_TAVILY:-"
        "local-proxy,direct,direct-v6}"
    ) in compose
    frontend_dockerfile = (root / "Dockerfile.frontend").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in frontend_dockerfile
    assert '"streamlit>=1.63.0,<2"' in frontend_dockerfile
    benchmark_workflow = (
        root / ".github" / "workflows" / "benchmark.yml"
    ).read_text(encoding="utf-8")
    assert 'python-version: "3.12"' in benchmark_workflow
