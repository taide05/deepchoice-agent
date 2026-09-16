from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from ..clarify.clarification_agent import ClarificationAgent
from ..clarify.session_manager import SessionManager
from ..security.input_limits import validate_safe_text

router = APIRouter(prefix="/clarify", tags=["clarify"])
session_manager = SessionManager()
clarify_agent = ClarificationAgent()


SessionId = Annotated[
    str,
    Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return validate_safe_text(value)


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return validate_safe_text(value)


@router.post("/start")
async def start_clarify(req: StartRequest):
    result = session_manager.create(req.query)
    session_id = result["session_id"]
    state = session_manager.get(session_id)

    agent_response = await clarify_agent.decide_and_respond(state)
    state.append_message("assistant", agent_response["answer"])

    return {
        "session_id": session_id,
        "answer": agent_response["answer"],
        "next_action": agent_response["action"],
        **{k: v for k, v in agent_response.items() if k not in ("action", "answer")},
    }


@router.post("/{session_id}/message")
async def clarify_message(session_id: SessionId, req: MessageRequest):
    try:
        session_manager.process_message(session_id, req.message)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    state = session_manager.get(session_id)
    agent_response = await clarify_agent.decide_and_respond(state)

    if agent_response.get("action") == "confirm":
        state.status = "ready"

    state.append_message("assistant", agent_response["answer"])

    return {
        "session_id": session_id,
        "answer": agent_response["answer"],
        "next_action": agent_response["action"],
        **{k: v for k, v in agent_response.items() if k not in ("action", "answer")},
    }


@router.get("/{session_id}/status")
async def clarify_status(session_id: SessionId):
    try:
        return session_manager.get_status(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")


@router.post("/{session_id}/finalize")
async def clarify_finalize(session_id: SessionId):
    try:
        session_manager.finalize(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    state = session_manager.get(session_id)
    final_response = await clarify_agent.finalize(state)
    state.append_message("assistant", final_response["answer"])

    return final_response
