from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..clarify.clarification_agent import ClarificationAgent
from ..clarify.session_manager import SessionManager, SessionState
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


class FinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clarify_rounds: int | None = Field(default=None, ge=0, le=100, strict=True)
    review_only: bool = Field(default=False, strict=True)


def _commit_response(state: SessionState, count: int, draft: SessionState) -> None:
    try:
        session_manager.commit_response(state, count, draft)
    except (KeyError, ValueError):
        raise HTTPException(status_code=409, detail="Clarification changed; review the current requirements")


async def _respond(state: SessionState) -> dict:
    count = len(state.messages)
    draft = state.model_copy(deep=True)
    agent_response = await clarify_agent.decide_and_respond(draft)
    draft.status = "ready" if agent_response.get("action") == "confirm" else "clarifying"
    draft.append_message("assistant", agent_response["answer"])
    _commit_response(state, count, draft)
    return {
        "session_id": draft.session_id,
        "answer": agent_response["answer"],
        "next_action": agent_response["action"],
        **{k: v for k, v in agent_response.items() if k not in ("action", "answer")},
    }


@router.post("/start")
async def start_clarify(req: StartRequest):
    result = session_manager.create(req.query)
    return await _respond(session_manager.get(result["session_id"]))


@router.post("/{session_id}/message")
async def clarify_message(session_id: SessionId, req: MessageRequest):
    try:
        session_manager.process_message(session_id, req.message)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unresolved input or session is full; start a new session with the complete request")
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return await _respond(session_manager.get(session_id))


@router.get("/{session_id}/status")
async def clarify_status(session_id: SessionId):
    try:
        return session_manager.get_status(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")


@router.post("/{session_id}/finalize")
async def clarify_finalize(session_id: SessionId, req: FinalizeRequest | None = None):
    try:
        session_manager.finalize(session_id, expected_round=req.clarify_rounds if req else None,
                                 review_only=req.review_only if req else False)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    except ValueError:
        raise HTTPException(status_code=409, detail="Review or clarify the latest requirements before finalizing")

    state = session_manager.get(session_id)
    count = len(state.messages)
    draft = state.model_copy(deep=True)
    final_response = (clarify_agent.prepare_confirmation(draft) if req and req.review_only
                      else await clarify_agent.finalize(draft))
    draft.append_message("assistant", final_response["answer"])
    _commit_response(state, count, draft)
    return final_response
