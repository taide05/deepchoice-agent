"""O1-B offline observations and real SQLite lease faults; no provider/model calls."""

import asyncio
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from benchmarks.product_baseline import diagnostic_projection, write_collection_summary
from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY, DeferredBudgetManager
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.observability import RuntimeTraceRecorder, SQLiteTraceStore, TraceStatus
from deepchoice.observability.query import SQLiteObservabilityQuery
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, TaskRecord
from deepchoice.persistence.repository import RunLeaseLostError, SQLiteTaskRunRepository
from deepchoice.runtime.context import bind_node_attempt, bind_run_context, RunContext
from deepchoice.runtime.instance_guard import RuntimeInstanceGuard, RuntimeInstanceLeaseLostError
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.server.app import health, _require_runtime_authority, RuntimeAuthorityUnavailableError
from deepchoice.utils import llm
from deepchoice.utils.call_diagnostics import (
    exception_category, observe_output, output_failure, public_call_result, run_failure,
    retrieval_failure,
    strict_json,
)


NOW = datetime(2026, 9, 17, tzinfo=UTC)

# Bounded ceiling for waiting on lease renewal progress. The renewal paths share
# one SQLite writer, so progress is measured by the counters themselves; this
# only stops a real stall from hanging the test.
HEARTBEAT_WAIT_SECONDS = 8.0


