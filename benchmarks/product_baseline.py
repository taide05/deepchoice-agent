"""Durable product-baseline collection and serial/concurrent comparison.

This module never uses the legacy direct-graph benchmark path or an LLM judge.
Collection is deliberately guarded by ``--execute-paid-runs`` because every
case can call paid LLM and retrieval services.
"""

from __future__ import annotations

import argparse
from collections import Counter
import asyncio
import csv
import hashlib
import json
import os
import platform
import random
import re
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from deepchoice.contracts.api import ResearchRequest

EXPECTED_CASE_COUNT = 12
TERMINAL_STATUSES = frozenset(
    {"completed", "completed_with_warnings", "failed", "timed_out", "cancelled"}
)
SUCCESS_STATUSES = frozenset({"completed", "completed_with_warnings"})
CASE_ID = re.compile(r"^P\d{2}$")
SCORE_FIELDS = (
    "decision_correctness",
    "citation_support",
    "source_quality",
    "conflict_handling",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _safe_api_base(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API base must be a credential-free HTTP(S) URL")
    return value.rstrip("/")


def load_dataset(path: Path, *, require_frozen: bool = False) -> tuple[dict[str, Any], str]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(dataset, dict):
        raise ValueError("dataset root must be an object")
    if dataset.get("dataset_id") != "product-baseline-v1":
        raise ValueError("unexpected dataset_id")
    if require_frozen and dataset.get("status") != "frozen":
        raise ValueError("paid collection requires a frozen dataset")
    if require_frozen:
        freeze_date = dataset.get("freeze_date")
        if not isinstance(freeze_date, str):
            raise ValueError("frozen dataset requires a freeze date")
        datetime.strptime(freeze_date, "%Y-%m-%d")
        policy = dataset.get("case_policy") or {}
        reference = Path(__file__).resolve().parent.parent / "docs" / "o1-reference-audit.md"
        if policy.get("approved_by") != "user-in-current-session" or policy.get(
            "reference_audit_sha256") != hashlib.sha256(reference.read_bytes()).hexdigest():
            raise ValueError("frozen dataset reference audit approval/hash is invalid")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        raise ValueError(f"dataset must contain exactly {EXPECTED_CASE_COUNT} cases")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each case must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or CASE_ID.fullmatch(case_id) is None:
            raise ValueError("case id must match PNN")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        if case.get("split") not in {"development", "holdout"}:
            raise ValueError(f"invalid split for {case_id}")
        ResearchRequest.model_validate(case.get("request"))
        rubric = case.get("rubric")
        if not isinstance(rubric, dict) or not rubric.get("must_answer"):
            raise ValueError(f"missing rubric for {case_id}")
        hitl = case.get("hitl")
        if not isinstance(hitl, dict) or hitl.get("action") not in {
            "provide_context",
            "limited_report",
            "cancel",
        }:
            raise ValueError(f"invalid HITL policy for {case_id}")
        if hitl["action"] == "provide_context" and not hitl.get("supplemental_input"):
            raise ValueError(f"missing HITL supplemental input for {case_id}")
        repeat_action = hitl.get("repeat_action", hitl["action"])
        if repeat_action not in {"provide_context", "limited_report", "cancel"}:
            raise ValueError(f"invalid repeated HITL policy for {case_id}")
        if repeat_action == "provide_context" and not hitl.get("supplemental_input"):
            raise ValueError(f"missing repeated HITL supplemental input for {case_id}")
    if seen != {f"P{index:02d}" for index in range(1, 13)}:
        raise ValueError("dataset must use fixed case identities P01..P12")
    if any(case["split"] != ("development" if int(case["id"][1:]) <= 8 else "holdout")
           for case in cases):
        raise ValueError("dataset must preserve the fixed 8/4 split")
    return dataset, _sha256(dataset)


def load_environment(path: Path, *, require_ready: bool = False) -> tuple[dict[str, Any], str]:
    environment = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(environment, dict) or environment.get("schema_version") != 1:
        raise ValueError("environment manifest must use schema_version 1")
    allowed = {
        "schema_version",
        "status",
        "model",
        "dependency_snapshot_sha256",
        "knowledge_snapshot_sha256",
        "retrieval_health",
        "llm_compatibility",
        "notes",
    }
    if set(environment) - allowed:
        raise ValueError("environment manifest contains unsupported fields")
    if environment.get("status") not in {"candidate", "ready"}:
        raise ValueError("environment manifest has invalid status")
    if require_ready and environment.get("status") != "ready":
        raise ValueError("paid collection requires a ready environment manifest")
    for field in ("dependency_snapshot_sha256", "knowledge_snapshot_sha256"):
        value = environment.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"environment manifest has invalid {field}")
        if require_ready and value == "0" * 64:
            raise ValueError("ready environment cannot contain placeholder hashes")
    model = environment.get("model")
    if not isinstance(model, dict):
        raise ValueError("environment manifest must identify the model configuration")
    if set(model) - {"provider", "model_id", "thinking"}:
        raise ValueError("model configuration contains unsupported fields")
    if model.get("provider") != "deepseek-flash":
        raise ValueError("product baseline requires the DeepSeek Flash provider")
    if not all(isinstance(model.get(field), str) and model[field] for field in ("model_id", "thinking")):
        raise ValueError("model_id and thinking must be non-empty strings")
    if environment.get("retrieval_health") not in {"not_run", "passed", "failed"}:
        raise ValueError("environment manifest has invalid retrieval_health")
    if environment.get("llm_compatibility") not in {"not_run", "passed", "failed"}:
        raise ValueError("environment manifest has invalid llm_compatibility")
    if require_ready:
        if environment.get("retrieval_health") != "passed":
            raise ValueError("retrieval health must pass before paid collection")
        if environment.get("llm_compatibility") != "passed":
            raise ValueError("LLM compatibility must pass before paid collection")
    return environment, _sha256(environment)


def _http_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP_{response.status_code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else f"HTTP_{response.status_code}"


@dataclass(frozen=True)
class CollectionOptions:
    profile: str
    repetition: int
    concurrency: int
    poll_interval_seconds: float
    case_timeout_seconds: float


class DurableBaselineCollector:
    def __init__(
        self,
        client: httpx.AsyncClient,
        output_dir: Path,
        *,
        experiment_id: str,
        dataset_hash: str,
        options: CollectionOptions,
    ) -> None:
        self.client = client
        self.output_dir = output_dir
        self.experiment_id = experiment_id
        self.dataset_hash = dataset_hash
        self.options = options
        self._write_lock = asyncio.Lock()
        self._active_cases = 0
        self.peak_in_flight = 0
        self._running_cases: set[str] = set()
        self.peak_observed_running = 0
        self._abort_reason: str | None = None

    async def _healthy(self) -> bool:
        if self._abort_reason:
            return False
        try:
            response, payload = await self._request_json("GET", "/health")
        except httpx.HTTPError:
            self._abort_reason = "RUNTIME_HEALTH_UNAVAILABLE"
            return False
        if response.status_code != 200 or not payload or payload.get("runtime_instance") != "active":
            self._abort_reason = "RUNTIME_HEALTH_UNAVAILABLE"
            return False
        self._last_runtime_observations = payload.get("runtime_observations")
        self._last_run_heartbeat = payload.get("run_heartbeat")
        if isinstance(self._last_runtime_observations, dict) and self._last_runtime_observations.get("authority_valid") is False:
            self._abort_reason = "RUNTIME_HEALTH_UNAVAILABLE"
            return False
        return True

    async def _sample_observability(self, record: dict[str, Any], *, final: bool = False) -> None:
        record["observability_final"] = False
        try:
            response, observation = await self._request_json(
                "GET", f"/api/v1/tasks/{record['task_id']}/observability")
        except httpx.HTTPError:
            return  # Preserve the last readable usage on transport loss.
        if response.status_code == 200 and observation:
            if observation.get("run_id", record["run_id"]) != record["run_id"]:
                record["error_code"] = "OBSERVABILITY_RUN_MISMATCH"
                self._abort_reason = record["error_code"]
                return
            record["observability"] = observation
            record["observability_sampled_at"] = _utc_now()
            record["observability_final"] = final and record["status"] in TERMINAL_STATUSES

    async def _cancel_and_settle(self, record: dict[str, Any]) -> None:
        task_id = record["task_id"]
        response, task = await self._request_json("POST", f"/api/v1/tasks/{task_id}/cancel")
        if response.status_code != 200 or task is None:
            record["error_code"] = _http_error_code(response)
            return
        cutoff = time.monotonic() + 30
        while True:
            record["status"] = task["task"]["status"]
            if record["status"] in TERMINAL_STATUSES:
                return
            if time.monotonic() >= cutoff:
                record["error_code"] = "CANCELLATION_UNSETTLED"
                return
            await asyncio.sleep(max(0.1, min(self.options.poll_interval_seconds, 2)))
            response, task = await self._request_json("GET", f"/api/v1/tasks/{task_id}")
            if response.status_code != 200 or task is None:
                record["error_code"] = _http_error_code(response)
                return
            if (task.get("latest_run") or {}).get("run_id") != record["run_id"]:
                record["error_code"] = "RUN_IDENTITY_CHANGED"
                return

    async def _journal(self, record: dict[str, Any], event: str) -> None:
        """Persist submission identity immediately; never retry uncertain creation."""
        entry = {key: record.get(key) for key in (
            "experiment_id", "case_id", "task_id", "run_id", "manifest_id", "status"
        )}
        entry.update(event=event, observed_at=_utc_now())
        async with self._write_lock:
            with (self.output_dir / "admissions.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    async def collect(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.options.concurrency)

        async def bounded(case: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                self._active_cases += 1
                self.peak_in_flight = max(self.peak_in_flight, self._active_cases)
                try:
                    return await self._collect_case(case)
                finally:
                    self._active_cases -= 1
                    self._running_cases.discard(case["id"])

        results = await asyncio.gather(*(bounded(case) for case in cases))
        return list(results)

    async def _request_json(
        self, method: str, path: str, **kwargs: Any
    ) -> tuple[httpx.Response, dict[str, Any] | None]:
        response = await self.client.request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return response, payload if isinstance(payload, dict) else None

    async def _resolve_decision(
        self,
        case: dict[str, Any],
        task: dict[str, Any],
        decision: dict[str, Any],
        *,
        resolution_index: int,
    ) -> str | None:
        task_id = task["task"]["task_id"]
        policy = case["hitl"]
        action = (
            policy["action"]
            if resolution_index == 0
            else policy.get("repeat_action", policy["action"])
        )
        body: dict[str, Any] = {"action": action}
        if action == "provide_context":
            body["supplemental_input"] = policy["supplemental_input"]
        response, _ = await self._request_json(
            "POST",
            f"/api/v1/tasks/{task_id}/decisions/{decision['decision_id']}",
            headers={"If-Match": str(task["task"]["version"])},
            json=body,
        )
        return None if response.status_code == 202 else _http_error_code(response)

    async def _collect_case(self, case: dict[str, Any]) -> dict[str, Any]:
        started_wall = _utc_now()
        started = time.monotonic()
        case_id = case["id"]
        record: dict[str, Any] = {
            "schema_version": 1,
            "experiment_id": self.experiment_id,
            "dataset_hash": self.dataset_hash,
            "profile": self.options.profile,
            "repetition": self.options.repetition,
            "requested_concurrency": self.options.concurrency,
            "case_id": case_id,
            "split": case["split"],
            "started_at": started_wall,
            "ended_at": None,
            "wall_time_ms": None,
            "task_id": None,
            "run_id": None,
            "manifest_id": None,
            "status": "collector_error",
            "collector_timeout": False,
            "hitl_resolutions": 0,
            "report_path": None,
            "snapshot_path": None,
            "observability": None,
            "observability_final": False,
            "observability_sampled_at": None,
            "error_code": None,
        }
        try:
            if not await self._healthy():
                record["status"] = "not_submitted"
                record["error_code"] = self._abort_reason
                return await self._finish(record, started)
            await self._journal(record, "submission_started")
            response, task = await self._request_json(
                "POST", "/api/v1/tasks", json=case["request"]
            )
            if response.status_code != 202 or task is None:
                record["error_code"] = _http_error_code(response)
                self._abort_reason = record["error_code"]
                return await self._finish(record, started)
            task_id = task["task"]["task_id"]
            record["task_id"] = task_id
            latest_run = task.get("latest_run") or {}
            record["run_id"] = latest_run.get("run_id")
            record["manifest_id"] = latest_run.get("manifest_id")
            await self._journal(record, "admitted")
            resolved_decisions: set[str] = set()
            saw_running = False
            allowed_decision_requeue = False
            last_sample = 0.0

            while True:
                if not await self._healthy():
                    record["error_code"] = self._abort_reason
                    break
                if time.monotonic() - started >= self.options.case_timeout_seconds:
                    record["collector_timeout"] = True
                    await self._cancel_and_settle(record)
                    break
                response, task = await self._request_json(
                    "GET", f"/api/v1/tasks/{task_id}"
                )
                if response.status_code != 200 or task is None:
                    record["error_code"] = _http_error_code(response)
                    self._abort_reason = record["error_code"]
                    break
                status = task["task"]["status"]
                record["status"] = status
                latest_run = task.get("latest_run") or {}
                if latest_run.get("run_id") != record["run_id"] or latest_run.get(
                    "manifest_id") != record["manifest_id"]:
                    record["error_code"] = "RUN_IDENTITY_CHANGED"
                    self._abort_reason = record["error_code"]
                    break
                if status == "running":
                    saw_running = True
                    allowed_decision_requeue = False
                    self._running_cases.add(case_id)
                    self.peak_observed_running = max(self.peak_observed_running, len(self._running_cases))
                else:
                    self._running_cases.discard(case_id)
                if status == "queued" and saw_running and not allowed_decision_requeue:
                    record["error_code"] = "UNEXPECTED_RUN_REQUEUE"
                    self._abort_reason = record["error_code"]
                    break
                if status == "interrupted":
                    record["error_code"] = "RUN_INTERRUPTED_NO_AUTO_RESUME"
                    self._abort_reason = record["error_code"]
                    break
                if status in TERMINAL_STATUSES:
                    break
                if status == "waiting_for_input":
                    decision_response, decision = await self._request_json(
                        "GET", f"/api/v1/tasks/{task_id}/decision"
                    )
                    decision_id = decision.get("decision_id") if decision else None
                    if decision_response.status_code != 200 or not isinstance(
                        decision_id, str
                    ):
                        record["error_code"] = _http_error_code(decision_response)
                        break
                    if decision_id in resolved_decisions:
                        await asyncio.sleep(self.options.poll_interval_seconds)
                        continue
                    error_code = await self._resolve_decision(
                        case,
                        task,
                        decision,
                        resolution_index=len(resolved_decisions),
                    )
                    if error_code is not None:
                        record["error_code"] = error_code
                        break
                    resolved_decisions.add(decision_id)
                    allowed_decision_requeue = True
                    record["hitl_resolutions"] += 1
                if time.monotonic() - last_sample >= 5:
                    await self._sample_observability(record)
                    last_sample = time.monotonic()
                    if self._abort_reason:
                        break
                await asyncio.sleep(self.options.poll_interval_seconds)

            await self._collect_artifacts(record)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record["error_code"] = type(exc).__name__
            self._abort_reason = record["error_code"]
        return await self._finish(record, started)

    async def _collect_artifacts(self, record: dict[str, Any]) -> None:
        task_id = record.get("task_id")
        if not isinstance(task_id, str):
            return
        await self._sample_observability(record, final=True)
        if record.get("error_code") == "OBSERVABILITY_RUN_MISMATCH":
            return
        if record["status"] not in SUCCESS_STATUSES:
            return
        response, snapshot = await self._request_json(
            "GET", f"/api/v1/tasks/{task_id}/snapshot"
        )
        if response.status_code != 200 or snapshot is None:
            record["error_code"] = _http_error_code(response)
            return
        snapshot_relative = Path(record["split"]) / "snapshots" / f"{record['case_id']}.json"
        snapshot_destination = self.output_dir / snapshot_relative
        snapshot_destination.parent.mkdir(parents=True, exist_ok=True)
        snapshot_destination.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record["snapshot_path"] = snapshot_relative.as_posix()
        response, report = await self._request_json(
            "GET", f"/api/v1/tasks/{task_id}/report"
        )
        if response.status_code != 200 or report is None:
            record["error_code"] = _http_error_code(response)
            return
        text = report.get("report")
        if report.get("run_id", record["run_id"]) != record["run_id"]:
            record["error_code"] = "REPORT_RUN_MISMATCH"
            return
        if not isinstance(text, str) or not text.strip():
            record["error_code"] = "EMPTY_REPORT"
            return
        relative = Path(record["split"]) / "reports" / f"{record['case_id']}.md"
        destination = self.output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        record["report_path"] = relative.as_posix()

    async def _finish(
        self, record: dict[str, Any], started: float
    ) -> dict[str, Any]:
        record["ended_at"] = _utc_now()
        record["wall_time_ms"] = round((time.monotonic() - started) * 1000)
        record["usage"] = record_usage_projection(record)
        record["runtime_observations"] = getattr(self, "_last_runtime_observations", None)
        record["run_heartbeat"] = getattr(self, "_last_run_heartbeat", None)
        record["diagnostics"] = diagnostic_projection(record)
        async with self._write_lock:
            with (self.output_dir / "runs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        print(json.dumps({"case_id": record["case_id"], "status": record["status"],
                          "usage": record["usage"], "wall_time_ms": record["wall_time_ms"]}), flush=True)
        return record


def diagnostic_projection(record: dict[str, Any]) -> dict:
    """Known-call denominators, never infer success from missing historical fields."""
    observation = record.get("observability") or {}
    calls = observation.get("calls") or []
    llm = [call for call in calls if call.get("kind") == "llm"]
    known = [call["diagnostics"] for call in llm if isinstance(call.get("diagnostics"), dict)]
    json_calls = [item for item in known if item.get("json_status") not in {None, "not_requested"}]
    repairs = [item["repair_attempts"] for item in json_calls if type(item.get("repair_attempts")) is int]
    return {
        "run_failure_category": observation.get("run_failure_category"),
        "collector_error_code": record.get("error_code"),
        "observed_llm_calls": len(llm) if observation.get("availability") == "available" else None,
        "diagnostic_known_calls": len(known),
        "diagnostic_missing_calls": len(llm) - len(known) if observation.get("availability") == "available" else None,
        "finish_reason_known_calls": sum(item.get("finish_reason") is not None for item in known),
        "truncated_calls": sum(item.get("truncated") is True for item in known),
        "json_observed_calls": len(json_calls),
        "strict_json_calls": sum(item.get("json_status") == "strict" for item in json_calls),
        "strict_json_rate": sum(item.get("json_status") == "strict" for item in json_calls) / len(json_calls) if json_calls else None,
        "repair_attempts_known_calls": sum(type(item.get("repair_attempts")) is int for item in json_calls),
        "repair_attempts": sum(repairs) if repairs else None,
        "schema_checked_calls": sum(item.get("schema_status") in {"valid", "invalid"} for item in json_calls),
        "schema_valid_calls": sum(item.get("schema_status") == "valid" for item in json_calls),
        "schema_invalid_calls": sum(item.get("schema_status") == "invalid" for item in json_calls),
        "failure_categories": dict(Counter(
            call["failure_category"] for call in calls if call.get("failure_category"))),
        "observation_final": record.get("observability_final", False),
        "qualification": "not_evaluated",
    }


def usage_projection(observability: dict[str, Any] | None) -> dict[str, Any]:
    """Known Trace usage is distinct from conservative budget charges."""
    observation = observability or {}
    totals = observation.get("totals") or {}
    fields = ("input_tokens", "output_tokens", "total_tokens", "llm_calls",
              "retrieval_calls", "external_calls", "failed_calls", "node_retries")
    projection = {field: totals.get(field) for field in fields}
    projection["token_usage_complete"] = totals.get("token_usage_complete", False)
    for field in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "prompt_cache_hit_ratio"):
        projection[field] = totals.get(field)
    projection["cache_usage_known_calls"] = totals.get("cache_usage_known_calls", 0)
    projection["cache_usage_complete"] = totals.get("cache_usage_complete", False)
    calls = observation.get("calls") or []
    available = observation.get("availability") == "available"
    projection["http_calls"] = sum(call.get("kind") == "http" for call in calls) if available else None
    projection["llm_retries"] = sum(call.get("kind") == "llm" and
        isinstance(call.get("retry_no"), int) and call["retry_no"] > 0 for call in calls) if available else None
    budget = observation.get("budget") or {}
    projection["budget_resources"] = budget.get("resources") or {}
    projection["budget_admission_denied"] = budget.get("admission_denied")
    projection["price_availability"] = budget.get("price_availability", "unavailable")
    return projection


def record_usage_projection(record: dict[str, Any]) -> dict[str, Any]:
    projection = usage_projection(record.get("observability"))
    final = (record["status"] in TERMINAL_STATUSES and record.get("observability_final", True))
    projection["observation_final"] = bool(final)
    projection["observed_at"] = record.get("observability_sampled_at")
    if not final:
        projection["token_usage_complete"] = False
        projection["cache_usage_complete"] = False
        projection["prompt_cache_hit_ratio"] = None
    return projection


def node_usage_projection(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Group public LLM calls by node attempt, including failed retries."""
    from deepchoice.utils.token_usage import TOKEN_FIELDS, cache_totals, public_usage

    groups: dict[tuple[str, int], list[dict]] = {}
    for call in (record.get("observability") or {}).get("calls") or []:
        if call.get("kind") == "llm":
            name = call.get("node_name")
            attempt = call.get("node_attempt_no")
            # Older collector fixtures/records may lack public attribution.
            key = (name if isinstance(name, str) and name else "unattributed",
                   attempt if type(attempt) is int and attempt > 0 else 0)
            groups.setdefault(key, []).append(call)
    final = record_usage_projection(record)["observation_final"]
    rows = []
    for (node_name, attempt_no), calls in sorted(groups.items()):
        usages = [public_usage(call.get("usage")) for call in calls]
        cache = cache_totals(usages)
        if not final:
            cache["cache_usage_complete"] = False
            cache["prompt_cache_hit_ratio"] = None
        rows.append({
            "case_id": record["case_id"], "run_id": record.get("run_id"),
            "node_name": node_name, "node_attempt_no": attempt_no,
            "llm_calls": len(calls),
            "llm_retries": sum(type(call.get("retry_no")) is int and call["retry_no"] > 0 for call in calls),
            **{field: sum(usage[field] for usage in usages if field in usage)
               if any(field in usage for usage in usages) else None for field in TOKEN_FIELDS},
            "token_usage_complete": final and all(all(field in usage for field in TOKEN_FIELDS) for usage in usages),
            **cache,
            "observation_final": final,
            "observed_at": record.get("observability_sampled_at"),
            "price_availability": record_usage_projection(record)["price_availability"],
        })
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object record in {path}")
            records.append(value)
    return records


def write_score_template(output_dir: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "experiment_id",
        "profile",
        "repetition",
        "case_id",
        "run_id",
        "report_available",
        *SCORE_FIELDS,
        "major_errors",
        "reviewer",
        "evidence_notes",
    ]
    with (output_dir / "scores.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item["case_id"]):
            writer.writerow(
                {
                    "experiment_id": record["experiment_id"],
                    "profile": record["profile"],
                    "repetition": record["repetition"],
                    "case_id": record["case_id"],
                    "run_id": record.get("run_id") or "",
                    "report_available": bool(record.get("report_path")),
                    "major_errors": "",
                    "reviewer": "",
                    "evidence_notes": "",
                }
            )


def write_collection_summary(output_dir: Path, records: list[dict[str, Any]]) -> None:
    succeeded = sum(bool(record.get("report_path")) for record in records)
    timed_out = sum(bool(record.get("collector_timeout")) for record in records)
    total_wall = sum(int(record.get("wall_time_ms") or 0) for record in records)
    diagnostic_fields = ["case_id", "run_id", "kind", "node_name", "node_attempt_no",
                         "provider", "call_no", "retry_no", "status", "failure_category",
                         "policy", "finish_reason", "truncated", "json_status",
                         "repair_attempts", "parse_ok", "schema_status"]
    with (output_dir / "diagnostics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=diagnostic_fields)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item["case_id"]):
            for call in (record.get("observability") or {}).get("calls") or []:
                row = {**call, **(call.get("diagnostics") or {}),
                       "case_id": record["case_id"], "run_id": record.get("run_id")}
                writer.writerow({field: row.get(field) for field in diagnostic_fields})
    (output_dir / "diagnostics-summary.json").write_text(json.dumps({
        "policy": "node-shape-v1", "case_denominator": len(records),
        "cases": [{"case_id": record["case_id"], **diagnostic_projection(record)} for record in records],
        "live_qualification": "not_evaluated",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    usage_fields = ["case_id", "status", "wall_time_ms", "input_tokens", "output_tokens",
                    "total_tokens", "token_usage_complete", "llm_calls", "retrieval_calls",
                    "http_calls", "llm_retries", "failed_calls", "price_availability",
                    "observation_final", "observed_at", "prompt_cache_hit_tokens",
                    "prompt_cache_miss_tokens", "cache_usage_known_calls",
                    "cache_usage_complete", "prompt_cache_hit_ratio"]
    with (output_dir / "usage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=usage_fields)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item["case_id"]):
            usage = record.get("usage") or record_usage_projection(record)
            writer.writerow({field: record.get(field) if field in record else usage.get(field)
                             for field in usage_fields})
    usages = [record.get("usage") or record_usage_projection(record) for record in records]
    node_fields = ["case_id", "run_id", "node_name", "node_attempt_no", "llm_calls",
                   "llm_retries", "input_tokens", "output_tokens", "total_tokens",
                   "token_usage_complete", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
                   "cache_usage_known_calls", "cache_usage_complete", "prompt_cache_hit_ratio",
                   "observation_final", "observed_at", "price_availability"]
    with (output_dir / "usage-by-node.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=node_fields)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item["case_id"]):
            writer.writerows(node_usage_projection(record))
    known = [usage["total_tokens"] for usage in usages]
    known = [value for value in known if isinstance(value, int)]
    complete = sum(usage["token_usage_complete"] is True for usage in usages)
    lines = [
        "# Product baseline collection",
        "",
        f"- Cases: {len(records)}",
        f"- Reports available: {succeeded}",
        f"- Collector timeouts: {timed_out}",
        f"- Sum of per-case wall time: {total_wall} ms",
        f"- Complete token usage: {complete}/{len(records)} runs",
        f"- Complete context-cache usage: {sum(usage.get('cache_usage_complete') is True for usage in usages)}/{len(records)} runs",
        f"- Known total tokens (not necessarily full spend): {sum(known) if known else 'unknown'}",
        f"- Known per-run token median: {statistics.median(known) if known else 'unknown'}",
        f"- Known per-run token range: {str(min(known)) + '..' + str(max(known)) if known else 'unknown'}",
        "- Monetary cost: unknown unless a separately verified price snapshot is supplied",
        "- Quality verdict: pending human scoring",
        "",
        "This summary is a collection record, not a product-quality claim.",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_scores(path: Path, runs: dict[str, dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    scores: dict[str, dict[str, float | int]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = row.get("case_id", "")
            if case_id in scores:
                raise ValueError(f"duplicate score for {case_id}")
            run = runs.get(case_id)
            if run is None or row.get("run_id") != run.get("run_id") or row.get(
                "experiment_id") != run.get("experiment_id"):
                raise ValueError("score identity does not match collected run")
            if not row.get("reviewer") or not row.get("evidence_notes"):
                raise ValueError("scoring requires reviewer and evidence notes")
            parsed: dict[str, float | int] = {}
            for field in SCORE_FIELDS:
                raw = (row.get(field) or "").strip()
                if not raw:
                    raise ValueError(f"missing {field} score for {case_id}")
                value = float(raw)
                if not 0 <= value <= 1:
                    raise ValueError(f"{field} must be between 0 and 1")
                parsed[field] = value
            raw_errors = (row.get("major_errors") or "").strip()
            if not raw_errors:
                raise ValueError(f"missing major_errors for {case_id}")
            parsed["major_errors"] = int(raw_errors)
            if parsed["major_errors"] < 0:
                raise ValueError("major_errors cannot be negative")
            scores[case_id] = parsed
    return scores


def compare_profiles(serial_dir: Path, concurrent_dir: Path) -> dict[str, Any]:
    serial_runs = _read_jsonl(serial_dir / "runs.jsonl")
    concurrent_runs = _read_jsonl(concurrent_dir / "runs.jsonl")
    if len(serial_runs) != EXPECTED_CASE_COUNT or len(concurrent_runs) != EXPECTED_CASE_COUNT:
        raise ValueError("each profile must contain exactly 12 run records")
    serial_by_case = {record["case_id"]: record for record in serial_runs}
    concurrent_by_case = {record["case_id"]: record for record in concurrent_runs}
    if len(serial_by_case) != EXPECTED_CASE_COUNT or set(serial_by_case) != set(
        concurrent_by_case
    ):
        raise ValueError("serial and concurrent profiles must contain the same 12 cases")
    if {record.get("profile") for record in serial_runs} != {"serial"}:
        raise ValueError("serial directory contains a non-serial profile")
    if {record.get("profile") for record in concurrent_runs} != {"concurrent"}:
        raise ValueError("concurrent directory contains a non-concurrent profile")
    if {record.get("requested_concurrency") for record in serial_runs} != {1}:
        raise ValueError("serial profile must use whole-case concurrency 1")
    if {record.get("requested_concurrency") for record in concurrent_runs} != {12}:
        raise ValueError("concurrent profile must use whole-case concurrency 12")
    repetitions = {record.get("repetition") for record in serial_runs + concurrent_runs}
    if len(repetitions) != 1:
        raise ValueError("profiles must use the same repetition")
    hashes = {
        record.get("dataset_hash") for record in serial_runs + concurrent_runs
    }
    if len(hashes) != 1:
        raise ValueError("profiles must use one identical dataset hash")
    serial_metadata = json.loads((serial_dir / "experiment.json").read_text(encoding="utf-8"))
    concurrent_metadata = json.loads((concurrent_dir / "experiment.json").read_text(encoding="utf-8"))
    for field in ("environment_hash", "git_commit", "dataset_hash"):
        if not serial_metadata.get(field) or serial_metadata[field] != concurrent_metadata.get(field):
            raise ValueError("profiles must use identical verified experiment identities")
    if serial_metadata["dataset_hash"] != next(iter(hashes)):
        raise ValueError("experiment dataset identity differs from run records")
    for case_id in serial_by_case:
        if not serial_by_case[case_id].get("manifest_id") or serial_by_case[case_id]["manifest_id"] != concurrent_by_case[case_id].get("manifest_id"):
            raise ValueError("paired runs must use one identical manifest identity")
    missing = [case_id for case_id in sorted(serial_by_case) if not (
        serial_by_case[case_id].get("report_path") and concurrent_by_case[case_id].get("report_path"))]
    if missing:
        return {"schema_version": 1, "dataset_hash": next(iter(hashes)), "case_count": 12,
                "paired_report_count": 12 - len(missing), "quality_verdict": "unavailable",
                "reason": "MISSING_PAIRED_REPORTS", "passed": False, "compared_at": _utc_now()}
    serial_scores = _read_scores(serial_dir / "scores.csv", serial_by_case)
    concurrent_scores = _read_scores(concurrent_dir / "scores.csv", concurrent_by_case)
    if set(serial_scores) != set(serial_by_case) or set(concurrent_scores) != set(
        serial_by_case
    ):
        raise ValueError("score rows must match collected cases")

    serial_completed = sum(
        record.get("status") in SUCCESS_STATUSES for record in serial_runs
    )
    concurrent_completed = sum(
        record.get("status") in SUCCESS_STATUSES for record in concurrent_runs
    )
    metric_deltas: dict[str, float] = {}
    for field in SCORE_FIELDS:
        serial_mean = sum(float(score[field]) for score in serial_scores.values()) / 12
        concurrent_mean = (
            sum(float(score[field]) for score in concurrent_scores.values()) / 12
        )
        metric_deltas[field] = round(concurrent_mean - serial_mean, 6)

    severe_pair_drops: list[str] = []
    moderate_pair_drops: list[str] = []
    for case_id in sorted(serial_by_case):
        delta = float(concurrent_scores[case_id]["decision_correctness"]) - float(
            serial_scores[case_id]["decision_correctness"]
        )
        if delta < -0.20:
            severe_pair_drops.append(case_id)
        elif delta < -0.10:
            moderate_pair_drops.append(case_id)
    serial_errors = sum(int(score["major_errors"]) for score in serial_scores.values())
    concurrent_errors = sum(
        int(score["major_errors"]) for score in concurrent_scores.values()
    )
    checks = {
        "all_paired_reports_available": all(record.get("report_path") for record in serial_runs + concurrent_runs),
        "completion_not_lower": concurrent_completed >= serial_completed,
        "decision_mean_drop_at_most_5pp": metric_deltas["decision_correctness"] >= -0.05,
        "citation_mean_drop_at_most_5pp": metric_deltas["citation_support"] >= -0.05,
        "source_mean_drop_at_most_5pp": metric_deltas["source_quality"] >= -0.05,
        "conflict_mean_drop_at_most_10pp": metric_deltas["conflict_handling"] >= -0.10,
        "no_new_major_errors": all(int(concurrent_scores[case]["major_errors"]) <=
                                    int(serial_scores[case]["major_errors"]) for case in serial_by_case),
        "no_case_decision_drop_over_20pp": not severe_pair_drops,
        "at_most_two_case_drops_over_10pp": len(moderate_pair_drops) <= 2,
    }
    return {
        "schema_version": 1,
        "dataset_hash": next(iter(hashes)),
        "case_count": 12,
        "serial_completed": serial_completed,
        "concurrent_completed": concurrent_completed,
        "metric_deltas": metric_deltas,
        "serial_major_errors": serial_errors,
        "concurrent_major_errors": concurrent_errors,
        "severe_pair_drops": severe_pair_drops,
        "moderate_pair_drops": moderate_pair_drops,
        "checks": checks,
        "passed": all(checks.values()),
        "compared_at": _utc_now(),
    }


async def _collect(args: argparse.Namespace) -> int:
    dataset_path = Path(args.cases_file)
    dataset, dataset_hash = load_dataset(dataset_path, require_frozen=True)
    environment, environment_hash = load_environment(
        Path(args.environment_file), require_ready=True
    )
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        raise ValueError("output directory must not already exist")
    if not args.execute_paid_runs:
        raise ValueError("collection requires --execute-paid-runs")
    expected_concurrency = 1 if args.profile == "serial" else 12
    if args.concurrency != expected_concurrency:
        raise ValueError(
            f"{args.profile} profile requires --concurrency {expected_concurrency}"
        )
    api_base = _safe_api_base(args.api_base)
    output_dir.mkdir(parents=True)
    experiment_id = str(uuid.uuid4())
    options = CollectionOptions(
        profile=args.profile,
        repetition=args.repetition,
        concurrency=args.concurrency,
        poll_interval_seconds=args.poll_interval,
        case_timeout_seconds=args.case_timeout,
    )
    metadata = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "dataset_id": dataset["dataset_id"],
        "dataset_version": dataset["version"],
        "dataset_hash": dataset_hash,
        "dataset_freeze_date": dataset["freeze_date"],
        "environment_hash": environment_hash,
        "environment": environment,
        "profile": args.profile,
        "repetition": args.repetition,
        "requested_concurrency": args.concurrency,
        "api_origin": api_base,
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "started_at": _utc_now(),
        "source_health": environment["retrieval_health"],
        "llm_compatibility": environment["llm_compatibility"],
    }
    from deepchoice.contracts.manifest import build_core_asset_registry
    metadata["core_asset_registry_id"] = build_core_asset_registry().registry_id
    seed = 20260916 + args.repetition
    cases = list(dataset["cases"])
    if args.command == "collect-single":
        cases = [case for case in cases if case["id"] == args.case_id and case["split"] == "development"]
        if len(cases) != 1:
            raise ValueError("single-case validation requires one development case")
    metadata["execution_mode"] = "single" if args.command == "collect-single" else "batch"
    metadata["case_denominator"] = len(cases)
    random.Random(seed).shuffle(cases)
    metadata["order_seed"] = seed
    metadata["case_order"] = [case["id"] for case in cases]
    (output_dir / "experiment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(base_url=api_base, timeout=timeout) as client:
        health = await client.get("/health")
        if health.status_code != 200:
            raise RuntimeError("durable API health check failed")
        collector = DurableBaselineCollector(
            client,
            output_dir,
            experiment_id=experiment_id,
            dataset_hash=dataset_hash,
            options=options,
        )
        records = await collector.collect(cases)
    write_score_template(output_dir, records)
    write_collection_summary(output_dir, records)
    metadata["ended_at"] = _utc_now()
    metadata["observed_status_counts"] = {
        status: sum(record["status"] == status for record in records)
        for status in sorted({record["status"] for record in records})
    }
    metadata["terminal_counts"] = {status: count for status, count in metadata["observed_status_counts"].items()
                                   if status in TERMINAL_STATUSES}
    metadata["collector_stop_reason"] = collector._abort_reason
    if collector._abort_reason:
        metadata["source_health"] = "degraded"
    metadata["peak_in_flight_cases"] = collector.peak_in_flight
    metadata["peak_observed_running_cases"] = collector.peak_observed_running
    metadata["admitted_run_denominator"] = sum(bool(record.get("run_id")) for record in records)
    metadata["manifest_ids"] = sorted({record["manifest_id"] for record in records if record.get("manifest_id")})
    (output_dir / "experiment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect and compare the durable DeepChoice product baseline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate a dataset without calls")
    validate.add_argument(
        "--cases-file", default="benchmarks/product-baseline-v1.json"
    )
    validate.add_argument("--require-frozen", action="store_true")

    collect = subparsers.add_parser("collect", help="execute one paid collection profile")
    collect.add_argument("--cases-file", default="benchmarks/product-baseline-v1.json")
    collect.add_argument("--environment-file", required=True)
    collect.add_argument("--output-dir", required=True)
    collect.add_argument("--api-base", default="http://127.0.0.1:8000")
    collect.add_argument("--profile", choices=("serial", "concurrent"), required=True)
    collect.add_argument("--repetition", type=int, choices=(1, 2), required=True)
    collect.add_argument("--concurrency", type=int, choices=(1, 12), required=True)
    collect.add_argument("--poll-interval", type=float, default=2.0)
    collect.add_argument("--case-timeout", type=float, default=2100.0)
    collect.add_argument("--execute-paid-runs", action="store_true")

    single = subparsers.add_parser("collect-single", help="execute exactly one development case, never a batch")
    single.add_argument("--case-id", choices=tuple(f"P{i:02d}" for i in range(1, 9)), required=True)
    single.add_argument("--cases-file", default="benchmarks/product-baseline-v1.json")
    single.add_argument("--environment-file", required=True)
    single.add_argument("--output-dir", required=True)
    single.add_argument("--api-base", default="http://127.0.0.1:8000")
    single.add_argument("--repetition", type=int, choices=(1, 2), required=True)
    single.add_argument("--poll-interval", type=float, default=2.0)
    single.add_argument("--case-timeout", type=float, default=2100.0)
    single.add_argument("--execute-paid-runs", action="store_true")
    single.set_defaults(profile="serial", concurrency=1)

    compare = subparsers.add_parser("compare", help="compare scored profile artifacts")
    compare.add_argument("--serial-dir", required=True)
    compare.add_argument("--concurrent-dir", required=True)
    compare.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            dataset, digest = load_dataset(
                Path(args.cases_file), require_frozen=args.require_frozen
            )
            print(
                json.dumps(
                    {
                        "dataset_id": dataset["dataset_id"],
                        "version": dataset["version"],
                        "status": dataset["status"],
                        "case_count": len(dataset["cases"]),
                        "sha256": digest,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command in {"collect", "collect-single"}:
            return asyncio.run(_collect(args))
        result = compare_profiles(Path(args.serial_dir), Path(args.concurrent_dir))
        output = Path(args.output)
        if output.exists():
            raise ValueError("comparison output must not already exist")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if result["passed"] else 1
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        print(f"product baseline stopped: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
