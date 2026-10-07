from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from deepchoice.agents.evidence_decision_gate import _public_gaps, should_request_evidence_decision
from deepchoice.budget.limited import minimum_evidence_gaps, minimum_evidence_is_met
from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.hitl import DECISION_TTL, DecisionPause, DecisionResolution
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import CheckpointReference, RunRecord, TaskRecord
from deepchoice.persistence.repository import (
    CheckpointNotAvailableError,
    DecisionConflictError,
    RepositoryOperationError,
    RunLeaseLostError,
    SQLiteTaskRunRepository,
)
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    connection = await connect_database(tmp_path / "hitl.db")
    await run_migrations(connection)
    repo = SQLiteTaskRunRepository(connection)
    try:
        yield repo
    finally:
        await connection.close()


async def _running_with_checkpoint(repository, *, task_id="task-1", run_id="run-1", manifest=None):
    request = ResearchRequest(query="compare FastAPI and Flask")
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
        manifest=manifest or build_run_manifest(request.model_dump()),
        budget_policy=DEFAULT_RUN_BUDGET_POLICY,
        thread_id=run_id,
        created_at=NOW,
        updated_at=NOW,
    )
    await repository.create_task_with_run(task, run)
    grant = await repository.acquire_run_lease(
        run_id,
        lease_owner="worker-a",
        lease_ttl=timedelta(minutes=1),
        run_timeout=timedelta(minutes=30),
        now=NOW,
    )
    reference = CheckpointReference(
        run_id=run_id,
        checkpoint_ns="",
        storage_checkpoint_ns="deepchoice-execution-1",
        checkpoint_id="checkpoint-1",
        node="__interrupt__",
        state_schema_version=run.manifest.state_schema_version,
        execution_epoch=grant.execution_epoch,
        created_at=NOW + timedelta(seconds=1),
    )
    await repository.add_checkpoint_reference(
        reference,
        lease_owner="worker-a",
        execution_epoch=grant.execution_epoch,
        now=NOW + timedelta(seconds=1),
    )
    return task, run, grant, reference


def _pause(decision_id="decision-1") -> DecisionPause:
    return DecisionPause(
        decision_id=decision_id,
        reason="Evidence is structurally insufficient.",
        gaps=("Missing independent evidence.",),
    )


async def _paused(repository):
    task, run, grant, reference = await _running_with_checkpoint(repository)
    decision = await repository.pause_for_decision(
        _pause(),
        reference,
        lease_owner="worker-a",
        execution_epoch=grant.execution_epoch,
        now=NOW + timedelta(seconds=2),
    )
    return task, run, grant, reference, decision


@pytest.mark.asyncio
async def test_pause_is_fenced_checkpoint_bound_and_atomic(repository):
    _, _, grant, reference = await _running_with_checkpoint(repository)
    decision = await repository.pause_for_decision(
        _pause(), reference, lease_owner="worker-a",
        execution_epoch=grant.execution_epoch, now=NOW + timedelta(seconds=2)
    )
    current = await repository.get_task("task-1")
    assert current.task.status is TaskStatus.WAITING_FOR_INPUT
    assert current.latest_run.status is RunStatus.WAITING_FOR_INPUT
    assert current.latest_run.lease_owner is None
    assert decision.expires_at == NOW + timedelta(seconds=2) + DECISION_TTL
    event = (await repository.list_task_events("task-1"))[-1]
    assert event.type == "decision.required"
    assert "checkpoint" not in str(event.public_payload).lower()
    assert "epoch" not in str(event.public_payload).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["provide_context", "limited_report"])
