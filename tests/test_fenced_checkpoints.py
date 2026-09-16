"""Checkpoint write fencing and accepted resume pinning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.contracts.api import ResearchRequest
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.records import CheckpointReference, RunRecord, TaskRecord
from deepchoice.persistence.repository import RunLeaseLostError, SQLiteTaskRunRepository
from deepchoice.runtime.checkpoints import FencedCheckpointSaver
from deepchoice.runtime.lifecycle import RunStatus, TaskStatus


class FakeSaver(BaseCheckpointSaver[Any]):
    def __init__(self) -> None:
        super().__init__()
        self.puts = 0
        self.writes = 0

    async def aput(self, config, checkpoint, metadata, new_versions):
        self.puts += 1
        return {"configurable": {"checkpoint_id": "stored"}}

    async def aput_writes(self, config, writes, task_id, task_path=""):
        self.writes += 1

    def get_next_version(self, current, channel):
        return "delegated-version"


@pytest.mark.asyncio
async def test_fenced_saver_checks_guard_before_each_async_write() -> None:
    delegate = FakeSaver()
    allowed = True
    guard_calls = 0

    async def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if not allowed:
            raise RuntimeError("lease lost")

    saver = FencedCheckpointSaver(delegate, guard, write_namespace="epoch-1")
    config = {"configurable": {"thread_id": "run-1"}}
    assert await saver.aput(config, {}, {}, {}) == {
        "configurable": {"checkpoint_id": "stored", "checkpoint_ns": ""}
    }
    await saver.aput_writes(config, (("channel", "value"),), "task-1")
    assert (guard_calls, delegate.puts, delegate.writes) == (2, 1, 1)

    allowed = False
    with pytest.raises(RuntimeError, match="lease lost"):
        await saver.aput(config, {}, {}, {})
    with pytest.raises(RuntimeError, match="lease lost"):
        await saver.aput_writes(config, (), "task-1")
    assert (guard_calls, delegate.puts, delegate.writes) == (4, 1, 1)
    assert saver.get_next_version(None, None) == "delegated-version"


def test_checkpoint_pin_is_only_added_to_resume_initial_config() -> None:
    orchestrator = ChiefEditorAgent(
        {"query": "compare FastAPI and Flask"},
        thread_id="run-1",
        checkpoint_id="accepted-checkpoint",
    )
    assert orchestrator._make_config() == {
        "configurable": {"thread_id": "run-1"}
    }
    assert orchestrator._make_config(pin_checkpoint=True) == {
        "configurable": {
            "thread_id": "run-1",
            "checkpoint_id": "accepted-checkpoint",
        }
    }


class BlockingWritesSaver:
    def __init__(self, delegate: AsyncSqliteSaver) -> None:
        import asyncio

        self.delegate = delegate
        self.serde = delegate.serde
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def aput_writes(self, *args, **kwargs):
        self.entered.set()
        await self.release.wait()
        return await self.delegate.aput_writes(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)


@pytest.mark.asyncio
async def test_late_old_epoch_writes_are_excluded_from_new_epoch_resume(
    tmp_path: Path,
) -> None:
    import asyncio

    connection = await aiosqlite.connect(tmp_path / "isolated-checkpoints.db")
    delegate = AsyncSqliteSaver(connection)
    await delegate.setup()
    blocking = BlockingWritesSaver(delegate)
    old_owner = True

    async def old_guard() -> None:
        if not old_owner:
            raise RuntimeError("old owner fenced")

    async def new_guard() -> None:
        return None

    try:
        old = FencedCheckpointSaver(
            blocking,
            old_guard,
            write_namespace="epoch-1",
        )
        logical = {"configurable": {"thread_id": "run-1", "checkpoint_ns": ""}}
        checkpoint = empty_checkpoint()
        checkpoint["id"] = "00000000-0000-0000-0000-000000000001"
        accepted = await old.aput(logical, checkpoint, {}, {})

        late = asyncio.create_task(
            old.aput_writes(accepted, (("late", "stale-value"),), "old-task")
        )
        await blocking.entered.wait()
        old_owner = False
        new = FencedCheckpointSaver(
            delegate,
            new_guard,
            read_namespace="epoch-1",
            read_checkpoint_id=checkpoint["id"],
            write_namespace="epoch-2",
        )
        blocking.release.set()
        await late

        resumed = await new.aget_tuple(accepted)
        assert resumed is not None
        assert resumed.config["configurable"]["checkpoint_ns"] == ""
        assert resumed.pending_writes == []

        physical_old = await delegate.aget_tuple(
            {
                "configurable": {
                    "thread_id": "run-1",
                    "checkpoint_ns": "epoch-1",
                    "checkpoint_id": checkpoint["id"],
                }
            }
        )
        assert physical_old is not None
        assert physical_old.pending_writes == [
            ("old-task", "late", "stale-value")
        ]
    finally:
        await connection.close()


class ResumeState(TypedDict):
    value: int


@pytest.mark.asyncio
async def test_real_state_graph_resumes_across_physical_namespaces(
    tmp_path: Path,
) -> None:
    connection = await aiosqlite.connect(tmp_path / "state-graph-checkpoints.db")
    delegate = AsyncSqliteSaver(connection)
    await delegate.setup()

    async def guard() -> None:
        return None

    workflow = StateGraph(ResumeState)
    workflow.add_node("first", lambda state: {"value": state["value"] + 1})
    workflow.add_node("second", lambda state: {"value": state["value"] + 10})
    workflow.set_entry_point("first")
    workflow.add_edge("first", "second")
    workflow.add_edge("second", END)
    config = {"configurable": {"thread_id": "run-graph"}}
    try:
        first_saver = FencedCheckpointSaver(
            delegate, guard, write_namespace="epoch-1"
        )
        first_graph = workflow.compile(
            checkpointer=first_saver, interrupt_after=["first"]
        )
        assert (await first_graph.ainvoke({"value": 0}, config=config))["value"] == 1
        accepted = await first_graph.aget_state(config)
        accepted_id = accepted.config["configurable"]["checkpoint_id"]
        assert accepted.config["configurable"].get("checkpoint_ns", "") == ""

        second_saver = FencedCheckpointSaver(
            delegate,
            guard,
            read_namespace="epoch-1",
            read_checkpoint_id=accepted_id,
            write_namespace="epoch-2",
        )
        second_graph = workflow.compile(
            checkpointer=second_saver, interrupt_after=["first"]
        )
        resumed_config = {
            "configurable": {
                "thread_id": "run-graph",
                "checkpoint_id": accepted_id,
            }
        }
        result = await second_graph.ainvoke(None, config=resumed_config)
        assert result["value"] == 11
        latest = await second_graph.aget_state(config)
        assert latest.values["value"] == 11
        assert latest.config["configurable"].get("checkpoint_ns", "") == ""
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_real_sqlite_saver_rejects_late_write_from_old_epoch(
    tmp_path: Path,
) -> None:
    product_connection = await connect_database(tmp_path / "product.db")
    checkpoint_connection = await aiosqlite.connect(tmp_path / "checkpoints.db")
    try:
        await run_migrations(product_connection)
        repository = SQLiteTaskRunRepository(product_connection)
        request = ResearchRequest(query="compare FastAPI and Flask")
        manifest = build_run_manifest(request.model_dump())
        now = datetime(2026, 1, 1, tzinfo=UTC)
        task = TaskRecord(
            task_id="task-1",
            status=TaskStatus.QUEUED,
            request=request,
            latest_run_id="run-1",
            created_at=now,
            updated_at=now,
        )
        run = RunRecord(
            run_id="run-1",
            task_id="task-1",
            status=RunStatus.QUEUED,
            manifest=manifest,
            budget_policy=DEFAULT_RUN_BUDGET_POLICY,
            thread_id="run-1",
            created_at=now,
            updated_at=now,
        )
        await repository.create_task_with_run(task, run)
        old_grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="old-owner",
            lease_ttl=timedelta(seconds=1),
            run_timeout=timedelta(minutes=1),
            now=now,
        )

        old_guard_now = now

        async def old_guard() -> None:
            await repository.fence_run(
                run.run_id,
                lease_owner="old-owner",
                execution_epoch=old_grant.execution_epoch,
                now=old_guard_now,
            )

        delegate = AsyncSqliteSaver(checkpoint_connection)
        await delegate.setup()
        old_saver = FencedCheckpointSaver(
            delegate, old_guard, write_namespace="epoch-1"
        )
        config = {"configurable": {"thread_id": run.thread_id, "checkpoint_ns": ""}}
        accepted_checkpoint = empty_checkpoint()
        accepted_checkpoint["id"] = "00000000-0000-0000-0000-000000000000"
        await old_saver.aput(config, accepted_checkpoint, {}, {})
        await repository.add_checkpoint_reference(
            CheckpointReference(
                run_id=run.run_id,
                checkpoint_id=accepted_checkpoint["id"],
                state_schema_version=manifest.state_schema_version,
                execution_epoch=old_grant.execution_epoch,
                created_at=now,
            ),
            lease_owner="old-owner",
            execution_epoch=old_grant.execution_epoch,
            now=now,
        )

        old_guard_now = now + timedelta(seconds=2)
        await repository.recover_runs(now=now + timedelta(seconds=2))
        new_grant = await repository.acquire_run_lease(
            run.run_id,
            lease_owner="new-owner",
            lease_ttl=timedelta(seconds=30),
            run_timeout=timedelta(minutes=1),
            now=now + timedelta(seconds=2),
        )

        late_checkpoint = empty_checkpoint()
        late_checkpoint["id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        with pytest.raises(RunLeaseLostError):
            await old_saver.aput(config, late_checkpoint, {}, {})
        latest = await delegate.aget_tuple(
            {"configurable": {"thread_id": run.thread_id, "checkpoint_ns": "epoch-1"}}
        )
        assert latest.checkpoint["id"] == accepted_checkpoint["id"]

        async def new_guard() -> None:
            await repository.fence_run(
                run.run_id,
                lease_owner="new-owner",
                execution_epoch=new_grant.execution_epoch,
                now=now + timedelta(seconds=2),
            )

        current_checkpoint = empty_checkpoint()
        current_checkpoint["id"] = "11111111-1111-1111-1111-111111111111"
        stored = await FencedCheckpointSaver(
            delegate, new_guard, write_namespace="epoch-2"
        ).aput(
            config, current_checkpoint, {}, {}
        )
        assert stored["configurable"]["checkpoint_id"] == current_checkpoint["id"]
        assert (
            await delegate.aget_tuple(
                {
                    "configurable": {
                        "thread_id": run.thread_id,
                        "checkpoint_ns": "epoch-2",
                    }
                }
            )
        ).checkpoint["id"] == current_checkpoint["id"]
    finally:
        await checkpoint_connection.close()
        await product_connection.close()
from deepchoice.budget import DEFAULT_RUN_BUDGET_POLICY
