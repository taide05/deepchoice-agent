"""Importing API contracts must not load the native embedding dependency."""

import builtins
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def isolated_embedding():
    path = Path(__file__).parents[1] / "src/deepchoice/utils/embedding.py"
    spec = importlib.util.spec_from_file_location("isolated_embedding", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_defers_dependency_and_constructor_forwards_arguments(monkeypatch):
    original_import = builtins.__import__

    def forbid_native_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise AssertionError("embedding dependency imported before first use")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_native_import)
    embedding = isolated_embedding()
    assert embedding._model is None
    monkeypatch.setattr(builtins, "__import__", original_import)
    calls = []
    native_model = object()

    def constructor(*args, **kwargs):
        calls.append((args, kwargs))
        return native_model

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=constructor))
    assert embedding.SentenceTransformer("model", device="cpu") is native_model
    assert calls == [(("model",), {"device": "cpu"})]


def test_failed_first_dependency_import_can_retry_without_cached_model(monkeypatch):
    embedding = isolated_embedding()
    original_import = builtins.__import__

    def missing_dependency(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("dependency unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_dependency)
    with pytest.raises(ImportError, match="dependency unavailable"):
        embedding.get_embedding_model()
    assert embedding._model is None
    monkeypatch.setattr(builtins, "__import__", original_import)
    native_model = object()
    calls = []

    def constructor(name):
        calls.append(name)
        return native_model

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=constructor))
    assert embedding.get_embedding_model() is native_model
    assert embedding.get_embedding_model() is native_model
    assert calls == ["BAAI/bge-m3"]
