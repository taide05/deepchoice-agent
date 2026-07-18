from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..clarify.session_manager import SessionManager
from ..clarify.clarification_agent import ClarificationAgent

router = APIRouter(prefix="/clarify", tags=["clarify"])
session_manager = SessionManager()
clarify_agent = ClarificationAgent()


class StartRequest(BaseModel):
    query: str


class MessageRequest(BaseModel):
    message: str


@router.post("/start")
async def start_clarify(req: StartRequest):
    result = session_manager.create(req.query)
    session_id = result["session_id"]
    state = session_manager._sessions[session_id]

    agent_response = await clarify_agent.decide_and_respond(state)
    state.messages.append({"role": "assistant", "content": agent_response["answer"]})

    return {
        "session_id": session_id,
        "answer": agent_response["answer"],
        "next_action": agent_response["action"],
        **{k: v for k, v in agent_response.items() if k not in ("action", "answer")},
    }


@router.post("/{session_id}/message")
async def clarify_message(session_id: str, req: MessageRequest):
    try:
        session_manager.process_message(session_id, req.message)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    state = session_manager._sessions[session_id]
    agent_response = await clarify_agent.decide_and_respond(state)

    if agent_response.get("action") == "confirm":
        state.status = "ready"

    state.messages.append({"role": "assistant", "content": agent_response["answer"]})

    return {
        "session_id": session_id,
        "answer": agent_response["answer"],
        "next_action": agent_response["action"],
        **{k: v for k, v in agent_response.items() if k not in ("action", "answer")},
    }


@router.get("/{session_id}/status")
async def clarify_status(session_id: str):
    try:
        return session_manager.get_status(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")


@router.post("/{session_id}/finalize")
async def clarify_finalize(session_id: str):
    try:
        session_manager.finalize(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    state = session_manager._sessions[session_id]
    final_response = await clarify_agent._handle_finalize(state)
    state.messages.append({"role": "assistant", "content": final_response["answer"]})

    return final_response
