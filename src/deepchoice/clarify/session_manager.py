import re
import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..security.input_limits import validate_safe_text

BoundedStateText = Annotated[str, StringConstraints(max_length=4000)]
ShortStateText = Annotated[str, StringConstraints(max_length=500)]
SESSION_ID_PATTERN = re.compile(r"^clarify_[0-9a-f]{12}$")


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    session_id: str = ""
    status: Literal["clarifying","ready","running","done"] = "clarifying"
    
    candidate_techs: list[ShortStateText] = Field(default_factory=list, max_length=50)
    scene: Literal["solo","team","enterprise"] | None = None
    complexity: Literal["simple","medium","complex"] | None = None

    constraints: list[ShortStateText] = Field(default_factory=list, max_length=50)
    unknown_techs: bool = False

    clarify_rounds: int = Field(default=0, ge=0, le=100)
    filled_required: list[ShortStateText] = Field(default_factory=list, max_length=20)
    missing_required: list[ShortStateText] = Field(default_factory=list, max_length=20)
    clarity_score: float = Field(default=0.0, ge=0.0, le=1.0)

    messages: list[dict[str, BoundedStateText]] = Field(default_factory=list, max_length=40)

    clarified_task: dict | None = None
    sub_questions: list[ShortStateText] | None = Field(default=None, max_length=20)
    last_active: float = Field(default_factory = time.time)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if value and not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid session id")
        return value

    @field_validator(
        "candidate_techs",
        "constraints",
        "filled_required",
        "missing_required",
        "sub_questions",
    )
    @classmethod
    def validate_text_collections(cls, values):
        if values is not None:
            for value in values:
                validate_safe_text(value)
        return values

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, values: list[dict[str, str]]) -> list[dict[str, str]]:
        for message in values:
            if set(message) != {"role", "content"}:
                raise ValueError("session message shape is invalid")
            if message["role"] not in {"user", "assistant"}:
                raise ValueError("session message role is invalid")
            validate_safe_text(message["content"])
            maximum = 2000 if message["role"] == "user" else 4000
            if not message["content"] or len(message["content"]) > maximum:
                raise ValueError("session message length is invalid")
        return values

    def append_message(self, role: Literal["user", "assistant"], content: str) -> None:
        safe_content = validate_safe_text(str(content))
        max_length = 2000 if role == "user" else 4000
        if not safe_content or len(safe_content) > max_length:
            raise ValueError("session message length is invalid")
        updated = [*self.messages, {"role": role, "content": safe_content}]
        # Assignment validation enforces the collection and item bounds.
        self.messages = updated

class SessionManager:
    SESSION_TIMEOUT = 1800
    KNOWN_TECHS = {
        "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#",
        "fastapi", "flask", "django", "express", "next.js", "react", "vue", "angular",
        "postgresql", "mysql", "mongodb", "redis", "sqlite", "elasticsearch",
        "docker", "kubernetes", "nginx", "git", "github", "gitlab", "ci/cd",
        "aws", "azure", "gcp", "linux", "bash", "shell",
        "langchain", "langgraph", "llamaIndex", "chromadb", "pinecone", "weaviate",
        "mcp", "openai", "anthropic", "huggingface", "ollama", "vllm",
        "rag", "agent", "llm", "embedding", "vector", "prompt",
        "rest", "graphql", "grpc", "websocket", "kafka", "rabbitmq",
        "pytorch", "tensorflow", "jupyter", "pandas", "numpy",
        "streamlit", "celery", "pytest", "pre-commit", "swagger",
    } 

    def __init__(self):
        self._sessions = {}
    
    def create(self,query:str) -> dict:
        query = query.strip()
        if not query or len(query) > 4000:
            raise ValueError("query length is invalid")
        validate_safe_text(query)
        session_id = f"clarify_{uuid4().hex[:12]}"
        state = self._extract_initial_state(query)
        state.session_id = session_id
        state.append_message("user", query)
        self._sessions[session_id] = state
        return self._response(state)

    def _extract_initial_state(self, query: str) -> SessionState:
        state = SessionState()
        state.missing_required = ["candidate_techs","scene","complexity"]
        state.clarity_score = 0.15
        response = self._detect_tech_keywords(query)
        if response:
            state.candidate_techs = response
            state.missing_required.remove("candidate_techs")
            state.filled_required.append("candidate_techs")
        else:
            state.unknown_techs = True
        return state

    def _response(self, state: SessionState) -> dict:
        return {
            "session_id": state.session_id,
            "status": state.status,
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
        }

    def _detect_tech_keywords(self,query: str) -> list[str]:
        lowered = query.lower()
        found = []        
        for tech in self.KNOWN_TECHS:
            if re.search(rf"\b{re.escape(tech)}\b", lowered):
                found.append(tech)
        return found

    def process_message(self,session_id:str,message:str) -> dict:
        state = self._get_or_raise(session_id)
        message = message.strip()
        if not message or len(message) > 2000:
            raise ValueError("message length is invalid")
        validate_safe_text(message)
        state.last_active = time.time()
        state.append_message("user", message)
        state.clarify_rounds += 1
        return self._response(state)

    def _get_or_raise(self,session_id:str) -> SessionState:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise KeyError
        if session_id not in self._sessions:
            raise KeyError
        state = self._sessions[session_id]
        if time.time() - state.last_active > self.SESSION_TIMEOUT:
            del self._sessions[session_id]
            raise KeyError
        return state

    def get(self, session_id: str) -> SessionState:
        """Public accessor for a session state; raises KeyError if missing/expired."""
        return self._get_or_raise(session_id)

    def _apply_soft_gate(self,state:SessionState) -> SessionState:
        if state.scene is None:
            state.scene = "team"
        if state.complexity is None:
            state.complexity = "medium"
        state.filled_required = []
        state.missing_required = []
        if state.candidate_techs:
            state.filled_required.append("candidate_techs")
        else:
            state.missing_required.append("candidate_techs")
        if state.scene is not None:
            state.filled_required.append("scene")
        else:
            state.missing_required.append("scene")
        if state.complexity is not None:
            state.filled_required.append("complexity")
        else:
            state.missing_required.append("complexity")
        state.clarity_score = len(state.filled_required)/(len(state.missing_required) + len(state.filled_required))
        return state
    
    def finalize(self,session_id:str) -> dict:
        state = self._get_or_raise(session_id)
        self._apply_soft_gate(state)
        state.status = "ready"
        return self._response(state)
    
    def get_status(self,session_id:str) -> dict:
        state = self._get_or_raise(session_id)
        return self._response(state)
