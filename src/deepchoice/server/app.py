import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..agents.orchestrator import ChiefEditorAgent, _get_sqlite_saver
from ..contracts.api import (
    ResearchRequest,
    ResearchStartedResponse,
    RunRecordResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskRecordResponse,
)
from ..contracts.errors import (
    DeepChoiceError,
    ErrorCategory,
    ErrorDetail,
    ErrorResponse,
    normalize_error,
)
from ..contracts.manifest import build_run_manifest
from ..formats.citations import build_toc, inject_citations, number_sources
from ..formats.comparison_matrix import render as render_comparison_matrix
from ..formats.evidence_first import render as render_evidence_first
from ..formats.pdf import render_pdf
from ..formats.what_why_how import render as render_what_why_how
from ..persistence.database import DEFAULT_DB_PATH, DatabaseConnectionError, _await_cleanup, connect_database
from ..persistence.migrations import run_migrations
from ..persistence.records import TaskWithRun
from ..persistence.repository import SQLiteTaskRunRepository
from ..runtime.coordinator import RunCoordinator
from ..runtime.lifecycle import TaskStatus
from ..services.tasks import TaskService
from ..utils.views import print_agent_output
from .clarify_routes import router as clarify_router
from .legacy_import import import_legacy_snapshots
from .snapshot_store import (
    list_history,
    load_snapshot,
    save_failed_snapshot,
    save_report,
    save_snapshot,
)
from .task_event_stream import iter_task_event_sse, parse_last_event_id

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own the product database's one connection for this app lifespan."""

    connection = None
    checkpoint_connection = None
    coordinator = None
    try:
        database_path = getattr(application.state, "product_database_path", None)
        connection = await connect_database(database_path or DEFAULT_DB_PATH)
        connection_lock = asyncio.Lock()
        async with connection_lock:
            await run_migrations(connection)
        repository = SQLiteTaskRunRepository(connection, connection_lock)
        legacy_snapshot_root = Path(
            getattr(application.state, "legacy_snapshot_root", OUTPUT_DIR)
        )
        legacy_import_summary = await import_legacy_snapshots(
            legacy_snapshot_root,
            repository,
        )
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        checkpoint_path = Path(
            getattr(
                application.state,
                "checkpoint_database_path",
                OUTPUT_DIR / "checkpoints.db",
            )
        )
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_connection = await aiosqlite.connect(str(checkpoint_path))
        cursor = await checkpoint_connection.execute("PRAGMA busy_timeout = 5000")
        await cursor.close()
        cursor = await checkpoint_connection.execute("PRAGMA journal_mode = WAL")
        await cursor.fetchone()
        await cursor.close()
        checkpointer = AsyncSqliteSaver(checkpoint_connection)
        await checkpointer.setup()
        execution_enabled = bool(
            getattr(application.state, "execution_enabled", True)
        )
        coordinator = RunCoordinator(
            repository,
            checkpointer,
            enabled=execution_enabled,
        )
        application.state.product_database_connection = connection
        application.state.product_database_lock = connection_lock
        application.state.task_repository = repository
        application.state.task_service = TaskService(repository)
        application.state.legacy_import_summary = legacy_import_summary
        application.state.run_coordinator = coordinator
        application.state.execution_enabled = execution_enabled
        await coordinator.start()
        yield
    finally:
        if coordinator is not None:
            await coordinator.stop()
        application.state.run_coordinator = None
        application.state.task_service = None
        application.state.task_repository = None
        application.state.legacy_import_summary = None
        application.state.product_database_lock = None
        application.state.product_database_connection = None
        if connection is not None:
            await _await_cleanup(connection.close())
        if checkpoint_connection is not None:
            await _await_cleanup(checkpoint_connection.close())


app = FastAPI(title="DeepChoice API", version="0.1.0", lifespan=lifespan)
app.include_router(clarify_router)

OUTPUT_DIR = Path("./outputs")
_active_tasks: dict[str, dict] = {}
FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}


def _get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if not isinstance(service, TaskService):
        raise DatabaseConnectionError(retryable=True)
    return service


def _get_run_coordinator(request: Request) -> RunCoordinator | None:
    coordinator = getattr(request.app.state, "run_coordinator", None)
    return coordinator if isinstance(coordinator, RunCoordinator) else None


def _get_task_repository(request: Request) -> SQLiteTaskRunRepository:
    repository = getattr(request.app.state, "task_repository", None)
    if not isinstance(repository, SQLiteTaskRunRepository):
        raise DatabaseConnectionError(retryable=True)
    return repository


