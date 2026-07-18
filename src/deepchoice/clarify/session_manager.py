import time
from uuid import uuid4
from pydantic import BaseModel,Field
from typing import Literal

class SessionState(BaseModel):
    session_id: str = ""
    status: Literal["clarifying","ready","running","done"] = "clarifying"
    
    candidate_techs: list[str] = []
    scene: Literal["solo","team","enterprise"] | None = None
    complexity: Literal["simple","medium","complex"] | None = None

    constraints: list[str] = []
    unknown_techs: bool = False
    tech_recommendations: list[dict] = []

    clarify_rounds: int = 0
    filled_required: list[str] = []
    missing_required: list[str] = []
    clarity_score: float = 0.0

    messages: list[dict] = []

    clarified_task: dict | None = None
    sub_questions: list[str] | None = None
    last_active: float = Field(default_factory = time.time)

class SessionManager():
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
        session_id = f"clarify_{uuid4().hex[:12]}"
        state = self._extract_initial_state(query)
        self._sessions[session_id] = state
        state.session_id = session_id
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
        for i in self.KNOWN_TECHS:
            if i in lowered:
                found.append(i)
        return found

    def process_message(self,session_id:str,message:str) -> dict:
        state = self._get_or_raise(session_id)
        state.last_active = time.time()
        user_message = {"role":"user","content":message}
        state.messages.append(user_message)
        state.clarify_rounds += 1
        self._update_state_from_message(state,message)
        return self._response(state)

    def _get_or_raise(self,session_id:str) -> SessionState:
        if session_id not in self._sessions:
            raise KeyError
        state = self._sessions[session_id]
        if time.time() - state.last_active > self.SESSION_TIMEOUT:
            del self._sessions[session_id]
            raise KeyError
        return state

    def _update_state_from_message(self, state: SessionState, message: str) -> SessionState:
        return state

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

    def _cleanup_expired(self):
        for sid in list(self._sessions.keys()):
            state = self._sessions[sid]
            if time.time() - state.last_active > self.SESSION_TIMEOUT:
                del self._sessions[sid]
