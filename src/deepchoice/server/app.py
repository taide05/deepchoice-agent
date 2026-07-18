import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from ..agents.orchestrator import ChiefEditorAgent
from .snapshot_store import save_snapshot, load_snapshot, save_report, list_history
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first
from ..formats.comparison_matrix import render as render_comparison_matrix
from .clarify_routes import router as clarify_router

app = FastAPI(title="DeepChoice API", version="0.1.0")
app.include_router(clarify_router)

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
    orchestrator = ChiefEditorAgent(task)
    task_id = orchestrator.task_id

    state_proxy = {
        "task": task,
        "sub_questions": [],
        "search_results": [],
        "source_scores": [],
        "conflicts": [],
        "evidence_chains": [],
        "report": "",
        "confidence": "",
        "knowledge_gaps": [],
        "retry_count": 0,
        "partial_failures": [],
        "current_phase": "",
    }
    _active_tasks[task_id] = state_proxy

    asyncio.create_task(_run_research(task_id, orchestrator, state_proxy))

    return {"task_id": task_id, "status": "started"}


async def _run_research(task_id: str, orchestrator: ChiefEditorAgent, state_proxy: dict):
    try:
        state_proxy["current_phase"] = "query_analysis"
        result = await orchestrator.run_research_task()

        for key in state_proxy:
            if key in result:
                state_proxy[key] = result[key]

        state_proxy["current_phase"] = "complete"
        save_snapshot(task_id, result)
        save_report(task_id, result.get("report", ""))
    except Exception as e:
        state_proxy["current_phase"] = "complete"
        state_proxy["confidence"] = "low"
        state_proxy["report"] = f"Research failed: {str(e)}"


@app.get("/research/{task_id}/stream")
async def stream_research(task_id: str):
    state_proxy = _active_tasks.get(task_id)
    if not state_proxy:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        phases = [
            "query_analysis", "retrieval", "source_evaluation",
            "conflict_detection", "evidence_chain", "report_generation", "self_review",
        ]
        last_phase = None
        while True:
            current = state_proxy.get("current_phase", "")
            if current != last_phase:
                if last_phase and last_phase != "complete":
                    yield f"data: {json.dumps({'phase': last_phase, 'status': 'done'})}\n\n"
                if current and current != "complete":
                    yield f"data: {json.dumps({'phase': current, 'status': 'running'})}\n\n"
                last_phase = current

            if current == "complete":
                yield f"data: {json.dumps({'phase': 'complete', 'status': 'done', 'confidence': state_proxy.get('confidence', '')})}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/research/{task_id}/status")
async def research_status(task_id: str):
    state_proxy = _active_tasks.get(task_id)
    if not state_proxy:
        snapshot = load_snapshot(task_id)
        if snapshot:
            return {"task_id": task_id, "status": "complete"}
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task_id,
        "status": "running",
        "phase": state_proxy.get("current_phase", ""),
    }


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