async def queued(tmp_path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    lock = asyncio.Lock()
    repo = SQLiteTaskRunRepository(connection, lock)
    request = ResearchRequest(query="compare two options")
    task = TaskRecord(task_id="task", status=TaskStatus.QUEUED, request=request,
                      latest_run_id="run", created_at=NOW, updated_at=NOW)
    run = RunRecord(run_id="run", task_id="task", status=RunStatus.QUEUED,
                    manifest=build_run_manifest(request.model_dump()),
                    budget_policy=DEFAULT_RUN_BUDGET_POLICY,
                    thread_id="run", created_at=NOW, updated_at=NOW)
    try:
        await repo.create_task_with_run(task, run)
    except BaseException:
        await connection.close()
        raise
    return connection, lock, repo, run


@pytest.mark.parametrize("content,parsed,ok,status,schema,category", [
    ('{"sub_questions":["q"],"constraints":[]}', {"sub_questions": ["q"], "constraints": []}, True, "strict", "valid", None),
    ('{sub_questions:["q"],constraints:[]}', {"sub_questions": ["q"], "constraints": []}, True, "repaired", "valid", None),
    ('{"sub_questions":[1],"constraints":[]}', {"sub_questions": [1], "constraints": []}, True, "strict", "invalid", "json_schema_error"),
    ("[]", {}, False, "non_object", "invalid", "json_parse_error"),
    ("broken", {}, False, "invalid", "invalid", "json_parse_error"),
    ('{"x":1,"x":2}', {"x": 2}, True, "repaired", "invalid", "json_schema_error"),
    ('{"x":NaN}', {"x": None}, True, "repaired", "invalid", "json_schema_error"),
])
def test_strict_repair_and_shape_are_separate(content, parsed, ok, status, schema, category):
    result = observe_output(SimpleNamespace(finish_reason="stop"),
                            json_requested=True, content=content, parsed=parsed,
                            parse_ok=ok, repair_attempts=1, tag="query_analyzer")
    assert result["json_status"] == status
    assert result["schema_status"] == schema
    assert result["repair_attempts"] == 1
    assert output_failure(result) == category
    assert content not in json.dumps(result)


def test_missing_finish_and_unconfigured_shape_are_unknown_not_passed():
    result = observe_output(SimpleNamespace(), json_requested=True,
                            content='{"ok":true}', parsed={"ok": True}, parse_ok=True, tag="clarification")
    assert result["finish_reason"] is None and result["truncated"] is None
    assert result["schema_status"] == "not_configured"
    truncated = observe_output(SimpleNamespace(finish_reason="length"), json_requested=True,
                               content="broken", parsed={}, parse_ok=False)
    assert output_failure(truncated) == "output_truncated"


@pytest.mark.parametrize("number", ["1e999", "-1e999"])
def test_strict_json_rejects_exponent_overflow_without_changing_compatible_output(number):
    content = '{"ok":true,"x":' + number + '}'
    with pytest.raises(ValueError):
        strict_json(content)
    compatible = json.loads(content)
    result = observe_output(SimpleNamespace(finish_reason="stop"), json_requested=True,
                            content=content, parsed=compatible, parse_ok=True,
                            repair_attempts=1, tag="o1-json-probe")
    assert result["json_status"] == "repaired" and result["schema_status"] == "valid"
    assert strict_json('{"x":1e3}') == {"x": 1000.0}


@pytest.mark.parametrize("tag,payload", [
    ("conflict_scan", {"has_difference": "false", "type": "none", "explanation": "x"}),
    ("conflict_arbitration", {"resolution": "unknown", "confidence": "high", "reasoning": "x", "key_factor": "x"}),
    ("search_web", {"query": "x", "max_results": True}),
])
def test_observe_only_shapes_reject_wrong_types_and_enums(tag, payload):
    result = observe_output(None, json_requested=True, content=json.dumps(payload),
                            parsed=payload, parse_ok=True, tag=tag)
    assert result["schema_status"] == "invalid"


def test_public_projection_never_exposes_stored_arbitrary_summary():
    assert public_call_result('{"error":"secret","failure_category":"secret"}') == {}
    safe = public_call_result(json.dumps({"failure_category": "rate_limited", "raw": "secret",
        "diagnostics": {"finish_reason": "length", "truncated": True, "raw": "secret"}}))
    assert safe["failure_category"] == "rate_limited"
    assert "secret" not in json.dumps(safe)
    for value in (True, -1, 3, "1"):
        assert "diagnostics" not in public_call_result(json.dumps({"diagnostics": {"repair_attempts": value}}))


@pytest.mark.asyncio
async def test_llm_legacy_return_and_usage_preserved_with_persisted_diagnostics(tmp_path, monkeypatch):
    connection, lock, repo, _ = await queued(tmp_path)
    try:
        grant = await repo.acquire_run_lease("run", lease_owner="worker", lease_ttl=timedelta(seconds=30),
                                             run_timeout=timedelta(minutes=5))
        trace = RuntimeTraceRecorder(SQLiteTraceStore(connection, lock).bind(
            run_id="run", execution_epoch=grant.execution_epoch, lease_owner="worker"), task_id="task")
        attempt = await trace.start_node_attempt("query_analyzer")
        response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(
                content='{sub_questions:["q"],constraints:[]}'))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15), model="test")
        create = AsyncMock(return_value=response)
        monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        usage, diagnostics = [], []
        class Cancellation:
            async def raise_if_cancelled(self):
                return None

        current = await repo.get_run("run")
        with bind_run_context(RunContext.from_run_record(
            current, cancellation=Cancellation(), trace=trace, budget=DeferredBudgetManager())):
            with bind_node_attempt(attempt.node_attempt_id):
                result = await llm.call_model([{"role": "user", "content": "private JSON prompt"}],
                    response_format="json", tag="query_analyzer", usage=usage, diagnostics=diagnostics)
        assert result == {"sub_questions": ["q"], "constraints": []}
        assert usage == [{"model": "test", "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}]
        observation = (await SQLiteObservabilityQuery(connection, lock).for_task("task")).model_dump(mode="json")
        call = observation["calls"][0]
        assert call["status"] == "succeeded"  # Transport succeeded, output truncated.
        assert call["failure_category"] == "output_truncated"
        assert call["diagnostics"]["json_status"] == "repaired"
        assert diagnostics[0]["diagnostics"] == call["diagnostics"]
        assert "private JSON prompt" not in json.dumps(observation)
        assert create.call_count == 1
        await trace.finish_node_attempt(attempt, status=TraceStatus.SUCCEEDED)
    finally:
        await connection.close()


@pytest.mark.parametrize("error_type,status,expected", [
    ("HTTPStatusError", 429, "rate_limited"), ("APITimeoutError", None, "provider_timeout"),
    ("APIConnectionError", None, "transport_error"), ("ProviderAdmissionError", None, "provider_admission_failed"),
])
def test_exception_categories_are_content_free(error_type, status, expected):
    cls = type(error_type, (Exception,), {"status_code": status})
    assert exception_category(cls("secret raw error")) == expected


def test_run_budget_recovery_timeout_categories_distinct():
    assert run_failure("failed", "RUN_BUDGET_PERSISTENCE_FAILED") == "budget_gate_failed"
    assert run_failure("failed", "RUN_BUDGET_EXCEEDED") == "budget_exceeded"
    assert run_failure("interrupted", None) == "runtime_recovery"
    assert run_failure("timed_out", None) == "run_timeout"
    assert run_failure("failed", "secret") == "unknown"
    assert retrieval_failure("ReadTimeout()") == "provider_timeout"
    assert retrieval_failure("ProviderRateLimitError: HTTP 429") == "rate_limited"
    assert retrieval_failure("RetrievalContractError: invalid retrieval contract") == "retrieval_contract_error"
    assert retrieval_failure("secret raw traceback") == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("content,expected_attempts", [(None, 0), ('{"ok":true}', 2)])
async def test_repair_attempts_count_actual_parser_invocations(monkeypatch, content, expected_attempts):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=None, model="test")
    monkeypatch.setattr(llm, "_get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))))
    calls = []

    def fake_repair(value):
        calls.append(value)
        if len(calls) == 1:
            raise json.JSONDecodeError("synthetic", value, 0)
        return {"ok": True}

    monkeypatch.setattr(llm.json_repair, "loads", fake_repair)
    diagnostics = []
    await llm.call_model([{"role": "user", "content": "JSON"}], response_format="json",
                         diagnostics=diagnostics, tag="o1-json-probe")
    assert len(calls) == expected_attempts
    assert diagnostics[0]["diagnostics"]["repair_attempts"] == expected_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,json_content,qualification", [
    ("stop", '{"ok":true}', "passed"),
    ("length", '{"ok":true}', "failed"),
    (None, '{"ok":true}', "unavailable"),
    ("stop", '{ok:true}', "failed"),
])
async def test_paid_probe_qualification_offline_strict_shape_and_finish(monkeypatch, reason, json_content, qualification):
    from benchmarks import product_baseline_preflight

    responses = [
        SimpleNamespace(model="test", usage=None, choices=[SimpleNamespace(
            finish_reason=reason, message=SimpleNamespace(content=json_content))]),
        SimpleNamespace(model="test", usage=None, choices=[SimpleNamespace(
            finish_reason="tool_calls", message=SimpleNamespace(tool_calls=[SimpleNamespace(
                function=SimpleNamespace(name="check", arguments='{"ok":true}'))]))]),
    ]

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=responses)))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    client = Client()
    monkeypatch.setattr(llm, "_get_client", lambda **_: client)
    monkeypatch.setattr(product_baseline_preflight, "load_dotenv", lambda: None)
    result = await product_baseline_preflight.probe()
    assert result["output_qualification"] == qualification
    assert result["passed"] == (qualification == "passed")
    assert result["research_runs_submitted"] == 0
    assert client.chat.completions.create.call_count == 2
    assert "arguments" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer_wait", [False, True])