def _task_detail_response(record: TaskWithRun) -> TaskDetailResponse:
    return TaskDetailResponse(
        task=TaskRecordResponse.model_validate(record.task.model_dump(mode="json")),
        latest_run=(
            RunRecordResponse(
                run_id=record.latest_run.run_id,
                task_id=record.latest_run.task_id,
                status=record.latest_run.status.value,
                manifest_id=record.latest_run.manifest.manifest_id,
                started_at=record.latest_run.started_at,
                ended_at=record.latest_run.ended_at,
                deadline_at=record.latest_run.deadline_at,
                version=record.latest_run.version,
                created_at=record.latest_run.created_at,
                updated_at=record.latest_run.updated_at,
            )
            if record.latest_run is not None
            else None
        ),
    )


def _error_response(
    status_code: int,
    detail,
    error: ErrorDetail,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(detail=detail, error=error).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(_request: Request, exc: RequestValidationError):
    # Do not echo rejected input values: validation failures can contain user
    # credentials or other sensitive text in Pydantic's default ``input`` key.
    details = [
        {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
        for item in exc.errors()
    ]
    error = ErrorDetail(
        category=ErrorCategory.VALIDATION,
        code="REQUEST_VALIDATION_FAILED",
        message="Request validation failed",
        action="Correct the invalid fields and submit the request again.",
        details=details,
    )
    return _error_response(422, details, error)


@app.exception_handler(DeepChoiceError)
async def deepchoice_error_handler(_request: Request, exc: DeepChoiceError):
    return _error_response(exc.status_code, str(exc), exc.error_detail)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException):
    is_server_error = exc.status_code >= 500
    category = (
        ErrorCategory.INTERNAL
        if is_server_error
        else ErrorCategory.NOT_FOUND if exc.status_code == 404 else ErrorCategory.REQUEST
    )
    message = (
        "Internal request failed"
        if is_server_error
        else exc.detail if isinstance(exc.detail, str) else "Request failed"
    )
    error = ErrorDetail(
        category=category,
        code=(
            "INTERNAL_HTTP_ERROR"
            if is_server_error
            else "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        ),
        message=message,
        action="Check the request and try again.",
    )
    detail = message if is_server_error else exc.detail
    return _error_response(exc.status_code, detail, error, headers=exc.headers)


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, exc: Exception):
    error = normalize_error(exc)
    return _error_response(500, error.message, error)

# Single source of truth: workflow node name -> progress phase. The 7 phase names
# match the frontend PHASES list; keep the fallback copy in frontend/app.py in sync.
NODE_TO_PHASE = {
    "query_analyzer": "query_analysis",
    "query_adapter": "query_analysis",
    "multi_retriever": "retrieval",
    "source_evaluator": "source_evaluation",
    "conflict_detector": "conflict_detection",
    "evidence_chain": "evidence_chain",
    "conclusion_synthesizer": "evidence_chain",
    "report_generator": "report_generation",
    "self_reviewer": "self_review",
}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post(
    "/api/v1/tasks",
    response_model=TaskDetailResponse,
    status_code=202,
)
async def create_task(request: Request, body: ResearchRequest) -> TaskDetailResponse:
    """Persist a queued task/run pair and submit it to the durable coordinator."""

    record = await _get_task_service(request).create(body)
    coordinator = _get_run_coordinator(request)
    if coordinator is not None and record.latest_run is not None:
        try:
            await coordinator.submit(record.latest_run.run_id, resume=False)
        except Exception:
            # Persistence is authoritative; periodic recovery will submit queued work.
            pass
    return _task_detail_response(record)


class IfMatchRequiredError(DeepChoiceError):
    def __init__(self, task_id: str) -> None:
        super().__init__(
            "The If-Match task version is required.",
            category=ErrorCategory.CONTRACT,
            code="TASK_VERSION_REQUIRED",
            status_code=428,
            retryable=False,
            action='Send If-Match with the current task version, for example "3".',
            scope="task_lifecycle",
            task_id=task_id,
        )


class InvalidIfMatchError(DeepChoiceError):
    def __init__(self, task_id: str) -> None:
        super().__init__(
            "The If-Match task version is invalid.",
            category=ErrorCategory.VALIDATION,
            code="INVALID_TASK_VERSION",
            status_code=422,
            retryable=False,
            action='Use a non-negative integer or quoted integer, for example "3".',
            scope="task_lifecycle",
            task_id=task_id,
        )


class InvalidLastEventIdError(DeepChoiceError):
    def __init__(self, task_id: str) -> None:
        super().__init__(
            "The Last-Event-ID cursor is invalid.",
            category=ErrorCategory.VALIDATION,
            code="INVALID_LAST_EVENT_ID",
            status_code=422,
            retryable=False,
            action="Reconnect without Last-Event-ID or use a non-negative event ID.",
            scope="task_events",
            task_id=task_id,
        )


def _parse_if_match(value: str | None, task_id: str) -> int:
    if value is None:
        raise IfMatchRequiredError(task_id)
    candidate = value.strip()
    match = re.fullmatch(r'(?:"(\d+)"|(\d+))', candidate)
    if match is None:
        raise InvalidIfMatchError(task_id)
    digits = match.group(1) or match.group(2)
    if len(digits) > 19:
        raise InvalidIfMatchError(task_id)
    parsed = int(digits)
    if parsed > 9_223_372_036_854_775_807:
        raise InvalidIfMatchError(task_id)
    return parsed


@app.post(
    "/api/v1/tasks/{task_id}/cancel",
    response_model=TaskDetailResponse,
)
async def cancel_task(task_id: str, request: Request) -> TaskDetailResponse:
    record = await _get_task_service(request).cancel(task_id)
    coordinator = _get_run_coordinator(request)
    if (
        coordinator is not None
        and record.latest_run is not None
        and record.task.status is TaskStatus.CANCELLING
    ):
        await coordinator.cancel_active(record.latest_run.run_id)
    return _task_detail_response(record)


@app.post(
    "/api/v1/tasks/{task_id}/resume",
    response_model=TaskDetailResponse,
    status_code=202,
)
async def resume_task(task_id: str, request: Request) -> TaskDetailResponse:
    expected = _parse_if_match(request.headers.get("if-match"), task_id)
    record = await _get_task_service(request).resume(
        task_id, expected_task_version=expected
    )
    coordinator = _get_run_coordinator(request)
    if coordinator is not None and record.latest_run is not None:
        try:
            await coordinator.submit(
                record.latest_run.run_id,
                resume=record.latest_run.execution_epoch > 0,
            )
        except Exception:
            # The durable mutation succeeded; periodic recovery is the wake-up fallback.
            pass
    return _task_detail_response(record)


@app.get(
    "/api/v1/tasks/{task_id}",
    response_model=TaskDetailResponse,
)
async def get_task(task_id: str, request: Request) -> TaskDetailResponse:
    record = await _get_task_service(request).get(task_id)
    return _task_detail_response(record)


@app.get(
    "/api/v1/tasks",
    response_model=TaskListResponse,
)
async def get_tasks(
    request: Request,
    status: TaskStatus | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TaskListResponse:
    page = await _get_task_service(request).list(
        status=status,
        cursor=cursor,
        limit=limit,
    )
    return TaskListResponse(
        items=tuple(_task_detail_response(item) for item in page.items),
        next_cursor=page.next_cursor,
    )


@app.get("/api/v1/tasks/{task_id}/events")
async def stream_task_events(task_id: str, request: Request) -> StreamingResponse:
    """Replay durable public task events and continue from Last-Event-ID."""

    service = _get_task_service(request)
    await service.get(task_id)
    try:
        last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    except ValueError:
        raise InvalidLastEventIdError(task_id) from None

    repository = _get_task_repository(request)

    async def load_public_snapshot(snapshot_task_id: str) -> TaskDetailResponse:
        return _task_detail_response(await service.get(snapshot_task_id))

    return StreamingResponse(
        iter_task_event_sse(
            repository,
            task_id,
            last_event_id=last_event_id,
            snapshot_loader=load_public_snapshot,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Stream wake-up sentinels pushed by _run_research into entry["queue"].
# Data events live only in entry["events"] (single source, replayable) — the
# queue carries control signals so subscribers wake up without double-yielding.
_STREAM_TICK = object()
_STREAM_DONE = object()
_STREAM_ERROR = object()


@app.post("/research", response_model=ResearchStartedResponse)
async def start_research(request: ResearchRequest):
    task = request.model_dump(exclude_none=True)
    run_manifest = build_run_manifest(task)
    checkpointer = await _get_sqlite_saver()
    thread_id = str(uuid.uuid4())
    orchestrator = ChiefEditorAgent(
        task,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_manifest=run_manifest,
    )
    task_id = orchestrator.task_id

    _active_tasks[task_id] = {
        "thread_id": thread_id,
        "orchestrator": orchestrator,
        "queue": asyncio.Queue(),
        "events": [],
        "status": "running",
        "manifest": run_manifest,
    }

    asyncio.create_task(_run_research(task_id, orchestrator))

    return ResearchStartedResponse(
        task_id=task_id,
        status="started",
        manifest_id=run_manifest.manifest_id,
    )


def _format_event(event: dict) -> str:
    node_name = list(event.keys())[0]
    node_data = event[node_name]
    payload = {
        "node": node_name,
        "update": node_data,
        "phase": NODE_TO_PHASE.get(node_name),
        "ts": time.time(),
    }
    if node_name == "__error__":
        error_detail = node_data.get("error_detail") or normalize_error(
            RuntimeError(node_data.get("detail", ""))
        ).model_dump(mode="json")
        payload["detail"] = error_detail["message"]
        payload["error_detail"] = error_detail
        payload["update"] = {
            "detail": error_detail["message"],
            "error_detail": error_detail,
        }
    return f"event: {node_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _run_research(task_id: str, orchestrator: ChiefEditorAgent):
    entry = _active_tasks[task_id]
    try:
        async for event in orchestrator.astream_research_task():
            entry["events"].append(event)
            entry["queue"].put_nowait(_STREAM_TICK)

        state = await orchestrator.get_state()
        result = state.values if state else {}
        save_snapshot(task_id, result)
        if result.get("report"):
            save_report(task_id, result["report"])

        entry["status"] = "complete"
        entry["result"] = result
        entry["queue"].put_nowait(_STREAM_DONE)
    except Exception as e:
        error_detail = normalize_error(e)
        public_message = error_detail.message
        # I1 fix: persist whatever the checkpoint holds so a failed run is
        # inspectable after restart instead of vanishing with process memory.
        try:
            state = await orchestrator.get_state()
            partial = state.values if state else {}
            save_failed_snapshot(task_id, partial, public_message)
        except Exception as persist_err:
            print_agent_output(f"Failed to persist failure snapshot for {task_id}: {persist_err}", agent="SERVER")
        entry["status"] = "failed"
        entry["error"] = public_message
        entry["error_detail"] = error_detail.model_dump(mode="json")
        entry["events"].append(
            {
                "__error__": {
                    "detail": public_message,
                    "error_detail": entry["error_detail"],
                },
            }
        )
        entry["queue"].put_nowait(_STREAM_ERROR)
    finally:
        # I6 fix: the per-request sqlite connection must not outlive the task.
        checkpointer = getattr(orchestrator, "checkpointer", None)
        conn = getattr(checkpointer, "conn", None)
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass


@app.get("/research/{task_id}/stream")
async def stream_research(task_id: str):
    entry = _active_tasks.get(task_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        idx = 0
        while True:
            events = entry["events"]
            if idx < len(events):
                yield _format_event(events[idx])
                idx += 1
                continue
            if entry.get("status") != "running":
                break
            await entry["queue"].get()

        if entry.get("status") == "complete":
            yield f"event: __done__\ndata: {json.dumps({'node': '__done__', 'update': {}})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/research/{task_id}/status")
async def research_status(task_id: str, request: Request):
    entry = _active_tasks.get(task_id)
    if entry and entry.get("status") == "complete":
        return {
            "task_id": task_id,
            "status": "complete",
            "confidence": entry.get("result", {}).get("confidence", ""),
        }
    if entry and entry.get("status") == "failed":
        error_detail = entry.get("error_detail") or normalize_error(
            RuntimeError(entry.get("error", ""))
        ).model_dump(mode="json")
        return {
            "task_id": task_id,
            "status": "failed",
            "error": error_detail["message"],
            "error_detail": error_detail,
        }

    orchestrator = entry.get("orchestrator") if entry else None
    if orchestrator:
        try:
            if orchestrator.live_phase:
                return {
                    "task_id": task_id,
                    "status": "running",
                    "phase": orchestrator.live_phase,
                }
            state = await orchestrator.get_state()
            if state and state.values:
                current = state.values.get("current_phase", "running")
                return {
                    "task_id": task_id,
                    "status": "running",
                    "phase": current,
                    "checkpoint_step": state.metadata.get("step", -1) if state.metadata else -1,
                }
        except Exception as e:
            print_agent_output(f"Status check failed for {task_id}: {e}", agent="SERVER")

    if not entry:
        snapshot = load_snapshot(task_id)
        if snapshot:
            return {"task_id": task_id, "status": "complete"}
        repository = getattr(request.app.state, "task_repository", None)
        if not isinstance(repository, SQLiteTaskRunRepository):
            raise HTTPException(status_code=404, detail="Task not found")
        record = await repository.get_task(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")
        status = record.task.status
        if status in {TaskStatus.COMPLETED, TaskStatus.COMPLETED_WITH_WARNINGS}:
            return {"task_id": task_id, "status": "complete"}
        if status in {
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.CANCELLED,
            TaskStatus.INTERRUPTED,
        }:
            error_detail = ErrorDetail(
                category=(
                    ErrorCategory.TIMEOUT
                    if status is TaskStatus.TIMED_OUT
                    else ErrorCategory.RESEARCH
                ),
                code=f"TASK_{status.value.upper()}",
                message=f"Task ended with status {status.value}.",
                action="Inspect the durable task detail or resume the task when allowed.",
                retryable=status in {
                    TaskStatus.FAILED,
                    TaskStatus.TIMED_OUT,
                    TaskStatus.INTERRUPTED,
                },
                scope="task_lifecycle",
                task_id=task_id,
            )
            return {
                "task_id": task_id,
                "status": "failed",
                "error": error_detail.message,
                "error_detail": error_detail.model_dump(mode="json"),
            }
        return {
            "task_id": task_id,
            "status": "running",
            "phase": status.value,
        }

    return {
        "task_id": task_id,
        "status": "running",
        "phase": "unknown",
    }


@app.get("/research/{task_id}/checkpoints")
async def research_checkpoints(task_id: str):
    entry = _active_tasks.get(task_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")

    orchestrator = entry.get("orchestrator")
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Orchestrator not found")

    try:
        history = await orchestrator.get_state_history()
        checkpoints = []
        for state in history:
            cp = {
                "step": state.metadata.get("step", "?") if state.metadata else "?",
                "source": state.metadata.get("source", "?") if state.metadata else "?",
                "phase": state.values.get("current_phase", "") if state.values else "",
                "confidence": state.values.get("confidence", "") if state.values else "",
            }
            checkpoints.append(cp)
        return {"task_id": task_id, "checkpoints": checkpoints}
    except Exception as e:
        raise DeepChoiceError(
            "Unable to read checkpoints",
            category=ErrorCategory.PERSISTENCE,
            code="CHECKPOINT_READ_FAILED",
            status_code=500,
            retryable=True,
            action="Retry after checking checkpoint storage availability.",
            task_id=task_id,
        ) from e


@app.get("/research/{task_id}/report")
async def research_report(task_id: str, format: str = ""):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")

    requested_format = format or snapshot.get("task", {}).get("report_format", "what_why_how")
    renderer = FORMAT_RENDERERS.get(requested_format, render_what_why_how)
    report = renderer(snapshot)

    return {"task_id": task_id, "report": report, "format": requested_format}


@app.get("/research/{task_id}/annotated")
async def research_annotated(task_id: str, format: str = ""):
    """Report with numbered citation badges and TOC anchors for the reading view."""
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")

    requested_format = format or snapshot.get("task", {}).get("report_format", "what_why_how")
    renderer = FORMAT_RENDERERS.get(requested_format, render_what_why_how)
    report = renderer(snapshot)

    registry = number_sources(snapshot.get("evidence_chains", []))
    report = inject_citations(report, registry)
    toc, report = build_toc(report)

    return {
        "task_id": task_id,
        "format": requested_format,
        "report": report,
        "toc": toc,
        "citations": registry,
    }


@app.get("/research/{task_id}/export")
async def research_export(task_id: str, format: str = "md", report_format: str = ""):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")

    renderer = FORMAT_RENDERERS.get(
        report_format or snapshot.get("task", {}).get("report_format", "what_why_how"),
        render_what_why_how,
    )
    report = renderer(snapshot)

    filename = f"deepchoice-report-{task_id}"
    export_format = format or "md"

    if export_format == "md":
        return Response(
            content=report,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
        )

    if export_format == "pdf":
        registry = number_sources(snapshot.get("evidence_chains", []))
        report = inject_citations(report, registry)
        _, report = build_toc(report)
        try:
            pdf_bytes = render_pdf(report)
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="PDF support not installed (xhtml2pdf). Use format=md or browser print.",
            )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        )

    raise HTTPException(status_code=400, detail=f"Unsupported format: {export_format}")


@app.get("/research/{task_id}/snapshot")
async def research_snapshot(task_id: str):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")
    return snapshot


@app.post("/research/{task_id}/regenerate")
async def regenerate_report(task_id: str, format: str = "what_why_how"):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")

    renderer = FORMAT_RENDERERS.get(format, render_what_why_how)
    report = renderer(snapshot)
    save_report(task_id, report)
    return {"task_id": task_id, "report": report, "format": format}


@app.get("/tasks/{task_id}")
async def task_status(task_id: str, request: Request):
    """Convenience alias for /research/{task_id}/status."""
    return await research_status(task_id, request)


@app.get("/history")
async def history():
    return {"tasks": list_history()}
