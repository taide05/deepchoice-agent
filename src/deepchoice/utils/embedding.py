"""Embedding model access: explicit local loading, never an implicit download.

A research run must never discover, mid-run, that the model it needs is not on
disk: resolving ``BAAI/bge-m3`` through the hub makes ``huggingface_hub`` issue a
HEAD request per config file, retry it five times, and — because the call is
synchronous — block whatever called it. When the network is unreachable that is
tens of minutes inside a research node, with no failure reported and no way for
the wall clock to fire.

So the model is loaded from local files only, and the attempt is made *before*
research is dispatched:

  prepare_embedding_model()   Attempts the local load once and records the result.
  get_embedding_model()       Returns the loaded model, or raises
                              EmbeddingModelUnavailable immediately if the local
                              model is not available.

``local_files_only=True`` is the explicit local loading mode. It means no hub
resolution, no HEAD requests, no download — a missing model fails at once. Both
functions are synchronous and must be called from a worker thread when they are
invoked from a request path, so they cannot block the service event loop.
"""
from __future__ import annotations

import threading
import time

MODEL_NAME = "BAAI/bge-m3"

_model = None
_lock = threading.Lock()
_state = {
    "prepared": False,
    "available": None,      # None before preparation, then bool
    "reason": "",           # "model_missing" | "model_load_failed"
    "detail": "",
    "prepared_at": None,
    "prepare_seconds": None,
    "thread": "",
}

# Verification-only hook: lets a test substitute the local load without touching
# the network. Production code never replaces it.
_loader = None


class EmbeddingModelUnavailable(RuntimeError):
    """The local embedding model is not available, so this source cannot retrieve."""


def _local_loader():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, local_files_only=True)


def prepare_embedding_model() -> dict:
    """Load the model from local files only, once, before any research dispatch.

    Returns a copy of the state. Never raises: an unavailable model is a
    recorded condition that makes the KB source fail fast, not a crash.
    """
    global _model
    with _lock:
        if _state["prepared"]:
            return dict(_state)
        _state["prepared"] = True
        _state["prepared_at"] = time.time()
        _state["thread"] = threading.current_thread().name
        started = time.monotonic()
        try:
            _model = (_loader or _local_loader)()
            _state["available"] = True
        except Exception as exc:  # model absent or unreadable; not a crash
            _state["available"] = False
            _state["reason"] = ("model_missing" if isinstance(exc, (OSError, FileNotFoundError))
                                else "model_load_failed")
            _state["detail"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        _state["prepare_seconds"] = round(time.monotonic() - started, 2)
        return dict(_state)


def get_embedding_model():
    """The loaded local model, or ``EmbeddingModelUnavailable`` — never a download.

    Preparation is idempotent, so a caller that has to reach this before the
    startup preload still cannot trigger repeated loads or hub access.
    """
    if _model is not None:
        return _model
    state = prepare_embedding_model()
    if _model is None:
        raise EmbeddingModelUnavailable(
            f"local embedding model {MODEL_NAME} is unavailable "
            f"({state.get('reason') or 'not prepared'}: {state.get('detail') or 'no detail'}); "
            f"this source is reported unavailable instead of downloading it"
        )
    return _model


def embedding_model_state() -> dict:
    """A copy of the recorded preparation state, for startup diagnostics."""
    return dict(_state)


def set_local_loader(loader) -> None:
    """Verification-only: substitute the local loader. Never used in production."""
    global _loader
    _loader = loader


def reset_embedding_model_state() -> None:
    """Verification-only: forget the loaded model and the recorded state."""
    global _model, _loader
    with _lock:
        _model = None
        _loader = None
        _state.update({
            "prepared": False, "available": None, "reason": "", "detail": "",
            "prepared_at": None, "prepare_seconds": None, "thread": "",
        })
