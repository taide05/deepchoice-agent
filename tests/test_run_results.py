"""Contracts for immutable durable results and their public API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import RunRecord, RunResultRecord, TaskRecord
from deepchoice.persistence.repository import (
    RepositoryOperationError,
    RunLeaseLostError,
    SQLiteTaskRunRepository,
)
from deepchoice.runtime.coordinator import build_public_run_result
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.server import app as app_module


def _records(task_id: str = "task-result", run_id: str = "run-result"):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchRequest(query="compare FastAPI and Flask")
    task = TaskRecord(
        task_id=task_id,
        status=TaskStatus.QUEUED,
        request=request,
        latest_run_id=run_id,
        created_at=now,
        updated_at=now,
    )
    run = RunRecord(
        run_id=run_id,
        task_id=task_id,
        status=RunStatus.QUEUED,
        manifest=build_run_manifest(request.model_dump()),
        budget_policy=DEFAULT_RUN_BUDGET_POLICY,
        thread_id=run_id,
        created_at=now,
        updated_at=now,
    )
    return task, run


def _result(run_id: str, *, report_format: str = "what_why_how"):
    report = "# Durable report"
    return RunResultRecord(
        run_id=run_id,
        snapshot={
            "task": {"query": "compare FastAPI and Flask", "report_format": report_format},
            "evidence_chains": [],
            "confidence": "high",
            "report": report,
        },
        report=report,
        report_format=report_format,
        created_at=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
    )


def test_provisional_analysis_survives_public_result_roundtrip_with_warning():
    from deepchoice.formats.what_why_how import render

    task, run = _records()
    analysis = "SQLite allows only one writer. [Source: SQLite Docs]"
    state = {"task": task.request.model_dump(), "final_recommendation": {
        "winner": "context_dependent", "ranked_options": [],
        "requirement_assessments": [{
            "id": "C1", "requirement": "Write concurrency", "status": "unknown",
            "explanation": "Unknown: independent verification needed.", "evidence_ids": [],
            "provisional_explanation": analysis, "lease_owner": "private-worker",
        }],
    }}
    state["report"] = render(state)
    result = build_public_run_result(run, task.request.model_dump(), state, created_at=run.created_at)
    restored = RunResultRecord.model_validate_json(result.model_dump_json())
    row = restored.snapshot["final_recommendation"]["requirement_assessments"][0]
    assert row["provisional_explanation"] == analysis and row["status"] == "unknown"
    assert "lease_owner" not in row and "private-worker" not in restored.model_dump_json()
    assert "Analysis awaiting independent verification (not a satisfied requirement)" in restored.report
    assert analysis in restored.report


def test_validation_only_plan_survives_public_result_without_original_operations():
    from deepchoice.formats.what_why_how import render
    from deepchoice.utils.decision_contract import abstain_recommendation

    task, run = _records()
    recommendation = abstain_recommendation({
        "action_plan": [{"step": "UNSAFE_LIVE_CUTOVER", "verification": "Later",
                         "change_trigger": "Now", "rollback": "UNSAFE_OLD_SNAPSHOT"}],
    }, task.request.query)
    recommendation["lease_owner"] = "private-worker"
    state = {"task": task.request.model_dump(), "final_recommendation": recommendation}
    state["report"] = render(state)
    result = build_public_run_result(run, task.request.model_dump(), state, created_at=run.created_at)
    restored = RunResultRecord.model_validate_json(result.model_dump_json())
    assert restored.snapshot["final_recommendation"]["action_plan_mode"] == "validation_only"
    assert "Isolated validation only; no production changes" in restored.report
    assert restored.snapshot["final_recommendation"]["deployment_readiness"] == "unverified"
    assert "Deployment acceptance: unverified" in restored.report
    assert "acknowledged writes" in restored.report
    for forbidden in ("UNSAFE_LIVE_CUTOVER", "UNSAFE_OLD_SNAPSHOT", "private-worker"):
        assert forbidden not in restored.model_dump_json()


def test_withdrawn_action_can_remain_only_as_citation_audit_text_in_public_snapshot():
    from deepchoice.agents.citation_validator import _calibrate_decision
    from deepchoice.citations import (
        CitationCheck, CitationReason, CitationStatus, CitationStatusCounts, CitationVerification,
    )
    from deepchoice.formats.what_why_how import render

    task, run = _records()
    text = "UNSAFE_OLD_SNAPSHOT"
    verification = CitationVerification(status_counts=CitationStatusCounts(unsupported=1), checks=(
        CitationCheck(claim_id="original-action", claim_path="final_recommendation.action_plan[0].rollback",
                      claim_text=text, status=CitationStatus.UNSUPPORTED, reason=CitationReason.CITATION_MISSING),
    ))
    recommendation = _calibrate_decision({
        "decision_basis_version": "constraint-aware-v1",
        "requirement_assessments": [{"id": "A1", "requirement": "Recovery boundary", "status": "unknown"}],
        "action_plan": [{"step": "UNSAFE_LIVE_CUTOVER", "verification": "Later",
                         "change_trigger": "Now", "rollback": text}],
    }, verification, task.request.query)
    state = {"task": task.request.model_dump(), "final_recommendation": recommendation,
             "citation_verification": verification.model_dump(mode="json")}
    state["report"] = render(state)
    result = build_public_run_result(run, task.request.model_dump(), state, created_at=run.created_at)
    restored = RunResultRecord.model_validate_json(result.model_dump_json())
    audit = restored.snapshot["citation_verification"]["checks"][0]
    assert audit["claim_text"] == text and audit["status"] == "unsupported"
    assert text not in str(restored.snapshot["final_recommendation"])
    assert text not in restored.report and "UNSAFE_LIVE_CUTOVER" not in restored.report
    assert "Isolated validation only; no production changes" in restored.report


@pytest.mark.asyncio
async def test_result_and_successful_terminal_event_commit_together(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    task, run = _records()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        await repository.create_task_with_run(task, run)
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
            now=now,
        )
        finalized = await repository.finalize_run_with_result(
            run.run_id,
            _result(run.run_id),
            lease_owner="worker",
            execution_epoch=grant.execution_epoch,
            now=now + timedelta(seconds=2),
        )

        assert finalized.task.status is TaskStatus.COMPLETED
        assert (await repository.get_run_result(run.run_id)).report == "# Durable report"
        assert (await repository.list_task_events(task.task_id))[-1].type == "run.completed"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await connection.execute(
                "UPDATE run_results SET report='changed' WHERE run_id=?", (run.run_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await connection.execute("DELETE FROM run_results WHERE run_id=?", (run.run_id,))
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_stale_epoch_and_result_insert_failure_write_nothing(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    task, run = _records()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        await repository.create_task_with_run(task, run)
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
            now=now,
        )
        before = await repository.get_task(task.task_id)
        before_events = await repository.list_task_events(task.task_id)

        with pytest.raises(RunLeaseLostError):
            await repository.finalize_run_with_result(
                run.run_id,
                _result(run.run_id),
                lease_owner="worker",
                execution_epoch=grant.execution_epoch + 1,
                now=now + timedelta(seconds=1),
            )
        assert await repository.get_task(task.task_id) == before
        assert await repository.get_run_result(run.run_id) is None
        assert await repository.list_task_events(task.task_id) == before_events

        # The format mismatch is detected after lifecycle UPDATE statements;
        # the enclosing transaction must roll every prior write back.
        with pytest.raises(RepositoryOperationError):
            await repository.finalize_run_with_result(
                run.run_id,
                _result(run.run_id, report_format="evidence_first"),
                lease_owner="worker",
                execution_epoch=grant.execution_epoch,
                now=now + timedelta(seconds=1),
            )
        assert await repository.get_task(task.task_id) == before
        assert await repository.get_run_result(run.run_id) is None
        assert await repository.list_task_events(task.task_id) == before_events
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_cancel_or_deadline_wins_without_publishing_result(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    task, run = _records()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        await repository.create_task_with_run(task, run)
        grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="worker",
            lease_ttl=timedelta(minutes=10),
            run_timeout=timedelta(seconds=1),
            now=now,
        )
        finalized = await repository.finalize_run_with_result(
            run.run_id,
            _result(run.run_id),
            lease_owner="worker",
            execution_epoch=grant.execution_epoch,
            now=now + timedelta(seconds=2),
        )
        assert finalized.task.status is TaskStatus.TIMED_OUT
        assert await repository.get_run_result(run.run_id) is None
        assert (await repository.list_task_events(task.task_id))[-1].type == "run.timed_out"
    finally:
        await connection.close()


def test_public_result_uses_allowlist_and_removes_private_nested_values():
    task, run = _records()
    state = type(
        "State",
        (),
        {
            "values": {
                "task": {"query": "mutated"},
                "report": "# Public",
                "confidence": "high",
                "evidence_chains": [
                    {
                        "claim": "supported",
                        "checkpoint_id": "private-cp",
                        "_error": "raw secret exception",
                        "api_key": "sk-private-api-key",
                        "Authorization": "Bearer private-token",
                        "provider_password": "private-password",
                        "nested": {
                            "credentials": "private-credential",
                            "accessToken": "private-access-token",
                            "clientSecret": "private-client-secret",
                            "privateKey": "private-key-material",
                            "apiKey": "private-camel-api-key",
                        },
                    }
                ],
                "search_results": [{
                    "source": "chroma",
                    "status": "success",
                    "results": [{
                        "url": "https://example.com/docs",
                        "title": "Public docs",
                        "snippet": "Public excerpt",
                        "_seed_target_id": "private-target",
                        "_seed_source_type": "official",
                        "_seed_seed_identity_sha256": "a" * 64,
                    }],
                }],
                "token_usage": {"input_tokens": 12, "output_tokens": 7},
                "citation_verification": {
                    "schema_version": 1,
                    "policy_version": "deterministic-citation-v1",
                    "status_counts": {
                        "verified": 1,
                        "unsupported": 0,
                        "unreachable": 0,
                        "unknown": 0,
                    },
                    "checks": [{
                        "claim_id": "claim-public",
                        "claim_path": "final_recommendation.winner_rationale",
                        "claim_text": "Public claim",
                        "source_title": "Public docs",
                        "canonical_url": "https://example.com/docs",
                        "status": "verified",
                        "reason": "lexical_support",
                        "raw_body": "must not survive nested sanitization",
                    }],
                },
                "run_manifest": {"manifest_id": "private"},
                "unknown_state": "private",
            }
        },
    )()
    result = build_public_run_result(
        run,
        task.request.model_dump(mode="json", exclude_none=True),
        state,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    encoded = result.model_dump_json()
    assert result.snapshot["task"]["query"] == task.request.query
    assert "run_manifest" not in result.snapshot
    assert "unknown_state" not in result.snapshot
    assert "checkpoint_id" not in encoded
    assert "raw secret exception" not in encoded
    assert "sk-private-api-key" not in encoded
    assert "private-token" not in encoded
    assert "private-password" not in encoded
    assert "private-credential" not in encoded
    assert "private-access-token" not in encoded
    assert "private-client-secret" not in encoded
    assert "private-key-material" not in encoded
    assert "private-camel-api-key" not in encoded
    assert result.snapshot["token_usage"]["input_tokens"] == 12
    assert result.snapshot["citation_verification"]["status_counts"]["verified"] == 1
    public_source = result.snapshot["search_results"][0]["results"][0]
    assert public_source == {
        "url": "https://example.com/docs",
        "title": "Public docs",
        "snippet": "Public excerpt",
    }
    assert "raw_body" not in result.snapshot["citation_verification"]["checks"][0]
    assert "must not survive nested sanitization" not in encoded


def test_public_result_rejects_success_without_report():
    task, run = _records()
    state = type("State", (), {"values": {"confidence": "high"}})()
    with pytest.raises(ValueError, match="non-empty public report"):
        build_public_run_result(
            run,
            task.request.model_dump(mode="json", exclude_none=True),
            state,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


@pytest.fixture
def durable_client(tmp_path: Path):
    state = app_module.app.state
    missing = object()
    names = (
        "execution_enabled",
        "checkpoint_database_path",
        "product_database_path",
        "legacy_snapshot_root",
    )
    old = {name: getattr(state, name, missing) for name in names}
    state.execution_enabled = False
    state.checkpoint_database_path = tmp_path / "checkpoints.db"
    state.product_database_path = tmp_path / "product.db"
    state.legacy_snapshot_root = tmp_path / "legacy"
    try:
        with TestClient(app_module.app) as client:
            yield client
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(state, name)
            else:
                setattr(state, name, value)


def test_durable_result_api_and_legacy_fallback(durable_client, monkeypatch):
    client = durable_client
    created = client.post(
        "/api/v1/tasks", json={"query": "compare FastAPI and Flask"}
    ).json()
    task_id = created["task"]["task_id"]
    run_id = created["latest_run"]["run_id"]
    repository = app_module.app.state.task_repository

    async def complete():
        grant = await repository.acquire_run_lease(
            run_id,
            lease_owner="worker",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=5),
        )
        return await repository.finalize_run_with_result(
            run_id,
            _result(run_id),
            lease_owner="worker",
            execution_epoch=grant.execution_epoch,
        )

    client.portal.call(complete)
    monkeypatch.setattr(app_module, "load_snapshot", lambda _task_id: None)

    snapshot = client.get(f"/api/v1/tasks/{task_id}/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["confidence"] == "high"
    assert "manifest" not in snapshot.text
    report = client.get(f"/api/v1/tasks/{task_id}/report")
    assert report.status_code == 200
    assert report.json()["run_id"] == run_id
    assert report.json()["report"] == "# Durable report"
    assert client.get(f"/api/v1/tasks/{task_id}/annotated").status_code == 200
    export = client.get(f"/api/v1/tasks/{task_id}/export?format=md")
    assert export.status_code == 200
    assert export.text == "# Durable report"

    legacy = client.get(f"/research/{task_id}/report")
    assert legacy.status_code == 200
    assert legacy.headers["deprecation"] == "true"
    assert legacy.json()["report"]
    legacy_snapshot = client.get(f"/research/{task_id}/snapshot")
    assert legacy_snapshot.status_code == 200
    assert legacy_snapshot.headers["warning"].startswith("299 DeepChoice")


def test_result_api_distinguishes_not_ready_and_terminal_unavailable(durable_client):
    client = durable_client
    created = client.post("/api/v1/tasks", json={"query": "queued"}).json()
    task_id = created["task"]["task_id"]
    not_ready = client.get(f"/api/v1/tasks/{task_id}/report")
    assert not_ready.status_code == 409
    assert not_ready.json()["error"]["code"] == "TASK_RESULT_NOT_READY"
    assert not_ready.json()["error"]["retryable"] is True

    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    unavailable = client.get(f"/api/v1/tasks/{task_id}/snapshot")
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "TASK_RESULT_UNAVAILABLE"
    assert unavailable.json()["error"]["retryable"] is False


def test_lost_runtime_lease_blocks_mutations_but_keeps_reads(durable_client):
    client = durable_client
    created = client.post("/api/v1/tasks", json={"query": "existing"}).json()
    task_id = created["task"]["task_id"]
    version = created["task"]["version"]
    app_module.app.state.runtime_instance_status = "lost"
    try:
        health = client.get("/health")
        assert health.status_code == 503
        assert client.get(f"/api/v1/tasks/{task_id}").status_code == 200
        for response in (
            client.post("/api/v1/tasks", json={"query": "blocked"}),
            client.post(f"/api/v1/tasks/{task_id}/cancel"),
            client.post(
                f"/api/v1/tasks/{task_id}/resume",
                headers={"If-Match": str(version)},
            ),
        ):
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "RUNTIME_INSTANCE_LEASE_LOST"
    finally:
        app_module.app.state.runtime_instance_status = "active"
