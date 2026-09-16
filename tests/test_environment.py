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


def test_compose_passes_deepseek_settings_without_qwen_credentials():
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    for name in ("DS_FLASH_API_KEY", "FLASH_API_KEY", "DEEPSEEK_API_KEY", "DS_FLASH_MODEL",
                 "DS_FLASH_BASE_URL", "LLM_DS_CONCURRENCY", "DEEPCHOICE_SYNTH_THINKING"):
        assert f"- {name}=" in compose
    for name in ("QW_FLASH_API_KEY", "PRO_API_KEY", "LLM_API_KEY", "LLM_QW_CONCURRENCY"):
        assert f"- {name}=" not in compose