@pytest.mark.parametrize("delay", [20, 31])
async def test_run_heartbeat_cannot_revive_expired_lease_after_wait(tmp_path, writer_wait, delay):
    connection, lock, repo, _ = await queued(tmp_path)
    current = NOW
    grant = await repo.acquire_run_lease("run", lease_owner="worker", lease_ttl=timedelta(seconds=30),
                                       run_timeout=timedelta(minutes=5), clock=lambda: current)
    writer = await connect_database(tmp_path / "product.db") if writer_wait else None
    before = (await repo.get_run("run")).model_dump()
    if writer:
        await writer.execute("BEGIN IMMEDIATE")
    else:
        await lock.acquire()
    renewal = asyncio.create_task(repo.heartbeat_run_lease(
        "run", lease_owner="worker", execution_epoch=grant.execution_epoch,
        lease_ttl=timedelta(seconds=30), clock=lambda: current))
    try:
        await asyncio.sleep(0.02)
        current += timedelta(seconds=delay)
        if writer:
            await writer.commit()
        else:
            lock.release()
        if delay > 30:
            with pytest.raises(RunLeaseLostError):
                await renewal
            assert (await repo.get_run("run")).model_dump() == before
        else:
            renewed = await renewal
            assert renewed.lease_expires_at == current + timedelta(seconds=30)
        events = await (await connection.execute("SELECT COUNT(*) FROM task_events")).fetchone()
        assert events[0] == 2  # queued + started, heartbeats never publish events.
    finally:
        if writer:
            await writer.rollback()
            await writer.close()
        elif lock.locked():
            lock.release()
        await asyncio.gather(renewal, return_exceptions=True)
        await connection.close()


