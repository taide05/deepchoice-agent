"""Durable, fenced execution coordination for persisted research runs."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.contracts.errors import normalize_error
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence.records import (
    CheckpointReference,
    RunRecord,
    TaskWithRun,
)
from deepchoice.persistence.repository import (
    RunLeaseLostError,
    SQLiteTaskRunRepository,
)
from deepchoice.runtime.checkpoints import FencedCheckpointSaver
from deepchoice.runtime.lifecycle import RunStatus


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _execution_checkpoint_namespace(execution_epoch: int) -> str:
    """Return an internal namespace never exposed to the root StateGraph."""

    return f"deepchoice-execution-{execution_epoch}"


async def _settle_shielded(task: asyncio.Task[Any]) -> Any:
    """Wait for an authority-changing operation despite repeated cancellation.

    The caller must still propagate its original ``CancelledError`` after this
    bounded operation settles.  Shielding avoids the ambiguous state where the
    SQLite worker commits a lease after cancellation has already unwound the
    coordinator runner.
    """

    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class RunCoordinator:
    """Own local runner tasks while SQLite remains the execution authority."""

    def __init__(
        self,
        repository: SQLiteTaskRunRepository,
        checkpointer: Any,
        *,
        enabled: bool = True,
        lease_ttl: timedelta = timedelta(seconds=30),
        heartbeat_interval: timedelta = timedelta(seconds=10),
        run_timeout: timedelta = timedelta(seconds=1800),
        recovery_interval: timedelta = timedelta(seconds=10),
        owner_id: str | None = None,
        clock: Callable[[], datetime] = _utc_now,
        orchestrator_factory: Callable[..., ChiefEditorAgent] = ChiefEditorAgent,
    ) -> None:
        if min(lease_ttl, heartbeat_interval, run_timeout, recovery_interval) <= timedelta(0):
            raise ValueError("coordinator durations must be positive")
        if heartbeat_interval >= lease_ttl:
            raise ValueError("heartbeat_interval must be shorter than lease_ttl")
        self.repository = repository
        self.checkpointer = checkpointer
        self.enabled = enabled
        self.lease_ttl = lease_ttl
        self.heartbeat_interval = heartbeat_interval
        self.run_timeout = run_timeout
        self.recovery_interval = recovery_interval
        self.owner_id = owner_id or str(uuid.uuid4())
        self._clock = clock
        self._orchestrator_factory = orchestrator_factory
        self._active: dict[str, asyncio.Task[None]] = {}
        self._active_lock = asyncio.Lock()
        self._recovery_task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def active_runs(self) -> tuple[str, ...]:
        return tuple(self._active)

    async def start(self) -> tuple[str, ...]:
        recovered = await self.repository.recover_runs(now=self._clock())
        if self.enabled:
            for item in recovered:
                await self.submit(item.run_id, resume=item.resume)
            self._recovery_task = asyncio.create_task(
                self._recovery_loop(), name="deepchoice-run-recovery"
            )
        return tuple(item.run_id for item in recovered)

    async def submit(self, run_id: str, *, resume: bool | None = None) -> bool:
        if not self.enabled or self._stopping:
            return False
        async with self._active_lock:
            if not self.enabled or self._stopping:
                return False
            existing = self._active.get(run_id)
            if existing is not None and not existing.done():
                return False
            if resume is None:
                run = await self.repository.get_run(run_id)
                if run is None:
                    return False
                reference = await self.repository.get_latest_checkpoint_reference(
                    run_id, state_schema_version=run.manifest.state_schema_version
                )
                resume = reference is not None
            task = asyncio.create_task(
                self._run(run_id, resume=resume), name=f"deepchoice-run-{run_id}"
            )
            self._active[run_id] = task
            task.add_done_callback(
                lambda completed, key=run_id: self._discard(key, completed)
            )
            return True

    def _discard(self, run_id: str, completed: asyncio.Task[None]) -> None:
        if not completed.cancelled():
            try:
                completed.exception()
            except Exception:
                pass
        if self._active.get(run_id) is completed:
            self._active.pop(run_id, None)

    async def cancel_active(self, run_id: str) -> None:
        task = self._active.get(run_id)
        if task is not None and not task.done():
            task.cancel()

    async def stop(self) -> None:
        self._stopping = True
        recovery = self._recovery_task
        self._recovery_task = None
        if recovery is not None:
            recovery.cancel()
        async with self._active_lock:
            active = tuple(self._active.values())
        for task in active:
            task.cancel()
        if recovery is not None:
            await asyncio.gather(recovery, return_exceptions=True)
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self._active.clear()

    async def _recovery_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.recovery_interval.total_seconds())
                recovered = await self.repository.recover_runs(now=self._clock())
                for item in recovered:
                    await self.submit(item.run_id, resume=item.resume)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient product DB error is retried on the next bounded tick.
                continue

    async def _heartbeat(
        self, run_id: str, execution_epoch: int, runner: asyncio.Task[Any]
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval.total_seconds())
                renewed = await self.repository.heartbeat_run_lease(
                    run_id,
                    lease_owner=self.owner_id,
                    execution_epoch=execution_epoch,
                    lease_ttl=self.lease_ttl,
                    now=self._clock(),
                )
                if renewed.status is RunStatus.CANCELLING:
                    if not runner.done():
                        runner.cancel()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            if not runner.done():
                runner.cancel()

    async def _finalize(
        self,
        run_id: str,
        execution_epoch: int,
        status: RunStatus,
        *,
        error_id: str | None = None,
    ) -> TaskWithRun | None:
        try:
            return await self.repository.finalize_run(
                run_id,
                lease_owner=self.owner_id,
                execution_epoch=execution_epoch,
                status=status,
                error_id=error_id,
                now=self._clock(),
            )
        except RunLeaseLostError:
            return None

    async def _record_checkpoint(
        self,
        orchestrator: ChiefEditorAgent,
        run_id: str,
        execution_epoch: int,
        node: str | None,
        state_schema_version: int,
        storage_namespace: str,
    ) -> None:
        await self.repository.fence_run(
            run_id,
            lease_owner=self.owner_id,
            execution_epoch=execution_epoch,
            now=self._clock(),
        )
        state = await orchestrator.get_state()
        config = getattr(state, "config", None) if state is not None else None
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        checkpoint_id = configurable.get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            return
        reference = CheckpointReference(
            run_id=run_id,
            checkpoint_ns=getattr(orchestrator, "checkpoint_ns", ""),
            storage_checkpoint_ns=storage_namespace,
            checkpoint_id=checkpoint_id,
            node=node,
            state_schema_version=state_schema_version,
            execution_epoch=execution_epoch,
            created_at=self._clock(),
        )
        await self.repository.add_checkpoint_reference(
            reference,
            lease_owner=self.owner_id,
            execution_epoch=execution_epoch,
            now=self._clock(),
        )

    async def _run(self, run_id: str, *, resume: bool) -> None:
        grant = None
        heartbeat: asyncio.Task[None] | None = None
        acquisition: asyncio.Task[Any] | None = None

        async def stop_heartbeat() -> None:
            nonlocal heartbeat
            if heartbeat is None:
                return
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            heartbeat = None

        try:
            acquisition = asyncio.create_task(
                self.repository.acquire_run_lease(
                    run_id,
                    lease_owner=self.owner_id,
                    lease_ttl=self.lease_ttl,
                    run_timeout=self.run_timeout,
                    now=self._clock(),
                ),
                name=f"deepchoice-lease-acquire-{run_id}",
            )
            grant = await asyncio.shield(acquisition)
            resume = grant.resume
            current = await self.repository.get_task(grant.task_id)
            if current is None or current.latest_run is None:
                raise RunLeaseLostError(run_id)
            run = current.latest_run

            async def guard() -> None:
                fenced = await self.repository.fence_run(
                    run_id,
                    lease_owner=self.owner_id,
                    execution_epoch=grant.execution_epoch,
                    now=self._clock(),
                )
                if fenced.status is RunStatus.CANCELLING:
                    raise asyncio.CancelledError

            checkpoint_id = None
            read_namespace = None
            if resume:
                reference = await self.repository.get_latest_checkpoint_reference(
                    run_id,
                    state_schema_version=run.manifest.state_schema_version,
                    checkpoint_ns=run.checkpoint_ns,
                )
                if reference is not None:
                    checkpoint_id = reference.checkpoint_id
                    read_namespace = reference.storage_checkpoint_ns
                else:
                    resume = False

            write_namespace = _execution_checkpoint_namespace(grant.execution_epoch)
            fenced_checkpointer = FencedCheckpointSaver(
                self.checkpointer,
                guard,
                logical_namespace=run.checkpoint_ns,
                read_namespace=read_namespace,
                read_checkpoint_id=checkpoint_id,
                write_namespace=write_namespace,
            )

            if (
                resume
                and checkpoint_id is not None
                and hasattr(self.checkpointer, "aget_tuple")
            ):
                accepted = await fenced_checkpointer.aget_tuple(
                    {
                        "configurable": {
                            "thread_id": run.thread_id,
                            "checkpoint_ns": run.checkpoint_ns,
                            "checkpoint_id": checkpoint_id,
                        }
                    }
                )
                if accepted is None:
                    finalized = await self._finalize(
                        run_id, grant.execution_epoch, RunStatus.INTERRUPTED
                    )
                    if (
                        finalized is not None
                        and finalized.latest_run is not None
                        and finalized.task.status.value == RunStatus.INTERRUPTED.value
                    ):
                        replacement_id = str(uuid.uuid4())
                        created_at = self._clock()
                        replacement = RunRecord(
                            run_id=replacement_id,
                            task_id=finalized.task.task_id,
                            status=RunStatus.QUEUED,
                            manifest=build_run_manifest(
                                finalized.task.request.model_dump(exclude_none=True)
                            ),
                            thread_id=replacement_id,
                            checkpoint_ns="",
                            created_at=created_at,
                            updated_at=created_at,
                        )
                        try:
                            await self.repository.retry_task_with_run(
                                finalized.task.task_id,
                                replacement,
                                expected_task_version=finalized.task.version,
                                updated_at=created_at,
                            )
                            await self.submit(replacement_id, resume=False)
                        except Exception:
                            # The interrupted old run remains a safe observable
                            # state if another writer wins the replacement CAS.
                            pass
                    return

            orchestrator = self._orchestrator_factory(
                current.task.request.model_dump(exclude_none=True),
                checkpointer=fenced_checkpointer,
                thread_id=run.thread_id,
                run_manifest=run.manifest,
                checkpoint_ns=run.checkpoint_ns,
                checkpoint_id=checkpoint_id,
                execution_guard=guard,
            )
            runner = asyncio.current_task()
            if runner is None:  # pragma: no cover
                raise RuntimeError("coordinator runner is unavailable")
            heartbeat = asyncio.create_task(
                self._heartbeat(run_id, grant.execution_epoch, runner),
                name=f"deepchoice-heartbeat-{run_id}",
            )
            remaining = max(0.0, (grant.deadline_at - self._clock()).total_seconds())
            async with asyncio.timeout(remaining):
                async for event in orchestrator.astream_research_task(resume=resume):
                    await guard()
                    node = next(iter(event), None) if isinstance(event, dict) else None
                    await self._record_checkpoint(
                        orchestrator,
                        run_id,
                        grant.execution_epoch,
                        node,
                        run.manifest.state_schema_version,
                        write_namespace,
                    )
            await stop_heartbeat()
            await guard()
            await self._finalize(run_id, grant.execution_epoch, RunStatus.COMPLETED)
        except TimeoutError:
            await stop_heartbeat()
            if grant is not None:
                await self._finalize(run_id, grant.execution_epoch, RunStatus.TIMED_OUT)
        except asyncio.CancelledError:
            await stop_heartbeat()
            if grant is None and acquisition is not None:
                try:
                    grant = await _settle_shielded(acquisition)
                except (Exception, asyncio.CancelledError):
                    # Acquisition did not commit a usable lease, so there is no
                    # owner/epoch with which to perform a legitimate finalize.
                    grant = None
            if grant is not None:
                finalization = asyncio.create_task(
                    self._finalize(
                        run_id, grant.execution_epoch, RunStatus.INTERRUPTED
                    ),
                    name=f"deepchoice-cancel-finalize-{run_id}",
                )
                try:
                    await _settle_shielded(finalization)
                except (Exception, asyncio.CancelledError):
                    # Preserve cancellation as the caller-visible outcome. A
                    # failed fenced finalize remains recoverable after expiry.
                    pass
            raise
        except RunLeaseLostError:
            await stop_heartbeat()
            return
        except Exception as exc:
            await stop_heartbeat()
            if grant is not None:
                detail = normalize_error(exc)
                await self._finalize(
                    run_id,
                    grant.execution_epoch,
                    RunStatus.FAILED,
                    error_id=detail.code,
                )
        finally:
            await stop_heartbeat()


__all__ = ["RunCoordinator"]
