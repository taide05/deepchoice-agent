import asyncio
import json
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..agents.orchestrator import ChiefEditorAgent, _get_sqlite_saver
from ..formats.citations import build_toc, inject_citations, number_sources
from ..formats.comparison_matrix import render as render_comparison_matrix
from ..formats.evidence_first import render as render_evidence_first
from ..formats.pdf import render_pdf
from ..formats.what_why_how import render as render_what_why_how
from ..utils.views import print_agent_output
from .clarify_routes import router as clarify_router
from .resume import (
    REASON_ALREADY_COMPLETE,
    REASON_ATTEMPTS_EXHAUSTED,
    REASON_FEATURE_DISABLED,
    REASON_NO_CHECKPOINT,
    REASON_NO_RUN_RECORD,
    REASON_SCHEMA_MISMATCH,
    build_resume_info,
    max_attempts,
    read_task_run_state,
    resume_enabled,
)
from .security import ApiSecurityMiddleware
from .snapshot_store import (
    list_history,
    load_failed_snapshot,
    load_snapshot,
    save_failed_snapshot,
    save_report,
    save_snapshot,
)

app = FastAPI(title="DeepChoice API", version="0.1.0")
app.add_middleware(ApiSecurityMiddleware)
app.include_router(clarify_router)

OUTPUT_DIR = Path("./outputs")
_active_tasks: dict[str, dict] = {}
FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}

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


# Stream wake-up sentinels pushed by _run_research into entry["queue"].
# Data events live only in entry["events"] (single source, replayable) — the
# queue carries control signals so subscribers wake up without double-yielding.
_STREAM_TICK = object()
_STREAM_DONE = object()
_STREAM_ERROR = object()

# One lock per task, so a double-click / retried request cannot resume the same
# task twice. The deployment is a single uvicorn worker, so an in-process lock is
# sufficient; it is released by _run_research when the resumed attempt ends.
_resume_locks: dict[str, asyncio.Lock] = {}

# reason -> (HTTP detail code, status code). Feature-disabled reads as 404 (the
# route exists but the capability is off), every other refusal is a 409.
_RESUME_REASON_ERRORS = {
    REASON_FEATURE_DISABLED: ("RESUME_DISABLED", 404),
    REASON_ALREADY_COMPLETE: ("ALREADY_COMPLETE", 409),
    REASON_NO_RUN_RECORD: ("NOT_RESUMABLE", 409),
    REASON_SCHEMA_MISMATCH: ("SCHEMA_MISMATCH", 409),
    REASON_ATTEMPTS_EXHAUSTED: ("RESUME_EXHAUSTED", 409),
    REASON_NO_CHECKPOINT: ("NOT_RESUMABLE", 409),
}


def _current_schema_version() -> int:
    """The graph schema version this build writes/accepts (0 when unknown)."""
    try:
        import run_limits

        return int(run_limits.GRAPH_SCHEMA_VERSION)
    except Exception:
        return 0


def _task_run_state(task_id: str) -> dict:
    return read_task_run_state(OUTPUT_DIR / task_id)


def _resume_info(task_id: str) -> dict:
    return build_resume_info(
        complete_snapshot=load_snapshot(task_id),
        failed_snapshot=load_failed_snapshot(task_id),
        run_state=_task_run_state(task_id),
        current_schema_version=_current_schema_version(),
    )


def _resume_metadata(state, attempt: int) -> dict:
    """Checkpoint position saved into a failed snapshot for a later resume."""
    next_nodes = list(getattr(state, "next", None) or ())
    metadata = getattr(state, "metadata", None)
    step = metadata.get("step") if isinstance(metadata, dict) else None
    return {
        "attempt": max(1, int(attempt)),
        "max_attempts": max_attempts(),
        "next_nodes": [str(node) for node in next_nodes],
        "checkpoint_step": step,
    }


def _failed_status_payload(task_id: str, error: str) -> dict:
    """Status body for a failed task, including whether it can be resumed."""
    info = _resume_info(task_id)
    return {
        "task_id": task_id,
        "status": "failed",
        "error": error,
        "attempt": info["attempt"],
        "max_attempts": info["max_attempts"],
        "resumable": info["resumable"],
        "reason": info["reason"],
        "next_node": info["next_node"],
        "checkpoint_step": info["checkpoint_step"],
    }


@app.post("/research")
async def start_research(task: dict):
    checkpointer = await _get_sqlite_saver()
    thread_id = str(uuid.uuid4())
    orchestrator = ChiefEditorAgent(
        task,
        checkpointer=checkpointer,
        thread_id=thread_id,
    )
    task_id = orchestrator.task_id

    _active_tasks[task_id] = {
        "thread_id": thread_id,
        "orchestrator": orchestrator,
        "queue": asyncio.Queue(),
        "events": [],
        "status": "running",
        "cancel_requested": False,
    }

    # The handle is kept so a normal cancellation can reach the running task.
    _active_tasks[task_id]["task"] = asyncio.create_task(
        _run_research(task_id, orchestrator))

    return {"task_id": task_id, "status": "started"}