@pytest.mark.asyncio
async def test_run_acquisition_ttl_starts_after_writer_wait(tmp_path):
    connection, _, repo, _ = await queued(tmp_path)
    writer = await connect_database(tmp_path / "product.db")
    current = NOW
    await writer.execute("BEGIN IMMEDIATE")
    acquisition = asyncio.create_task(repo.acquire_run_lease(
        "run", lease_owner="worker", lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5), clock=lambda: current))
    try:
        await asyncio.sleep(0.02)
        current += timedelta(seconds=31)
        await writer.commit()
        grant = await acquisition
        assert grant.lease_expires_at == current + timedelta(seconds=30)
        assert grant.deadline_at == current + timedelta(minutes=5)
    finally:
        await writer.rollback()
        await asyncio.gather(acquisition, return_exceptions=True)
        await writer.close()
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [20, 31])
async def test_instance_renewal_samples_after_sqlite_writer_wait(tmp_path, delay):
    connection, lock, _, _ = await queued(tmp_path)
    writer = await connect_database(tmp_path / "product.db")
    current = NOW
    guard = RuntimeInstanceGuard(connection, lock, clock=lambda: current)
    await guard.acquire()
    before = await (await connection.execute("SELECT lease_expires_at FROM runtime_instance_leases")).fetchone()
    await writer.execute("BEGIN IMMEDIATE")
    renewal = asyncio.create_task(guard.renew_once())
    try:
        await asyncio.sleep(0.02)
        current += timedelta(seconds=delay)
        await writer.commit()
        if delay > 30:
            with pytest.raises(RuntimeInstanceLeaseLostError):
                await renewal
            after = await (await connection.execute("SELECT lease_expires_at FROM runtime_instance_leases")).fetchone()
            assert before == after and not guard.has_authority
        else:
            await renewal
            assert guard.observations()["renewals"] == 1
            assert guard.has_authority
        assert not connection.in_transaction
    finally:
        await writer.rollback()
        await asyncio.gather(renewal, return_exceptions=True)
        await guard.release()
        await writer.close()
        await connection.close()


