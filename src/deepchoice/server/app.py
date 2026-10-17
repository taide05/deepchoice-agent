import asyncio
import json
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse

from ..agents.orchestrator import ChiefEditorAgent, _get_sqlite_saver
from ..formats.citations import build_toc, inject_citations, number_sources
from ..formats.comparison_matrix import render as render_comparison_matrix
from ..formats.evidence_first import render as render_evidence_first
from ..formats.pdf import render_pdf
from ..formats.what_why_how import render as render_what_why_how
from ..utils.views import print_agent_output
from .clarify_routes import router as clarify_router
from .snapshot_store import (
    list_history,
    load_snapshot,
    save_failed_snapshot,
    save_report,
    save_snapshot,
)

app = FastAPI(title="DeepChoice API", version="0.1.0")
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


async def _run_research(task_id: str, orchestrator: ChiefEditorAgent):
    entry = _active_tasks[task_id]

    # The run record starts from here — the moment research actually begins —
    # not from service start, and before the first node can block. The launcher's
    # guard takes its deadline from this record, so if it cannot be established
    # the task fails here: no node runs and no research outbound call is made.
    import run_limits

    try:
        run_limits.begin_run(task_id, str(OUTPUT_DIR / task_id))
    except Exception as record_err:
        await _fail_before_dispatch(task_id, entry, str(record_err))
        return

    end_state = "failed"
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
        try:
            state = await orchestrator.get_state()
            partial = state.values if state else {}
            save_failed_snapshot(task_id, partial, str(e))
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
        }
    if entry and entry.get("status") == "failed":
        return {
            "task_id": task_id,
            "status": "failed",
            "error": entry.get("error", ""),
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
        raise HTTPException(status_code=404, detail="Task not found")

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
