import json
import asyncio
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from ..agents.orchestrator import ChiefEditorAgent, _get_sqlite_saver
from .snapshot_store import save_snapshot, load_snapshot, save_report, list_history
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first
from ..formats.comparison_matrix import render as render_comparison_matrix
from .clarify_routes import router as clarify_router

app = FastAPI(title="DeepChoice API", version="0.1.0")
app.include_router(clarify_router)

OUTPUT_DIR = Path("./outputs")
_active_tasks: dict[str, dict] = {}
FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}


@app.get("/health")
async def health():
    return {"status": "ok"}


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
    }

    asyncio.create_task(_run_research(task_id, orchestrator))

    return {"task_id": task_id, "status": "started"}


async def _run_research(task_id: str, orchestrator: ChiefEditorAgent):
    try:
        result = await orchestrator.run_research_task()

        save_snapshot(task_id, result)
        save_report(task_id, result.get("report", ""))

        _active_tasks.pop(task_id, None)
        _active_tasks[task_id] = {
            "thread_id": orchestrator.thread_id,
            "orchestrator": orchestrator,
            "status": "complete",
            "result": result,
        }
    except Exception as e:
        _active_tasks[task_id] = {
            "thread_id": orchestrator.thread_id,
            "orchestrator": orchestrator,
            "status": "failed",
            "error": str(e),
        }


@app.get("/research/{task_id}/stream")
async def stream_research(task_id: str):
    entry = _active_tasks.get(task_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")

    orchestrator = entry.get("orchestrator")
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Orchestrator not found")

    async def event_generator():
        try:
            async for event in orchestrator.astream_research_task():
                node_name = list(event.keys())[0]
                node_data = event[node_name]
                yield f"data: {json.dumps({'node': node_name, 'update': node_data}, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        yield f"data: {json.dumps({'node': '__done__', 'update': {}})}\n\n"

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
            state = await orchestrator.get_state()
            if state and state.values:
                current = state.values.get("current_phase", "running")
                return {
                    "task_id": task_id,
                    "status": "running",
                    "phase": current,
                    "checkpoint_step": state.metadata.get("step", -1) if state.metadata else -1,
                }
        except Exception:
            pass

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


@app.get("/history")
async def history():
    return {"tasks": list_history()}
