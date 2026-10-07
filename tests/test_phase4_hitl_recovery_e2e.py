"""Phase 4 durable HITL recovery acceptance with real LangGraph checkpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, TypedDict

import aiosqlite
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from deepchoice.contracts.api import ResearchRequest
from deepchoice.hitl import DECISION_TTL, DecisionResolution
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.repository import (
    DecisionConflictError,
    SQLiteTaskRunRepository,
    TaskVersionConflictError,
)
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus
from deepchoice.services.tasks import TaskService


class _RecoveryState(TypedDict, total=False):
    pre_gate_visits: int
    resolution: dict[str, str]
    report: str


class RealDecisionOrchestrator:
    """Small real StateGraph used to prove interrupt checkpoint recovery."""

    expires_at: ClassVar[datetime]
    pre_gate_calls: ClassVar[int] = 0
    continuation_calls: ClassVar[int] = 0
    constructed_checkpoint_ids: ClassVar[list[str | None]] = []
    seen_resolutions: ClassVar[list[dict[str, str]]] = []

    def __init__(
        self,
        _task,
        *,
        checkpointer,
        thread_id: str,
        checkpoint_id: str | None = None,
        **_kwargs,
    ) -> None:
        self.thread_id = thread_id
        self.checkpoint_id = checkpoint_id
        self.checkpoint_ns = ""
        type(self).constructed_checkpoint_ids.append(checkpoint_id)

        workflow = StateGraph(_RecoveryState)
        workflow.add_node("pre_gate", self._pre_gate)
        workflow.add_node("decision_gate", self._decision_gate)
        workflow.add_node("continuation", self._continuation)
        workflow.add_edge(START, "pre_gate")
        workflow.add_edge("pre_gate", "decision_gate")
        workflow.add_edge("decision_gate", "continuation")
        workflow.add_edge("continuation", END)
        self._graph = workflow.compile(checkpointer=checkpointer)

    @classmethod
    def reset(cls, *, now: datetime) -> None:
        cls.expires_at = now + DECISION_TTL
        cls.pre_gate_calls = 0
        cls.continuation_calls = 0
        cls.constructed_checkpoint_ids = []
        cls.seen_resolutions = []

    @staticmethod
    async def _pre_gate(_state: _RecoveryState) -> _RecoveryState:
        RealDecisionOrchestrator.pre_gate_calls += 1
        return {"pre_gate_visits": 1}

    @staticmethod
    async def _decision_gate(_state: _RecoveryState) -> _RecoveryState:
        resolution = interrupt(
            {
                "decision_id": "decision-recovery-e2e",
                "kind": "evidence-insufficient",
                "reason": "Independent evidence is still insufficient.",
                "gaps": ["A second independent source is missing."],
                "allowed_actions": [
                    "provide_context",
                    "limited_report",
                    "cancel",
                ],
                "expires_at": RealDecisionOrchestrator.expires_at.isoformat(),
            }
        )
        return {"resolution": resolution}

    @staticmethod
    async def _continuation(state: _RecoveryState) -> _RecoveryState:
        RealDecisionOrchestrator.continuation_calls += 1
        resolution = state["resolution"]
        RealDecisionOrchestrator.seen_resolutions.append(resolution)
        return {
            "report": "# Recovered after evidence decision\n\n"
            f"Action: {resolution['action']}"
        }

    def _config(self, *, pin_checkpoint: bool) -> dict:
        configurable = {"thread_id": self.thread_id}
        if pin_checkpoint and self.checkpoint_id is not None:
            configurable["checkpoint_id"] = self.checkpoint_id
        return {"configurable": configurable}

    async def astream_research_task(
        self,
        *,
        resume: bool = False,
        resume_value: dict[str, str] | None = None,
    ):
        graph_input = (
            Command(resume=resume_value)
            if resume and resume_value is not None
            else None if resume else {}
        )
        async for event in self._graph.astream(
            graph_input,
            config=self._config(pin_checkpoint=resume),
            stream_mode="updates",
        ):
            yield event

    async def get_state(self):
        return await self._graph.aget_state(self._config(pin_checkpoint=False))


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def _open_stores(
    product_path: Path,
    checkpoint_path: Path,
    *,
    migrate: bool = False,
):
    product = await connect_database(product_path)
    if migrate:
        await run_migrations(product)
    checkpoint = await aiosqlite.connect(checkpoint_path)
    saver = AsyncSqliteSaver(checkpoint)
    await saver.setup()
    return product, checkpoint, saver, SQLiteTaskRunRepository(product)


def _coordinator(
    repository: SQLiteTaskRunRepository,
    saver: AsyncSqliteSaver,
    *,
    owner_id: str,
    clock: _MutableClock,
) -> RunCoordinator:
    return RunCoordinator(
        repository,
        saver,
        owner_id=owner_id,
        clock=clock,
        lease_ttl=timedelta(minutes=1),
        heartbeat_interval=timedelta(seconds=1),
        run_timeout=timedelta(minutes=30),
        recovery_interval=timedelta(milliseconds=20),
        orchestrator_factory=RealDecisionOrchestrator,
    )


async def _wait_inactive(coordinator: RunCoordinator, run_id: str) -> None:
    try:
        async with asyncio.timeout(10):
            while run_id in coordinator.active_runs:
                await asyncio.sleep(0.01)
    except TimeoutError:
        run = await coordinator.repository.get_run(run_id)
        raise AssertionError(
            f"run {run_id!r} did not become inactive; status={run.status if run else None}"
        ) from None


async def _create_and_pause(
    product_path: Path,
    checkpoint_path: Path,
    *,
    clock: _MutableClock,
):
    product, checkpoint, saver, repository = await _open_stores(
        product_path, checkpoint_path, migrate=True
    )
    created = await TaskService(repository, clock=clock).create(
        ResearchRequest(query="compare two local deployment options")
    )
    assert created.latest_run is not None
    task_id = created.task.task_id
    run_id = created.latest_run.run_id
    coordinator = _coordinator(
        repository, saver, owner_id="before-pause", clock=clock
    )
    assert await coordinator.submit(run_id, resume=False)
    await _wait_inactive(coordinator, run_id)
    waiting = await repository.get_task(task_id)
    decision = await repository.get_latest_decision(task_id)
    assert waiting is not None and waiting.latest_run is not None
    assert waiting.task.status is TaskStatus.WAITING_FOR_INPUT
    assert waiting.latest_run.status is RunStatus.WAITING_FOR_INPUT
    assert decision is not None and decision.status == "pending"
    await coordinator.stop()
    await product.close()
    await checkpoint.close()
    return task_id, run_id, decision


@pytest.mark.asyncio
async def test_pending_decision_survives_restart_without_auto_resume(
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.db"
    checkpoint_path = tmp_path / "checkpoints.db"
    clock = _MutableClock(datetime(2026, 9, 15, tzinfo=UTC))
    RealDecisionOrchestrator.reset(now=clock.now)
    task_id, run_id, _decision = await _create_and_pause(
        product_path, checkpoint_path, clock=clock
    )

    product, checkpoint, saver, repository = await _open_stores(
        product_path, checkpoint_path
    )
    coordinator = _coordinator(
        repository, saver, owner_id="pending-restart", clock=clock
    )
    try:
        assert await coordinator.start() == ()
        await asyncio.sleep(0.06)
        current = await repository.get_task(task_id)
        decision = await repository.get_latest_decision(task_id)
        assert current is not None and current.latest_run is not None
        assert current.task.status is TaskStatus.WAITING_FOR_INPUT
        assert current.latest_run.status is RunStatus.WAITING_FOR_INPUT
        assert decision is not None and decision.status == "pending"
        assert coordinator.active_runs == ()
        assert RealDecisionOrchestrator.pre_gate_calls == 1
        assert RealDecisionOrchestrator.continuation_calls == 0
        assert RealDecisionOrchestrator.constructed_checkpoint_ids == [None]
        assert current.latest_run.run_id == run_id

        assert current.task.version > 0
        with pytest.raises(TaskVersionConflictError):
            await repository.resolve_decision(
                task_id,
                decision.decision_id,
                DecisionResolution(action="limited_report"),
                expected_task_version=current.task.version - 1,
                now=clock.now,
            )
        after_conflict = await repository.get_task(task_id)
        pending = await repository.get_latest_decision(task_id)
        assert after_conflict is not None and after_conflict.latest_run is not None
        assert after_conflict.task.status is TaskStatus.WAITING_FOR_INPUT
        assert after_conflict.latest_run.status is RunStatus.WAITING_FOR_INPUT
        assert pending is not None and pending.status == "pending"
        assert RealDecisionOrchestrator.continuation_calls == 0
    finally:
        await coordinator.stop()
        await product.close()
        await checkpoint.close()


@pytest.mark.asyncio
async def test_resolution_wakeup_loss_recovers_bound_checkpoint_exactly_once(
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.db"
    checkpoint_path = tmp_path / "checkpoints.db"
    clock = _MutableClock(datetime(2026, 9, 15, tzinfo=UTC))
    RealDecisionOrchestrator.reset(now=clock.now)
    task_id, run_id, paused_decision = await _create_and_pause(
        product_path, checkpoint_path, clock=clock
    )
    resolution = DecisionResolution(
        action="provide_context",
        supplemental_input="The deployment must remain fully offline.",
    )

    # Resolve durably, then lose the in-process wakeup before any coordinator
    # can submit the queued run.
    product, checkpoint, _saver, repository = await _open_stores(
        product_path, checkpoint_path
    )
    waiting = await repository.get_task(task_id)
    assert waiting is not None
    resolved = await repository.resolve_decision(
        task_id,
        paused_decision.decision_id,
        resolution,
        expected_task_version=waiting.task.version,
        now=clock.now,
    )
    assert not resolved.replayed
    await product.close()
    await checkpoint.close()

    product, checkpoint, saver, repository = await _open_stores(
        product_path, checkpoint_path
    )
    coordinator = _coordinator(
        repository, saver, owner_id="resolved-restart", clock=clock
    )
    try:
        assert await coordinator.start() == (run_id,)
        await _wait_inactive(coordinator, run_id)
        completed = await repository.get_task(task_id)
        result = await repository.get_run_result(run_id)
        assert completed is not None and completed.latest_run is not None
        assert completed.task.status is TaskStatus.COMPLETED
        assert completed.latest_run.status is RunStatus.COMPLETED
        assert completed.latest_run.run_id == run_id
        assert result is not None
        assert result.report == (
            "# Recovered after evidence decision\n\nAction: provide_context"
        )
        assert RealDecisionOrchestrator.pre_gate_calls == 1
        assert RealDecisionOrchestrator.continuation_calls == 1
        assert RealDecisionOrchestrator.constructed_checkpoint_ids == [
            None,
            paused_decision.checkpoint_id,
        ]
        assert RealDecisionOrchestrator.seen_resolutions == [
            resolution.model_dump(mode="json", exclude_none=True)
        ]
        assert await repository.recover_runs(now=clock.now) == ()

        replay = await repository.resolve_decision(
            task_id,
            paused_decision.decision_id,
            resolution,
            expected_task_version=0,
            now=clock.now,
        )
        assert replay.replayed
        with pytest.raises(DecisionConflictError):
            await repository.resolve_decision(
                task_id,
                paused_decision.decision_id,
                DecisionResolution(action="limited_report"),
                expected_task_version=replay.task.task.version,
                now=clock.now,
            )
        assert RealDecisionOrchestrator.continuation_calls == 1
    finally:
        await coordinator.stop()
        await product.close()
        await checkpoint.close()


@pytest.mark.asyncio
async def test_cancelled_decision_never_resumes_graph(tmp_path: Path) -> None:
    product_path = tmp_path / "product.db"
    checkpoint_path = tmp_path / "checkpoints.db"
    clock = _MutableClock(datetime(2026, 9, 15, tzinfo=UTC))
    RealDecisionOrchestrator.reset(now=clock.now)
    task_id, run_id, paused_decision = await _create_and_pause(
        product_path, checkpoint_path, clock=clock
    )

    product, checkpoint, saver, repository = await _open_stores(
        product_path, checkpoint_path
    )
    waiting = await repository.get_task(task_id)
    assert waiting is not None
    await repository.resolve_decision(
        task_id,
        paused_decision.decision_id,
        DecisionResolution(action="cancel"),
        expected_task_version=waiting.task.version,
        now=clock.now,
    )
    coordinator = _coordinator(
        repository, saver, owner_id="cancel-restart", clock=clock
    )
    try:
        assert await coordinator.start() == ()
        current = await repository.get_task(task_id)
        assert current is not None and current.latest_run is not None
        assert current.task.status is TaskStatus.CANCELLED
        assert current.latest_run.status is RunStatus.CANCELLED
        assert current.latest_run.run_id == run_id
        assert RealDecisionOrchestrator.pre_gate_calls == 1
        assert RealDecisionOrchestrator.continuation_calls == 0
        assert RealDecisionOrchestrator.constructed_checkpoint_ids == [None]
    finally:
        await coordinator.stop()
        await product.close()
        await checkpoint.close()


@pytest.mark.asyncio
async def test_expiry_boundary_cancels_without_resuming_graph(tmp_path: Path) -> None:
    product_path = tmp_path / "product.db"
    checkpoint_path = tmp_path / "checkpoints.db"
    clock = _MutableClock(datetime(2026, 9, 15, tzinfo=UTC))
    RealDecisionOrchestrator.reset(now=clock.now)
    task_id, run_id, paused_decision = await _create_and_pause(
        product_path, checkpoint_path, clock=clock
    )
    clock.now = paused_decision.expires_at

    product, checkpoint, saver, repository = await _open_stores(
        product_path, checkpoint_path
    )
    coordinator = _coordinator(
        repository, saver, owner_id="expiry-restart", clock=clock
    )
    try:
        assert await coordinator.start() == ()
        current = await repository.get_task(task_id)
        decision = await repository.get_latest_decision(task_id)
        assert current is not None and current.latest_run is not None
        assert current.task.status is TaskStatus.CANCELLED
        assert current.latest_run.status is RunStatus.CANCELLED
        assert current.latest_run.run_id == run_id
        assert decision is not None and decision.status == "expired"
        assert RealDecisionOrchestrator.pre_gate_calls == 1
        assert RealDecisionOrchestrator.continuation_calls == 0
        assert RealDecisionOrchestrator.constructed_checkpoint_ids == [None]
        assert await repository.recover_runs(
            now=clock.now + timedelta(seconds=1)
        ) == ()
        event_types = [
            event.type for event in await repository.list_task_events(task_id)
        ]
        assert event_types.count("decision.expired") == 1
    finally:
        await coordinator.stop()
        await product.close()
        await checkpoint.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["provide_context", "limited_report"])
async def test_default_reviewed_graph_pauses_and_resumes_without_replaying_review(tmp_path, monkeypatch, action):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from copy import deepcopy
    from tests.test_self_review import make_state, reviewed, revision, CORRECTED, BAD
    from deepchoice.agents.orchestrator import ChiefEditorAgent
    from deepchoice.agents import self_reviewer

    fixture = make_state()
    answer = reviewed([revision(), {"analysis_id": "A2", "action": "keep"}])
    answer.update(confidence="low", knowledge_gaps=["PRIVATE_ADDITIONAL_CONTEXT", "PRIVATE_SOURCE_BODY"])
    model = AsyncMock(return_value=answer)
    monkeypatch.setattr(self_reviewer, "call_model", model)
    async def noop(_state): return {}
    async def cited(_state):
        return {key: deepcopy(fixture[key]) for key in ("final_recommendation", "evidence_chains", "citation_verification")}
    class ReviewedOrchestrator(ChiefEditorAgent):
        def _initialize_agents(self):
            agents = super()._initialize_agents()
            for key in ("query_analyzer", "query_adapter", "multi_retriever", "source_evaluator",
                        "conflict_detector", "evidence_chain", "conclusion_synthesizer"):
                agents[key] = SimpleNamespace(run=noop)
            agents["citation_validator"] = SimpleNamespace(run=cited)
            return agents
    clock = _MutableClock(datetime.now(UTC))
    product_path, checkpoint_path = tmp_path / "product.db", tmp_path / "checkpoints.db"
    def coordinator(repository, saver, owner):
        return RunCoordinator(repository, saver, owner_id=owner, clock=clock,
                              lease_ttl=timedelta(minutes=1), heartbeat_interval=timedelta(seconds=1),
                              recovery_interval=timedelta(seconds=10), orchestrator_factory=ReviewedOrchestrator)
    product, checkpoint, saver, repository = await _open_stores(product_path, checkpoint_path, migrate=True)
    active = coordinator(repository, saver, "before-review-pause")
    try:
        created = await TaskService(repository, clock=clock).create(ResearchRequest(**fixture["task"]))
        task_id, run_id = created.task.task_id, created.latest_run.run_id
        assert await active.submit(run_id, resume=False)
        await _wait_inactive(active, run_id)
        waiting = await repository.get_task(task_id)
        decision = await repository.get_latest_decision(task_id)
        assert waiting.task.status is TaskStatus.WAITING_FOR_INPUT
        assert decision is not None and "PRIVATE_SOURCE_BODY" not in str(decision.gaps)
        model.assert_awaited_once()
    finally:
        await active.stop()
        await product.close()
        await checkpoint.close()
    product, checkpoint, saver, repository = await _open_stores(product_path, checkpoint_path)
    active = coordinator(repository, saver, "after-review-pause")
    try:
        assert await active.start() == ()
        await asyncio.sleep(0.06)
        model.assert_awaited_once()  # A pending restart never replays the reviewer.
        waiting = await repository.get_task(task_id)
        resolution = DecisionResolution(action=action, **({"supplemental_input": "PRIVATE_ADDITIONAL_CONTEXT"} if action == "provide_context" else {}))
        resolved = await repository.resolve_decision(task_id, decision.decision_id, resolution,
            expected_task_version=waiting.task.version, now=clock.now)
        assert not resolved.replayed
        assert await active.submit(run_id, resume=True)
        await _wait_inactive(active, run_id)
        completed = await repository.get_task(task_id)
        result = await repository.get_run_result(run_id)
        assert completed.task.status is (TaskStatus.COMPLETED if action == "provide_context" else TaskStatus.COMPLETED_WITH_WARNINGS) and result is not None
        assert model.await_count == (2 if action == "provide_context" else 1)
        assert BAD not in result.report
        assert "PRIVATE_ADDITIONAL_CONTEXT" not in str(result)
        assert "PRIVATE_SOURCE_BODY" not in str(result)
        if action == "provide_context":
            assert CORRECTED in result.report
            assert "PRIVATE_ADDITIONAL_CONTEXT" in model.await_args.args[0][1]["content"]
        else:
            assert "Evidence-limited report" in result.report
        replay = await repository.resolve_decision(task_id, decision.decision_id, resolution,
            expected_task_version=0, now=clock.now)
        assert replay.replayed
        assert model.await_count == (2 if action == "provide_context" else 1)
    finally:
        await active.stop()
        await product.close()
        await checkpoint.close()


@pytest.mark.asyncio
async def test_actual_gate_checkpoint_uses_shared_safe_structural_gaps(tmp_path, monkeypatch):
    from deepchoice.agents import evidence_decision_gate as gate
    monkeypatch.setattr(gate, "get_run_context", lambda: object())
    initial = {
        "evidence_chains": [{"conclusion": f"Finding {index}", "sources": [{
            "url": f"https://same.example/{index}", "title": "Source",
            "snippet": "Usable evidence", "score": 8}], "disputed": False} for index in range(3)],
        "conflicts": [], "knowledge_gaps": ["PRIVATE_SUPPLEMENTAL_SOURCE"],
        "final_recommendation": {"decision_basis_version": "constraint-aware-v1", "winner": "context_dependent"},
    }
    workflow = StateGraph(dict)
    workflow.add_node("evidence_gate", gate.EvidenceDecisionGateAgent().run)
    workflow.add_edge(START, "evidence_gate")
    workflow.add_edge("evidence_gate", END)
    config = {"configurable": {"thread_id": "actual-gaps"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "actual-gate-checkpoints.db")) as saver:
        graph = workflow.compile(checkpointer=saver)
        paused = await graph.ainvoke(initial, config)
        payload = paused["__interrupt__"][0].value
        assert payload["gaps"] == [
            "Fewer than 2 distinct valid HTTP(S) hostnames are available in usable evidence.",
            "Additional unresolved evidence or reasoning gaps were reported."]
        assert payload["allowed_actions"] == ["provide_context", "limited_report", "cancel"]
        assert "PRIVATE_SUPPLEMENTAL_SOURCE" not in str(payload)
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("evidence_gate",)
        continued = await graph.ainvoke(Command(resume={"action": "provide_context",
                                                       "supplemental_input": "Additional private context"}), config)
        assert continued["_evidence_decision_route"] == "provide_context"
        assert continued["_supplemental_input"] == "Additional private context"
        assert continued["_evidence_decision_gate_seen"] is True
        assert (await graph.aget_state(config)).next == ()
