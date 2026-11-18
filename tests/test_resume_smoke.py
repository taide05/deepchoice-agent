"""Offline tests for the M5 real-resume smoke script (scripts/resume_smoke.py).

The script drives a live API, so its HTTP sequence is tested with an in-memory
httpx.MockTransport double: no network, no credentials, no model calls.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "resume_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("resume_smoke_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


def _state(**overrides) -> dict:
    state = {
        "task_id": "smoke-task-1",
        "calls": [],
        "stream_calls": 0,
        "resumed": False,
        "resumable": True,
        "resume_refused": False,
        "resume_in_progress": False,
        "created": False,
    }
    state.update(overrides)
    return state


def _handler(state: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        state["calls"].append((request.method, path, dict(request.url.params)))
        if request.method == "POST" and path == "/research":
            state["created"] = True
            return httpx.Response(200, json={"task_id": state["task_id"]})
        if request.method == "GET" and path.endswith("/stream"):
            state["stream_calls"] += 1
            if state["stream_calls"] == 1:
                body = (
                    'data: {"node": "query_analyzer", "ts": 1}\n\n'
                    'data: {"node": "query_adapter", "ts": 2}\n\n'
                )
            else:
                body = (
                    'data: {"node": "evidence_chain", "ts": 3}\n\n'
                    'data: {"node": "__done__"}\n\n'
                )
            return httpx.Response(200, content=body.encode("utf-8"))
        if request.method == "POST" and path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "cancelled"})
        if request.method == "POST" and path.endswith("/resume"):
            assert json.loads(request.content) == {"confirm": True}
            if state["resume_refused"]:
                return httpx.Response(
                    409, json={"detail": "RESUME_EXHAUSTED: attempts exhausted"})
            if state["resume_in_progress"]:
                state["resumed"] = True
                return httpx.Response(
                    409, json={"detail": "RESUME_IN_PROGRESS: already running"})
            state["resumed"] = True
            return httpx.Response(
                202, json={"task_id": state["task_id"], "status": "resuming",
                           "attempt": 2})
        if request.method == "GET" and path.endswith("/status"):
            if state["resumed"]:
                return httpx.Response(200, json={"status": "complete", "attempt": 2})
            if state["resumable"]:
                return httpx.Response(200, json={
                    "status": "failed", "resumable": True, "attempt": 1,
                    "max_attempts": 2, "next_node": "evidence_chain",
                    "checkpoint_step": 5})
            return httpx.Response(200, json={
                "status": "failed", "resumable": False, "attempt": 2,
                "max_attempts": 2, "reason": "attempts_exhausted"})
        if request.method == "GET" and path.endswith("/snapshot"):
            if request.url.params.get("attempt") == "1":
                return httpx.Response(200, json={
                    "task": {"query": "q"}, "_attempt": 1,
                    "_status": "failed", "_error": "boom"})
            return httpx.Response(200, json={
                "task": {"query": "q"}, "report": "# R", "confidence": "high"})
        if request.method == "GET" and path.endswith("/history"):
            return httpx.Response(200, json={"tasks": [{
                "task_id": state["task_id"], "attempts": 2,
                "status": "complete"}]})
        return httpx.Response(404, json={"detail": "not found"})

    return handler


def _client(state: dict) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler(state)))


def test_full_smoke_passes_and_drives_the_contract():
    state = _state()
    with _client(state) as client:
        result = smoke.run_smoke(client, "http://smoke.test", timeout_s=30)

    assert result["passed"] is True
    assert result["task_id"] == "smoke-task-1"
    assert result["checks"] == {
        "status_complete": True,
        "resume_attempt_advanced": True,
        "complete_snapshot": True,
        "first_attempt_snapshot": True,
        "history_attempts": True,
    }
    assert state["created"] is True
    posts = [path for method, path, _ in state["calls"] if method == "POST"]
    assert posts.count("/research") == 1
    assert posts.count("/research/smoke-task-1/cancel") == 1
    assert posts.count("/research/smoke-task-1/resume") == 1
    assert state["stream_calls"] == 2


def test_existing_task_mode_skips_creation_and_cancellation():
    state = _state(task_id="existing-task")
    with _client(state) as client:
        result = smoke.run_smoke(client, "http://smoke.test",
                                 task_id="existing-task", timeout_s=30)

    assert result["passed"] is True
    assert result["mode"] == "resume-existing"
    posts = [path for method, path, _ in state["calls"] if method == "POST"]
    assert posts == ["/research/existing-task/resume"]
    assert state["stream_calls"] == 1  # only the resumed stream


def test_non_resumable_run_fails_before_calling_resume():
    state = _state(resumable=False)
    with _client(state) as client:
        with pytest.raises(smoke.SmokeError):
            smoke.run_smoke(client, "http://smoke.test", timeout_s=0.3)

    posts = [path for method, path, _ in state["calls"] if method == "POST"]
    assert "/research/smoke-task-1/resume" not in posts


def test_resume_refusal_is_reported():
    state = _state(resume_refused=True)
    with _client(state) as client:
        with pytest.raises(smoke.SmokeError, match="RESUME_EXHAUSTED"):
            smoke.run_smoke(client, "http://smoke.test", timeout_s=30)


def test_resume_in_progress_attaches_instead_of_failing():
    state = _state(resume_in_progress=True)
    with _client(state) as client:
        result = smoke.run_smoke(client, "http://smoke.test", timeout_s=30)

    assert result["passed"] is True
    assert result["resume"]["in_progress"] is True


def test_verification_detects_a_missing_first_attempt_snapshot():
    state = _state()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/snapshot"):
            if request.url.params.get("attempt") == "1":
                return httpx.Response(404, json={"detail": "Attempt not found"})
        return _handler(state)(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(smoke.SmokeError, match="first_attempt_snapshot"):
            smoke.run_smoke(client, "http://smoke.test", timeout_s=30)