@pytest.mark.asyncio
async def test_health_and_admission_fail_closed_before_loss_callback(tmp_path):
    connection, lock, _, _ = await queued(tmp_path)
    current = NOW
    guard = RuntimeInstanceGuard(connection, lock, clock=lambda: current)
    application = FastAPI()
    application.state.runtime_instance_status = "active"
    application.state.runtime_instance_guard = guard
    request = Request({"type": "http", "app": application})
    try:
        await guard.acquire()
        assert (await health(request)).status_code == 200
        current += timedelta(seconds=31)
        response = await health(request)
        assert response.status_code == 503
        payload = json.loads(response.body)
        assert payload["runtime_instance"] == "lost"
        assert payload["runtime_observations"]["authority_valid"] is False
        assert "owner" not in json.dumps(payload) and "epoch" not in json.dumps(payload)
        with pytest.raises(RuntimeAuthorityUnavailableError):
            _require_runtime_authority(request)
        current = NOW  # An expired local authority cannot be revived by clock rollback.
        assert not guard.has_authority
    finally:
        await guard.release()
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["constructor", "model", "query"])
async def test_cold_model_and_chroma_initialization_do_not_block_instance_heartbeat(tmp_path, monkeypatch, stage):
    from deepchoice.agents.multi_retriever import _invoke_retriever_untraced
    from deepchoice.retrievers import chroma_kb
    from deepchoice.utils import embedding

    entered, release = threading.Event(), threading.Event()
    loaders = []

    def blocking(point):
        if stage == point:
            entered.set()
            assert release.wait(3)

    def fake_loader(_name):
        loaders.append(1)
        blocking("model")
        return SimpleNamespace(encode=lambda _q: np.array([0.1, 0.2]))

    class Collection:
        def query(self, **_):
            blocking("query")
            return {"ids": [[]], "metadatas": [[]], "documents": [[]]}

    def persistent(**_):
        blocking("constructor")
        return SimpleNamespace(get_or_create_collection=lambda _name: Collection())

    monkeypatch.setattr(embedding, "_model", None)
    monkeypatch.setattr(embedding, "SentenceTransformer", fake_loader)
    monkeypatch.setattr(chroma_kb.chromadb, "PersistentClient", persistent)
    connection, lock, _, _ = await queued(tmp_path)
    guard = RuntimeInstanceGuard(connection, lock, lease_seconds=1, heartbeat_seconds=0.01)
    await guard.acquire()
    lost = asyncio.Event()
    guard.start_heartbeat(lost.set)
    calls = [asyncio.create_task(_invoke_retriever_untraced(
        "chroma", chroma_kb.ChromaKB, query="q", sub_questions=[], adapted_queries=[])) for _ in range(2)]
    try:
        for _ in range(200):
            if entered.is_set() and guard.observations()["renewals"] >= 2:
                break
            await asyncio.sleep(0.005)
        assert entered.is_set() and guard.observations()["renewals"] >= 2
        assert guard.has_authority and not lost.is_set()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*calls), timeout=3)
        assert len(loaders) == 1
        assert all(result.status == "success" for result, _ in results)
    finally:
        release.set()
        await asyncio.gather(*calls, return_exceptions=True)
        await guard.release()
        await connection.close()


@pytest.mark.asyncio
async def test_twelve_dedicated_lease_heartbeats_survive_primary_lock_backlog(tmp_path):
    from deepchoice.runtime.coordinator import RunCoordinator

    connection, lock, repo, first_run = await queued(tmp_path)
    lease_connection = await connect_database(tmp_path / "product.db")
    lease_lock = asyncio.Lock()
    lease_repo = SQLiteTaskRunRepository(lease_connection, lease_lock)
    guard = RuntimeInstanceGuard(
        lease_connection,
        lease_lock,
        lease_seconds=3,
        heartbeat_seconds=0.1,
    )
    runs = [first_run]
    request = ResearchRequest(query="compare two options")
    for index in range(1, 12):
        task_id, run_id = f"task-{index}", f"run-{index}"
        task = TaskRecord(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            request=request,
            latest_run_id=run_id,
            created_at=NOW,
            updated_at=NOW,
        )
        run = RunRecord(
            run_id=run_id,
            task_id=task_id,
            status=RunStatus.QUEUED,
            manifest=build_run_manifest(request.model_dump()),
            budget_policy=DEFAULT_RUN_BUDGET_POLICY,
            thread_id=run_id,
            created_at=NOW,
            updated_at=NOW,
        )
        await repo.create_task_with_run(task, run)
        runs.append(run)

    grants = {}
    for run in runs:
        grants[run.run_id] = await repo.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
        )
    coordinator = RunCoordinator(
        repo,
        None,
        owner_id="worker",
        lease_ttl=timedelta(seconds=3),
        heartbeat_interval=timedelta(seconds=0.1),
        heartbeat_repository=lease_repo,
    )
    lost = asyncio.Event()
    runners = {
        run.run_id: asyncio.create_task(asyncio.Event().wait())
        for run in runs
    }
    heartbeats = []
    try:
        await guard.acquire()
        guard.start_heartbeat(lost.set)
        heartbeats = [
            asyncio.create_task(
                coordinator._heartbeat(
                    run.run_id,
                    grants[run.run_id].execution_epoch,
                    runners[run.run_id],
                )
            )
            for run in runs
        ]
        await lock.acquire()
        # Both renewal paths write to the same product database, so the
        # broadcast renewal shares one SQLite writer with the twelve dedicated
        # run heartbeats. Wait for the conditions themselves rather than a
        # fixed number of 10 ms sleeps, and keep a bounded deadline so a real
        # stall still fails instead of hanging.
        deadline = time.monotonic() + max(
            HEARTBEAT_WAIT_SECONDS, 20 * guard._heartbeat_seconds
        )
        while time.monotonic() < deadline:
            if (
                guard.observations()["renewals"] >= 2
                and coordinator.heartbeat_observations()["successes"] >= 12
            ):
                break
            await asyncio.sleep(guard._heartbeat_seconds)
        assert guard.observations()["renewals"] >= 2, (
            f"dedicated lease renewals did not start: {guard.observations()} "
            f"{coordinator.heartbeat_observations()} "
            f"{[runner.done() for runner in runners.values()]}"
        )
        assert coordinator.heartbeat_observations()["successes"] >= 12

        # Exceed the accepted lease window while ordinary product work is
        # unable to acquire the primary application lock.
        await asyncio.sleep(3.2)
        assert guard.has_authority and not lost.is_set()
        assert all(not runner.done() for runner in runners.values())
        assert guard.observations()["renewals"] >= 3
        assert coordinator.heartbeat_observations()["successes"] >= 24
        for run in runs:
            renewed = await lease_repo.get_run(run.run_id)
            assert renewed is not None and renewed.status is RunStatus.RUNNING
            assert renewed.lease_expires_at > datetime.now(UTC)
    finally:
        if lock.locked():
            lock.release()
        for runner in runners.values():
            runner.cancel()
        for heartbeat in heartbeats:
            heartbeat.cancel()
        await asyncio.gather(
            *runners.values(), *heartbeats, return_exceptions=True
        )
        await guard.release()
        await lease_connection.close()
        await connection.close()


