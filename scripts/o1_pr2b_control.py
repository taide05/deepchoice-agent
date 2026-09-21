"""Execute one frozen O1-PR2 profile with corrected PR2B controls."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import psutil
from dotenv import load_dotenv

EXPECTED_COMMIT = "7d622fd4916dad950ca077924327647a1f8f12c0"
EXPECTED_DATASET = "e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f"
EXPECTED_KNOWLEDGE = "e55ddcac30d0e498c6e5ae02cb40d1bae95eb2831fda71e924ed9211b76466e4"
EXPECTED_DEPENDENCIES = "c07764a225a2eef37b2ee47dacdd1dec0efac5cd263c4522b5c121c50a40493b"
EXPECTED_CONFIGURATION = "4240dcd933e728eff05ea91d27cc5a57056c6c87404d20fa3b946cef50d9c474"
EXPECTED_ENDPOINT = "12b8deaccc34b32757dbb1497e029da0c2e7b26ffa86b9c926c08cb4692f4508"
EXPECTED_PROXY = "813477bf51a0efb3b5926c3759f01d02cdf25cd70e6cfc7fa186d9d5e1e1d118"
EXPECTED_EMBEDDING_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EXPECTED_MANIFEST_BY_CASE = {"P01": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P02": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P03": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P04": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P05": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P06": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P07": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P08": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a", "P09": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P10": "e7389bdbe64920fa7d00879e4de449498b945ce16c548f1341d4f2ec4adbaef6", "P11": "4374d25d239cdc5891453a3785479c91bc52cf272db5c0e32b11c5a755eed563", "P12": "3a7cd59683104f31c9e43f2b52defdef2c3c2bdf3fe48e5853482d9b0dddcd4a"}
EXPECTED_ASSET_REGISTRY = "15cb66f6602a7f36090c1337f983ecbdbb3c74e77d7c9ca52c6c3c5ba799c850"
EXPECTED_COMPARISON_CHECKS = {
    "all_paired_reports_available", "completion_not_lower",
    "decision_mean_drop_at_most_5pp", "citation_mean_drop_at_most_5pp",
    "source_mean_drop_at_most_5pp", "conflict_mean_drop_at_most_10pp",
    "no_new_major_errors", "no_case_decision_drop_over_20pp",
    "at_most_two_case_drops_over_10pp",
}
SUCCESS = frozenset({"completed", "completed_with_warnings"})
TERMINAL = frozenset({"completed", "completed_with_warnings", "failed", "cancelled", "timed_out"})
PROFILE = {
    "serial-r1": ("serial", 1, 1),
    "concurrent-r1": ("concurrent", 1, 12),
    "concurrent-r2": ("concurrent", 2, 12),
    "serial-r2": ("serial", 2, 1),
}
CANCEL_SETTLE_TIMEOUT_SECONDS = 180.0
CANCEL_POLL_INTERVAL_SECONDS = 1.0
STOP_MINIMUM_AVAILABLE_BYTES = 512 * 1024 ** 2


def stamp():
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, value: dict):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def manifest_map_sha256(value: dict) -> str:
    return hashlib.sha256(signature(value).encode("utf-8")).hexdigest()


def signature(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_EXPECTED_SOURCES = {
    "tavily", "chroma", "github", "arxiv", "community", "official",
}


def source_anomaly(snapshot) -> bool:
    """Require the six source envelopes; other partial failures have other meanings."""

    if not isinstance(snapshot, dict):
        return True
    results = snapshot.get("search_results")
    if not isinstance(results, list) or len(results) != len(_EXPECTED_SOURCES):
        return True
    sources = []
    for item in results:
        if (not isinstance(item, dict)
                or item.get("status") != "success"
                or not isinstance(item.get("source"), str)):
            return True
        sources.append(item["source"])
    return len(set(sources)) != len(sources) or set(sources) != _EXPECTED_SOURCES


def budget_anomaly(record: dict) -> bool:
    observation = record.get("observability")
    if not isinstance(observation, dict):
        return True
    budget = observation.get("budget")
    if (not isinstance(budget, dict)
            or budget.get("availability") != "available"
            or not isinstance(budget.get("resources"), dict)):
        return True
    required = {"active_milliseconds", "llm_calls", "retrieval_calls", "total_tokens"}
    resources = budget["resources"]
    if not required.issubset(resources):
        return True
    for name in required:
        resource = resources.get(name)
        if (not isinstance(resource, dict)
                or resource.get("availability") != "available"
                or type(resource.get("exhausted")) is not bool):
            return True
        if resource["exhausted"]:
            return True
    return budget.get("admission_denied") is True


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_identity(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError("artifact tree is empty")
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


_HTTP_OPERATIONS = {
    "tavily_static_probe", "tavily_business", "llm", "github", "arxiv",
    "community", "official", "other", "safe_fetch_public",
}

_SAFE_FETCH_FAILURES = {
    "safety_rejected", "route_unavailable", "route_unsupported",
    "dns_uncertain", "timeout", "response_rejected",
}


def telemetry_state(
        path: Path, *, require_ready: bool = True,
        require_stopped: bool = False,
        require_runner_returned: bool = False) -> dict:
    state = {
        "anomaly": True, "reason": "telemetry_missing", "ready": False,
        "service_stopped": False, "asyncio_runner_returned": False,
        "embedding_started": 0, "embedding_ended": 0,
        "embedding_inflight": 0,
    }
    if not path.is_file():
        return state
    try:
        payload = path.read_bytes()
        if not payload or not payload.endswith(b"\n"):
            state["reason"] = "telemetry_truncated"
            return state
        anomaly_reason = None
        cancelled_http_failure = False
        for line in payload.splitlines():
            if not line:
                state["reason"] = "telemetry_empty_line"
                return state
            event = json.loads(line)
            if (not isinstance(event, dict)
                    or event.get("schema_version") != 1
                    or not isinstance(event.get("event"), str)):
                state["reason"] = "telemetry_schema_invalid"
                return state
            kind = event["event"]
            if kind == "telemetry_ready":
                state["ready"] = True
            elif kind == "service_stopped":
                state["service_stopped"] = True
            elif kind == "asyncio_runner_returned":
                state["asyncio_runner_returned"] = True
            elif kind == "embedding_first_start":
                state["embedding_started"] += 1
            elif kind == "embedding_first_end":
                state["embedding_ended"] += 1
            elif kind == "external_http_failure":
                operation = event.get("operation")
                error_type = event.get("error_type")
                if operation == "safe_fetch_public":
                    if (event.get("source") != "safe_fetch"
                            or event.get("method") != "GET"):
                        anomaly_reason = "safe_fetch_public_failed"
                    elif error_type == "CancelledError":
                        cancelled_http_failure = True
                    elif (error_type != "UnsafeUrlError"
                            or event.get("failure") not in _SAFE_FETCH_FAILURES):
                        anomaly_reason = "safe_fetch_public_failed"
                elif operation not in _HTTP_OPERATIONS:
                    anomaly_reason = "external_http_operation_invalid"
                elif error_type == "CancelledError":
                    cancelled_http_failure = True
                else:
                    anomaly_reason = "external_http_failure"
            elif kind == "external_http_response":
                operation = event.get("operation")
                source = event.get("source")
                method = event.get("method")
                status_code = event.get("status_code")
                if operation not in _HTTP_OPERATIONS or not isinstance(status_code, int):
                    anomaly_reason = "external_http_response_invalid"
                elif operation == "tavily_static_probe":
                    if source != "tavily" or method != "HEAD" or not 200 <= status_code < 500:
                        anomaly_reason = "tavily_static_probe_failed"
                elif operation == "safe_fetch_public":
                    if (source != "safe_fetch" or method != "GET"
                            or not 200 <= status_code < 500):
                        anomaly_reason = "safe_fetch_public_failed"
                elif not 200 <= status_code < 400:
                    anomaly_reason = "external_http_status_failed"
        if state["embedding_ended"] > state["embedding_started"]:
            state["reason"] = "embedding_telemetry_unbalanced"
            return state
        state["embedding_inflight"] = (
            state["embedding_started"] - state["embedding_ended"])
        if anomaly_reason is not None:
            state["reason"] = anomaly_reason
            return state
        if cancelled_http_failure:
            state["reason"] = "external_http_cancelled"
            return state
        if require_ready and not state["ready"]:
            state["reason"] = "telemetry_ready_missing"
            return state
        if require_stopped and not state["service_stopped"]:
            state["reason"] = "service_stopped_missing"
            return state
        if require_runner_returned and not state["asyncio_runner_returned"]:
            state["reason"] = "asyncio_runner_returned_missing"
            return state
        state["anomaly"] = False
        state["reason"] = None
        return state
    except Exception:
        state["reason"] = "telemetry_parse_failed"
        return state


def telemetry_http_anomaly(
        path: Path, *, require_ready: bool = True,
        require_stopped: bool = False,
        require_runner_returned: bool = False) -> bool:
    return bool(telemetry_state(
        path, require_ready=require_ready,
        require_stopped=require_stopped,
        require_runner_returned=require_runner_returned)["anomaly"])


def polling_stop_reason(*, health_safe: bool, telemetry_path: Path) -> str | None:
    """Attribute authority loss before cancellation-only HTTP fallout."""

    telemetry = telemetry_state(telemetry_path)
    if telemetry["anomaly"] and telemetry["reason"] != "external_http_cancelled":
        return "PR2_EXTERNAL_HTTP_STOP"
    if not health_safe:
        return "PR2_RESOURCE_OR_LEASE_STOP"
    if telemetry["anomaly"]:
        return "PR2_EXTERNAL_HTTP_STOP"
    return None


def call_anomaly(record: dict) -> bool:
    observation = record.get("observability")
    if not isinstance(observation, dict):
        return True
    calls = observation.get("calls")
    if not isinstance(calls, list):
        return True
    return any(
        not isinstance(call, dict)
        or call.get("status") != "succeeded"
        or bool(call.get("failure_category"))
        for call in calls
    )


def verify_round_one_gate(root: Path) -> None:
    gate_path = root / "round-1-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if (gate.get("schema_version") != 1 or gate.get("round") != 1
            or gate.get("passed") is not True
            or gate.get("candidate_git_commit") != EXPECTED_COMMIT
            or gate.get("dataset_hash") != EXPECTED_DATASET
            or gate.get("manifest_map_sha256") !=
                manifest_map_sha256(EXPECTED_MANIFEST_BY_CASE)
            or gate.get("core_asset_registry_id") != EXPECTED_ASSET_REGISTRY
            or gate.get("completed_report_count") != 24
            or gate.get("paired_case_count") != 12
            or gate.get("independent_review_complete") is not True
            or gate.get("no_unresolved_blockers") is not True):
        raise ValueError("round-one gate identity or completion is invalid")
    profiles = gate.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"serial-r1", "concurrent-r1"}:
        raise ValueError("round-one gate profile set is invalid")
    tool_pairs = set()
    for profile in ("serial-r1", "concurrent-r1"):
        control = root / profile / "control/profile-control-result.json"
        identity = root / profile / "control/controller-identity.json"
        collection = root / "collections" / profile
        control_payload = json.loads(control.read_text(encoding="utf-8"))
        identity_payload = json.loads(identity.read_text(encoding="utf-8"))
        verify_frozen_tools(root, identity_payload)
        expected = profiles.get(profile)
        if (control_payload.get("execution_succeeded") is not True
                or control_payload.get("profile") != profile
                or control_payload.get("observed_records") != 12
                or control_payload.get("report_count") != 12
                or control_payload.get("metrics_complete") is not True
                or not isinstance(expected, dict)
                or expected.get("control_result_sha256") != file_hash(control)
                or expected.get("controller_identity_sha256") != file_hash(identity)
                or expected.get("collection_tree_sha256") != tree_identity(collection)
                or expected.get("controller_sha256") !=
                    identity_payload.get("controller_sha256")
                or expected.get("child_sha256") != identity_payload.get("child_sha256")):
            raise ValueError("round-one gate profile binding is invalid")
        tool_pairs.add((identity_payload.get("controller_sha256"),
                        identity_payload.get("child_sha256")))
    review_root = root / "review/round-1"
    review_lock = review_root / "review-lock.json"
    comparison = review_root / "comparison.json"
    review = json.loads(review_lock.read_text(encoding="utf-8"))
    compared = json.loads(comparison.read_text(encoding="utf-8"))
    checks = compared.get("checks")
    if (len(tool_pairs) != 1
            or gate.get("review_lock_sha256") != file_hash(review_lock)
            or gate.get("comparison_sha256") != file_hash(comparison)
            or gate.get("review_evidence_tree_sha256") != tree_identity(review_root)
            or review.get("status") != "locked"
            or review.get("review_count") != 24
            or review.get("independent_coverage") != "complete"
            or review.get("human_calibration") != "not_run"
            or compared.get("dataset_hash") != EXPECTED_DATASET
            or compared.get("case_count") != 12
            or compared.get("passed") is not True
            or not isinstance(checks, dict)
            or set(checks) != EXPECTED_COMPARISON_CHECKS
            or not all(checks.values())
            or gate.get("comparison_checks") != checks):
        raise ValueError("round-one review or comparison binding is invalid")

def verify_frozen_tools(root: Path, identity: dict | None = None) -> None:
    environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    frozen = (environment.get("notes") or {}).get("pr2_tool_hashes")
    tool_directory = Path(__file__).resolve().parent
    if (not isinstance(frozen, dict) or not frozen
            or any(file_hash(tool_directory / name) != digest
                   for name, digest in frozen.items())
            or (identity is not None and identity.get("pr2_tool_hashes") != frozen)):
        raise ValueError("PR2 tool identity differs from the frozen environment")

def gate_prerequisite(root: Path, profile: str) -> None:
    if profile == "serial-r1":
        return
    if profile == "concurrent-r1":
        path = root / "serial-r1/control/profile-control-result.json"
        required = "execution_succeeded"
    elif profile == "concurrent-r2":
        verify_round_one_gate(root)
        return
    else:
        path = root / "concurrent-r2/control/profile-control-result.json"
        required = "execution_succeeded"
    payload = json.loads(path.read_text(encoding="utf-8"))
    prior_profile = "serial-r1" if profile == "concurrent-r1" else "concurrent-r2"
    identity = json.loads((root / prior_profile /
                           "control/controller-identity.json").read_text(encoding="utf-8"))
    verify_frozen_tools(root, identity)
    if (payload.get(required) is not True
            or payload.get("profile") != prior_profile
            or payload.get("observed_records") != 12
            or payload.get("report_count") != 12
            or payload.get("metrics_complete") is not True):
        raise ValueError("prior profile or round gate has not passed")


def mutation_blocked(first_stop: str | None, abort_reason: str | None,
                     method: str, path: str) -> bool:
    return bool(method == "POST" and not path.endswith("/cancel")
                and (first_stop is not None or abort_reason is not None))


def frozen_decision(case: dict, index: int) -> dict:
    limit = 2 if case["hitl"]["action"] == "provide_context" else 1
    if index >= limit:
        raise ValueError("decision count exceeds the frozen case policy")
    action = (case["hitl"]["action"] if index == 0
              else case["hitl"].get("repeat_action", case["hitl"]["action"]))
    body = {"action": action}
    if action == "provide_context":
        body["supplemental_input"] = case["hitl"]["supplemental_input"]
    return body


async def wait_for_embedding_quiescence(
        child, telemetry_path: Path, *, timeout_seconds: float = 180.0) -> dict:
    started = time.monotonic()
    structural_failures = {
        "telemetry_missing", "telemetry_truncated", "telemetry_empty_line",
        "telemetry_schema_invalid", "embedding_telemetry_unbalanced",
        "telemetry_ready_missing", "telemetry_parse_failed",
    }
    while child.poll() is None:
        state = telemetry_state(telemetry_path, require_ready=True)
        if state["reason"] in structural_failures:
            return {"complete": False, "reason": state["reason"],
                    "waited_ms": round((time.monotonic() - started) * 1000)}
        if state["embedding_inflight"] == 0:
            return {"complete": True, "reason": "embedding_quiescent",
                    "waited_ms": round((time.monotonic() - started) * 1000)}
        if time.monotonic() - started >= timeout_seconds:
            return {"complete": False, "reason": "embedding_quiescence_timeout",
                    "waited_ms": round((time.monotonic() - started) * 1000)}
        await asyncio.sleep(0.5)
    return {"complete": True, "reason": "child_already_exited",
            "waited_ms": round((time.monotonic() - started) * 1000)}


async def shutdown_child(
        child, stop_flag: Path, owned_launcher,
        telemetry_path: Path | None = None) -> dict:
    result = {"action": "graceful", "unresolved": False, "error_type": None,
              "quiescence": None}
    if telemetry_path is not None and child.poll() is None:
        result["quiescence"] = await wait_for_embedding_quiescence(
            child, telemetry_path)
        if result["quiescence"]["complete"] is not True:
            result["unresolved"] = True
    try:
        if not stop_flag.exists():
            stop_flag.touch(exist_ok=False)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["unresolved"] = True
    cutoff = time.monotonic() + 60
    while child.poll() is None and time.monotonic() < cutoff:
        await asyncio.sleep(0.5)
    if child.poll() is not None:
        return result
    process = owned_launcher()
    if process is None:
        result.update(action="ownership_unresolved", unresolved=True)
        return result
    try:
        result["action"] = "terminate"
        process.terminate()
        cutoff = time.monotonic() + 15
        while child.poll() is None and time.monotonic() < cutoff:
            await asyncio.sleep(0.25)
        if child.poll() is None:
            process = owned_launcher()
            if process is None:
                result.update(action="kill_ownership_unresolved", unresolved=True)
                return result
            result["action"] = "kill"
            process.kill()
            cutoff = time.monotonic() + 15
            while child.poll() is None and time.monotonic() < cutoff:
                await asyncio.sleep(0.25)
        if child.poll() is None:
            result["unresolved"] = True
    except (psutil.Error, OSError) as exc:
        result.update(unresolved=True, error_type=type(exc).__name__)
    return result

async def settle(
        api_base: str, task_ids: list[str], journal: Path, safe: bool, *,
        timeout_seconds: float = CANCEL_SETTLE_TIMEOUT_SECONDS,
        poll_interval_seconds: float = CANCEL_POLL_INTERVAL_SECONDS) -> dict:
    result = {
        "attempted": 0,
        "settled": 0,
        "unresolved": [],
        "timeout_seconds": timeout_seconds,
        "resource_stop": False,
    }
    if not safe:
        result["unresolved"] = list(task_ids)
        return result
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("cleanup timing must be positive")
    timeout = httpx.Timeout(10, connect=5)
    pending = []
    async with httpx.AsyncClient(base_url=api_base, timeout=timeout) as client:
        for task_id in task_ids:
            try:
                response = await client.get(f"/api/v1/tasks/{task_id}")
                payload = response.json() if response.status_code == 200 else None
                status = ((payload or {}).get("task") or {}).get("status")
                if status in TERMINAL:
                    result["settled"] += 1
                    continue
                result["attempted"] += 1
                append(journal, {"event": "cleanup_cancel_attempt", "task_id": task_id,
                                 "at": stamp()})
                response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
                if response.status_code != 200:
                    result["unresolved"].append(task_id)
                    continue
                payload = response.json()
                status = ((payload or {}).get("task") or {}).get("status")
                if status in TERMINAL:
                    result["settled"] += 1
                else:
                    pending.append(task_id)
            except (httpx.HTTPError, ValueError, KeyError):
                result["unresolved"].append(task_id)

        cutoff = time.monotonic() + timeout_seconds
        while pending:
            if time.monotonic() >= cutoff:
                result["unresolved"].extend(pending)
                break
            try:
                available = psutil.virtual_memory().available
            except psutil.Error:
                result["unresolved"].extend(pending)
                break
            if available < STOP_MINIMUM_AVAILABLE_BYTES:
                result["resource_stop"] = True
                result["unresolved"].extend(pending)
                for task_id in pending:
                    append(journal, {
                        "event": "cleanup_resource_stop",
                        "task_id": task_id,
                        "available_bytes": available,
                        "at": stamp(),
                    })
                break
            await asyncio.sleep(min(
                poll_interval_seconds,
                max(0.0, cutoff - time.monotonic()),
            ))
            remaining = []
            for task_id in pending:
                try:
                    response = await client.get(f"/api/v1/tasks/{task_id}")
                    if response.status_code != 200:
                        result["unresolved"].append(task_id)
                        continue
                    payload = response.json()
                    status = ((payload or {}).get("task") or {}).get("status")
                    if status in TERMINAL:
                        result["settled"] += 1
                    else:
                        remaining.append(task_id)
                except (httpx.HTTPError, ValueError, KeyError):
                    result["unresolved"].append(task_id)
            pending = remaining
    return result


def _stop_final_row(
        task_id: str, binding: dict[str, str], detail: dict,
        observation: dict) -> dict:
    task = detail.get("task")
    latest_run = detail.get("latest_run")
    expected_run_id = binding.get("run_id")
    if (not isinstance(task, dict) or not isinstance(latest_run, dict)
            or task.get("task_id") != task_id
            or task.get("latest_run_id") != expected_run_id
            or latest_run.get("task_id") != task_id
            or latest_run.get("run_id") != expected_run_id
            or task.get("status") not in TERMINAL
            or latest_run.get("status") != task.get("status")):
        raise ValueError("task_identity_or_terminal_state_invalid")
    budget = observation.get("budget")
    if (observation.get("schema_version") != 1
            or observation.get("task_id") != task_id
            or observation.get("run_id") != expected_run_id
            or observation.get("availability") != "available"
            or observation.get("budget_policy_availability") != "available"
            or not isinstance(budget, dict)
            or budget.get("availability") != "available"
            or not isinstance(budget.get("resources"), dict)
            or not isinstance(observation.get("totals"), dict)
            or not isinstance(observation.get("nodes"), list)
            or not isinstance(observation.get("calls"), list)):
        raise ValueError("final_observability_invalid")
    return {
        "case_id": binding["case_id"],
        "task_id": task_id,
        "run_id": expected_run_id,
        "status": task["status"],
        "sampled_at": stamp(),
        "observability": observation,
    }


async def collect_stop_final_observability(
        api_base: str, task_bindings: dict[str, dict[str, str]], safe: bool,
        *, client: httpx.AsyncClient | None = None) -> dict:
    """Capture terminal, public latest-run telemetry without rewriting runs.jsonl."""
    result = {
        "schema_version": 1,
        "complete": False,
        "admitted_run_denominator": len(task_bindings),
        "observations": [],
        "errors": [],
    }
    if not safe:
        result["errors"].append({"category": "service_not_safe"})
        return result
    owned_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            base_url=api_base, timeout=httpx.Timeout(10, connect=5))
    try:
        for task_id, binding in sorted(
                task_bindings.items(), key=lambda item: item[1]["case_id"]):
            try:
                detail_response = await client.get(f"/api/v1/tasks/{task_id}")
                if detail_response.status_code != 200:
                    raise ValueError("task_snapshot_unavailable")
                detail = detail_response.json()
                if not isinstance(detail, dict):
                    raise ValueError("task_snapshot_invalid")
                observation_response = await client.get(
                    f"/api/v1/tasks/{task_id}/observability")
                if observation_response.status_code != 200:
                    raise ValueError("final_observability_unavailable")
                observation = observation_response.json()
                if not isinstance(observation, dict):
                    raise ValueError("final_observability_invalid")
                result["observations"].append(
                    _stop_final_row(task_id, binding, detail, observation))
            except httpx.HTTPError:
                result["errors"].append({
                    "case_id": binding["case_id"],
                    "task_id": task_id,
                    "category": "public_api_transport_failure",
                })
            except (KeyError, TypeError, ValueError) as exc:
                category = str(exc)
                if category not in {
                        "task_snapshot_unavailable", "task_snapshot_invalid",
                        "task_identity_or_terminal_state_invalid",
                        "final_observability_unavailable",
                        "final_observability_invalid"}:
                    category = "public_api_payload_invalid"
                result["errors"].append({
                    "case_id": binding.get("case_id"),
                    "task_id": task_id,
                    "category": category,
                })
    finally:
        if owned_client:
            await client.aclose()
    result["complete"] = bool(
        len(result["observations"]) == len(task_bindings)
        and not result["errors"])
    return result


def active_budget_metrics(stop_final: dict) -> dict:
    rows = []
    for observation in stop_final.get("observations") or []:
        resource = (((observation.get("observability") or {}).get("budget") or {})
                    .get("resources", {}).get("active_milliseconds"))
        rows.append({
            "case_id": observation.get("case_id"),
            "task_id": observation.get("task_id"),
            "run_id": observation.get("run_id"),
            "availability": resource.get("availability") if isinstance(resource, dict) else None,
            "hard_limit": resource.get("hard_limit") if isinstance(resource, dict) else None,
            "settled": resource.get("settled") if isinstance(resource, dict) else None,
            "unknown_spend": resource.get("unknown_spend") if isinstance(resource, dict) else None,
            "reserved": resource.get("reserved") if isinstance(resource, dict) else None,
            "remaining": resource.get("remaining") if isinstance(resource, dict) else None,
            "exhausted": resource.get("exhausted") if isinstance(resource, dict) else None,
        })
    denominator = stop_final.get("admitted_run_denominator")
    complete = bool(
        stop_final.get("complete") is True
        and type(denominator) is int
        and len(rows) == denominator
        and all(row["availability"] == "available"
                and type(row["settled"]) is int
                and type(row["unknown_spend"]) is int
                and type(row["reserved"]) is int
                and type(row["exhausted"]) is bool
                for row in rows))
    return {
        "schema_version": 1,
        "complete": complete,
        "resource": "active_milliseconds",
        "admitted_run_denominator": denominator,
        "runs": rows,
    }


def lifecycle_metrics(database: Path, task_cases: dict[str, str]) -> dict:
    if not database.is_file():
        raise ValueError("product database is unavailable")
    uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        task_rows = connection.execute(
            "SELECT task_id, status, latest_run_id FROM tasks ORDER BY task_id").fetchall()
        run_rows = connection.execute(
            "SELECT run_id, task_id, status, created_at, started_at, ended_at "
            "FROM runs ORDER BY task_id, created_at").fetchall()
        event_rows = connection.execute(
            "SELECT run_id, type, created_at FROM task_events "
            "WHERE type IN ('decision.required','decision.resolved','decision.cancelled') "
            "ORDER BY event_id").fetchall()
    finally:
        connection.close()
    database_tasks = {str(row[0]): {"status": str(row[1]), "latest_run_id": row[2]}
                      for row in task_rows}
    run_counts: dict[str, int] = {}
    for run in run_rows:
        run_counts[str(run[1])] = run_counts.get(str(run[1]), 0) + 1
    events: dict[str, list[tuple[str, str]]] = {}
    for run_id, event_type, created_at in event_rows:
        if run_id is not None:
            events.setdefault(str(run_id), []).append((str(event_type), str(created_at)))
    rows = []
    complete = True
    for run_id, task_id, status, created_at, started_at, ended_at in run_rows:
        if task_id not in task_cases:
            continue
        def parsed(value):
            return datetime.fromisoformat(value) if isinstance(value, str) else None
        created = parsed(created_at)
        started = parsed(started_at)
        ended = parsed(ended_at)
        queue_ms = ((started - created).total_seconds() * 1000
                    if created is not None and started is not None else None)
        elapsed_ms = ((ended - started).total_seconds() * 1000
                      if started is not None and ended is not None else None)
        waiting_ms = 0.0
        pending = None
        for event_type, at in events.get(str(run_id), []):
            observed = parsed(at)
            if event_type == "decision.required":
                if pending is not None:
                    complete = False
                pending = observed
            elif pending is not None and observed is not None:
                interval = (observed - pending).total_seconds() * 1000
                if interval < 0:
                    complete = False
                else:
                    waiting_ms += interval
                pending = None
            elif event_type in {"decision.resolved", "decision.cancelled"}:
                complete = False
        if pending is not None:
            complete = False
            waiting_value = None
        else:
            waiting_value = round(waiting_ms)
        non_hitl_elapsed_ms = (max(0.0, elapsed_ms - waiting_ms)
                               if elapsed_ms is not None and waiting_value is not None else None)
        task_identity = database_tasks.get(str(task_id), {})
        if (queue_ms is None or non_hitl_elapsed_ms is None or status not in TERMINAL
                or task_identity.get("status") != status
                or task_identity.get("latest_run_id") != run_id
                or run_counts.get(str(task_id)) != 1):
            complete = False
        rows.append({
            "case_id": task_cases[task_id],
            "task_id": task_id,
            "run_id": str(run_id),
            "status": str(status),
            "queue_ms": round(queue_ms) if queue_ms is not None else None,
            "non_hitl_elapsed_ms": (round(non_hitl_elapsed_ms)
                                     if non_hitl_elapsed_ms is not None else None),
            "hitl_wait_ms": waiting_value,
            "elapsed_after_start_ms": round(elapsed_ms) if elapsed_ms is not None else None,
        })
    created_values = [datetime.fromisoformat(row[3]) for row in run_rows if row[3]]
    ended_values = [datetime.fromisoformat(row[5]) for row in run_rows if row[5]]
    makespan = ((max(ended_values) - min(created_values)).total_seconds() * 1000
                if created_values and len(ended_values) == len(run_rows) else None)
    unexpected = sorted(set(database_tasks) - set(task_cases))
    missing = sorted(set(task_cases) - set(database_tasks))
    nonterminal = sorted(task_id for task_id, value in database_tasks.items()
                         if value["status"] not in TERMINAL)
    complete = (complete and len(rows) == len(task_cases)
                and not unexpected and not missing and not nonterminal)
    return {
        "schema_version": 1,
        "complete": complete,
        "database_task_count": len(database_tasks),
        "known_task_count": len(task_cases),
        "unexpected_task_ids": unexpected,
        "missing_task_ids": missing,
        "nonterminal_task_ids": nonterminal,
        "profile_makespan_ms": round(makespan) if makespan is not None else None,
        "runs": sorted(rows, key=lambda row: row["case_id"]),
    }

async def execute(root: Path, frozen_root: Path, env_file: Path, profile: str) -> bool:
    if not env_file.is_file():
        raise ValueError("private environment is unavailable")
    load_dotenv(env_file, override=False)
    os.chdir(frozen_root)
    sys.path.insert(0, str(frozen_root))
    from benchmarks import product_baseline as baseline
    from benchmarks import product_baseline_qualification as qualification
    from benchmarks.product_baseline import load_dataset
    from benchmarks.product_baseline_experiment import RESOURCE_SETTINGS, embedding_revision, tree_hash
    from deepchoice.contracts.manifest import build_core_asset_registry

    profile_kind, repetition, concurrency = PROFILE[profile]
    gate_prerequisite(root, profile)
    cfg = qualification.trusted_configuration()
    environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    notes = environment["notes"]
    if qualification.git_identity() != EXPECTED_COMMIT or notes.get("git_commit") != EXPECTED_COMMIT:
        raise ValueError("candidate changed before admission")
    expected_settings = {**RESOURCE_SETTINGS,
                         "LLM_DS_CONCURRENCY": os.getenv("LLM_DS_CONCURRENCY", "80"),
                         "DEEPCHOICE_SYNTH_THINKING": "0"}
    dependency_path = root / "dependencies.json"
    dependencies = json.loads(dependency_path.read_text(encoding="utf-8"))
    if (notes.get("dataset_hash") != EXPECTED_DATASET
            or environment.get("knowledge_snapshot_sha256") != EXPECTED_KNOWLEDGE
            or environment.get("dependency_snapshot_sha256") != EXPECTED_DEPENDENCIES
            or qualification.file_hash(dependency_path) != EXPECTED_DEPENDENCIES
            or notes.get("configuration_sha256") != EXPECTED_CONFIGURATION
            or qualification.configuration_sha256(cfg) != EXPECTED_CONFIGURATION
            or notes.get("endpoint_sha256") != EXPECTED_ENDPOINT
            or notes.get("safe_fetch_proxy_sha256") != EXPECTED_PROXY
            or cfg.safe_fetch_proxy_sha256 != EXPECTED_PROXY
            or notes.get("embedding_revision") != EXPECTED_EMBEDDING_REVISION
            or embedding_revision() != EXPECTED_EMBEDDING_REVISION
            or notes.get("expected_manifest_by_case") != EXPECTED_MANIFEST_BY_CASE
            or notes.get("core_asset_registry_id") != EXPECTED_ASSET_REGISTRY
            or build_core_asset_registry().registry_id != EXPECTED_ASSET_REGISTRY
            or notes.get("settings") != expected_settings
            or environment.get("model") != {"provider": "deepseek-flash",
                                             "model_id": "deepseek-v4-flash",
                                             "thinking": "disabled"}
            or dependencies != [list(value) for value in qualification.dependency_records()]):
        raise ValueError("frozen PR1 environment identity changed before admission")
    profile_root = root / profile
    runtime = profile_root / "runtime"
    control = profile_root / "control"
    collection = root / "collections" / profile
    if (not profile_root.is_dir() or any(runtime.iterdir()) or any(control.iterdir())
            or collection.exists()):
        raise ValueError("profile must be fresh and empty")
    if tree_hash(profile_root / "knowledge") != EXPECTED_KNOWLEDGE:
        raise ValueError("profile knowledge identity changed")
    if psutil.virtual_memory().available < 2 * 1024 ** 3:
        raise RuntimeError("insufficient startup memory")

    dataset, dataset_hash = load_dataset(
        frozen_root / "benchmarks/product-baseline-v1.json", require_frozen=True)
    if dataset_hash != EXPECTED_DATASET:
        raise ValueError("frozen dataset hash changed")
    cases = {signature(case["request"]): case for case in dataset["cases"]}
    tool_directory = Path(__file__).resolve().parent
    frozen_tool_hashes = notes.get("pr2_tool_hashes")
    if (not isinstance(frozen_tool_hashes, dict) or not frozen_tool_hashes
            or any(qualification.file_hash(tool_directory / name) != digest
                   for name, digest in frozen_tool_hashes.items())):
        raise ValueError("PR2 control tooling changed after environment freeze")
    child_path = (tool_directory / "o1_pr2b_child.py").resolve()
    journal = control / "control-admissions.jsonl"
    events = control / "control-events.jsonl"
    stop_flag = control / "stop-service.flag"
    qualification.write_json(control / "controller-identity.json", {
        "controller_sha256": qualification.file_hash(Path(__file__)),
        "child_sha256": qualification.file_hash(child_path),
        "pr2_tool_hashes": frozen_tool_hashes,
        "git_commit": EXPECTED_COMMIT,
        "dataset_hash": EXPECTED_DATASET,
        "profile": profile,
        "repetition": repetition,
        "concurrency": concurrency,
        "startup_minimum_available_bytes": 2 * 1024 ** 3,
        "stop_minimum_available_bytes": STOP_MINIMUM_AVAILABLE_BYTES,
        "auto_recovery": False,
        "started_at": stamp(),
    })

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    api_base = f"http://127.0.0.1:{port}"
    arguments = [
        str(child_path), "--root", str(root), "--port", str(port),
        "--profile", profile, "--frozen-root", str(frozen_root),
        "--control-root", str(control),
    ]
    child = subprocess.Popen(
        [sys.executable, *arguments], cwd=frozen_root, env=os.environ.copy(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        launcher_identity = (child.pid, psutil.Process(child.pid).create_time())
    except psutil.Error:
        child.terminate()
        child.wait(timeout=15)
        raise RuntimeError("could not freeze launcher identity")

    def owned_launcher():
        if child.poll() is not None:
            return None
        try:
            process = psutil.Process(child.pid)
            if ((process.pid, process.create_time()) != launcher_identity
                    or process.cmdline()[1:] != arguments):
                return None
            return process
        except psutil.Error:
            return None

    server_identity = None
    def owned_server():
        nonlocal server_identity
        if child.poll() is not None:
            return None
        try:
            launcher = owned_launcher()
            if launcher is None:
                return None
            candidates = []
            for process in [launcher, *launcher.children(recursive=True)]:
                if process.cmdline()[1:] != arguments:
                    continue
                if any(connection.status == psutil.CONN_LISTEN
                       and tuple(connection.laddr) == ("127.0.0.1", port)
                       for connection in process.net_connections(kind="inet")):
                    candidates.append(process)
            if len(candidates) != 1:
                return None
            process = candidates[0]
            identity = (process.pid, process.create_time())
            if server_identity is not None and identity != server_identity:
                return None
            server_identity = identity
            return process
        except psutil.Error:
            return None

    original_request = baseline.DurableBaselineCollector._request_json
    original_case = baseline.DurableBaselineCollector._collect_case
    admission_cases = set()
    task_cases = {}
    task_bindings = {}
    decision_counts = {}
    first_stop = None
    cancellation_count = 0
    latest_health_safe = True

    def stop(collector, reason: str):
        nonlocal first_stop
        if first_stop is None:
            first_stop = reason
            append(events, {"event": "profile_stop", "reason": reason, "at": stamp()})
        collector._abort_reason = first_stop

    async def guarded(collector, method, path, **kwargs):
        nonlocal cancellation_count, latest_health_safe
        case_id = None
        if mutation_blocked(first_stop, collector._abort_reason, method, path):
            raise RuntimeError("profile stop latch forbids further mutation")
        if method == "POST" and path == "/api/v1/tasks":
            case = cases.get(signature(kwargs.get("json")))
            if case is None or case["id"] in admission_cases or len(admission_cases) >= 12:
                stop(collector, "PR2_ADMISSION_CONTRACT_STOP")
                raise RuntimeError("invalid or duplicate profile admission")
            if owned_server() is None:
                stop(collector, "PR2_PROCESS_OWNERSHIP_STOP")
                raise RuntimeError("service ownership unavailable")
            case_id = case["id"]
            admission_cases.add(case_id)
            append(journal, {"event": "admission_attempt", "case_id": case_id,
                             "ordinal": len(admission_cases), "at": stamp()})
        decision_match = re.fullmatch(
            r"/api/v1/tasks/([^/]+)/decisions/([^/]+)", path)
        if method == "POST" and decision_match:
            task_id = decision_match.group(1)
            case_id = task_cases.get(task_id)
            if case_id is None:
                stop(collector, "PR2_DECISION_CONTRACT_STOP")
                raise RuntimeError("decision is not bound to an admitted task")
            case = next(item for item in dataset["cases"] if item["id"] == case_id)
            index = decision_counts.get(task_id, 0)
            try:
                expected = frozen_decision(case, index)
            except ValueError:
                stop(collector, "PR2_DECISION_CONTRACT_STOP")
                raise
            if kwargs.get("json") != expected:
                stop(collector, "PR2_DECISION_CONTRACT_STOP")
                raise RuntimeError("decision differs from the frozen case policy")
            decision_counts[task_id] = index + 1
            append(journal, {"event": "decision_attempt", "case_id": case_id,
                             "action": expected["action"],
                             "ordinal": index + 1, "at": stamp()})
        if method == "POST" and path.endswith("/cancel"):
            task_id = path.split("/")[4] if len(path.split("/")) > 4 else ""
            if task_id not in task_cases:
                stop(collector, "PR2_CANCELLATION_CONTRACT_STOP")
                raise RuntimeError("cancellation is not bound to an admitted task")
            cancellation_count += 1
            append(journal, {"event": "collector_cancel_attempt",
                             "case_id": task_cases[task_id], "at": stamp()})

        response, payload = await original_request(collector, method, path, **kwargs)
        if method == "POST" and path == "/api/v1/tasks":
            if response.status_code != 202 or not payload:
                stop(collector, "PR2_ADMISSION_FAILURE_STOP")
            else:
                task = payload.get("task") or {}
                run = payload.get("latest_run") or {}
                task_id = task.get("task_id")
                run_id = run.get("run_id")
                if (not isinstance(task_id, str)
                        or not isinstance(run_id, str)
                        or run.get("manifest_id") !=
                            notes["expected_manifest_by_case"].get(case_id)):
                    stop(collector, "PR2_FROZEN_MANIFEST_STOP")
                    raise RuntimeError("admitted task differs from the frozen manifest")
                task_cases[task_id] = case_id
                task_bindings[task_id] = {
                    "case_id": case_id, "run_id": run_id}
                append(journal, {"event": "admitted", "case_id": case_id,
                                 "task_id": task_id, "run_id": run_id,
                                 "manifest_id": run.get("manifest_id"), "at": stamp()})
        if method == "GET" and path.endswith("/snapshot") and source_anomaly(payload):
            stop(collector, "PR2_SOURCE_DEGRADATION_STOP")
        if method == "GET" and path == "/health":
            memory = psutil.virtual_memory().available
            process = owned_server()
            try:
                rss = process.memory_info().rss if process is not None else None
            except psutil.Error:
                rss = None
            observation = (payload or {}).get("runtime_observations") or {}
            heartbeat = (payload or {}).get("run_heartbeat") or {}
            append(control / "resource-health.jsonl", {
                "at": stamp(), "available_bytes": memory, "service_rss_bytes": rss,
                "http_status": response.status_code,
                "runtime_instance": (payload or {}).get("runtime_instance"),
                "authority_valid": observation.get("authority_valid"),
                "heartbeat_success_age_ms": observation.get("heartbeat_success_age_ms"),
                "lease_remaining_ms": observation.get("lease_remaining_ms"),
                "heartbeat_failures": heartbeat.get("failures"),
                "lease_losses": heartbeat.get("lease_losses"),
            })
            running_authority_required = bool(collector._running_cases)
            authority_complete = (
                observation.get("authority_valid") is True
                and isinstance(observation.get("lease_remaining_ms"), (int, float))
                and observation["lease_remaining_ms"] > 0
                and type(heartbeat.get("failures")) is int
                and heartbeat["failures"] == 0
                and type(heartbeat.get("lease_losses")) is int
                and heartbeat["lease_losses"] == 0
            )
            latest_health_safe = bool(
                process is not None
                and response.status_code == 200
                and (payload or {}).get("runtime_instance") == "active"
                and memory >= STOP_MINIMUM_AVAILABLE_BYTES
                and (not running_authority_required or authority_complete)
            )
            poll_stop = polling_stop_reason(
                health_safe=latest_health_safe,
                telemetry_path=control / "telemetry.jsonl",
            )
            if poll_stop is not None:
                stop(collector, poll_stop)
                return httpx.Response(503), None
            if first_stop is not None:
                return httpx.Response(503), None
        return response, payload

    async def observed_case(collector, case):
        record = await original_case(collector, case)
        usage = record.get("usage") or {}
        diagnostics = record.get("diagnostics") or {}
        if (record.get("status") not in SUCCESS or record.get("error_code")
                or budget_anomaly(record)
                or call_anomaly(record)
                or record.get("observability_final") is not True
                or (record.get("observability") or {}).get("availability") != "available"
                or (isinstance(usage.get("failed_calls"), int) and usage["failed_calls"] > 0)
                or diagnostics.get("failure_categories")
                or diagnostics.get("run_failure_category")):
            stop(collector, "PR2_CASE_OR_BUDGET_STOP")
        return record

    result = {"profile": profile, "repetition": repetition, "concurrency": concurrency,
              "started_at": stamp(), "collection_finished": False}
    try:
        async with httpx.AsyncClient(base_url=api_base, timeout=5) as client:
            cutoff = time.monotonic() + 180
            ready = False
            while time.monotonic() < cutoff and child.poll() is None:
                try:
                    response = await client.get("/health")
                    payload = response.json()
                    if (response.status_code == 200
                            and payload.get("runtime_instance") == "active"
                            and owned_server() is not None):
                        ready = True
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                await asyncio.sleep(2)
            if not ready:
                raise RuntimeError("service readiness unavailable")
        baseline.DurableBaselineCollector._request_json = guarded
        baseline.DurableBaselineCollector._collect_case = observed_case
        args = argparse.Namespace(
            command="collect",
            cases_file=str(frozen_root / "benchmarks/product-baseline-v1.json"),
            environment_file=str(root / "environment.json"),
            output_dir=str(collection),
            execute_paid_runs=True,
            profile=profile_kind,
            concurrency=concurrency,
            repetition=repetition,
            poll_interval=2,
            case_timeout=2100,
            stop_at_hitl=False,
            case_id=None,
            api_base=api_base,
        )
        exit_code = await baseline._collect(args)
        result["collection_finished"] = exit_code == 0
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    finally:
        try:
            baseline.DurableBaselineCollector._request_json = original_request
            baseline.DurableBaselineCollector._collect_case = original_case
        except Exception as exc:
            result["restore_error_type"] = type(exc).__name__

        cleanup = {"attempted": 0, "settled": 0,
                   "unresolved": list(task_cases), "error_type": None}
        try:
            cleanup = await settle(
                api_base, list(task_cases), journal,
                owned_server() is not None and latest_health_safe)
            cleanup["error_type"] = None
        except Exception as exc:
            cleanup["error_type"] = type(exc).__name__

        stop_final = {
            "schema_version": 1, "complete": False,
            "admitted_run_denominator": len(task_bindings),
            "observations": [], "errors": [{"category": "capture_not_attempted"}],
        }
        try:
            stop_final = await collect_stop_final_observability(
                api_base, task_bindings,
                owned_server() is not None and latest_health_safe
                and not cleanup["unresolved"] and cleanup.get("error_type") is None)
        except Exception as exc:
            stop_final["errors"] = [{"category": type(exc).__name__}]
        try:
            qualification.write_json(
                control / "stop-final-observability.json", stop_final)
        except Exception as exc:
            stop_final["complete"] = False
            result["stop_final_write_error_type"] = type(exc).__name__

        shutdown = await shutdown_child(
            child, stop_flag, owned_launcher, control / "telemetry.jsonl")

        metrics = {"complete": False, "error_type": None}
        if child.poll() is not None:
            try:
                metrics = lifecycle_metrics(runtime / "product.db", task_cases)
                metrics["error_type"] = None
                qualification.write_json(control / "lifecycle-metrics.json", metrics)
            except Exception as exc:
                metrics = {"complete": False, "error_type": type(exc).__name__}
        else:
            metrics["error_type"] = "ServiceStillRunning"

        records = []
        record_error = None
        try:
            runs = collection / "runs.jsonl"
            if runs.is_file():
                records = [
                    json.loads(line)
                    for line in runs.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
        except Exception as exc:
            record_error = type(exc).__name__
        metadata = {}
        metadata_error = None
        metadata_valid = False
        try:
            experiment_path = collection / "experiment.json"
            metadata = json.loads(experiment_path.read_text(encoding="utf-8"))
            metadata_valid = bool(
                metadata.get("git_commit") == EXPECTED_COMMIT
                and metadata.get("dataset_hash") == EXPECTED_DATASET
                and metadata.get("profile") == profile_kind
                and metadata.get("repetition") == repetition
                and metadata.get("requested_concurrency") == concurrency
                and metadata.get("case_denominator") == 12
                and metadata.get("order_seed") == 20260916 + repetition
                and set(metadata.get("case_order") or []) ==
                    {f"P{ordinal:02d}" for ordinal in range(1, 13)}
                and metadata.get("admitted_run_denominator") == 12
                and metadata.get("manifest_ids") ==
                    sorted(set(EXPECTED_MANIFEST_BY_CASE.values()))
                and metadata.get("collector_stop_reason") is None
                and metadata.get("source_health") == "passed"
                and metadata.get("peak_in_flight_cases") == concurrency
            )
            experiment_sha256 = file_hash(experiment_path)
        except Exception as exc:
            metadata_error = type(exc).__name__
            experiment_sha256 = None
        active_budget = active_budget_metrics(stop_final)
        active_budget_complete = active_budget["complete"]
        try:
            qualification.write_json(
                control / "active-budget-metrics.json", active_budget)
        except Exception as exc:
            active_budget_complete = False
            result["active_budget_write_error_type"] = type(exc).__name__
        reports = sum(bool(record.get("report_path")) for record in records)
        successful = sum(
            record.get("status") in SUCCESS and not record.get("error_code")
            for record in records
        )
        result.update(
            ended_at=stamp(),
            admission_attempts=len(admission_cases),
            unique_admitted_tasks=len(task_cases),
            cancellation_attempts=cancellation_count + cleanup["attempted"],
            cleanup_settled=cleanup["settled"],
            cleanup_unresolved_count=len(cleanup["unresolved"]),
            cleanup_error_type=cleanup.get("error_type"),
            first_stop_reason=first_stop,
            observed_records=len(records),
            record_read_error_type=record_error,
            experiment_metadata_valid=metadata_valid,
            experiment_metadata_error_type=metadata_error,
            experiment_sha256=experiment_sha256,
            peak_in_flight_cases=metadata.get("peak_in_flight_cases"),
            peak_observed_running_cases=metadata.get("peak_observed_running_cases"),
            successful_records=successful,
            report_count=reports,
            restricted_report_count=sum(
                record.get("status") == "completed_with_warnings" for record in records),
            hitl_resolution_count=sum(
                record.get("hitl_resolutions") or 0 for record in records),
            total_case_wall_time_ms=sum(
                record.get("wall_time_ms") or 0 for record in records),
            profile_makespan_ms=metrics.get("profile_makespan_ms"),
            metrics_complete=metrics.get("complete") is True,
            stop_final_observability_complete=stop_final.get("complete") is True,
            stop_final_observability_error_count=len(stop_final.get("errors") or []),
            active_budget_metrics_complete=active_budget_complete,
            telemetry_external_anomaly=telemetry_http_anomaly(
                control / "telemetry.jsonl", require_stopped=True,
                require_runner_returned=True),
            metrics_error_type=metrics.get("error_type"),
            forced_service_stop_action=shutdown["action"],
            process_cleanup_unresolved=shutdown["unresolved"],
            process_cleanup_error_type=shutdown["error_type"],
            shutdown_quiescence=shutdown.get("quiescence"),
            graceful_service_exit=shutdown["action"] == "graceful" and child.poll() == 0,
            service_exit_code=child.poll(),
        )
        result["execution_succeeded"] = bool(
            result["collection_finished"] and first_stop is None
            and len(admission_cases) == 12 and len(task_cases) == 12
            and len(records) == 12 and successful == 12 and reports == 12
            and metadata_valid
            and not telemetry_http_anomaly(
                control / "telemetry.jsonl", require_stopped=True,
                require_runner_returned=True)
            and not cleanup["unresolved"] and cleanup.get("error_type") is None
            and metrics.get("complete") is True
            and stop_final.get("complete") is True
            and active_budget_complete
            and shutdown["action"] == "graceful"
            and not shutdown["unresolved"] and child.poll() == 0
        )
        try:
            qualification.write_json(
                control / "profile-control-result.json", result)
        except Exception as exc:
            result["result_write_error_type"] = type(exc).__name__
            result["execution_succeeded"] = False
        print(json.dumps(result, sort_keys=True), flush=True)
    return result["execution_succeeded"]


def admission_journal_counts(path: Path) -> dict:
    counts = {"admission_attempts": 0, "admitted": 0}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if value.get("event") == "admission_attempt":
                counts["admission_attempts"] += 1
            elif value.get("event") == "admitted":
                counts["admitted"] += 1
    except FileNotFoundError:
        pass
    except Exception:
        counts["journal_read_error"] = True
    return counts

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(PROFILE), required=True)
    parser.add_argument("--execute-paid-profile", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid_profile:
        parser.error("explicit paid profile execution flag required")
    try:
        ok = asyncio.run(execute(args.root.resolve(), args.frozen_root.resolve(),
                                 args.env_file.resolve(), args.profile))
        raise SystemExit(0 if ok else 1)
    except Exception as exc:
        counts = admission_journal_counts(
            args.root.resolve() / args.profile / "control/control-admissions.jsonl")
        print(json.dumps({"error_type": type(exc).__name__,
                          "research_runs_submitted": counts["admitted"],
                          **counts}, sort_keys=True), flush=True)
        raise SystemExit(1)