@app.post("/research/{task_id}/cancel")
async def cancel_research(task_id: str):
    """Normal cancellation path, used by the launcher before a forced stop.

    Cancelling the asyncio task is enough when the event loop is running. If the
    loop is blocked (which is the case the launcher's process guard exists for),
    this request times out and the guard stops the dedicated process instead.
    """
    entry = _active_tasks.get(task_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no active research {task_id}")
    entry["cancel_requested"] = True
    task = entry.get("task")
    if task is not None and not task.done():
        task.cancel()
    return {"task_id": task_id, "status": "cancelling"}


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
        payload["detail"] = node_data.get("detail", "")
    return f"event: {node_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _fail_before_dispatch(task_id: str, entry: dict, detail: str) -> None:
    """Fail the task visibly when research could not be started at all.

    No graph node runs and no research outbound call is made: the run record is a
    precondition for dispatch, so a missing record is a task failure rather than a
    warning printed beside a running task.
    """
    detail = f"research not started: {detail}"
    entry["status"] = "failed"
    entry["error"] = detail
    entry["events"].append({"__error__": {"detail": detail}})
    entry["queue"].put_nowait(_STREAM_ERROR)
    print_agent_output(f"{detail} ({task_id})", agent="SERVER")
    # The research task never ran, so its finally-block cleanup never will.
    checkpointer = getattr(entry.get("orchestrator"), "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    if conn is not None:
        try:
            await conn.close()
        except Exception:
            pass
    try:
        import run_limits

        # Best effort only; the record itself could not be written.
        run_limits.persist_counts(str(OUTPUT_DIR / task_id))
    except Exception:
        pass


async def _run_research(task_id: str, orchestrator: ChiefEditorAgent,
                        resume: bool = False):
    entry = _active_tasks[task_id]
    resume_attempt = max(1, int(entry.get("resume_attempt") or 1))

    # The run record starts from here — the moment research actually begins —
    # not from service start, and before the first node can block. The launcher's
    # guard takes its deadline from this record, so if it cannot be established
    # the task fails here: no node runs and no research outbound call is made.
    # A resumed attempt writes its own record: new attempt number, own budget.
    import run_limits

    try:
        run_limits.begin_run(task_id, str(OUTPUT_DIR / task_id),
                             attempt=resume_attempt)
    except Exception as record_err:
        await _fail_before_dispatch(task_id, entry, str(record_err))
        return

    end_state = "failed"
    try:
        stream = (orchestrator.resume_research_task() if resume
                  else orchestrator.astream_research_task())
        async for event in stream:
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
        end_state = "complete"
    except asyncio.CancelledError:
        # Normal cancellation (HTTP cancel or stream timer). Recorded as
        # cancelled — never as complete, and never as a forced stop.
        entry["status"] = "cancelled"
        entry["events"].append({"__error__": {"detail": "research cancelled"}})
        entry["queue"].put_nowait(_STREAM_ERROR)
        end_state = "cancelled"
        raise
    except Exception as e:
        # I1 fix: persist whatever the checkpoint holds so a failed run is
        # inspectable after restart instead of vanishing with process memory.
        # The checkpoint position is saved with it so a later resume knows where
        # to continue without opening the checkpoint database.
        try:
            state = await orchestrator.get_state()
            partial = dict(state.values) if state and state.values else {}
            partial["_resume"] = _resume_metadata(state, resume_attempt)
            save_failed_snapshot(task_id, partial, str(e))
            entry["resume"] = partial["_resume"]
        except Exception as persist_err:
            print_agent_output(f"Failed to persist failure snapshot for {task_id}: {persist_err}", agent="SERVER")
        entry["status"] = "failed"
        entry["error"] = str(e)
        entry["events"].append({"__error__": {"detail": str(e)}})
        entry["queue"].put_nowait(_STREAM_ERROR)
        end_state = "failed"
    finally:
        # I6 fix: the per-request sqlite connection must not outlive the task.
        checkpointer = getattr(orchestrator, "checkpointer", None)
        conn = getattr(checkpointer, "conn", None)
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
        # A resumed attempt owns its lock until it ends, whatever the outcome.
        lock = entry.get("resume_lock")
        if lock is not None and lock.locked():
            try:
                lock.release()
            except RuntimeError:
                pass
        # Save the request counters when this research ends, whatever the
        # outcome, instead of waiting for the whole service to stop. This
        # persists the counters that already exist; it adds no new accounting.
        try:
            import run_limits

            # Record how the run ended before the counters, so an abnormal exit
            # can never be read as a completion.
            run_limits.end_run(end_state)
            run_limits.persist_counts(str(OUTPUT_DIR / task_id))
        except Exception as persist_counts_err:
            print_agent_output(
                f"Could not persist run counters for {task_id}: {persist_counts_err}",
                agent="SERVER",
            )


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
async def research_status(task_id: str):
    entry = _active_tasks.get(task_id)
    if entry and entry.get("status") == "complete":
        return {
            "task_id": task_id,
            "status": "complete",
            "confidence": entry.get("result", {}).get("confidence", ""),
            "resumable": False,
            "reason": "already_complete",
        }
    if entry and entry.get("status") == "failed":
        return _failed_status_payload(task_id, entry.get("error", ""))
    if entry and entry.get("status") == "resuming":
        orchestrator = entry.get("orchestrator")
        return {
            "task_id": task_id,
            "status": "resuming",
            "attempt": entry.get("resume_attempt"),
            "phase": getattr(orchestrator, "live_phase", None) or "starting",
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
            return {
                "task_id": task_id,
                "status": "complete",
                "resumable": False,
                "reason": "already_complete",
            }
        failed = load_failed_snapshot(task_id)
        if failed:
            # A failed run stays inspectable after a restart instead of reading
            # as "task not found"; the partial snapshot carries what ended it and
            # whether the checkpoint has pending nodes to resume from.
            return _failed_status_payload(task_id, failed.get("_error", ""))
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": "running",
        "phase": "unknown",
    }


@app.post("/research/{task_id}/resume")
async def resume_research(task_id: str, body: dict | None = None):
    """Continue a failed task from its latest checkpoint.

    Disabled by default (RESUME_ENABLED=0). Every refusal is explicit: the caller
    learns whether the task is complete, exhausted, written by another graph
    schema, or simply has no pending checkpoint nodes.
    """
    if not resume_enabled():
        raise HTTPException(
            status_code=404,
            detail="RESUME_DISABLED: resume is disabled (RESUME_ENABLED=0)",
        )
    if not body or body.get("confirm") is not True:
        raise HTTPException(
            status_code=400,
            detail='RESUME_CONFIRM_REQUIRED: pass {"confirm": true}',
        )

    complete = load_snapshot(task_id)
    failed = load_failed_snapshot(task_id)
    run_state = _task_run_state(task_id)
    if not complete and not failed and not run_state:
        raise HTTPException(status_code=404, detail="Task not found")

    info = build_resume_info(
        complete_snapshot=complete,
        failed_snapshot=failed,
        run_state=run_state,
        current_schema_version=_current_schema_version(),
    )
    if not info["resumable"]:
        code, status_code = _RESUME_REASON_ERRORS.get(
            info["reason"], ("NOT_RESUMABLE", 409))
        raise HTTPException(
            status_code=status_code,
            detail=f"{code}: {info['reason']}",
        )

    entry = _active_tasks.get(task_id)
    if entry and entry.get("status") in {"running", "resuming"}:
        raise HTTPException(
            status_code=409,
            detail="RESUME_IN_PROGRESS: task is already running",
        )
    lock = _resume_locks.setdefault(task_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail="RESUME_IN_PROGRESS: a resume is already in progress",
        )
    await lock.acquire()

    spawned = False
    checkpointer = None
    try:
        checkpointer = await _get_sqlite_saver()
        if checkpointer is None:
            raise HTTPException(
                status_code=409,
                detail="NOT_RESUMABLE: checkpoint store unavailable",
            )
        task = (failed or {}).get("task") or {}
        # Confirm the checkpoint really has pending nodes before starting: the
        # saved metadata can be stale if the database was pruned.
        probe = ChiefEditorAgent(task, checkpointer=checkpointer,
                                 thread_id=task_id)
        state = await probe.get_state()
        next_nodes = list(getattr(state, "next", None) or ())
        if not next_nodes:
            raise HTTPException(
                status_code=409,
                detail="NOT_RESUMABLE: no pending checkpoint nodes",
            )

        orchestrator = ChiefEditorAgent(task, checkpointer=checkpointer,
                                        thread_id=task_id)
        attempt = int(info["attempt"]) + 1
        _active_tasks[task_id] = {
            "thread_id": task_id,
            "orchestrator": orchestrator,
            "queue": asyncio.Queue(),
            "events": [],
            "status": "resuming",
            "cancel_requested": False,
            "resume_attempt": attempt,
            "resume_lock": lock,
        }
        _active_tasks[task_id]["task"] = asyncio.create_task(
            _run_research(task_id, orchestrator, resume=True))
        spawned = True
        print_agent_output(
            f"Resuming {task_id} from checkpoint (attempt {attempt}/"
            f"{info['max_attempts']})", agent="SERVER")
        return JSONResponse(status_code=202, content={
            "task_id": task_id,
            "status": "resuming",
            "attempt": attempt,
            "max_attempts": info["max_attempts"],
            "next_nodes": next_nodes,
            "next_node": next_nodes[0],
            "checkpoint_step": info["checkpoint_step"],
        })
    finally:
        if not spawned:
            if checkpointer is not None:
                conn = getattr(checkpointer, "conn", None)
                if conn is not None:
                    try:
                        await conn.close()
                    except Exception:
                        pass
            if lock.locked():
                try:
                    lock.release()
                except RuntimeError:
                    pass


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
        raise HTTPException(status_code=500, detail=str(e))


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
        # A failed run persists its partial snapshot under a separate file. It is
        # served here (marked `_status: failed` and carrying `_error`) so the
        # partial result is inspectable rather than answering 404.
        snapshot = load_failed_snapshot(task_id)
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
async def task_status(task_id: str):
    """Convenience alias for /research/{task_id}/status."""
    return await research_status(task_id)


@app.get("/history")
async def history():
    return {"tasks": list_history()}