@pytest.mark.parametrize("invalid_identity", [False, True])
async def test_service_rejects_incompatible_decision_without_consuming_it(repository, action, invalid_identity):
    from deepchoice.contracts.errors import DeepChoiceError
    from deepchoice.contracts.manifest import _expected_manifest_id
    from deepchoice.services.tasks import TaskService

    historical = build_run_manifest({"query": "compare FastAPI and Flask"})
    qwen = historical.models[0].model_copy(update={
        "tier": "qwen-flash", "provider": "dashscope", "model": "qwen3.8-flash",
        "extra_body_json": '{"enable_thinking":false}',
    })
    historical = historical.model_copy(update={"models": (*historical.models, qwen)})
    historical = historical.model_copy(update={
        "manifest_id": "0" * 64 if invalid_identity else _expected_manifest_id(historical),
    })
    _, _, grant, reference = await _running_with_checkpoint(repository, manifest=historical)
    decision = await repository.pause_for_decision(
        _pause(), reference, lease_owner="worker-a", execution_epoch=grant.execution_epoch,
        now=NOW + timedelta(seconds=2),
    )
    before = await repository.get_task("task-1")
    events = await repository.list_task_events("task-1")
    service = TaskService(repository, clock=lambda: NOW + timedelta(minutes=1))
    with pytest.raises(DeepChoiceError) as caught:
        await service.resolve_decision(
            "task-1", decision.decision_id,
            DecisionResolution(action=action, supplemental_input="Private extra context" if action == "provide_context" else None),
            expected_task_version=before.task.version,
        )
    assert caught.value.error_detail.code == (
        "RUN_MANIFEST_ID_MISMATCH" if invalid_identity else "RUN_MANIFEST_INCOMPATIBLE"
    )
    assert await repository.get_task("task-1") == before
    assert await repository.get_latest_decision("task-1") == decision
    assert await repository.list_task_events("task-1") == events
    cancelled = await service.resolve_decision(
        "task-1", decision.decision_id, DecisionResolution(action="cancel"),
        expected_task_version=before.task.version,
    )
    assert cancelled.task.task.status is TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_service_resolution_replay_survives_runtime_change(repository, monkeypatch):
    from deepchoice.services.tasks import TaskService

    *_, decision = await _paused(repository)
    service = TaskService(repository, clock=lambda: NOW + timedelta(minutes=1))
    resolution = DecisionResolution(action="limited_report")
    await service.resolve_decision("task-1", decision.decision_id, resolution, expected_task_version=2)

    def forbidden(*args):
        raise AssertionError("An idempotent replay must not revalidate the runtime")

    monkeypatch.setattr("deepchoice.services.tasks.ensure_run_manifest_compatible", forbidden)
    replay = await service.resolve_decision("task-1", decision.decision_id, resolution, expected_task_version=2)
    assert replay.replayed
    assert replay.task.task.status is TaskStatus.QUEUED


