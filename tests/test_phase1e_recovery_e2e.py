from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

import aiosqlite
import httpx
import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deepchoice.contracts.api import ResearchRequest
from deepchoice.persistence import connect_database, run_migrations
from deepchoice.persistence.repository import SQLiteTaskRunRepository
from deepchoice.runtime.coordinator import RunCoordinator
from deepchoice.runtime.lifecycle import RunStatus
from deepchoice.services.tasks import TaskService
from deepchoice.server import app as app_module


class LocalRecoveryOrchestrator:
    """Local workflow exercising coordinator recovery without provider calls."""

    release_second: ClassVar[asyncio.Event]
    initial_calls: ClassVar[int] = 0
    resumed_calls: ClassVar[int] = 0
    seen_resumes: ClassVar[list[bool]] = []
    restored_value: ClassVar[int | None] = None

    def __init__(
        self,
        _task,
        *,
        checkpointer,
        thread_id,
        checkpoint_id=None,
        **_kwargs,
    ) -> None:
        self.checkpointer = checkpointer
        self.thread_id = thread_id
        self.checkpoint_id = checkpoint_id
        self.checkpoint_ns = ""
        self._stored_config: dict | None = None

    @classmethod
    def reset(cls) -> None:
        cls.release_second = asyncio.Event()
        cls.initial_calls = 0
        cls.resumed_calls = 0
        cls.seen_resumes = []
        cls.restored_value = None

    def _config(self, *, pin: bool = False) -> dict:
        configurable = {"thread_id": self.thread_id}
        if pin and self.checkpoint_id:
            configurable["checkpoint_id"] = self.checkpoint_id
        return {"configurable": configurable}

    async def _store(self, checkpoint_id: str, value: int, config: dict) -> None:
        checkpoint = empty_checkpoint()
        checkpoint["id"] = checkpoint_id
        checkpoint["channel_values"] = {"value": value}
        self._stored_config = await self.checkpointer.aput(config, checkpoint, {}, {})

    async def astream_research_task(self, *, resume: bool = False):
        self.seen_resumes.append(resume)
        if resume:
            type(self).resumed_calls += 1
            restored = await self.checkpointer.aget_tuple(self._config(pin=True))
            assert restored is not None
            value = int(restored.checkpoint["channel_values"]["value"])
            type(self).restored_value = value
            await self._store(
                "00000000-0000-0000-0000-000000000002",
                value + 10,
                restored.config,
            )
            yield {"second": {"value": 11}}
            return
        type(self).initial_calls += 1
        await self._store(
            "00000000-0000-0000-0000-000000000001",
            1,
            self._config(),
        )
        yield {"first": {"value": 1}}
        await self.release_second.wait()

    async def get_state(self):
        assert self._stored_config is not None

        class State:
            config = self._stored_config
            values = {"report": "# Recovered durable report", "confidence": "high"}

        return State()


async def _wait_for_event(repository, task_id: str, event_type: str) -> None:
    for _ in range(100):
        if any(
            event.type == event_type
            for event in await repository.list_task_events(task_id)
        ):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"event {event_type!r} was not emitted")


async def _wait_run_done(coordinator: RunCoordinator, repository, task_id: str, run_id: str) -> None:
    for _ in range(100):
        if run_id not in coordinator.active_runs:
            return
        await asyncio.sleep(0.01)
    run = await repository.get_run(run_id)
    if run is not None and run.status is RunStatus.COMPLETED:
        # The task done-callback may be one event-loop turn behind the durable
        # terminal commit under a heavily loaded full-suite run.
        return
    events = [event.type for event in await repository.list_task_events(task_id)]
    raise AssertionError(
        "recovered run did not complete: "
        f"status={run.status if run else None}, events={events}, "
        f"resumes={LocalRecoveryOrchestrator.seen_resumes}, "
        f"calls=({LocalRecoveryOrchestrator.initial_calls}, {LocalRecoveryOrchestrator.resumed_calls})"
    )


@pytest.mark.asyncio
async def test_process_restart_resumes_checkpoint_reference_and_event_history(
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "product.db"
    checkpoint_path = tmp_path / "checkpoints.db"
    LocalRecoveryOrchestrator.reset()

    product_one = await connect_database(product_path)
    checkpoint_one = await aiosqlite.connect(checkpoint_path)
    saver_one = AsyncSqliteSaver(checkpoint_one)
    await saver_one.setup()
    await run_migrations(product_one)
    repository_one = SQLiteTaskRunRepository(product_one)
    created = await TaskService(repository_one).create(
        ResearchRequest(query="local recovery contract")
    )
    assert created.latest_run is not None
    task_id = created.task.task_id
    run_id = created.latest_run.run_id
    coordinator_one = RunCoordinator(
        repository_one,
        saver_one,
        owner_id="before-restart",
        lease_ttl=timedelta(seconds=30),
        heartbeat_interval=timedelta(seconds=1),
        recovery_interval=timedelta(seconds=1),
        orchestrator_factory=LocalRecoveryOrchestrator,
    )
    assert await coordinator_one.submit(run_id, resume=False)
    await _wait_for_event(repository_one, task_id, "run.progress")
    await coordinator_one.stop()
    assert (await repository_one.get_run(run_id)).status is RunStatus.INTERRUPTED
    await product_one.close()
    await checkpoint_one.close()

    LocalRecoveryOrchestrator.release_second.set()
    product_two = await connect_database(product_path)
    checkpoint_two = await aiosqlite.connect(checkpoint_path)
    saver_two = AsyncSqliteSaver(checkpoint_two)
    await saver_two.setup()
    repository_two = SQLiteTaskRunRepository(product_two)
    coordinator_two = RunCoordinator(
        repository_two,
        saver_two,
        owner_id="after-restart",
        lease_ttl=timedelta(seconds=30),
        heartbeat_interval=timedelta(seconds=1),
        recovery_interval=timedelta(seconds=1),
        orchestrator_factory=LocalRecoveryOrchestrator,
    )
    try:
        assert await coordinator_two.start() == (run_id,)
        await _wait_run_done(coordinator_two, repository_two, task_id, run_id)
        assert (await repository_two.get_run(run_id)).status is RunStatus.COMPLETED
        assert LocalRecoveryOrchestrator.seen_resumes == [False, True]
        assert LocalRecoveryOrchestrator.initial_calls == 1
        assert LocalRecoveryOrchestrator.resumed_calls == 1
        assert LocalRecoveryOrchestrator.restored_value == 1
        event_types = [
            event.type for event in await repository_two.list_task_events(task_id)
        ]
        assert event_types == [
            "task.queued",
            "run.started",
            "run.progress",
            "run.interrupted",
            "run.auto_resumed",
            "run.started",
            "run.progress",
            "run.completed",
        ]
        result = await repository_two.get_run_result(run_id)
        assert result is not None
        assert result.report == "# Recovered durable report"

        old_service = getattr(app_module.app.state, "task_service", None)
        old_repository = getattr(app_module.app.state, "task_repository", None)
        app_module.app.state.task_service = TaskService(repository_two)
        app_module.app.state.task_repository = repository_two
        try:
            transport = httpx.ASGITransport(app=app_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                report = await client.get(f"/api/v1/tasks/{task_id}/report")
            assert report.status_code == 200
            assert report.json()["report"] == "# Recovered durable report"
        finally:
            app_module.app.state.task_service = old_service
            app_module.app.state.task_repository = old_repository
    finally:
        await coordinator_two.stop()
        await product_two.close()
        await checkpoint_two.close()
