"""Focused Phase 2-A trace, budget, context, and persistence contracts."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from deepchoice.budget import (
    CURRENT_PRICE_CATALOG,
    DEFAULT_RUN_BUDGET_POLICY,
    STANDARD_OBSERVE_RUN_BUDGET_POLICY,
    BudgetAmount,
    BudgetLedgerEntry,
    BudgetReservation,
    BudgetResource,
    PriceQuote,
    PriceStatus,
    ReservationStatus,
)
from deepchoice.contracts.api import ResearchRequest
from deepchoice.observability import NodeAttempt, TraceStatus
from deepchoice.persistence import (
    MIGRATIONS,
    RepositoryOperationError,
    SQLiteTaskRunRepository,
    connect_database,
    run_migrations,
)
from deepchoice.runtime import RunContext
from deepchoice.runtime.lifecycle import RunStatus
from deepchoice.services.tasks import TaskService


NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Cancellation:
    async def raise_if_cancelled(self) -> None:
        return None


class _Trace:
    async def record_run(self, trace): pass
    async def record_node_attempt(self, attempt): pass
    async def record_external_call(self, call): pass
    async def record_event(self, event): pass


class _Budget:
    run_id = "run-1"
    execution_epoch = 1
    async def reserve_bundle(self, **kwargs): raise NotImplementedError
    async def reserve(self, **kwargs): raise NotImplementedError
    async def settle(self, reservation_id, **kwargs): raise NotImplementedError
    async def release(self, reservation_id): raise NotImplementedError
    async def mark_unknown_spend(self, reservation_id, **kwargs): raise NotImplementedError
    async def reconcile(self): return 0
    async def raise_if_exhausted(self, *, partial_state=None): return None
    async def record_active_milliseconds(self): return None


def test_standard_policies_and_unknown_price_are_explicit() -> None:
    policy = DEFAULT_RUN_BUDGET_POLICY
    assert policy.policy_version == "standard-enforced-v1"
    assert policy.tier.value == "standard"
    assert policy.enforcement_mode.value == "enforced"
    assert policy.soft_limit_ratio == 0.8
    assert policy.hard_limits.llm_calls == 96
    assert policy.hard_limits.retrieval_calls == 72
    assert policy.hard_limits.total_tokens == 60_000
    assert policy.hard_limits.active_milliseconds == 900_000
    assert policy.hard_limits.cost_micro_usd is None

    historical = STANDARD_OBSERVE_RUN_BUDGET_POLICY
    assert historical.policy_version == "standard-observe-v1"
    assert historical.enforcement_mode.value == "observe_only"
    assert all(
        value is None for value in historical.hard_limits.model_dump().values()
    )
    quote = CURRENT_PRICE_CATALOG.quote(provider="unknown", model="unknown")
    assert quote.status is PriceStatus.UNKNOWN
    assert quote.input_micro_usd_per_million_tokens is None
    assert quote.output_micro_usd_per_million_tokens is None


@pytest.mark.parametrize(
    "field",
    [
        "apiKey", "APIKey", "apikey", "accessToken", "authToken",
        "refreshToken", "clientSecret", "privateKey", "Headers", "checkPointId",
    ],
)
def test_trace_summary_rejects_sensitive_key_variants(field: str) -> None:
    with pytest.raises(ValidationError):
        NodeAttempt(
            node_attempt_id="attempt-1", run_id="run-1", execution_epoch=1,
            node_name="retrieve", attempt_no=1, status=TraceStatus.STARTED,
            started_at=NOW, summary={field: "sensitive"},
        )


def test_trace_and_budget_contracts_are_strict_frozen_and_json_safe() -> None:
    source_summary = {"token_usage": {"items": [{"input_tokens": 12}]}}
    attempt = NodeAttempt(
        node_attempt_id="attempt-1", run_id="run-1", execution_epoch=1,
        node_name="retrieve", attempt_no=1, status=TraceStatus.STARTED,
        started_at=NOW, summary=source_summary,
    )
    source_summary["token_usage"]["items"][0]["input_tokens"] = 999
    detached = attempt.summary.to_dict()
    detached["token_usage"]["items"][0]["input_tokens"] = 888
    assert attempt.summary.to_dict()["token_usage"]["items"][0]["input_tokens"] == 12
    assert attempt.model_dump()["schema_version"] == 1
    with pytest.raises(ValidationError):
        attempt.node_name = "other"
    with pytest.raises(ValidationError):
        NodeAttempt(**attempt.model_dump(), unexpected=True)
    with pytest.raises(ValidationError):
        NodeAttempt(**{**attempt.model_dump(), "schema_version": 2})
    with pytest.raises(ValidationError):
        NodeAttempt(
            **{
                **attempt.model_dump(),
                "summary": {"metrics": [{"refreshToken": "sensitive"}]},
            }
        )
    with pytest.raises(ValidationError):
        NodeAttempt(**{**attempt.model_dump(), "summary": {1: "invalid key"}})
    with pytest.raises(ValidationError):
        NodeAttempt(**{**attempt.model_dump(), "summary": {"bad": object()}})
    with pytest.raises(ValidationError):
        BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=-1)
    assert BudgetAmount(
        resource=BudgetResource.LLM_CALLS, amount=1
    ).model_dump()["schema_version"] == 1
    with pytest.raises(ValidationError):
        BudgetAmount(
            schema_version=2, resource=BudgetResource.LLM_CALLS, amount=1
        )
    with pytest.raises(ValidationError):
        BudgetLedgerEntry(
            ledger_entry_id="entry-1",
            run_id="run-1",
            execution_epoch=1,
            reservation_id="reservation-1",
            entry_sequence=1,
            status=ReservationStatus.UNKNOWN_SPEND,
            resource=BudgetResource.LLM_CALLS,
            reserved_amount=1,
            actual_amount=0,
            price_status=PriceStatus.UNKNOWN,
            price_catalog_version="unpriced-v1",
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
            settled_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        BudgetReservation(
            reservation_id="reservation-1",
            run_id="run-1",
            execution_epoch=1,
            status=ReservationStatus.UNKNOWN_SPEND,
            reserved=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=2),
            actual=BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),
            price_status=PriceStatus.UNKNOWN,
            price_catalog_version="unpriced-v1",
            created_at=NOW,
            updated_at=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=1),
            settled_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        PriceQuote(
            catalog_version="unpriced-v1",
            provider="provider",
            model="model",
            status=PriceStatus.UNKNOWN,
            input_micro_usd_per_million_tokens=1,
        )


@pytest.mark.asyncio
async def test_v8_upgrade_preserves_old_run_without_policy(tmp_path) -> None:
    connection = await connect_database(tmp_path / "old.db")
    try:
        assert await run_migrations(connection, MIGRATIONS[:7]) == tuple(range(1, 8))
        await connection.execute(
            "INSERT INTO tasks(task_id,status,request_json,latest_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("task-old", "queued", '{"query":"old query"}', "run-old", NOW.isoformat(), NOW.isoformat()),
        )
        from deepchoice.contracts.manifest import build_run_manifest
        manifest = build_run_manifest({"query": "old query"})
        await connection.execute(
            "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("run-old", "task-old", "queued", manifest.model_dump_json(), "run-old", NOW.isoformat(), NOW.isoformat()),
        )
        await connection.commit()
        assert await run_migrations(connection) == (8,)
        repository = SQLiteTaskRunRepository(connection)
        old_run = await repository.get_run("run-old")
        assert old_run is not None and old_run.budget_policy is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_new_and_retry_runs_freeze_policy_atomically(tmp_path) -> None:
    connection = await connect_database(tmp_path / "tasks.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    ids = iter(uuid.UUID(int=value) for value in range(1, 8))
    service = TaskService(repository, uuid_factory=lambda: next(ids), clock=lambda: NOW)
    try:
        created = await service.create(ResearchRequest(query="compare a and b"))
        first = created.latest_run
        assert first is not None and first.budget_policy == DEFAULT_RUN_BUDGET_POLICY
        with pytest.raises(ValueError, match="frozen budget policy"):
            await repository.create_task_with_run(
                created.task,
                first.model_copy(update={"budget_policy": None}),
            )
        grant = await repository.acquire_run_lease(
            first.run_id, lease_owner="worker", lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5), now=NOW,
        )
        failed = await repository.finalize_run(
            first.run_id, lease_owner="worker", execution_epoch=grant.execution_epoch,
            status=RunStatus.FAILED, now=NOW + timedelta(seconds=1),
        )
        retried = await service.resume(
            created.task.task_id, expected_task_version=failed.task.version
        )
        assert retried.latest_run is not None
        assert retried.latest_run.run_id != first.run_id
        assert retried.latest_run.budget_policy == DEFAULT_RUN_BUDGET_POLICY

        await connection.execute(
            "CREATE TRIGGER reject_policy BEFORE INSERT ON run_budget_policies BEGIN SELECT RAISE(ABORT, 'no'); END"
        )
        with pytest.raises(RepositoryOperationError):
            await service.create(ResearchRequest(query="must roll back"))
        row = await (await connection.execute("SELECT count(*) FROM tasks WHERE request_json LIKE '%must roll back%'" )).fetchone()
        assert row[0] == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_v8_schema_fences_trace_epochs_and_keeps_audit_rows_immutable(
    tmp_path,
) -> None:
    connection = await connect_database(tmp_path / "constraints.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    service = TaskService(repository, clock=lambda: NOW)
    try:
        created = await service.create(ResearchRequest(query="trace contracts"))
        run_id = created.latest_run.run_id
        policy = await (
            await connection.execute(
                "SELECT policy_version, price_catalog_version FROM run_budget_policies "
                "WHERE run_id = ?",
                (run_id,),
            )
        ).fetchone()
        assert policy == ("standard-enforced-v1", "unpriced-v1")
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "UPDATE run_budget_policies SET price_catalog_version='changed' "
                "WHERE run_id = ?",
                (run_id,),
            )

        await connection.execute(
            "INSERT INTO node_attempts(node_attempt_id,run_id,execution_epoch,"
            "node_name,attempt_no,status,started_at,summary_json) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("node-1", run_id, 1, "query_analyzer", 1, "started", NOW.isoformat(), "{}"),
        )
        await connection.execute(
            "INSERT INTO node_attempts(node_attempt_id,run_id,execution_epoch,"
            "node_name,attempt_no,status,started_at,summary_json) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("node-2", run_id, 1, "retrieve", 1, "started", NOW.isoformat(), "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO external_calls(call_id,run_id,execution_epoch,node_attempt_id,"
                "call_no,kind,provider,operation,status,started_at,request_summary_json,"
                "result_summary_json,usage_summary_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "call-stale", run_id, 2, "node-1", 1, "llm", "provider", "complete",
                    "started", NOW.isoformat(), "{}", "{}", "{}",
                ),
            )
        await connection.execute(
            "INSERT INTO external_calls(call_id,run_id,execution_epoch,node_attempt_id,"
            "call_no,kind,provider,operation,status,started_at,request_summary_json,"
            "result_summary_json,usage_summary_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "call-1", run_id, 1, "node-1", 1, "llm", "provider", "complete",
                "started", NOW.isoformat(), "{}", "{}", "{}",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO trace_events(run_id,execution_epoch,seq,event_type,"
                "node_attempt_id,call_id,summary_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id, 1, 1, "call.started", "node-2", "call-1", "{}",
                    NOW.isoformat(),
                ),
            )
        await connection.execute(
            "INSERT INTO trace_events(run_id,execution_epoch,seq,event_type,summary_json,"
            "created_at) VALUES(?,?,?,?,?,?)",
            (run_id, 1, 1, "node.started", "{}", NOW.isoformat()),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO trace_events(run_id,execution_epoch,seq,event_type,"
                "summary_json,created_at) VALUES(?,?,?,?,?,?)",
                (run_id, 2, 1, "run.resumed", "{}", NOW.isoformat()),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "UPDATE trace_events SET event_type='changed' WHERE run_id = ?",
                (run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "DELETE FROM trace_events WHERE run_id = ?",
                (run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO budget_ledger(ledger_entry_id,run_id,execution_epoch,"
                "reservation_id,entry_sequence,status,resource,reserved_amount,actual_amount,"
                "price_status,price_catalog_version,summary_json,created_at,expires_at,settled_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "ledger-bad", run_id, 1, "reservation-1", 1, "unknown_spend",
                    "llm_calls", 1, 0, "unknown", "unpriced-v1", "{}", NOW.isoformat(),
                    (NOW + timedelta(minutes=1)).isoformat(), NOW.isoformat(),
                ),
            )
        await connection.execute(
            "INSERT INTO budget_ledger(ledger_entry_id,run_id,execution_epoch,"
            "reservation_id,entry_sequence,status,resource,reserved_amount,price_status,"
            "price_catalog_version,summary_json,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "ledger-1", run_id, 1, "reservation-1", 1, "reserved", "llm_calls", 1,
                "not_applicable", "unpriced-v1", "{}", NOW.isoformat(),
                (NOW + timedelta(minutes=1)).isoformat(),
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "DELETE FROM budget_ledger WHERE ledger_entry_id='ledger-1'"
            )
    finally:
        await connection.close()


def test_run_context_identity_comes_from_running_record() -> None:
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.persistence.records import RunRecord

    manifest = build_run_manifest({"query": "context"})
    running = RunRecord(
        run_id="run-1", task_id="task-1", status=RunStatus.RUNNING,
        manifest=manifest, thread_id="run-1", execution_epoch=3,
        deadline_at=NOW + timedelta(minutes=5), created_at=NOW, updated_at=NOW,
    )
    context = RunContext.from_run_record(
        running, cancellation=_Cancellation(), trace=_Trace(), budget=_Budget()
    )
    assert (context.task_id, context.run_id, context.manifest_id, context.execution_epoch) == (
        "task-1", "run-1", manifest.manifest_id, 3
    )
    with pytest.raises(ValidationError):
        context.execution_epoch = 4
    with pytest.raises(ValueError):
        RunContext.from_run_record(
            running.model_copy(update={"status": RunStatus.QUEUED}),
            cancellation=_Cancellation(), trace=_Trace(), budget=_Budget(),
        )
