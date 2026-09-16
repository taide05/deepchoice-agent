import asyncio

from fastapi.testclient import TestClient

import deepchoice.server.app as app_module
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory


client = TestClient(app_module.app)


class FakeOrchestrator:
    def __init__(self, task, **kwargs):
        self.task = task
        self.task_id = kwargs["thread_id"]
        self.thread_id = kwargs["thread_id"]
        self.run_manifest = kwargs["run_manifest"]
        self.checkpointer = kwargs.get("checkpointer")

    async def astream_research_task(self):
        if False:
            yield None

    async def get_state(self):
        return None


def _disable_background(monkeypatch):
    async def no_checkpointer():
        return None

    captured = {}

    def create_orchestrator(task, **kwargs):
        instance = FakeOrchestrator(task, **kwargs)
        captured["orchestrator"] = instance
        return instance

    def close_coroutine(coroutine):
        coroutine.close()
        return None

    monkeypatch.setattr(app_module, "_get_sqlite_saver", no_checkpointer)
    monkeypatch.setattr(app_module, "ChiefEditorAgent", create_orchestrator)
    monkeypatch.setattr(app_module.asyncio, "create_task", close_coroutine)
    return captured


def test_research_request_accepts_legacy_shape_and_strips_query(monkeypatch):
    captured = _disable_background(monkeypatch)

    response = client.post(
        "/research",
        json={
            "query": "  FastAPI vs Flask  ",
            "scene_context": "team",
            "constraints": ["Python"],
            "candidate_techs": ["FastAPI", "Flask"],
            "complexity": "medium",
            "report_format": "evidence_first",
            "sub_questions": ["Which is easier to operate?"],
            "gather_evidence": False,
            "language": "en",
        },
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert response.json()["status"] == "started"
    assert response.json()["manifest_id"]
    orchestrator = captured["orchestrator"]
    assert orchestrator.task["query"] == "FastAPI vs Flask"
    assert orchestrator.task["gather_evidence"] is False
    assert app_module._active_tasks[response.json()["task_id"]]["manifest"] is orchestrator.run_manifest


def test_research_request_rejects_empty_query_unknown_fields_and_bad_format():
    for payload in (
        {"query": "   "},
        {"query": "valid", "unknown": True},
        {"query": "valid", "report_format": "html"},
    ):
        response = client.post("/research", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]
        assert body["error"]["category"] == "validation"
        assert body["error"]["code"] == "REQUEST_VALIDATION_FAILED"
        assert all("input" not in item for item in body["detail"])


def test_http_exception_has_structured_error_and_legacy_detail():
    response = client.get("/research/not-present/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
    error = response.json()["error"]
    assert error["category"] == "not_found"
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "Task not found"
    assert error["retryable"] is False
    assert error["action"]


def test_deepchoice_error_handler_preserves_detail():
    error = DeepChoiceError(
        "budget exhausted",
        category=ErrorCategory.RESEARCH,
        code="BUDGET_EXHAUSTED",
        status_code=409,
    )
    response = asyncio.run(app_module.deepchoice_error_handler(None, error))

    assert response.status_code == 409
    assert response.body
    assert b"BUDGET_EXHAUSTED" in response.body
    assert b"budget exhausted" in response.body


def test_unexpected_error_handler_never_exposes_raw_exception():
    assert app_module.app.exception_handlers[Exception] is app_module.unexpected_error_handler
    response = asyncio.run(
        app_module.unexpected_error_handler(None, RuntimeError("secret db path"))
    )

    assert response.status_code == 500
    assert b"secret db path" not in response.body
    assert b"RESEARCH_FAILED" in response.body


def test_server_http_exception_never_reflects_detail():
    from fastapi import HTTPException

    response = asyncio.run(
        app_module.http_error_handler(
            None,
            HTTPException(status_code=500, detail="secret sqlite path"),
        )
    )

    assert response.status_code == 500
    assert b"secret sqlite path" not in response.body
    assert b"INTERNAL_HTTP_ERROR" in response.body


def test_background_failure_adds_structured_error_without_changing_legacy_event(monkeypatch):
    task_id = "structured-failure"

    class FailingOrchestrator:
        checkpointer = None

        async def astream_research_task(self):
            raise RuntimeError("boom")
            yield

        async def get_state(self):
            return None

    app_module._active_tasks[task_id] = {
        "queue": asyncio.Queue(),
        "events": [],
        "status": "running",
    }
    monkeypatch.setattr(app_module, "save_failed_snapshot", lambda *args: None)

    asyncio.run(app_module._run_research(task_id, FailingOrchestrator()))

    entry = app_module._active_tasks[task_id]
    assert entry["error"] == "Research failed"
    assert entry["events"][-1]["__error__"]["detail"] == "Research failed"
    assert entry["events"][-1]["__error__"]["error_detail"] == entry["error_detail"]
    assert entry["error_detail"]["code"] == "RESEARCH_FAILED"
    assert entry["error_detail"]["message"] == "Research failed"
    payload = app_module._format_event(entry["events"][-1])
    assert '"error_detail"' in payload
    status = client.get(f"/research/{task_id}/status").json()
    assert status["error"] == "Research failed"
    assert status["error_detail"] == entry["error_detail"]


def test_request_model_bounds_collection_and_item_lengths():
    too_many = [str(index) for index in range(51)]
    response = client.post("/research", json={"query": "valid", "constraints": too_many})
    assert response.status_code == 422

    response = client.post("/research", json={"query": "valid", "candidate_techs": ["x" * 501]})
    assert response.status_code == 422

    response = client.post(
        "/research",
        json={"query": "valid", "sub_questions": ["question"] * 21},
    )
    assert response.status_code == 422

    assert ResearchRequest(query=" x ").query == "x"
