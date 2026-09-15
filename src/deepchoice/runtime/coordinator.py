"""Durable, fenced execution coordination for persisted research runs."""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.budget import (
    DEFAULT_RUN_BUDGET_POLICY,
    BudgetExceededError,
    BudgetInsufficientEvidenceError,
    BudgetPersistenceError,
    SQLiteBudgetStore,
)
from deepchoice.budget.limited import build_budget_limited_state
from deepchoice.contracts.errors import normalize_error
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.persistence.records import (
    CheckpointReference,
    RunRecord,
    RunResultRecord,
    TaskWithRun,
)
from deepchoice.persistence.repository import (
    RunLeaseLostError,
    SQLiteTaskRunRepository,
)
from deepchoice.observability import RuntimeTraceRecorder, SQLiteTraceStore, TraceStatus
from deepchoice.runtime.checkpoints import FencedCheckpointSaver
from deepchoice.runtime.context import RunContext, bind_run_context
from deepchoice.runtime.lifecycle import RunStatus


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _execution_checkpoint_namespace(execution_epoch: int) -> str:
    """Return an internal namespace never exposed to the root StateGraph."""

    return f"deepchoice-execution-{execution_epoch}"


class _NoopTraceSink:
    """Keep budget context active when optional Trace persistence is absent."""

    async def record_run(self, trace) -> None:
        return None

    async def record_node_attempt(self, attempt) -> None:
        return None

    async def record_external_call(self, call) -> None:
        return None

    async def record_event(self, event) -> None:
        return None


_PUBLIC_RESULT_FIELDS = frozenset(
    {
        "adapted_queries",
        "agent_timing",
        "budget_limited",
        "citation_verification",
        "confidence",
        "conflicts",
        "current_phase",
        "data_source_note",
        "evidence_chains",
        "final_recommendation",
        "knowledge_gaps",
        "partial_failures",
        "quality_signals",
        "report",
        "retry_count",
        "search_results",
        "source_scores",
        "sub_questions",
        "token_usage",
    }
)
_PRIVATE_RESULT_KEYS = frozenset(
    {
        "checkpoint_id",
        "checkpoint_ns",
        "error_detail",
        "exception",
        "execution_epoch",
        "lease_owner",
        "manifest",
        "manifest_id",
        "raw_exception",
        "raw_body",
        "raw_html",
        "page_body",
        "response_body",
        "response_text",
        "run_manifest",
        "stacktrace",
        "storage_checkpoint_ns",
        "traceback",
    }
)
_SENSITIVE_RESULT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "id_token",
        "set_cookie",
        "token",
    }
)
_SENSITIVE_RESULT_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_authorization",
    "_client_secret",
    "_credential",
    "_credentials",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_secret_key",
    "_session_token",
    "_id_token",
    "_token",
)
_OMIT = object()


def _normalize_result_key(key: str) -> str:
    # Normalize camelCase/PascalCase/acronyms and header-style separators so
    # secret-shaped keys cannot bypass the recursive filter by changing case.
    separated = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    return re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")


def _is_private_result_key(key: str) -> bool:
    normalized = _normalize_result_key(key)
    return (
        key.startswith("_")
        or normalized in _PRIVATE_RESULT_KEYS
        or normalized in _SENSITIVE_RESULT_KEYS
        or normalized.endswith(_SENSITIVE_RESULT_SUFFIXES)
    )


