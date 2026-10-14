"""Public API contract boundaries.

The retired ``POST /research`` compatibility path was removed; the product
interface is ``POST /api/v1/tasks``. Both took ``ResearchRequest``, so the
request-model bounds and the structured-error handlers keep their coverage
here - only the transport changed. Tests that asserted the retired path's own
started-response shape and its in-process registry are gone with that path.
"""
import asyncio

from fastapi.testclient import TestClient

import deepchoice.server.app as app_module
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory


client = TestClient(app_module.app)


def test_create_task_rejects_empty_query_unknown_fields_and_bad_format():
    for payload in (
        {"query": "   "},
        {"query": "valid", "unknown": True},
        {"query": "valid", "report_format": "html"},
    ):
        response = client.post("/api/v1/tasks", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]
        assert body["error"]["category"] == "validation"
        assert body["error"]["code"] == "REQUEST_VALIDATION_FAILED"
        assert all("input" not in item for item in body["detail"])


def test_request_model_bounds_collection_and_item_lengths():
    too_many = [str(index) for index in range(51)]
    response = client.post("/api/v1/tasks", json={"query": "valid", "constraints": too_many})
    assert response.status_code == 422

    response = client.post("/api/v1/tasks", json={"query": "valid", "candidate_techs": ["x" * 501]})
    assert response.status_code == 422

    response = client.post(
        "/api/v1/tasks",
        json={"query": "valid", "sub_questions": ["question"] * 21},
    )
    assert response.status_code == 422

    assert ResearchRequest(query=" x ").query == "x"


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


def test_http_exception_404_has_structured_error_body():
    """The clarify routes still raise HTTPException(404); it must keep the
    structured envelope, not a bare FastAPI detail."""
    with TestClient(app_module.app) as client:
        response = client.get("/clarify/not-a-live-session/status")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"] == "Session not found or expired"
    error = body["error"]
    assert error["category"] == "not_found"
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "Session not found or expired"
    assert error["retryable"] is False
    assert error["action"]