@pytest.mark.asyncio
async def test_run_heartbeat_uses_deferred_clock_and_stops_runner_after_expiry(tmp_path):
    from deepchoice.runtime.coordinator import RunCoordinator

    connection, lock, repo, _ = await queued(tmp_path)
    current = NOW
    grant = await repo.acquire_run_lease("run", lease_owner="worker", lease_ttl=timedelta(seconds=30),
                                       run_timeout=timedelta(minutes=5), clock=lambda: current)
    coordinator = RunCoordinator(repo, None, owner_id="worker", clock=lambda: current,
                                 heartbeat_interval=timedelta(milliseconds=1))
    runner = asyncio.create_task(asyncio.Event().wait())
    await lock.acquire()
    heartbeat = asyncio.create_task(coordinator._heartbeat("run", grant.execution_epoch, runner))
    try:
        await asyncio.sleep(0.02)
        current += timedelta(seconds=31)
        lock.release()
        await asyncio.wait_for(heartbeat, timeout=1)
        with pytest.raises(asyncio.CancelledError):
            await runner
        stats = coordinator.heartbeat_observations()
        assert stats["failures"] == stats["lease_losses"] == 1
        assert stats["successes"] == 0
        assert stats["oldest_active_success_age_ms"] is None
        assert "worker" not in json.dumps(stats) and "run" not in json.dumps(stats)
    finally:
        if lock.locked():
            lock.release()
        runner.cancel()
        heartbeat.cancel()
        await asyncio.gather(runner, heartbeat, return_exceptions=True)
        await connection.close()


@pytest.mark.asyncio
async def test_conflict_cold_model_does_not_block_event_loop(monkeypatch):
    from deepchoice.agents import conflict_detector

    entered, release = threading.Event(), threading.Event()

    def loader():
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(encode=lambda _titles: np.array([[1, 0], [0, 1]]))

    monkeypatch.setattr(conflict_detector, "get_embedding_model", loader)
    scan = asyncio.create_task(conflict_detector.find_contradictions(
        [{"total_score": 6, "title": "a"}, {"total_score": 6, "title": "b"}]))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        release.set()
        assert await asyncio.wait_for(scan, timeout=1) == []
    finally:
        release.set()
        await asyncio.gather(scan, return_exceptions=True)


