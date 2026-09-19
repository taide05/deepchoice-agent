from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts import o1_pr2a_child as child
from scripts import o1_pr2a_control as control
from scripts import o1_pr2a_prepare as prepare


def _event(name: str, **fields) -> dict:
    return {"schema_version": 1, "event": name, **fields}


def _write_events(path: Path, *events: dict) -> None:
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _request(method: str, url: str) -> httpx.Request:
    return httpx.Request(method, url)


@pytest.mark.parametrize(
    ("method", "url", "expected"),
    [
        ("HEAD", "https://api.tavily.com/search", "tavily_static_probe"),
        ("HEAD", "https://api.tavily.com:443/search", "tavily_static_probe"),
        ("POST", "https://api.tavily.com/search", "tavily_business"),
        ("HEAD", "https://api.tavily.com/search?probe=1", "tavily_business"),
        ("HEAD", "http://api.tavily.com/search", "tavily_business"),
        ("HEAD", "https://api.tavily.com/other", "tavily_business"),
        ("POST", "https://api.deepseek.com/chat/completions", "llm"),
        ("GET", "https://api.github.com/repos/o/r", "github"),
        ("GET", "https://example.com/data", "other"),
    ],
)
def test_external_operation_classifier_is_exact(method, url, expected):
    assert child._external_operation(
        _request(method, url), "api.deepseek.com") == expected


@pytest.mark.parametrize("status_code", [200, 401, 404, 499])
def test_tavily_static_probe_accepts_only_2xx_through_4xx(tmp_path, status_code):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_events(
        telemetry,
        _event("telemetry_ready"),
        _event(
            "external_http_response",
            operation="tavily_static_probe",
            source="tavily",
            method="HEAD",
            status_code=status_code,
        ),
    )
    assert control.telemetry_state(telemetry)["anomaly"] is False


@pytest.mark.parametrize(
    "response",
    [
        {"operation": "tavily_static_probe", "source": "tavily",
         "method": "HEAD", "status_code": 500},
        {"operation": "tavily_business", "source": "tavily",
         "method": "POST", "status_code": 400},
        {"operation": "tavily_business", "source": "tavily",
         "method": "POST", "status_code": 429},
        {"operation": "github", "source": "github",
         "method": "HEAD", "status_code": 401},
        {"operation": "other", "source": "other",
         "method": "GET", "status_code": 503},
        {"source": "tavily", "method": "HEAD", "status_code": 401},
    ],
)
def test_nonprobe_4xx_5xx_and_invalid_operations_fail_closed(tmp_path, response):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_events(
        telemetry,
        _event("telemetry_ready"),
        _event("external_http_response", **response),
    )
    assert control.telemetry_state(telemetry)["anomaly"] is True


def test_external_transport_failure_and_truncated_telemetry_fail_closed(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_events(
        telemetry,
        _event("telemetry_ready"),
        _event(
            "external_http_failure",
            operation="llm",
            source="llm",
            method="POST",
        ),
    )
    assert control.telemetry_state(telemetry)["reason"] == "external_http_failure"

    telemetry.write_text('{"schema_version": 1', encoding="utf-8")
    assert control.telemetry_state(telemetry)["reason"] == "telemetry_truncated"


def test_final_telemetry_requires_asyncio_runner_return(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    _write_events(
        telemetry,
        _event("telemetry_ready"),
        _event("service_stopped"),
    )
    state = control.telemetry_state(
        telemetry, require_stopped=True, require_runner_returned=True)
    assert state["reason"] == "asyncio_runner_returned_missing"

    with telemetry.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_event("asyncio_runner_returned")) + "\n")
    assert control.telemetry_state(
        telemetry, require_stopped=True,
        require_runner_returned=True)["anomaly"] is False


class _Child:
    def __init__(self, stop_flag: Path):
        self.stop_flag = stop_flag

    def poll(self):
        return 0 if self.stop_flag.exists() else None