def _sanitize_public_json(value: Any) -> Any:
    """Copy JSON values while dropping private or exception-bearing fields."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _OMIT
    if isinstance(value, (list, tuple)):
        sanitized = (_sanitize_public_json(item) for item in value)
        return [item for item in sanitized if item is not _OMIT]
    if isinstance(value, dict):
        public: dict[str, Any] = {}
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or _is_private_result_key(key)
            ):
                continue
            sanitized = _sanitize_public_json(item)
            if sanitized is not _OMIT:
                public[key] = sanitized
        return public
    return _OMIT


def build_public_run_result(
    run: RunRecord,
    request: dict[str, Any],
    state: Any,
    *,
    created_at: datetime,
) -> RunResultRecord:
    """Freeze the public result allowlist without exposing checkpoint internals."""

    values = state if isinstance(state, dict) else getattr(state, "values", None)
    source = values if isinstance(values, dict) else {}
    snapshot: dict[str, Any] = {"task": _sanitize_public_json(request)}
    for key in _PUBLIC_RESULT_FIELDS:
        if key not in source:
            continue
        sanitized = _sanitize_public_json(source[key])
        if sanitized is not _OMIT:
            snapshot[key] = sanitized
    report = snapshot.get("report")
    if not isinstance(report, str) or not report.strip():
        raise ValueError("successful run state must contain a non-empty public report")
    snapshot["report"] = report
    return RunResultRecord(
        run_id=run.run_id,
        snapshot=snapshot,
        report=report,
        report_format=run.manifest.report.report_format,
        created_at=created_at,
    )


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
        trace_store: SQLiteTraceStore | None = None,
        budget_store: SQLiteBudgetStore | None = None,
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
        self._trace_store = trace_store
        self._budget_store = budget_store or SQLiteBudgetStore(
            repository._connection, repository._lock, clock=clock
        )
        self._active: dict[str, asyncio.Task[None]] = {}
        self._active_lock = asyncio.Lock()
        self._recovery_task: asyncio.Task[None] | None = None
        self._stopping = False

    def configure_trace_store(self, trace_store: SQLiteTraceStore) -> None:
        """Attach the composition-root trace store before execution starts."""

        if self._active or self._recovery_task is not None:
            raise RuntimeError("trace store must be configured before coordinator start")
        self._trace_store = trace_store

    def configure_budget_store(self, budget_store: SQLiteBudgetStore) -> None:
        """Attach the correctness-path budget store before execution starts."""

        if self._active or self._recovery_task is not None:
            raise RuntimeError("budget store must be configured before coordinator start")
        self._budget_store = budget_store

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
        result: RunResultRecord | None = None,
    ) -> TaskWithRun | None:
        try:
            if result is not None:
                return await self.repository.finalize_run_with_result(
                    run_id,
                    result,
                    lease_owner=self.owner_id,
                    execution_epoch=execution_epoch,
                    status=status,
                    now=self._clock(),
                )
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
        context_binding = None
        trace: RuntimeTraceRecorder | None = None
        budget = None
        orchestrator: ChiefEditorAgent | None = None
        trace_finished = False

        async def finish_trace(status: TraceStatus) -> None:
            nonlocal trace_finished
            if trace is not None and not trace_finished:
                await trace.finish_run(status)
                trace_finished = True

        async def stop_heartbeat() -> None:
            nonlocal heartbeat
            if heartbeat is None:
                return
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            heartbeat = None

        async def record_active_budget() -> None:
            if budget is None:
                return
            try:
                await budget.record_active_milliseconds()
            except asyncio.CancelledError:
                # This terminal measurement is ancillary.  In particular, a
                # second cancellation must not prevent the fenced lifecycle
                # finalization below from clearing a committed running lease.
                return
            except Exception:
                # Terminal measurement is best effort. Admission and settlement
                # around external calls remain fail-closed correctness paths.
                return

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
            if run.budget_policy is None:
                raise BudgetPersistenceError(
                    "durable execution requires a frozen budget policy"
                )

            async def guard() -> None:
                fenced = await self.repository.fence_run(
                    run_id,
                    lease_owner=self.owner_id,
                    execution_epoch=grant.execution_epoch,
                    now=self._clock(),
                )
                if fenced.status is RunStatus.CANCELLING:
                    raise asyncio.CancelledError

            class GuardCancellationPort:
                async def raise_if_cancelled(self) -> None:
                    await guard()

            if self._budget_store is None:
                raise BudgetPersistenceError("budget store is not configured")
            budget = self._budget_store.bind(
                run_id=run_id,
                execution_epoch=grant.execution_epoch,
                lease_owner=self.owner_id,
                policy=run.budget_policy,
                run_started_at=run.started_at or run.created_at,
                execution_started_at=self._clock(),
            )
            await budget.reconcile()

            trace_port = _NoopTraceSink()
            if self._trace_store is not None:
                sink = self._trace_store.bind(
                    run_id=run_id,
                    execution_epoch=grant.execution_epoch,
                    lease_owner=self.owner_id,
                )
                trace = RuntimeTraceRecorder(sink, task_id=grant.task_id)
                trace_port = trace
            context = RunContext.from_run_record(
                run,
                cancellation=GuardCancellationPort(),
                trace=trace_port,
                budget=budget,
            )
            context_binding = bind_run_context(context)
            context_binding.__enter__()
            if trace is not None:
                await trace.start_run()

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
                            budget_policy=DEFAULT_RUN_BUDGET_POLICY,
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
            await guard()
            final_state = await orchestrator.get_state()
            completed_at = self._clock()
            public_result = build_public_run_result(
                run,
                current.task.request.model_dump(mode="json", exclude_none=True),
                final_state,
                created_at=completed_at,
            )
            await stop_heartbeat()
            await guard()
            await record_active_budget()
            await finish_trace(TraceStatus.SUCCEEDED)
            await self._finalize(
                run_id,
                grant.execution_epoch,
                RunStatus.COMPLETED,
                result=public_result,
            )
        except BudgetExceededError as exc:
            await stop_heartbeat()
            if grant is not None:
                try:
                    await record_active_budget()
                    partial_state = exc.partial_state
                    if not isinstance(partial_state, dict) and orchestrator is not None:
                        checkpoint_state = await orchestrator.get_state()
                        checkpoint_values = getattr(checkpoint_state, "values", None)
                        if isinstance(checkpoint_values, dict):
                            partial_state = checkpoint_values
                    limited_state = build_budget_limited_state(
                        partial_state if isinstance(partial_state, dict) else {},
                        request=current.task.request.model_dump(
                            mode="json", exclude_none=True
                        ),
                        policy=run.budget_policy,
                        error=exc,
                    )
                    if limited_state is None:
                        await finish_trace(TraceStatus.FAILED)
                        detail = normalize_error(BudgetInsufficientEvidenceError())
                        await self._finalize(
                            run_id,
                            grant.execution_epoch,
                            RunStatus.FAILED,
                            error_id=detail.code,
                        )
                    else:
                        completed_at = self._clock()
                        public_result = build_public_run_result(
                            run,
                            current.task.request.model_dump(
                                mode="json", exclude_none=True
                            ),
                            limited_state,
                            created_at=completed_at,
                        )
                        await finish_trace(TraceStatus.SUCCEEDED)
                        await self._finalize(
                            run_id,
                            grant.execution_epoch,
                            RunStatus.COMPLETED_WITH_WARNINGS,
                            result=public_result,
                        )
                except asyncio.CancelledError:
                    await finish_trace(TraceStatus.CANCELLED)
                    finalization = asyncio.create_task(
                        self._finalize(
                            run_id, grant.execution_epoch, RunStatus.INTERRUPTED
                        ),
                        name=f"deepchoice-budget-cancel-finalize-{run_id}",
                    )
                    try:
                        await _settle_shielded(finalization)
                    except (Exception, asyncio.CancelledError):
                        pass
                    raise
                except Exception as fallback_exc:
                    await finish_trace(TraceStatus.FAILED)
                    detail = normalize_error(fallback_exc)
                    try:
                        await self._finalize(
                            run_id,
                            grant.execution_epoch,
                            RunStatus.FAILED,
                            error_id=detail.code,
                        )
                    except Exception:
                        # Recovery will fence an expired lease if persistence is
                        # unavailable during the terminal fallback itself.
                        pass
        except TimeoutError:
            await stop_heartbeat()
            if grant is not None:
                await record_active_budget()
                await finish_trace(TraceStatus.TIMED_OUT)
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
                await record_active_budget()
                await finish_trace(TraceStatus.CANCELLED)
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
                await record_active_budget()
                await finish_trace(TraceStatus.FAILED)
                detail = normalize_error(exc)
                await self._finalize(
                    run_id,
                    grant.execution_epoch,
                    RunStatus.FAILED,
                    error_id=detail.code,
                )
        finally:
            await stop_heartbeat()
            if context_binding is not None:
                context_binding.__exit__(None, None, None)


__all__ = ["RunCoordinator", "build_public_run_result"]