@pytest.mark.asyncio
async def test_observed_retrieval_rate_limit_preserves_envelope(tmp_path, monkeypatch):
    from deepchoice.agents.multi_retriever import _invoke_retriever_miss
    from deepchoice.retrievers.contracts import RetrievalResult

    class Limited:
        async def retrieve(self, _request):
            return RetrievalResult(source="arxiv", status="failed", results=[],
                                   error="HTTPStatusError: HTTP 429", latency_ms=1)

    connection, lock, repo, _ = await queued(tmp_path)
    try:
        await repo.acquire_run_lease("run", lease_owner="worker", lease_ttl=timedelta(seconds=30),
                                    run_timeout=timedelta(minutes=5))
        run = await repo.get_run("run")
        recorder = RuntimeTraceRecorder(SQLiteTraceStore(connection, lock).bind(
            run_id="run", execution_epoch=run.execution_epoch, lease_owner="worker"), task_id="task")
        node = await recorder.start_node_attempt("multi_retriever")

        class Cancellation:
            async def raise_if_cancelled(self):
                return None

        with bind_run_context(RunContext.from_run_record(
            run, cancellation=Cancellation(), trace=recorder, budget=DeferredBudgetManager())), bind_node_attempt(node.node_attempt_id):
            result, _ = await _invoke_retriever_miss(
                "arxiv", Limited, query="q", sub_questions=[], adapted_queries=[])
        assert result.status == "failed" and result.results == []
        call = (await SQLiteObservabilityQuery(connection, lock).for_task("task")).calls[0]
        assert call.status == "failed" and call.failure_category == "rate_limited"
    finally:
        await connection.close()


def test_collector_historical_missing_observations_remain_unknown(tmp_path):
    record = {"case_id": "P01", "experiment_id": "offline", "profile": "serial",
              "repetition": 1, "status": "failed", "observability_final": False,
              "observability": {"availability": "available", "calls": [{"kind": "llm"}]}}
    result = diagnostic_projection(record)
    assert result["diagnostic_known_calls"] == 0
    assert result["observed_llm_calls"] == 1
    assert result["qualification"] == "not_evaluated"
    assert result["run_failure_category"] is None
    write_collection_summary(tmp_path, [record])
    data = json.loads((tmp_path / "diagnostics-summary.json").read_text(encoding="utf-8"))
    assert data["live_qualification"] == "not_evaluated"
    assert data["case_denominator"] == 1
    assert (tmp_path / "diagnostics.csv").exists()


@pytest.mark.asyncio
async def test_release_during_renewal_cleans_row_and_allows_immediate_restart(tmp_path, monkeypatch):
    connection, lock, _, _ = await queued(tmp_path)
    guard = RuntimeInstanceGuard(connection, lock, heartbeat_seconds=0.01)
    second_connection = await connect_database(tmp_path / "product.db")
    second = RuntimeInstanceGuard(second_connection, asyncio.Lock())
    entered = asyncio.Event()
    original_commit = connection.commit

    async def paused_commit():
        entered.set()
        await asyncio.Event().wait()

    try:
        await guard.acquire()
        monkeypatch.setattr(connection, "commit", paused_commit)
        guard.start_heartbeat(lambda: None)
        await asyncio.wait_for(entered.wait(), timeout=1)
        # release cancels the in-flight renewal; rollback precedes cleanup.
        monkeypatch.setattr(connection, "commit", original_commit)
        await asyncio.wait_for(guard.release(), timeout=1)
        assert not connection.in_transaction
        count = await (await connection.execute("SELECT COUNT(*) FROM runtime_instance_leases")).fetchone()
        assert count[0] == 0
        await second.acquire()
        await guard.release()  # Never delete a replacement owner's lease.
        assert second.has_authority
        count = await (await connection.execute("SELECT COUNT(*) FROM runtime_instance_leases")).fetchone()
        assert count[0] == 1
    finally:
        monkeypatch.setattr(connection, "commit", original_commit)
        await guard.release()
        await second.release()
        await second_connection.close()
        await connection.close()