@pytest.mark.asyncio
async def test_pause_rejects_stale_lease_and_unaccepted_checkpoint_without_changes(repository):
    _, _, grant, reference = await _running_with_checkpoint(repository)
    bad = reference.model_copy(update={"checkpoint_id": "missing"})
    with pytest.raises(CheckpointNotAvailableError):
        await repository.pause_for_decision(
            _pause(), bad, lease_owner="worker-a",
            execution_epoch=grant.execution_epoch, now=NOW + timedelta(seconds=2)
        )
    with pytest.raises(RunLeaseLostError):
        await repository.pause_for_decision(
            _pause(), reference, lease_owner="worker-b",
            execution_epoch=grant.execution_epoch, now=NOW + timedelta(seconds=2)
        )
    current = await repository.get_task("task-1")
    assert current.task.status is TaskStatus.RUNNING
    assert await repository.get_latest_decision("task-1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["provide_context", "limited_report", "cancel"])
async def test_three_resolution_actions(repository, action):
    *_, decision = await _paused(repository)
    resolution = DecisionResolution(
        action=action,
        supplemental_input="We require offline deployment." if action == "provide_context" else None,
    )
    result = await repository.resolve_decision(
        "task-1", decision.decision_id, resolution,
        expected_task_version=2, now=NOW + timedelta(minutes=1)
    )
    expected = TaskStatus.CANCELLED if action == "cancel" else TaskStatus.QUEUED
    assert result.task.task.status is expected
    assert result.task.latest_run.status.value == expected.value
    assert result.decision.status == ("cancelled" if action == "cancel" else "resolved")
    if action != "cancel":
        bound = await repository.get_resolved_decision_for_checkpoint(
            (await repository.get_latest_checkpoint_reference("run-1"))
        )
        assert bound.resolution == resolution


@pytest.mark.asyncio
async def test_maximum_multibyte_supplement_is_persisted(repository):
    *_, decision = await _paused(repository)
    supplemental_input = "界" * 4_000
    result = await repository.resolve_decision(
        "task-1",
        decision.decision_id,
        DecisionResolution(
            action="provide_context", supplemental_input=supplemental_input
        ),
        expected_task_version=2,
        now=NOW + timedelta(minutes=1),
    )
    assert result.decision.resolution is not None
    assert result.decision.resolution.supplemental_input == supplemental_input


@pytest.mark.asyncio
async def test_same_body_replay_ignores_new_task_version_but_different_body_conflicts(repository):
    *_, decision = await _paused(repository)
    resolution = DecisionResolution(action="limited_report")
    first = await repository.resolve_decision(
        "task-1", decision.decision_id, resolution,
        expected_task_version=2, now=NOW + timedelta(minutes=1)
    )
    replay = await repository.resolve_decision(
        "task-1", decision.decision_id, resolution,
        expected_task_version=0, now=NOW + timedelta(minutes=2)
    )
    assert replay.replayed is True
    assert replay.task.task.version == first.task.task.version
    with pytest.raises(DecisionConflictError):
        await repository.resolve_decision(
            "task-1", decision.decision_id, DecisionResolution(action="cancel"),
            expected_task_version=first.task.task.version, now=NOW + timedelta(minutes=2)
        )
    assert [e.type for e in await repository.list_task_events("task-1")].count("decision.resolved") == 1


@pytest.mark.asyncio
async def test_concurrent_different_resolutions_have_one_winner(repository):
    *_, decision = await _paused(repository)
    results = await asyncio.gather(
        repository.resolve_decision(
            "task-1", decision.decision_id, DecisionResolution(action="limited_report"),
            expected_task_version=2, now=NOW + timedelta(minutes=1)
        ),
        repository.resolve_decision(
            "task-1", decision.decision_id, DecisionResolution(action="cancel"),
            expected_task_version=2, now=NOW + timedelta(minutes=1)
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, DecisionConflictError) for item in results) == 1


@pytest.mark.asyncio
async def test_resolution_event_failure_rolls_back_decision_task_and_run(
    repository, monkeypatch
):
    *_, decision = await _paused(repository)
    original = repository._append_event_unlocked

    async def fail_resolution_event(**kwargs):
        if kwargs.get("event_type") == "decision.resolved":
            raise RuntimeError("injected event write failure")
        return await original(**kwargs)

    monkeypatch.setattr(repository, "_append_event_unlocked", fail_resolution_event)
    with pytest.raises(RepositoryOperationError):
        await repository.resolve_decision(
            "task-1",
            decision.decision_id,
            DecisionResolution(action="limited_report"),
            expected_task_version=2,
            now=NOW + timedelta(minutes=1),
        )

    current = await repository.get_task("task-1")
    stored = await repository.get_latest_decision("task-1")
    assert current.task.status is TaskStatus.WAITING_FOR_INPUT
    assert current.latest_run.status is RunStatus.WAITING_FOR_INPUT
    assert stored.status == "pending"
    assert stored.resolution is None
    assert "decision.resolved" not in {
        event.type for event in await repository.list_task_events("task-1")
    }


@pytest.mark.asyncio
async def test_expiry_boundary_is_cancelled_by_recovery_and_waiting_is_not_queued(repository):
    *_, decision = await _paused(repository)
    assert await repository.recover_runs(now=decision.expires_at - timedelta(microseconds=1)) == ()
    recovered = await repository.recover_runs(now=decision.expires_at)
    assert recovered == ()
    current = await repository.get_task("task-1")
    assert current.task.status is TaskStatus.CANCELLED
    assert (await repository.get_latest_decision("task-1")).status == "expired"
    assert (await repository.list_task_events("task-1"))[-1].type == "decision.expired"


@pytest.mark.asyncio
async def test_regular_cancel_resolves_pending_decision_in_same_transaction(repository):
    await _paused(repository)
    cancelled = await repository.cancel_task("task-1", updated_at=NOW + timedelta(minutes=1))
    assert cancelled.task.status is TaskStatus.CANCELLED
    decision = await repository.get_latest_decision("task-1")
    assert decision.status == "cancelled"
    assert decision.resolution.action == "cancel"


def _uncertain_state(*, enough: bool = False, ranked: int = 2) -> dict:
    chains = []
    count = 3 if enough else 1
    for index in range(count):
        chains.append({
            "conclusion": f"finding-{index}",
            "evidence_strength": "moderate",
            "disputed": False,
            "sources": [{
                "url": f"https://source{index}.example/item",
                "title": "source",
                "snippet": "evidence",
                "score": 7,
            }],
        })
    return {
        "evidence_chains": chains,
        "conflicts": [],
        "final_recommendation": {
            "winner": "context_dependent",
            "confidence": "low",
            "ranked_options": [
                {"name": f"option-{index}", "constraint_fit": "low"}
                for index in range(ranked)
            ],
        },
    }


def test_gate_requires_structural_insufficiency_and_direction_uncertainty_once():
    assert should_request_evidence_decision(_uncertain_state()) is True
    assert should_request_evidence_decision(_uncertain_state(enough=True)) is False
    assert should_request_evidence_decision(_uncertain_state(ranked=1)) is False
    seen = _uncertain_state()
    seen["_evidence_decision_gate_seen"] = True
    assert should_request_evidence_decision(seen) is False


_CHAIN_GAP = "Fewer than 3 non-disputed usable evidence chains are available."
_HOST_GAP = "Fewer than 2 distinct valid HTTP(S) hostnames are available in usable evidence."
_STRENGTH_GAP = "No usable evidence chain has moderate or strong evidence strength."


@pytest.mark.parametrize("variant, expected", [
    ("same-host", (_HOST_GAP,)),
    ("idna-host", (_HOST_GAP,)),
    ("weak-only", (_STRENGTH_GAP,)),
    ("canonical-duplicate", (_CHAIN_GAP,)),
    ("invalid-url", (_CHAIN_GAP,)),
    ("disputed", (_CHAIN_GAP,)),
    ("navigation", (_CHAIN_GAP,)),
    ("empty", (_CHAIN_GAP, _HOST_GAP, _STRENGTH_GAP)),
    ("sufficient", ()),
])
def test_public_structural_gaps_match_actual_admission(variant, expected):
    from copy import deepcopy
    state = _uncertain_state(enough=True)
    chains = state["evidence_chains"]
    if variant in {"same-host", "idna-host", "canonical-duplicate"}:
        urls = {
            "same-host": ["https://DOCS.example./a", "https://docs.example:443/b", "http://docs.example/c"],
            "idna-host": ["https://bücher.example/a", "https://xn--bcher-kva.example/b", "https://BÜCHER.example./c"],
            "canonical-duplicate": ["https://source0.example/a", "https://SOURCE0.example.:443/a", "https://source2.example/c"],
        }[variant]
        for chain, url in zip(chains, urls):
            chain["sources"][0]["url"] = url
    elif variant == "weak-only":
        for chain in chains:
            chain["evidence_strength"] = "strong"  # Untrusted label cannot replace source score.
            chain["sources"][0]["score"] = 5
    elif variant == "invalid-url":
        chains[0]["sources"][0]["url"] = "https://user:password@source0.example/a"
    elif variant == "disputed":
        state["conflicts"] = [{"source_a": {"url": chains[0]["sources"][0]["url"]},
                               "source_b": {"url": "https://other.example/dispute"}}]
    elif variant == "navigation":
        chains[0]["sources"][0]["snippet"] = "Official documentation site for source0"
    elif variant == "empty":
        state["evidence_chains"] = []
    original = deepcopy(state)
    assert minimum_evidence_gaps(state) == expected
    assert _public_gaps(state) == expected
    assert minimum_evidence_is_met(state) is (not expected)
    assert should_request_evidence_decision(state) is bool(expected)
    assert state == original


@pytest.mark.parametrize("quality_signals", [[], [{"agent": "self_reviewer"}], None])
def test_public_gaps_keep_structural_reasons_and_hide_raw_state(quality_signals):
    state = _uncertain_state(enough=True)
    for index, chain in enumerate(state["evidence_chains"]):
        chain["sources"][0]["url"] = f"https://same.example/{index}"
    state["knowledge_gaps"] = [f"PRIVATE_SUPPLEMENTAL_SOURCE_{index}" for index in range(20)]
    state["quality_signals"] = quality_signals
    state["citation_verification"] = {"status_counts": {"unsupported": 1, "unknown": 1}}
    gaps = _public_gaps(state)
    assert gaps[0] == _HOST_GAP and len(gaps) == 3
    assert "PRIVATE_SUPPLEMENTAL_SOURCE" not in str(gaps)
    assert "Additional unresolved evidence or reasoning gaps were reported." in gaps
    assert "One or more decision-critical citations remain unsupported or unknown." in gaps


def test_nonstructural_gaps_do_not_change_budget_or_hitl_admission():
    state = _uncertain_state(enough=True)
    state["knowledge_gaps"] = ["PRIVATE_CONTENT"]
    state["citation_verification"] = {"status_counts": {"unknown": 2}}
    assert len(_public_gaps(state)) == 2
    assert minimum_evidence_is_met(state)
    assert not should_request_evidence_decision(state)


@pytest.mark.parametrize("bad_count", ["invalid", None, -1, {}, True, 1.5])
def test_malformed_citation_counts_degrade_only_the_public_notice(bad_count):
    state = _uncertain_state(enough=True)
    state["citation_verification"] = {"status_counts": {"unsupported": bad_count, "unknown": 0}}
    assert _public_gaps(state) == ("Citation status information is unavailable.",)
    assert minimum_evidence_is_met(state)
    assert not should_request_evidence_decision(state)


@pytest.mark.parametrize("counts", [None, {}, {"unknown": 0}, [], "invalid"])
def test_missing_or_invalid_citation_counts_remain_unavailable(counts):
    state = _uncertain_state(enough=True)
    state["citation_verification"] = {"status_counts": counts}
    assert _public_gaps(state) == ("Citation status information is unavailable.",)
    assert minimum_evidence_is_met(state)
    assert not should_request_evidence_decision(state)