@pytest.mark.asyncio
async def test_shutdown_waits_for_cold_embedding_to_finish_before_stop(
        tmp_path, monkeypatch):
    telemetry = tmp_path / "telemetry.jsonl"
    stop_flag = tmp_path / "stop-service.flag"
    _write_events(
        telemetry,
        _event("telemetry_ready"),
        _event("embedding_first_start"),
    )
    observed_stop_state = []

    async def finish_embedding(_delay):
        observed_stop_state.append(stop_flag.exists())
        with telemetry.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_event("embedding_first_end")) + "\n")

    monkeypatch.setattr(control.asyncio, "sleep", finish_embedding)
    result = await control.shutdown_child(
        _Child(stop_flag), stop_flag, lambda: None, telemetry)

    assert observed_stop_state == [False]
    assert result["quiescence"]["complete"] is True
    assert result["quiescence"]["reason"] == "embedding_quiescent"
    assert result["action"] == "graceful"
    assert result["unresolved"] is False


@pytest.mark.asyncio
async def test_embedding_quiescence_timeout_is_unresolved(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    stop_flag = tmp_path / "stop-service.flag"
    _write_events(
        telemetry,
        _event("telemetry_ready"),
        _event("embedding_first_start"),
    )
    state = await control.wait_for_embedding_quiescence(
        _Child(stop_flag), telemetry, timeout_seconds=0)
    assert state["complete"] is False
    assert state["reason"] == "embedding_quiescence_timeout"


def _observation(task_id: str, run_id: str) -> dict:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "run_id": run_id,
        "availability": "available",
        "budget_policy_availability": "available",
        "budget": {
            "availability": "available",
            "resources": {
                "active_milliseconds": {
                    "availability": "available",
                    "hard_limit": 900_000,
                    "settled": 21_264,
                    "unknown_spend": 0,
                    "reserved": 0,
                    "remaining": 878_736,
                    "exhausted": False,
                }
            },
        },
        "nodes": [],
        "calls": [],
        "totals": {"llm_calls": 4, "retrieval_calls": 6, "total_tokens": 1265},
    }


@pytest.mark.asyncio
async def test_stop_final_capture_uses_terminal_public_observability():
    task_id = "task-1"
    run_id = "run-1"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/observability"):
            return httpx.Response(200, json=_observation(task_id, run_id))
        return httpx.Response(200, json={
            "task": {
                "task_id": task_id,
                "status": "cancelled",
                "latest_run_id": run_id,
            },
            "latest_run": {
                "task_id": task_id,
                "run_id": run_id,
                "status": "cancelled",
            },
        })

    async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://local.test") as client:
        result = await control.collect_stop_final_observability(
            "http://unused",
            {task_id: {"case_id": "P06", "run_id": run_id}},
            True,
            client=client,
        )

    assert result["complete"] is True
    assert result["admitted_run_denominator"] == 1
    assert result["observations"][0]["status"] == "cancelled"
    budget = control.active_budget_metrics(result)
    assert budget["complete"] is True
    assert budget["runs"][0]["settled"] == 21_264
    assert budget["runs"][0]["reserved"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", ["run-mismatch", "running"])
async def test_stop_final_capture_rejects_run_mismatch_and_nonterminal(bad_value):
    task_id = "task-1"
    expected_run = "run-1"
    actual_run = bad_value if bad_value == "run-mismatch" else expected_run
    status = "running" if bad_value == "running" else "cancelled"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/observability"):
            return httpx.Response(200, json=_observation(task_id, actual_run))
        return httpx.Response(200, json={
            "task": {
                "task_id": task_id,
                "status": status,
                "latest_run_id": actual_run,
            },
            "latest_run": {
                "task_id": task_id,
                "run_id": actual_run,
                "status": status,
            },
        })

    async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://local.test") as client:
        result = await control.collect_stop_final_observability(
            "http://unused",
            {task_id: {"case_id": "P01", "run_id": expected_run}},
            True,
            client=client,
        )

    assert result["complete"] is False
    assert result["observations"] == []
    assert (
        result["errors"][0]["category"]
        == "task_identity_or_terminal_state_invalid"
    )


def test_prepare_freezes_only_the_tracked_pr2a_control_chain():
    assert prepare.PR2A_CONTROL_CHAIN == (
        "o1_pr2a_prepare.py",
        "o1_pr2a_child.py",
        "o1_pr2a_control.py",
    )
