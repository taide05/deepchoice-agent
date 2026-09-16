"""Budget-cap policy and deterministic restricted-result contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.budget import (
    DEFAULT_RUN_BUDGET_POLICY,
    STANDARD_OBSERVE_RUN_BUDGET_POLICY,
    BudgetAmount,
    BudgetEnforcementMode,
    BudgetExceededError,
    BudgetHardLimits,
    BudgetResource,
    RunBudgetPolicy,
    reserve_call,
    settle_call,
)
from deepchoice.budget.limited import (
    build_budget_limited_state,
    minimum_evidence_is_met,
    usable_evidence_chains,
)
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.errors import ErrorCategory, normalize_error
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import CheckpointReference, RunRecord, TaskRecord
from deepchoice.persistence.repository import SQLiteTaskRunRepository
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.services.tasks import TaskService


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _chain(
    url: str,
    *,
    strength: str = "weak",
    disputed: bool = False,
    score: float = 7.0,
) -> dict:
    return {
        "conclusion": f"Finding from {url}",
        "sources": [
            {
                "url": url,
                "title": "Evidence",
                "snippet": "Relevant evidence",
                "score": score,
            }
        ],
        "evidence_strength": strength,
        "disputed": disputed,
    }


def _sufficient_state() -> dict:
    return {
        "evidence_chains": [
            _chain("https://docs.example.com/a", strength="moderate"),
            _chain("https://docs.example.com/b"),
            _chain("https://research.example.net/c"),
        ],
        "conflicts": [],
        "partial_failures": [],
        "knowledge_gaps": ["Long-term operational cost is not yet verified."],
    }


def _budget_error(state: dict | None = None) -> BudgetExceededError:
    return BudgetExceededError(
        BudgetResource.LLM_CALLS,
        limit=96,
        consumed=96,
        requested=1,
    ).attach_partial_state(state)


def test_minimum_evidence_requires_three_undisputed_chains_two_hosts_and_strength():
    state = _sufficient_state()
    assert minimum_evidence_is_met(state)

    same_host = dict(state)
    same_host["evidence_chains"] = [
        _chain("https://docs.example.com/a", strength="moderate"),
        _chain("https://DOCS.example.com./b"),
        _chain("https://docs.example.com/c"),
    ]
    assert not minimum_evidence_is_met(same_host)

    disputed = dict(state)
    disputed["conflicts"] = [
        {
            "source_a": {"url": "https://docs.example.com/b"},
            "source_b": {"url": "https://other.example.org/dispute"},
        }
    ]
    assert len(usable_evidence_chains(disputed)) == 2
    assert not minimum_evidence_is_met(disputed)

    invalid_url = dict(state)
    invalid_url["evidence_chains"] = [
        _chain("https://docs.example.com/a", strength="moderate"),
        _chain("ftp://research.example.net/b"),
        _chain("not a URL"),
    ]
    assert not minimum_evidence_is_met(invalid_url)

    only_weak = dict(state)
    only_weak["evidence_chains"] = [
        _chain("https://docs.example.com/a", score=5.0),
        _chain("https://docs.example.com/b", score=5.0),
        _chain("https://research.example.net/c", score=5.0),
    ]
    assert not minimum_evidence_is_met(only_weak)


def test_minimum_evidence_deduplicates_sources_and_derives_strength_from_score():
    duplicate = {
        "evidence_chains": [
            _chain("https://docs.example.com:443/a", strength="strong", score=5.0),
            _chain("https://DOCS.example.com./a", strength="strong", score=5.0),
            _chain("https://research.example.net/b", strength="strong", score=5.0),
        ],
        "conflicts": [],
    }
    assert len(usable_evidence_chains(duplicate)) == 2
    assert not minimum_evidence_is_met(duplicate)

    fabricated_strength = _sufficient_state()
    for chain in fabricated_strength["evidence_chains"]:
        chain["evidence_strength"] = "strong"
        chain["sources"][0]["score"] = 5.0
    assert not minimum_evidence_is_met(fabricated_strength)


def test_minimum_evidence_rejects_empty_low_score_and_canonical_disputes():
    empty = _sufficient_state()
    empty["evidence_chains"][0]["conclusion"] = " "
    assert not minimum_evidence_is_met(empty)

    low_score = _sufficient_state()
    low_score["evidence_chains"][0]["sources"][0]["score"] = 0
    assert not minimum_evidence_is_met(low_score)

    aliased_dispute = _sufficient_state()
    aliased_dispute["conflicts"] = [
        {
            "source_a": {"url": "https://DOCS.example.com.:443/a"},
            "source_b": {"url": "https://other.example.org/x"},
        }
    ]
    assert len(usable_evidence_chains(aliased_dispute)) == 2
    assert not minimum_evidence_is_met(aliased_dispute)


def test_minimum_evidence_can_be_built_locally_from_existing_scores():
    state = {
        "source_scores": [
            {"url": "https://a.example/1", "title": "A", "total_score": 6.0},
            {"url": "https://a.example/2", "title": "B", "total_score": 5.0},
            {"url": "https://b.example/3", "title": "C", "total_score": 5.0},
        ],
        "conflicts": [],
    }
    assert minimum_evidence_is_met(state)
    assert len(usable_evidence_chains(state)) == 3


def test_restricted_report_is_deterministic_and_explicitly_marked():
    request = {
        "query": "compare A and B",
        "report_format": "evidence_first",
    }
    error = _budget_error(_sufficient_state())
    first = build_budget_limited_state(
        error.partial_state,
        request=request,
        policy=DEFAULT_RUN_BUDGET_POLICY,
        error=error,
    )
    second = build_budget_limited_state(
        error.partial_state,
        request=request,
        policy=DEFAULT_RUN_BUDGET_POLICY,
        error=error,
    )
    assert first == second
    assert first is not None
    assert first["report"].startswith("> **Budget-limited report:**")
    assert first["budget_limited"] == {
        "limited": True,
        "policy_version": "standard-enforced-v1",
        "exhausted_resource": "llm_calls",
        "minimum_evidence_met": True,
        "reason": "RUN_BUDGET_EXCEEDED",
    }
    assert first["partial_failures"] == ["budget_exhausted"]


def test_budget_error_normalization_is_stable_and_private_values_are_omitted():
    detail = normalize_error(_budget_error())
    assert detail.category is ErrorCategory.BUDGET
    assert detail.code == "RUN_BUDGET_EXCEEDED"
    assert detail.details is None
    assert "96" not in detail.message


def test_standard_policy_keeps_headroom_over_user_supplied_historical_bound():
    """This is a configuration contract, not provider telemetry or a 95% claim."""
    limits = DEFAULT_RUN_BUDGET_POLICY.hard_limits
    assert limits.total_tokens == 3 * 20_000
    assert limits.active_milliseconds == int(2.5 * 360_000)
    assert limits.llm_calls == 96
    assert limits.retrieval_calls == 72


class _State:
    config = {"configurable": {}}

    def __init__(self, values: dict):
        self.values = values


class _BudgetCappedOrchestrator:
    partial_state: dict = {}
    provider_calls = 0

    def __init__(self, *_args, **_kwargs):
        pass

    async def get_state(self):
        return _State(self.partial_state)

    async def astream_research_task(self, *, resume=False):
        del resume
        self.__class__.provider_calls += 1
        if False:  # pragma: no cover - makes this an async generator
            yield {}
        raise _budget_error(self.partial_state)


class _RealBudgetGateOrchestrator:
    provider_calls = 0

    def __init__(self, *_args, **_kwargs):
        pass

    async def get_state(self):
        return _State(_sufficient_state())

    async def astream_research_task(self, *, resume=False):
        del resume
        first = await reserve_call(
            (BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),),
            call_id=None,
        )
        self.__class__.provider_calls += 1
        await settle_call(first, {BudgetResource.LLM_CALLS: 1})
        try:
            await reserve_call(
                (BudgetAmount(resource=BudgetResource.LLM_CALLS, amount=1),),
                call_id=None,
            )
        except BudgetExceededError as exc:
            raise exc.attach_partial_state(_sufficient_state())
        if False:  # pragma: no cover - makes this an async generator
            yield {}


class _CheckpointFallbackOrchestrator:
    entered = asyncio.Event()
    release = asyncio.Event()

    def __init__(self, *_args, **_kwargs):
        pass

    async def get_state(self):
        self.__class__.entered.set()
        await self.__class__.release.wait()
        return _State(_sufficient_state())

    async def astream_research_task(self, *, resume=False):
        del resume
        if False:  # pragma: no cover - makes this an async generator
            yield {}
        raise _budget_error()


@pytest_asyncio.fixture
async def repo(tmp_path: Path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    repository = SQLiteTaskRunRepository(connection)
    try:
        yield repository
    finally:
        await connection.close()


def _records(task_id: str, run_id: str, *, policy=DEFAULT_RUN_BUDGET_POLICY):
    request = ResearchRequest(query="compare A and B", report_format="evidence_first")
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
        budget_policy=policy,
        thread_id=run_id,
        created_at=NOW,
        updated_at=NOW,
    )
    return task, run


async def _wait_done(coordinator: RunCoordinator, run_id: str):
    for _ in range(400):
        if run_id not in coordinator.active_runs:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("coordinator run did not finish")


@pytest.mark.asyncio
async def test_budget_cap_persists_restricted_result_status_and_event_atomically(repo):
    task, run = _records("task-limited", "run-limited")
    await repo.create_task_with_run(task, run)
    _BudgetCappedOrchestrator.partial_state = _sufficient_state()
    _BudgetCappedOrchestrator.provider_calls = 0
    coordinator = RunCoordinator(
        repo,
        object(),
        owner_id="worker",
        orchestrator_factory=_BudgetCappedOrchestrator,
    )
    assert await coordinator.submit(run.run_id, resume=False)
    await _wait_done(coordinator, run.run_id)

    current = await repo.get_task(task.task_id)
    result = await repo.get_run_result(run.run_id)
    events = await repo.list_task_events(task.task_id)
    assert current is not None and current.latest_run is not None
    assert current.task.status is TaskStatus.COMPLETED_WITH_WARNINGS
    assert current.latest_run.status is RunStatus.COMPLETED_WITH_WARNINGS
    assert result is not None
    assert result.snapshot["budget_limited"]["limited"] is True
    assert result.report.startswith("> **Budget-limited report:**")
    assert events[-1].type == "run.completed_with_warnings"
    assert events[-1].public_payload == {"status": "completed_with_warnings"}
    assert _BudgetCappedOrchestrator.provider_calls == 1
    await coordinator.stop()


@pytest.mark.asyncio
async def test_real_sqlite_budget_denial_blocks_dispatch_and_builds_limited_result(repo):
    policy = RunBudgetPolicy(
        policy_version="standard-enforced-v1",
        enforcement_mode=BudgetEnforcementMode.ENFORCED,
        hard_limits=BudgetHardLimits(llm_calls=1),
        price_catalog_version="unpriced-v1",
    )
    task, run = _records("task-real-limit", "run-real-limit", policy=policy)
    await repo.create_task_with_run(task, run)
    _RealBudgetGateOrchestrator.provider_calls = 0
    coordinator = RunCoordinator(
        repo,
        object(),
        owner_id="worker",
        orchestrator_factory=_RealBudgetGateOrchestrator,
    )
    assert await coordinator.submit(run.run_id, resume=False)
    await _wait_done(coordinator, run.run_id)

    current = await repo.get_run(run.run_id)
    result = await repo.get_run_result(run.run_id)
    assert current is not None and current.status is RunStatus.COMPLETED_WITH_WARNINGS
    assert result is not None and result.snapshot["budget_limited"]["limited"] is True
    assert _RealBudgetGateOrchestrator.provider_calls == 1
    row = await (
        await repo._connection.execute(
            "SELECT status, actual_amount FROM budget_ledger "
            "WHERE run_id=? AND resource='llm_calls' "
            "ORDER BY entry_sequence DESC LIMIT 1",
            (run.run_id,),
        )
    ).fetchone()
    assert tuple(row) == ("settled", 1)
    await coordinator.stop()


@pytest.mark.asyncio
async def test_budget_cap_without_minimum_evidence_fails_with_stable_code(repo):
    task, run = _records("task-insufficient", "run-insufficient")
    await repo.create_task_with_run(task, run)
    _BudgetCappedOrchestrator.partial_state = {
        "evidence_chains": _sufficient_state()["evidence_chains"][:2]
    }
    _BudgetCappedOrchestrator.provider_calls = 0
    coordinator = RunCoordinator(
        repo,
        object(),
        owner_id="worker",
        orchestrator_factory=_BudgetCappedOrchestrator,
    )
    assert await coordinator.submit(run.run_id, resume=False)
    await _wait_done(coordinator, run.run_id)

    current = await repo.get_run(run.run_id)
    assert current is not None
    assert current.status is RunStatus.FAILED
    assert current.error_id == "BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE"
    assert await repo.get_run_result(run.run_id) is None
    assert (await repo.list_task_events(task.task_id))[-1].type == "run.failed"
    assert _BudgetCappedOrchestrator.provider_calls == 1
    await coordinator.stop()


@pytest.mark.asyncio
async def test_cancellation_during_restricted_fallback_clears_running_lease(repo):
    task, run = _records("task-limited-cancel", "run-limited-cancel")
    await repo.create_task_with_run(task, run)
    _CheckpointFallbackOrchestrator.entered = asyncio.Event()
    _CheckpointFallbackOrchestrator.release = asyncio.Event()
    coordinator = RunCoordinator(
        repo,
        object(),
        owner_id="worker",
        orchestrator_factory=_CheckpointFallbackOrchestrator,
    )
    assert await coordinator.submit(run.run_id, resume=False)
    await asyncio.wait_for(_CheckpointFallbackOrchestrator.entered.wait(), timeout=1)
    active = coordinator._active[run.run_id]
    await coordinator.cancel_active(run.run_id)
    with pytest.raises(asyncio.CancelledError):
        await active

    current = await repo.get_run(run.run_id)
    assert current is not None
    assert current.status is RunStatus.INTERRUPTED
    assert current.lease_owner is None
    assert current.lease_expires_at is None
    assert await repo.get_run_result(run.run_id) is None
    await coordinator.stop()


@pytest.mark.asyncio
async def test_stale_budget_fallback_cannot_publish_a_restricted_result(repo):
    task, run = _records("task-limited-stale", "run-limited-stale")
    await repo.create_task_with_run(task, run)
    _CheckpointFallbackOrchestrator.entered = asyncio.Event()
    _CheckpointFallbackOrchestrator.release = asyncio.Event()

    class _Clock:
        now = NOW

        def __call__(self):
            return self.now

    clock = _Clock()
    coordinator = RunCoordinator(
        repo,
        object(),
        owner_id="old-worker",
        clock=clock,
        lease_ttl=timedelta(seconds=30),
        heartbeat_interval=timedelta(seconds=10),
        orchestrator_factory=_CheckpointFallbackOrchestrator,
    )
    assert await coordinator.submit(run.run_id, resume=False)
    await asyncio.wait_for(_CheckpointFallbackOrchestrator.entered.wait(), timeout=1)
    clock.now = NOW + timedelta(seconds=31)
    await repo.recover_runs(now=clock.now)
    _CheckpointFallbackOrchestrator.release.set()
    await _wait_done(coordinator, run.run_id)

    current = await repo.get_run(run.run_id)
    assert current is not None
    assert current.status is RunStatus.INTERRUPTED
    assert await repo.get_run_result(run.run_id) is None
    assert all(
        event.type != "run.completed_with_warnings"
        for event in await repo.list_task_events(task.task_id)
    )
    await coordinator.stop()


@pytest.mark.asyncio
async def test_same_run_resume_keeps_frozen_observe_only_policy(repo):
    task, run = _records(
        "task-observe-resume",
        "run-observe-resume",
        policy=STANDARD_OBSERVE_RUN_BUDGET_POLICY,
    )
    await repo.create_task_with_run(task, run)
    grant = await repo.acquire_run_lease(
        run.run_id,
        lease_owner="old-worker",
        lease_ttl=timedelta(seconds=30),
        run_timeout=timedelta(minutes=5),
        now=NOW,
    )
    await repo.add_checkpoint_reference(
        CheckpointReference(
            run_id=run.run_id,
            checkpoint_id="cp-observe",
            state_schema_version=run.manifest.state_schema_version,
            execution_epoch=grant.execution_epoch,
            created_at=NOW,
        ),
        lease_owner="old-worker",
        execution_epoch=grant.execution_epoch,
        now=NOW,
    )
    interrupted = await repo.finalize_run(
        run.run_id,
        lease_owner="old-worker",
        execution_epoch=grant.execution_epoch,
        status=RunStatus.INTERRUPTED,
        now=NOW + timedelta(seconds=1),
    )
    resumed = await TaskService(repo, clock=lambda: NOW + timedelta(seconds=2)).resume(
        task.task_id,
        expected_task_version=interrupted.task.version,
    )
    assert resumed.latest_run is not None
    assert resumed.latest_run.run_id == run.run_id
    assert resumed.latest_run.budget_policy == STANDARD_OBSERVE_RUN_BUDGET_POLICY
