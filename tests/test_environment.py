"""Smoke tests for the supported API/UI dependency combination."""


def test_api_and_ui_dependencies_import_together():
    import fastapi
    import pyarrow
    import starlette
    import streamlit

    assert fastapi.__version__
    assert pyarrow.__version__
    assert starlette.__version__
    assert streamlit.__version__
