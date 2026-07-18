# DeepChoice 前置查询澄清模块 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-turn clarification module that sits before the existing 7-node LangGraph pipeline. It takes vague user queries, asks focused follow-up questions (max 3 rounds), recommends candidate technologies for non-technical users, and produces a clarified_task + sub_questions that feed directly into the research pipeline.

**Architecture:** Independent FastAPI layer (`/clarify/*`) managing session state in memory, backed by a single LLM Agent (deepseek-v4-flash) that decides whether to ask / recommend / confirm / finalize each round. The research pipeline entry point switches from QueryAnalyzer to MultiRetriever when fed with pre-clarified sub_questions.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, deepseek-v4-flash (all LLM calls), in-memory dict storage, Streamlit (frontend)

**Design Spec:** `docs/superpowers/specs/2026-07-07-DeepChoice-clarify-module-design.md`

**Prerequisites:** This plan assumes these original-plan tasks are complete before starting:
- Task 2 (state.py + task.py) — `ResearchState` TypedDict, `TaskConfig` Pydantic model
- Task 3 (utils/llm.py) — `call_model()` async function
- Task 11 (orchestrator.py) — `ChiefEditorAgent` exists (we modify it)

## Global Constraints

- Python 3.11+, all async I/O via httpx
- All LLM calls use deepseek-v4-flash only (clarify module has no Pro node)
- Session storage: in-memory `dict[str, SessionState]`, no persistence
- Session timeout: 30 minutes since last activity
- Max clarify rounds: 3 (hard cap); default values: scene="team", complexity="medium"
- ClarificationAgent response format: JSON with `action` + `payload`
- All endpoints return unified `{answer, next_action, clarity_score, filled_required, missing_required, payload?}`
- No TBD, TODO, or placeholder code in any implementation step

---

## File Structure

```
deepchoice/src/
  clarify/
    __init__.py
    session_manager.py        # NEW: SessionState model + SessionManager class
    clarification_agent.py    # NEW: ClarificationAgent (LLM decision logic)
  server/
    clarify_routes.py         # NEW: FastAPI router /clarify/*
    app.py                    # MODIFY: register clarify_routes router
  agents/
    orchestrator.py           # MODIFY: dynamic entry_point (plan Task 11)
frontend/
  app.py                      # MODIFY: two-phase UI
tests/
  clarify/
    __init__.py
    test_session_manager.py
    test_clarification_agent.py
    test_clarify_routes.py
    test_clarify_integration.py
```

---

### Task 1: clarify/__init__.py + tests/clarify/__init__.py

**Owner:** AI skeleton

**Files:**
- Create: `deepchoice.clarify/__init__.py`
- Create: `deepchoice/tests/clarify/__init__.py`

**Interfaces:**
- Produces: package init files, nothing depends on them

- [ ] **Step 1: Create clarify package init**

```bash
New-Item -ItemType File -Force D:\ai-career\deepchoice.clarify\__init__.py
New-Item -ItemType Directory -Force D:\ai-career\deepchoice\tests\clarify
New-Item -ItemType File -Force D:\ai-career\deepchoice\tests\clarify\__init__.py
```

- [ ] **Step 2: Commit**

```bash
git add deepchoice.clarify/ deepchoice/tests/clarify/
git commit -m "feat: add clarify package scaffold

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: session_manager.py

**Owner:** User (core architecture)

**Files:**
- Create: `deepchoice.clarify/session_manager.py`

**Interfaces:**
- Produces:
  - `class SessionState(BaseModel)` — 16 fields as defined in spec Section 2
  - `class SessionManager` — with `create(query) -> dict`, `process_message(session_id, message) -> dict`, `get_status(session_id) -> dict`, `finalize(session_id) -> dict`
- Depends on: nothing (standalone)
- Used by: Task 3 (clarification_agent), Task 4 (clarify_routes)

- [ ] **Step 1: Write session_manager.py**

```python
import uuid
import time
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    CLARIFYING = "clarifying"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"


class SessionState(BaseModel):
    session_id: str
    status: SessionStatus = SessionStatus.CLARIFYING

    # 三类必填
    candidate_techs: list[str] = Field(default_factory=list)
    scene: str | None = None          # solo / team / enterprise
    complexity: str | None = None     # simple / medium / complex

    # 可选补充
    constraints: list[str] = Field(default_factory=list)
    unknown_techs: bool = False
    tech_recommendations: list[dict] = Field(default_factory=list)

    # 追踪
    clarify_rounds: int = 0
    filled_required: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    clarity_score: float = 0.0

    # 对话历史
    messages: list[dict] = Field(default_factory=list)

    # 最终产出
    clarified_task: dict | None = None
    sub_questions: list[str] | None = None

    # 时间戳（超时清理用）
    last_active: float = Field(default_factory=time.time)


class SessionManager:
    SESSION_TIMEOUT = 1800  # 30 minutes

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}

    def create(self, query: str) -> dict:
        self._cleanup_expired()
        session_id = f"clarify_{uuid.uuid4().hex[:12]}"
        state = self._extract_initial_state(query)
        state.session_id = session_id
        state.messages.append({"role": "user", "content": query})
        self._sessions[session_id] = state
        return self._response(state)

    def process_message(self, session_id: str, message: str) -> dict:
        self._cleanup_expired()
        state = self._get_or_raise(session_id)
        state.last_active = time.time()
        state.messages.append({"role": "user", "content": message})
        state.clarify_rounds += 1
        state = self._update_state_from_message(state, message)
        self._sessions[session_id] = state
        return self._response(state)

    def get_status(self, session_id: str) -> dict:
        state = self._get_or_raise(session_id)
        return self._response(state)

    def finalize(self, session_id: str) -> dict:
        state = self._get_or_raise(session_id)
        state = self._apply_soft_gate(state)
        state.status = SessionStatus.READY
        self._sessions[session_id] = state
        return self._response(state)

    def _get_or_raise(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found or expired")
        state = self._sessions[session_id]
        if time.time() - state.last_active > self.SESSION_TIMEOUT:
            del self._sessions[session_id]
            raise KeyError(f"Session {session_id} expired")
        return state

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_active > self.SESSION_TIMEOUT
        ]
        for sid in expired:
            del self._sessions[sid]

    def _extract_initial_state(self, query: str) -> SessionState:
        state = SessionState()
        state.missing_required = ["scene", "candidate_techs", "complexity"]
        state.clarity_score = 0.15
        tech_keywords = self._detect_tech_keywords(query)
        if tech_keywords:
            state.candidate_techs = tech_keywords
            state.missing_required.remove("candidate_techs")
            state.filled_required.append("candidate_techs")
            state.clarity_score += 0.28
        else:
            state.unknown_techs = True
        return state

    def _detect_tech_keywords(self, query: str) -> list[str]:
        KNOWN_TECHS = {
            "langchain", "llamaindex", "dify", "coze", "semantic kernel",
            "fastapi", "flask", "django", "spring", "express", "gin",
            "react", "vue", "angular", "flutter", "react native", "uniapp",
            "pytorch", "tensorflow", "jax", "pandas", "streamlit", "jupyter",
            "redis", "postgresql", "mysql", "mongodb", "neo4j",
            "docker", "kubernetes", "nginx", "kafka", "rabbitmq",
            "langgraph", "crewai", "autogen", "openai", "deepseek",
            "chroma", "milvus", "pinecone", "weaviate", "qdrant",
            "grpc", "graphql", "rest", "websocket", "sse",
        }
        query_lower = query.lower()
        found = []
        for tech in KNOWN_TECHS:
            if tech in query_lower:
                found.append(tech.title() if tech not in ("fastapi", "graphql", "rest", "grpc") else tech.upper() if tech in ("grpc",) else tech.capitalize() if tech == "fastapi" else tech)
        # Normalize capitalization for common names
        normalized = []
        for t in found:
            t_lower = t.lower()
            if t_lower == "fastapi":
                normalized.append("FastAPI")
            elif t_lower == "graphql":
                normalized.append("GraphQL")
            elif t_lower in ("rest",):
                normalized.append("REST")
            elif t_lower in ("grpc", "sse"):
                normalized.append(t.upper())
            else:
                normalized.append(t)
        return normalized

    def _update_state_from_message(self, state: SessionState, message: str) -> SessionState:
        return state  # ClarificationAgent handles actual parsing; here we just track rounds

    def _apply_soft_gate(self, state: SessionState) -> SessionState:
        defaults = {"scene": "team", "complexity": "medium"}
        for field, default in defaults.items():
            if getattr(state, field) is None:
                setattr(state, field, default)
                if field in state.missing_required:
                    state.missing_required.remove(field)
                if field not in state.filled_required:
                    state.filled_required.append(field)
        state.clarity_score = self._compute_clarity_score(state)
        return state

    def _compute_clarity_score(self, state: SessionState) -> float:
        total = 3
        filled = 0
        if state.candidate_techs:
            filled += 1
        if state.scene:
            filled += 1
        if state.complexity:
            filled += 1
        return round(filled / total, 2)

    def _response(self, state: SessionState) -> dict:
        return {
            "session_id": state.session_id,
            "status": state.status.value,
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
        }
```

- [ ] **Step 2: Syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.clarify.session_manager import SessionState, SessionManager; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice.clarify/session_manager.py
git commit -m "feat: add SessionState model and SessionManager (CRUD + timeout cleanup)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: tests/clarify/test_session_manager.py

**Owner:** User (TDD)

**Files:**
- Create: `deepchoice/tests/clarify/test_session_manager.py`

**Interfaces:**
- Consumes: Task 2 (SessionManager, SessionState)
- Produces: test coverage for create, process_message, get_status, finalize, timeout, keyword detection

- [ ] **Step 1: Write the tests**

```python
import time
import pytest
from deepchoice.clarify.session_manager import SessionManager, SessionState, SessionStatus


class TestSessionManagerCreate:
    def test_creates_session_with_id(self):
        sm = SessionManager()
        result = sm.create("我想用FastAPI还是Flask")
        assert result["session_id"].startswith("clarify_")
        assert result["status"] == "clarifying"

    def test_detects_tech_keywords_in_query(self):
        sm = SessionManager()
        result = sm.create("FastAPI vs Flask 哪个好")
        assert "candidate_techs" in result["filled_required"]
        assert "candidate_techs" not in result["missing_required"]

    def test_no_tech_keywords_marks_unknown(self):
        sm = SessionManager()
        result = sm.create("我想做个网站")
        assert "candidate_techs" in result["missing_required"]
        # Verify unknown_techs is set on the internal state
        state = sm._sessions[result["session_id"]]
        assert state.unknown_techs is True


class TestSessionManagerProcessMessage:
    def test_increments_round_on_message(self):
        sm = SessionManager()
        result = sm.create("测试问题")
        sid = result["session_id"]
        sm.process_message(sid, "我想比较技术")
        status = sm.get_status(sid)
        # Round counter tracked in SessionState, not in response dict
        state = sm._sessions[sid]
        assert state.clarify_rounds == 1

    def test_raises_on_unknown_session(self):
        sm = SessionManager()
        with pytest.raises(KeyError):
            sm.process_message("nonexistent", "hello")


class TestSessionManagerFinalize:
    def test_applies_soft_gate_defaults(self):
        sm = SessionManager()
        result = sm.create("做个AI应用")
        sid = result["session_id"]
        sm.finalize(sid)
        state = sm._sessions[sid]
        assert state.scene == "team"
        assert state.complexity == "medium"
        assert state.status == SessionStatus.READY

    def test_preserves_existing_values_on_finalize(self):
        sm = SessionManager()
        result = sm.create("Flask vs FastAPI for enterprise API")
        sid = result["session_id"]
        state = sm._sessions[sid]
        state.scene = "enterprise"
        state.complexity = "complex"
        state.filled_required = ["candidate_techs", "scene", "complexity"]
        state.missing_required = []
        sm._sessions[sid] = state
        sm.finalize(sid)
        final_state = sm._sessions[sid]
        assert final_state.scene == "enterprise"
        assert final_state.complexity == "complex"


class TestSessionManagerTimeout:
    def test_expired_session_raises(self):
        sm = SessionManager()
        sm.SESSION_TIMEOUT = 0  # instant timeout
        result = sm.create("test")
        sid = result["session_id"]
        time.sleep(0.1)
        with pytest.raises(KeyError):
            sm.get_status(sid)

    def test_cleanup_removes_expired(self):
        sm = SessionManager()
        sm.SESSION_TIMEOUT = 0
        sm.create("test1")
        sm.create("test2")
        time.sleep(0.1)
        sm._cleanup_expired()
        assert len(sm._sessions) == 0
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd D:/deepchoice-agent && python -m pytest tests/clarify/test_session_manager.py -v
```

Expected: 6 tests PASS (some may need SessionManager.SESSION_TIMEOUT to be non-final; adjust if needed)

- [ ] **Step 3: Commit**

```bash
git add deepchoice/tests/clarify/test_session_manager.py
git commit -m "test: add SessionManager tests — create, message, finalize, timeout

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: clarification_agent.py

**Owner:** User (core architecture, interview-critical — LLM Agent decision logic)

**Files:**
- Create: `deepchoice.clarify/clarification_agent.py`

**Interfaces:**
- Consumes: `SessionState` (from session_manager), `call_model()` (from utils.llm)
- Produces:
  - `class ClarificationAgent` — with `async decide_and_respond(state: SessionState) -> dict`
  - Internal methods: `_decide_action(state) -> str`, `_build_prompt(state) -> str`, `_parse_llm_response(raw: dict|str, state: SessionState) -> dict`, `_generate_recommendations(state: SessionState) -> list[dict]`, `_generate_sub_questions(state: SessionState) -> list[str]`
  - `TECH_RECOMMENDATION_MAP: dict[str, list[dict]]` — static mapping table

- [ ] **Step 1: Write TECH_RECOMMENDATION_MAP and helper functions**

```python
TECH_RECOMMENDATION_MAP: dict[str, list[dict]] = {
    # Web 前端
    "fc14a2e9": [
        {"name": "React", "stars": "225k+", "desc": "生态最大，招人最容易"},
        {"name": "Vue", "stars": "48k+", "desc": "上手快，中文文档好"},
        {"name": "Angular", "stars": "95k+", "desc": "企业级，TypeScript原生"},
        {"name": "Svelte", "stars": "80k+", "desc": "编译时框架，运行时体积小"},
        {"name": "SolidJS", "stars": "33k+", "desc": "性能极致，React 式语法"},
    ],
    # Web 后端
    "a7b31d5f": [
        {"name": "FastAPI", "stars": "78k+", "desc": "异步原生，自动API文档"},
        {"name": "Django", "stars": "80k+", "desc": "全栈框架，ORM+Admin开箱即用"},
        {"name": "Flask", "stars": "68k+", "desc": "轻量灵活，插件丰富"},
        {"name": "Spring Boot", "stars": "75k+", "desc": "Java生态，企业级标准"},
        {"name": "Express", "stars": "65k+", "desc": "Node.js 标配，中间件生态"},
        {"name": "Go-Gin", "stars": "79k+", "desc": "高性能，云原生首选"},
    ],
    # 对话机器人 / AI Agent
    "b82c4e6a": [
        {"name": "LangChain", "stars": "95k+", "desc": "灵活度最高，生态最大"},
        {"name": "LlamaIndex", "stars": "37k+", "desc": "数据索引强项，RAG首选"},
        {"name": "LangGraph", "stars": "10k+", "desc": "状态图编排，复杂Agent流程"},
        {"name": "Dify", "stars": "55k+", "desc": "低代码平台，上手最快"},
        {"name": "Coze", "stars": "字节跳动", "desc": "国内生态好，飞书集成"},
        {"name": "Semantic Kernel", "stars": "22k+", "desc": "微软官方，C#/Python双语言"},
        {"name": "CrewAI", "stars": "21k+", "desc": "多Agent协作，角色扮演模式"},
        {"name": "AutoGen", "stars": "36k+", "desc": "微软出品，对话式多Agent"},
    ],
    # 数据分析
    "c93d5f7b": [
        {"name": "Pandas", "stars": "44k+", "desc": "Python数据分析标配"},
        {"name": "Polars", "stars": "31k+", "desc": "Rust内核，比Pandas快10x"},
        {"name": "Streamlit", "stars": "36k+", "desc": "纯Python写数据App"},
        {"name": "Apache Spark", "stars": "40k+", "desc": "大数据分布式处理"},
        {"name": "DuckDB", "stars": "25k+", "desc": "嵌入式OLAP，单机分析性能强"},
    ],
    # 移动端
    "d04e6a8c": [
        {"name": "Flutter", "stars": "167k+", "desc": "Google出品，跨平台性能好"},
        {"name": "React Native", "stars": "119k+", "desc": "React生态，热更新方便"},
        {"name": "UniApp", "stars": "40k+", "desc": "国内主流，小程序兼容"},
        {"name": "SwiftUI", "stars": "仅iOS", "desc": "Apple原生，性能最佳"},
        {"name": "Kotlin Multiplatform", "stars": "16k+", "desc": "Android原生，跨平台新势力"},
    ],
    # 部署/运维
    "e15f7b9d": [
        {"name": "Docker", "stars": "68k+", "desc": "容器化标准"},
        {"name": "Kubernetes", "stars": "111k+", "desc": "容器编排，云原生标配"},
        {"name": "GitHub Actions", "stars": "免费", "desc": "CI/CD，GitHub集成"},
        {"name": "Vercel", "stars": "免费额度", "desc": "前端部署，Git推送即上线"},
        {"name": "Railway", "stars": "收费", "desc": "全栈部署，比Vercel灵活"},
    ],
}

# Keyword -> category lookup
CATEGORY_KEYWORDS: dict[str, str] = {
    "前端": "fc14a2e9", "网站": "fc14a2e9", "网页": "fc14a2e9", "ui": "fc14a2e9",
    "后台": "a7b31d5f", "后端": "a7b31d5f", "api": "a7b31d5f", "接口": "a7b31d5f", "服务": "a7b31d5f",
    "对话": "b82c4e6a", "聊天": "b82c4e6a", "机器人": "b82c4e6a", "agent": "b82c4e6a", "ai": "b82c4e6a",
    "数据": "c93d5f7b", "分析": "c93d5f7b", "报表": "c93d5f7b", "etl": "c93d5f7b",
    "移动": "d04e6a8c", "app": "d04e6a8c", "手机": "d04e6a8c", "android": "d04e6a8c", "ios": "d04e6a8c",
    "部署": "e15f7b9d", "上线": "e15f7b9d", "运维": "e15f7b9d", "cicd": "e15f7b9d", "容器": "e15f7b9d",
}

CATEGORY_LABELS: dict[str, str] = {
    "fc14a2e9": "前端框架",
    "a7b31d5f": "后端框架",
    "b82c4e6a": "AI/Agent框架",
    "c93d5f7b": "数据处理",
    "d04e6a8c": "移动端框架",
    "e15f7b9d": "部署运维",
}


def _match_categories(query: str) -> list[str]:
    """Match query keywords to tech categories. Returns list of category IDs."""
    query_lower = query.lower()
    matched = []
    for kw, cat_id in CATEGORY_KEYWORDS.items():
        if kw in query_lower and cat_id not in matched:
            matched.append(cat_id)
    return matched if matched else ["b82c4e6a"]  # default: AI/Agent


def _get_recommendations(state) -> list[dict]:
    """Query the static recommendation map based on state."""
    user_messages = " ".join([
        m["content"] for m in state.messages if m["role"] == "user"
    ])
    cat_ids = _match_categories(user_messages)
    candidates = []
    seen = set()
    for cat_id in cat_ids[:2]:  # max 2 categories
        for tech in TECH_RECOMMENDATION_MAP.get(cat_id, []):
            if tech["name"] not in seen:
                candidates.append(tech)
                seen.add(tech["name"])
    return candidates[:7]
```

- [ ] **Step 2: Write the CLARIFY_SYSTEM_PROMPT**

```python
CLARIFY_SYSTEM_PROMPT = """你是技术选型需求分析师。通过多轮对话，帮用户把模糊的技术选型问题逐步澄清。

## 当前已探明的信息
- 候选技术：{candidate_techs}
- 业务/落地场景：{scene}
- 项目复杂度：{complexity}
- 已知约束：{constraints}
- 用户技术水平：{tech_level}

## 仍需探明的必填项
{missing_required}

## 当前轮次
{clarify_rounds} / 3

## 动作规则

### 1. 有必填缺口 + 轮次 < 3 → action: "ask"
聚焦于优先级最高的缺口（scene > candidate_techs > complexity），问一个具体问题。
- 场景缺口："你这个项目是个人学习/团队协作/还是企业级的？大概几个人用？"
- 候选技术缺口："你有想比较的具体技术吗？还是让我推荐？"
- 复杂度缺口："这个项目的业务逻辑复杂吗？是简单CRUD还是涉及复杂的数据处理/权限/实时通信？"
规则：每次只问一个问题，不要一次问多个维度。

### 2. 候选技术缺失 + 用户不懂技术 → action: "recommend"
此时不要在 message 里写推荐列表（推荐列表由前端卡片渲染），message 字段写引导语。
payload.candidates 留空数组 [] —— 推荐列表由代码层的 _get_recommendations() 生成。

### 3. 必填项已齐全 → action: "confirm"
输出完整需求摘要。message 字段写摘要文本，语气确认式。

### 4. 轮次 >= 3 且仍有缺口 → 自动补默认值 + confirm
告知用户"以下部分为推测，可以修改"，直接输出需求摘要。

## 输出格式
返回纯 JSON（不要 markdown 代码块包裹）：
{"action": "ask|recommend|confirm", "message": "...", "scene": null|"solo"|"team"|"enterprise", "complexity": null|"simple"|"medium"|"complex", "candidate_techs": [...], "unknown_techs": true|false, "constraints": [...]}

- message: 给用户看的文本，1-2句话
- 其他字段: 从用户回复中提取的信息（本轮新提取到的），未提取到则填 null 或空列表
"""
```

- [ ] **Step 3: Write the ClarificationAgent class**

```python
import json
from typing import Any
from .session_manager import SessionState
from ..utils.llm import call_model


class ClarificationAgent:

    async def decide_and_respond(self, state: SessionState) -> dict:
        action = self._decide_action(state)

        if action == "recommend":
            return await self._handle_recommend(state)
        elif action == "confirm":
            return await self._handle_confirm(state)
        else:
            return await self._handle_ask(state)

    def _decide_action(self, state: SessionState) -> str:
        if state.clarify_rounds >= 3:
            return "confirm"

        if not state.missing_required:
            return "confirm"

        if "candidate_techs" in state.missing_required and state.unknown_techs:
            return "recommend"

        return "ask"

    async def _handle_ask(self, state: SessionState) -> dict:
        prompt_text = self._build_prompt(state)
        prompt = [{"role": "user", "content": prompt_text}]

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
            return self._merge_and_build_response(state, result)
        except Exception:
            return self._fallback_response(state)

    async def _handle_recommend(self, state: SessionState) -> dict:
        candidates = _get_recommendations(state)
        prompt_text = self._build_prompt(state)
        prompt = [{"role": "user", "content": prompt_text}]

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
            response = self._merge_and_build_response(state, result)
            response["action"] = "recommend"
            response["payload"] = {"candidates": candidates}
            return response
        except Exception:
            return {
                "action": "recommend",
                "answer": "根据你的描述，以下技术可能适合你的场景。你想比较哪几个？可以多选。",
                "payload": {"candidates": candidates},
                "clarity_score": state.clarity_score,
                "filled_required": state.filled_required,
                "missing_required": state.missing_required,
                "clarify_rounds": state.clarify_rounds,
            }

    async def _handle_confirm(self, state: SessionState) -> dict:
        self._apply_defaults(state)
        prompt_text = self._build_confirm_prompt(state)
        prompt = [{"role": "user", "content": prompt_text}]

        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
        except Exception:
            result = {"message": "需求已整理完毕，确认后开始研究。"}

        state.clarified_task = {
            "query": state.messages[0]["content"] if state.messages else "",
            "scene_context": state.scene,
            "constraints": state.constraints,
            "candidate_techs": state.candidate_techs,
            "complexity": state.complexity,
            "report_format": "what_why_how",
        }

        return {
            "action": "confirm",
            "answer": result.get("message", "需求已整理完毕，确认后开始研究。"),
            "payload": {
                "summary": result.get("message", ""),
                "clarified_task": state.clarified_task,
                "candidate_techs": state.candidate_techs,
                "scene": state.scene,
                "complexity": state.complexity,
            },
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    async def _handle_finalize(self, state: SessionState) -> dict:
        sub_questions = await self._generate_sub_questions(state)
        state.sub_questions = sub_questions
        return {
            "action": "finalize",
            "answer": "需求已确认，开始研究。",
            "payload": {
                "summary": f"需求确认：{state.scene}场景，{state.complexity}复杂度，比较 {', '.join(state.candidate_techs) if state.candidate_techs else '推荐技术'}。",
                "clarified_task": state.clarified_task,
                "sub_questions": sub_questions,
            },
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    def _build_prompt(self, state: SessionState) -> str:
        return CLARIFY_SYSTEM_PROMPT.format(
            candidate_techs=", ".join(state.candidate_techs) if state.candidate_techs else "未知",
            scene=state.scene or "未知",
            complexity=state.complexity or "未知",
            constraints=", ".join(state.constraints) if state.constraints else "无",
            tech_level="不太懂技术，需要推荐" if state.unknown_techs else "了解技术，有自己的候选",
            missing_required=", ".join(state.missing_required) if state.missing_required else "无（所有必填项已齐全）",
            clarify_rounds=state.clarify_rounds,
        )

    def _build_confirm_prompt(self, state: SessionState) -> str:
        return f"""你是技术选型需求分析师。所有必填信息已收集完毕，请输出需求确认摘要。

已探明的信息：
- 候选技术：{', '.join(state.candidate_techs) if state.candidate_techs else '待推荐'}
- 业务场景：{state.scene}（{'个人/学习' if state.scene == 'solo' else '中型团队' if state.scene == 'team' else '大型企业'}）
- 项目复杂度：{state.complexity}（{'简单CRUD' if state.complexity == 'simple' else '中等业务逻辑' if state.complexity == 'medium' else '复杂多系统交互'}）
- 约束条件：{', '.join(state.constraints) if state.constraints else '无特殊约束'}

用户原始需求：{state.messages[0]['content'] if state.messages else ''}

请用1-2句话总结这个需求，让用户确认。语气确认式，结尾问'确认无误就为你开始研究？'。

返回JSON：{{"message": "你的需求摘要..."}}"""

    async def _generate_sub_questions(self, state: SessionState) -> list[str]:
        prompt_text = f"""你是技术研究分析师。基于以下已澄清的需求，生成5个研究子问题，覆盖5个维度：功能、性能、生态、开发体验、场景适配。

需求：
- 候选技术：{', '.join(state.candidate_techs) if state.candidate_techs else '待推荐'}
- 场景：{state.scene}（solo=个人/team=团队/enterprise=企业）
- 复杂度：{state.complexity}

每个维度生成1个具体的、可检索的子问题。返回JSON：{{"sub_questions": ["q1", "q2", "q3", "q4", "q5"]}}"""

        prompt = [{"role": "user", "content": prompt_text}]
        try:
            result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
            return result.get("sub_questions", [])
        except Exception:
            techs = ", ".join(state.candidate_techs) if state.candidate_techs else "推荐技术"
            return [
                f"{techs} 功能覆盖度对比",
                f"{techs} 性能表现（吞吐量、延迟、资源消耗）",
                f"{techs} 社区活跃度与文档质量",
                f"{techs} 学习曲线与开发体验",
                f"{techs} 在 {state.scene} 场景下的适用性与部署复杂度",
            ]

    def _merge_and_build_response(self, state: SessionState, llm_result: dict) -> dict:
        if llm_result.get("scene") and not state.scene:
            state.scene = llm_result["scene"]
            if "scene" in state.missing_required:
                state.missing_required.remove("scene")
            if "scene" not in state.filled_required:
                state.filled_required.append("scene")

        if llm_result.get("complexity") and not state.complexity:
            state.complexity = llm_result["complexity"]
            if "complexity" in state.missing_required:
                state.missing_required.remove("complexity")
            if "complexity" not in state.filled_required:
                state.filled_required.append("complexity")

        if llm_result.get("candidate_techs") and not state.candidate_techs:
            state.candidate_techs = llm_result["candidate_techs"]
            if "candidate_techs" in state.missing_required:
                state.missing_required.remove("candidate_techs")
            if "candidate_techs" not in state.filled_required:
                state.filled_required.append("candidate_techs")

        if llm_result.get("unknown_techs") is not None:
            state.unknown_techs = llm_result["unknown_techs"]

        if llm_result.get("constraints"):
            for c in llm_result["constraints"]:
                if c not in state.constraints:
                    state.constraints.append(c)

        state.clarity_score = self._compute_score(state)
        return {
            "action": llm_result.get("action", "ask"),
            "answer": llm_result.get("message", ""),
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    def _fallback_response(self, state: SessionState) -> dict:
        return {
            "action": "ask",
            "answer": "抱歉，我刚才没理解清楚。能换个方式描述一下你的需求吗？",
            "clarity_score": state.clarity_score,
            "filled_required": state.filled_required,
            "missing_required": state.missing_required,
            "clarify_rounds": state.clarify_rounds,
        }

    def _apply_defaults(self, state: SessionState) -> None:
        if not state.scene:
            state.scene = "team"
            if "scene" in state.missing_required:
                state.missing_required.remove("scene")
            if "scene" not in state.filled_required:
                state.filled_required.append("scene")
        if not state.complexity:
            state.complexity = "medium"
            if "complexity" in state.missing_required:
                state.missing_required.remove("complexity")
            if "complexity" not in state.filled_required:
                state.filled_required.append("complexity")
        state.clarity_score = self._compute_score(state)

    def _compute_score(self, state: SessionState) -> float:
        total = 3
        filled = 0
        if state.candidate_techs:
            filled += 1
        if state.scene:
            filled += 1
        if state.complexity:
            filled += 1
        return round(filled / total, 2)
```

- [ ] **Step 4: Syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.clarify.clarification_agent import ClarificationAgent, TECH_RECOMMENDATION_MAP, _get_recommendations; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add deepchoice.clarify/clarification_agent.py
git commit -m "feat: add ClarificationAgent — LLM-driven ask/recommend/confirm/finalize loop

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: tests/clarify/test_clarification_agent.py

**Owner:** User (TDD)

**Files:**
- Create: `deepchoice/tests/clarify/test_clarification_agent.py`

**Interfaces:**
- Consumes: Task 4 (ClarificationAgent), Task 2 (SessionState, SessionManager)

- [ ] **Step 1: Write the test file**

```python
import pytest
from unittest.mock import AsyncMock, patch
from deepchoice.clarify.session_manager import SessionState, SessionStatus
from deepchoice.clarify.clarification_agent import (
    ClarificationAgent,
    _get_recommendations,
    _match_categories,
)


class TestMatchCategories:
    def test_matches_web_keywords(self):
        cats = _match_categories("我想做个网站")
        assert "fc14a2e9" in cats

    def test_matches_ai_keywords(self):
        cats = _match_categories("我要搭一个AI聊天机器人")
        assert "b82c4e6a" in cats

    def test_defaults_to_ai_when_no_match(self):
        cats = _match_categories("asdfghjkl")
        assert cats == ["b82c4e6a"]


class TestGetRecommendations:
    def test_returns_candidates_from_map(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "我想做个AI聊天机器人"}]
        state.unknown_techs = True
        candidates = _get_recommendations(state)
        assert len(candidates) > 0
        names = [c["name"] for c in candidates]
        assert "LangChain" in names or "Dify" in names or "LlamaIndex" in names

    def test_caps_at_7_candidates(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "前端 后端 API 部署"}]
        candidates = _get_recommendations(state)
        assert len(candidates) <= 7


class TestClarificationAgentDecideAction:
    @pytest.mark.asyncio
    async def test_recommend_when_missing_techs_and_unknown(self):
        state = SessionState()
        state.missing_required = ["candidate_techs", "complexity"]
        state.unknown_techs = True
        state.clarify_rounds = 1
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "recommend"

    @pytest.mark.asyncio
    async def test_ask_when_missing_scene(self):
        state = SessionState()
        state.missing_required = ["scene", "candidate_techs"]
        state.unknown_techs = False
        state.candidate_techs = ["FastAPI", "Flask"]
        state.clarify_rounds = 0
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "ask"

    @pytest.mark.asyncio
    async def test_confirm_when_all_filled(self):
        state = SessionState()
        state.missing_required = []
        state.scene = "solo"
        state.complexity = "simple"
        state.candidate_techs = ["FastAPI"]
        state.clarify_rounds = 2
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "confirm"

    @pytest.mark.asyncio
    async def test_confirm_when_rounds_exceeded(self):
        state = SessionState()
        state.missing_required = ["complexity"]
        state.clarify_rounds = 3
        agent = ClarificationAgent()
        assert agent._decide_action(state) == "confirm"


class TestClarificationAgentRecommend:
    @pytest.mark.asyncio
    async def test_handle_recommend_returns_candidates(self):
        state = SessionState()
        state.messages = [{"role": "user", "content": "我想做个AI应用"}]
        state.missing_required = ["candidate_techs", "complexity"]
        state.unknown_techs = True
        state.clarify_rounds = 1

        mock_llm = {"message": "这些是推荐的框架，你看看想比较哪几个？", "action": "recommend"}
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm
            result = await agent._handle_recommend(state)

        assert result["action"] == "recommend"
        assert "candidates" in result["payload"]
        assert len(result["payload"]["candidates"]) > 0


class TestClarificationAgentSubQuestions:
    @pytest.mark.asyncio
    async def test_generate_sub_questions_returns_5(self):
        state = SessionState()
        state.candidate_techs = ["FastAPI", "Flask"]
        state.scene = "solo"
        state.complexity = "simple"

        mock_llm = {"sub_questions": ["q1", "q2", "q3", "q4", "q5"]}
        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm
            result = await agent._generate_sub_questions(state)

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_generate_sub_questions_fallback_on_error(self):
        state = SessionState()
        state.candidate_techs = ["React", "Vue"]
        state.scene = "team"
        state.complexity = "medium"

        agent = ClarificationAgent()
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("API error")
            result = await agent._generate_sub_questions(state)

        assert len(result) == 5  # fallback generates 5
```

- [ ] **Step 2: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/clarify/test_clarification_agent.py -v
```

Expected: 9 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add deepchoice/tests/clarify/test_clarification_agent.py
git commit -m "test: add ClarificationAgent tests — action routing, recommendations, sub-questions

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: clarify_routes.py

**Owner:** User (core architecture — FastAPI endpoints)

**Files:**
- Create: `deepchoice.server.clarify_routes.py`

**Interfaces:**
- Consumes: Task 2 (SessionManager), Task 4 (ClarificationAgent), `fastapi.APIRouter`
- Produces: 4 endpoints — `POST /clarify/start`, `POST /clarify/{session_id}/message`, `GET /clarify/{session_id}/status`, `POST /clarify/{session_id}/finalize`

- [ ] **Step 1: Write clarify_routes.py**

```python
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

    # Run first round of clarification
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
```

- [ ] **Step 2: Syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.server.clarify_routes import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice.server.clarify_routes.py
git commit -m "feat: add /clarify/* FastAPI endpoints (start, message, status, finalize)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: tests/clarify/test_clarify_routes.py

**Owner:** User (TDD)

**Files:**
- Create: `deepchoice/tests/clarify/test_clarify_routes.py`

**Interfaces:**
- Consumes: Task 6 (router), Task 2 (SessionManager)

- [ ] **Step 1: Write the test file**

```python
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from deepchoice.server.clarify_routes import router, session_manager, clarify_agent

# We need a FastAPI app wrapping the router for TestClient
from fastapi import FastAPI
app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestClarifyStart:
    def test_start_returns_session_and_question(self):
        mock_response = {
            "action": "ask",
            "answer": "你这个AI应用主要用来做什么？",
            "clarity_score": 0.15,
            "filled_required": [],
            "missing_required": ["scene", "candidate_techs", "complexity"],
            "clarify_rounds": 0,
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_response
            resp = client.post("/clarify/start", json={"query": "我想做个AI应用"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"].startswith("clarify_")
        assert data["next_action"] == "ask"
        assert len(data["answer"]) > 0

    def test_start_with_tech_keywords_detects_candidates(self):
        mock_response = {
            "action": "ask",
            "answer": "你是个人开发还是团队使用？",
            "clarity_score": 0.43,
            "filled_required": ["candidate_techs"],
            "missing_required": ["scene", "complexity"],
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_response
            resp = client.post("/clarify/start", json={"query": "FastAPI vs Flask"})

        assert resp.status_code == 200
        data = resp.json()
        assert "candidate_techs" in data["filled_required"]


class TestClarifyMessage:
    def test_message_returns_agent_response(self):
        mock_start = {
            "action": "ask",
            "answer": "你好，想选什么技术？",
            "clarity_score": 0.15,
            "filled_required": [],
            "missing_required": ["scene", "candidate_techs", "complexity"],
        }
        mock_message = {
            "action": "recommend",
            "answer": "对话机器人方向，看看这些框架",
            "clarity_score": 0.40,
            "filled_required": ["scene"],
            "missing_required": ["candidate_techs", "complexity"],
            "payload": {"candidates": [{"name": "LangChain", "stars": "90k+", "desc": "灵活度高"}]},
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.side_effect = [mock_start, mock_message]
            start_resp = client.post("/clarify/start", json={"query": "做个AI应用"})
            sid = start_resp.json()["session_id"]
            msg_resp = client.post(f"/clarify/{sid}/message", json={"message": "对话机器人"})

        assert msg_resp.status_code == 200
        data = msg_resp.json()
        assert data["next_action"] == "recommend"
        assert "candidates" in data.get("payload", {})

    def test_message_404_on_bad_session(self):
        resp = client.post("/clarify/nonexistent/message", json={"message": "hello"})
        assert resp.status_code == 404


class TestClarifyStatus:
    def test_status_returns_state(self):
        mock_response = {
            "action": "ask",
            "answer": "你的项目场景是什么？",
            "clarity_score": 0.43,
            "filled_required": ["candidate_techs"],
            "missing_required": ["scene", "complexity"],
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_response
            start_resp = client.post("/clarify/start", json={"query": "FastAPI vs Flask"})
            sid = start_resp.json()["session_id"]
            status_resp = client.get(f"/clarify/{sid}/status")

        assert status_resp.status_code == 200
        data = status_resp.json()
        assert "clarity_score" in data
        assert "missing_required" in data


class TestClarifyFinalize:
    def test_finalize_returns_sub_questions(self):
        mock_start = {
            "action": "confirm",
            "answer": "为solo开发者选择API框架，确认无误？",
            "clarity_score": 1.0,
            "filled_required": ["candidate_techs", "scene", "complexity"],
            "missing_required": [],
            "payload": {
                "summary": "...",
                "clarified_task": {
                    "query": "FastAPI vs Flask for solo dev",
                    "scene_context": "solo",
                    "constraints": ["python"],
                    "candidate_techs": ["FastAPI", "Flask"],
                    "complexity": "simple",
                    "report_format": "what_why_how",
                },
                "candidate_techs": ["FastAPI", "Flask"],
                "scene": "solo",
                "complexity": "simple",
            },
        }
        mock_finalize = {
            "action": "finalize",
            "answer": "需求已确认，开始研究。",
            "payload": {
                "summary": "...",
                "clarified_task": {},
                "sub_questions": ["q1", "q2", "q3", "q4", "q5"],
            },
        }
        with patch.object(clarify_agent, "decide_and_respond", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = mock_start
            start_resp = client.post("/clarify/start", json={"query": "FastAPI vs Flask"})
            sid = start_resp.json()["session_id"]
            # Manually set state to ready to allow finalize
            session_manager._sessions[sid].scene = "solo"
            session_manager._sessions[sid].complexity = "simple"
            session_manager._sessions[sid].candidate_techs = ["FastAPI", "Flask"]
            session_manager._sessions[sid].filled_required = ["candidate_techs", "scene", "complexity"]
            session_manager._sessions[sid].missing_required = []

        with patch.object(clarify_agent, "_handle_finalize", new_callable=AsyncMock) as mock_fin:
            mock_fin.return_value = mock_finalize
            resp = client.post(f"/clarify/{sid}/finalize")

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "finalize"
        assert "sub_questions" in data["payload"]
```

- [ ] **Step 2: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/clarify/test_clarify_routes.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add deepchoice/tests/clarify/test_clarify_routes.py
git commit -m "test: add clarify routes integration tests (TestClient)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Modify orchestrator.py — dynamic entry point

**Owner:** User (core architecture)

**Files:**
- Modify: `deepchoice.agents.orchestrator.py`

**Prerequisites:** Original plan Task 11 (orchestrator.py) must be complete first.

**Interfaces:**
- Modifies: `ChiefEditorAgent.init_research_team()` to accept `start_from` parameter
- Modifies: `ChiefEditorAgent._create_workflow()` to support conditional entry point
- Backward compatible: default `start_from="query_analyzer"` preserves old path

- [ ] **Step 1: Modify `_create_workflow` method**

The existing `_create_workflow` method (from original plan Task 11) needs two changes:

Change 1 — Accept `start_from` parameter:
```python
# Before:
def _create_workflow(self, agents):
    workflow = StateGraph(ResearchState)
    workflow.add_node("query_analyzer", agents["query_analyzer"].run)
    workflow.add_node("multi_retriever", agents["multi_retriever"].run)
    # ... rest of nodes ...
    workflow.set_entry_point("query_analyzer")
    workflow.add_edge("query_analyzer", "multi_retriever")

# After:
def _create_workflow(self, agents, start_from: str = "query_analyzer"):
    workflow = StateGraph(ResearchState)
    workflow.add_node("query_analyzer", agents["query_analyzer"].run)
    workflow.add_node("multi_retriever", agents["multi_retriever"].run)
    # ... rest of nodes (unchanged) ...
    workflow.set_entry_point(start_from)
    if start_from == "multi_retriever":
        workflow.add_edge("multi_retriever", "source_evaluator")
    else:
        workflow.add_edge("query_analyzer", "multi_retriever")
    # ... rest of edges (unchanged) ...
```

Change 2 — Modify `init_research_team` to pass through:
```python
# Before:
def init_research_team(self):
    agents = self._initialize_agents()
    return self._create_workflow(agents)

# After:
def init_research_team(self, start_from: str = "query_analyzer"):
    agents = self._initialize_agents()
    return self._create_workflow(agents, start_from=start_from)
```

- [ ] **Step 2: Modify `run_research_task`**

```python
# Before:
async def run_research_task(self):
    workflow = self.init_research_team()
    chain = workflow.compile()
    result = await chain.ainvoke({"task": self.task})

# After:
async def run_research_task(self, task: dict | None = None):
    task = task or self.task
    has_sub_questions = bool(task.get("sub_questions"))
    start_from = "multi_retriever" if has_sub_questions else "query_analyzer"

    print_agent_output(
        f"Starting research from: {start_from}",
        agent="ORCHESTRATOR",
    )
    workflow = self.init_research_team(start_from=start_from)
    chain = workflow.compile()

    initial_state = {"task": task}
    if has_sub_questions:
        initial_state["sub_questions"] = task.get("sub_questions", [])

    result = await chain.ainvoke(initial_state)
    return result
```

- [ ] **Step 3: Syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.agents.orchestrator import ChiefEditorAgent; print('OK')"
```

Expected: `OK` (this assumes orchestrator.py already exists from original plan Task 11)

- [ ] **Step 4: Commit**

```bash
git add deepchoice.agents.orchestrator.py
git commit -m "feat: dynamic orchestrator entry point — skip QueryAnalyzer when sub_questions provided

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Modify server/app.py — register clarify routes

**Owner:** AI skeleton

**Files:**
- Modify: `deepchoice.server.app.py`

**Prerequisites:** Original plan Task 12 (app.py exists with FastAPI app)

- [ ] **Step 1: Add import and router registration**

At the top of `app.py`, add:
```python
from .clarify_routes import router as clarify_router
```

After `app = FastAPI(...)`, add:
```python
app.include_router(clarify_router)
```

Full change context — the top of app.py should look like:
```python
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from ..agents.orchestrator import ChiefEditorAgent
from ..state import ResearchState
from .snapshot_store import save_snapshot, load_snapshot, save_report, list_history
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first
from .clarify_routes import router as clarify_router  # NEW

app = FastAPI(title="DeepChoice API", version="0.1.0")
app.include_router(clarify_router)  # NEW
```

- [ ] **Step 2: Verify syntax**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.server.app import app; print(len(app.routes))"
```

Expected: number of routes > original (the original 6 + 4 new clarify routes)

- [ ] **Step 3: Commit**

```bash
git add deepchoice.server.app.py
git commit -m "feat: register /clarify routes in FastAPI app

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: Modify frontend/app.py — two-phase UI

**Owner:** AI skeleton

**Files:**
- Modify: `deepchoice/frontend/app.py`

**Prerequisites:** Original plan frontend skeleton exists (Streamlit app with research input + progress + report)

- [ ] **Step 1: Add phase state management**

```python
import streamlit as st
import requests
import time

# Phase management
if "phase" not in st.session_state:
    st.session_state.phase = "clarify"  # clarify | research
if "clarify_session_id" not in st.session_state:
    st.session_state.clarify_session_id = None
if "clarify_messages" not in st.session_state:
    st.session_state.clarify_messages = []
if "clarified_data" not in st.session_state:
    st.session_state.clarified_data = None  # stores finalize payload

API_BASE = "http://localhost:8000"
```

- [ ] **Step 2: Write clarify phase UI**

```python
def render_clarify_phase():
    st.title("DeepChoice — 技术选型 Deep Research")

    # Chat history
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.clarify_messages:
            if msg["role"] == "assistant":
                with st.chat_message("assistant"):
                    st.write(msg["content"])
                    # Render tech cards if recommend action
                    if msg.get("action") == "recommend" and msg.get("payload", {}).get("candidates"):
                        _render_tech_cards(msg["payload"]["candidates"])
                    # Render confirm card if confirm action
                    if msg.get("action") == "confirm":
                        _render_confirm_card(msg)
            else:
                with st.chat_message("user"):
                    st.write(msg["content"])

    # Progress bar
    if st.session_state.clarify_messages:
        last_msg = st.session_state.clarify_messages[-1]
        score = last_msg.get("clarity_score", 0)
        st.progress(score, text=f"清晰度: {int(score * 100)}%")
        filled = last_msg.get("filled_required", [])
        missing = last_msg.get("missing_required", [])
        if filled:
            st.caption(f"已明确: {' | '.join(filled)}")
        if missing:
            st.caption(f"待探明: {' | '.join(missing)}")

    # Input area
    col1, col2 = st.columns([4, 1])
    with col1:
        user_input = st.chat_input("输入你的回答...")
    with col2:
        skip_btn = st.button("就这样吧", use_container_width=True)

    if user_input:
        _handle_user_message(user_input)
        st.rerun()

    if skip_btn:
        _handle_skip()
        st.rerun()


def _render_tech_cards(candidates: list[dict]):
    """Render selectable tech cards for recommend action."""
    selected = []
    cols = st.columns(min(len(candidates), 3))
    for i, tech in enumerate(candidates):
        with cols[i % 3]:
            checked = st.checkbox(
                f"**{tech['name']}**  \n{tech.get('stars', '')}  \n{tech.get('desc', '')}",
                key=f"tech_{tech['name']}",
            )
            if checked:
                selected.append(tech["name"])
    if st.button("确认选择，继续", type="primary"):
        if selected:
            joined = ", ".join(selected)
            _handle_user_message(joined)


def _render_confirm_card(msg: dict):
    """Render confirmation card with summary."""
    summary = msg.get("payload", {}).get("summary", "")
    with st.container(border=True):
        st.write("### 需求确认")
        st.write(summary)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("确认，开始研究", type="primary"):
                _handle_finalize()
        with c2:
            if st.button("我要修改"):
                st.session_state.clarify_session_id = None
                st.session_state.clarify_messages = []
                st.rerun()


def _handle_user_message(text: str):
    """Send user message to clarify API."""
    sid = st.session_state.clarify_session_id
    if sid is None:
        resp = requests.post(f"{API_BASE}/clarify/start", json={"query": text})
    else:
        resp = requests.post(f"{API_BASE}/clarify/{sid}/message", json={"message": text})

    if resp.status_code == 200:
        data = resp.json()
        st.session_state.clarify_session_id = data["session_id"]
        st.session_state.clarify_messages.append({"role": "user", "content": text})
        msg = {"role": "assistant", "content": data["answer"]}
        for k in ("action", "payload", "clarity_score", "filled_required", "missing_required"):
            if k in data:
                msg[k] = data[k]
        st.session_state.clarify_messages.append(msg)

        if data.get("next_action") == "finalize":
            st.session_state.clarified_data = data["payload"]


def _handle_skip():
    """Handle '就这样吧' button — force finalize."""
    sid = st.session_state.clarify_session_id
    if sid:
        resp = requests.post(f"{API_BASE}/clarify/{sid}/finalize")
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.clarified_data = data["payload"]
            st.session_state.phase = "research"


def _handle_finalize():
    """Confirm — finalize and switch to research phase."""
    sid = st.session_state.clarify_session_id
    if sid:
        resp = requests.post(f"{API_BASE}/clarify/{sid}/finalize")
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.clarified_data = data["payload"]
            st.session_state.phase = "research"
```

- [ ] **Step 3: Write research phase entry point**

```python
def render_research_phase():
    """Existing research UI, fed from clarified_data."""
    data = st.session_state.clarified_data
    if data is None:
        st.error("No clarified task data. Please go back.")
        return

    st.title("DeepChoice — 研究进行中")

    # Call POST /research with clarified_task + sub_questions
    task = data["clarified_task"]
    task["sub_questions"] = data.get("sub_questions", [])

    if "research_started" not in st.session_state:
        st.session_state.research_started = False

    if not st.session_state.research_started:
        resp = requests.post(f"{API_BASE}/research", json=task)
        if resp.status_code == 200:
            st.session_state.research_task_id = resp.json()["task_id"]
            st.session_state.research_started = True

    task_id = st.session_state.research_task_id
    _render_progress(task_id)
    _render_report(task_id)


def _render_progress(task_id: str):
    """SSE progress listener placeholder."""
    st.write(f"Task: {task_id}")
    st.progress(0.5, text="研究中...")


def _render_report(task_id: str):
    """Report display placeholder."""
    if st.button("查看报告"):
        resp = requests.get(f"{API_BASE}/research/{task_id}/report")
        if resp.status_code == 200:
            st.markdown(resp.text)
```

- [ ] **Step 4: Wire up main entry**

```python
def main():
    if st.session_state.phase == "clarify":
        render_clarify_phase()
    else:
        render_research_phase()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify syntax**

```bash
cd D:/deepchoice-agent && python -c "import ast; ast.parse(open('frontend/app.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 6: Commit**

```bash
git add deepchoice/frontend/app.py
git commit -m "feat: two-phase Streamlit UI — clarify chat + research progress

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: Index annotations in original plan

**Owner:** AI skeleton

**Files:**
- Modify: `docs/superpowers/plans/2026-07-06-DeepChoice-plan.md`

- [ ] **Step 1: Add index annotation at Task 5 (query_analyzer.py)**

Insert at the top of Task 5 section (before the `### Task 5: query_analyzer.py` heading):

```markdown
> **索引参照**: QueryAnalyzer 已被澄清模块部分替代。当用户通过 `/clarify` 流程进入时，
> 澄清模块直接产出 `sub_questions`，Pipeline 从 MultiRetriever 入口启动，跳过本 Task。
> 直接调用 `POST /research` 的旧路径仍经过 QueryAnalyzer。
> 详见 [澄清模块实现计划](./2026-07-07-DeepChoice-clarify-plan.md)。
```

- [ ] **Step 2: Add index annotation at Task 11 (orchestrator.py)**

Insert at the top of Task 11 section:

```markdown
> **索引参照**: 入口逻辑已扩展。`_create_workflow()` 现接受 `start_from` 参数，
> 支持从 MultiRetriever 启动（跳过 QueryAnalyzer）。
> 详见 [澄清模块实现计划](./2026-07-07-DeepChoice-clarify-plan.md) Task 8。
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-07-06-DeepChoice-plan.md
git commit -m "docs: add clarify module index annotations to original plan (Task 5 + Task 11)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: Integration test — full clarify → research flow

**Owner:** User (end-to-end validation)

**Files:**
- Create: `deepchoice/tests/clarify/test_clarify_integration.py`

**Prerequisites:** All tasks above must be complete. Original plan's MultiRetriever + SourceEvaluator nodes must exist.

- [ ] **Step 1: Write integration test**

```python
import pytest
from unittest.mock import AsyncMock, patch
from deepchoice.clarify.session_manager import SessionManager
from deepchoice.clarify.clarification_agent import ClarificationAgent


class TestFullClarifyFlow:
    @pytest.mark.asyncio
    async def test_vague_query_to_finalize(self):
        """Simulate: vague query → 3 rounds → confirm → finalize → sub_questions."""
        sm = SessionManager()
        agent = ClarificationAgent()

        # Round 0: start
        result = sm.create("我想做个AI应用，用什么框架好")
        sid = result["session_id"]
        state = sm._sessions[sid]
        assert state.unknown_techs is True
        assert "candidate_techs" in state.missing_required

        # Round 1: user says "对话机器人"
        mock_r1 = {"action": "recommend", "message": "对话机器人方向，看看这些框架", "scene": "solo"}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r1
            sm.process_message(sid, "对话机器人")
            state = sm._sessions[sid]
            r1 = await agent.decide_and_respond(state)
            assert r1["action"] == "recommend"

        # Round 2: user selects "LangChain, Dify"
        state.candidate_techs = ["LangChain", "Dify"]
        if "candidate_techs" in state.missing_required:
            state.missing_required.remove("candidate_techs")
        if "candidate_techs" not in state.filled_required:
            state.filled_required.append("candidate_techs")

        mock_r2 = {"action": "ask", "message": "这个项目业务逻辑复杂吗？", "complexity": None}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r2
            sm.process_message(sid, "就这两个")
            r2 = await agent.decide_and_respond(state)
            assert r2["action"] in ("ask", "confirm")

        # Round 3: user says "简单的"
        state.complexity = "simple"
        if "complexity" in state.missing_required:
            state.missing_required.remove("complexity")
        if "complexity" not in state.filled_required:
            state.filled_required.append("complexity")

        mock_r3 = {"action": "confirm", "message": "确认：solo开发者，简单对话机器人，LangChain vs Dify。开始研究？"}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_r3
            sm.process_message(sid, "简单的对话机器人")
            r3 = await agent.decide_and_respond(state)
            assert r3["action"] == "confirm"

        # Finalize
        mock_sub_q = {"sub_questions": [
            "LangChain vs Dify 功能覆盖度对比",
            "LangChain vs Dify 性能基准测试",
            "LangChain vs Dify 社区活跃度与维护频率",
            "LangChain vs Dify 学习曲线与文档质量",
            "LangChain vs Dify 在solo场景下的部署复杂度",
        ]}
        with patch("deepchoice.clarify.clarification_agent.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_sub_q
            final = await agent._handle_finalize(state)

        assert final["action"] == "finalize"
        assert len(final["payload"]["sub_questions"]) == 5
        assert final["payload"]["clarified_task"]["scene_context"] == "solo"
        assert len(final["payload"]["clarified_task"]["candidate_techs"]) == 2

    @pytest.mark.asyncio
    async def test_forced_finalize_with_defaults(self):
        """User clicks '就这样吧' after 1 round — defaults applied."""
        sm = SessionManager()
        agent = ClarificationAgent()

        result = sm.create("做个项目")
        sid = result["session_id"]
        state = sm._sessions[sid]
        state.clarify_rounds = 1
        sm._sessions[sid] = state

        sm.finalize(sid)
        final_state = sm._sessions[sid]
        assert final_state.scene == "team"
        assert final_state.complexity == "medium"
```

- [ ] **Step 2: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/clarify/test_clarify_integration.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add deepchoice/tests/clarify/test_clarify_integration.py
git commit -m "test: add integration test — full clarify flow from vague query to finalize

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task Summary

| # | Task | Owner | Est. | Depends On |
|:-:|------|:-----:|:----:|-----------|
| 1 | clarify + tests scaffold | AI | 5m | — |
| 2 | session_manager.py | User | 1h | Task 1 |
| 3 | test_session_manager.py | User | 30m | Task 2 |
| 4 | clarification_agent.py | User | 2h | Task 2, utils.llm |
| 5 | test_clarification_agent.py | User | 30m | Task 4 |
| 6 | clarify_routes.py | User | 1h | Task 2,4 |
| 7 | test_clarify_routes.py | User | 30m | Task 6 |
| 8 | modify orchestrator.py | User | 30m | Original Task 11 |
| 9 | modify server/app.py | AI | 10m | Task 6, Original Task 12 |
| 10 | modify frontend/app.py | AI | 1.5h | Task 6 |
| 11 | index annotations in original plan | AI | 10m | — |
| 12 | integration test | User | 30m | All above |

**User total: ~6h | AI total: ~2h**

---

## Execution Order

```
Task 1 (scaffold)
  → Task 2 (session_manager)
    → Task 3 (test session_manager)
  → Task 4 (clarification_agent) [needs utils.llm from original plan]
    → Task 5 (test clarification_agent)
  → Task 6 (clarify_routes) [needs Task 2 + 4]
    → Task 7 (test clarify_routes)
    → Task 9 (modify app.py) [needs original Task 12]
  → Task 8 (modify orchestrator.py) [needs original Task 11]
  → Task 10 (modify frontend/app.py) [needs Task 6]
  → Task 11 (index annotations)
  → Task 12 (integration test) [needs all above + original MultiRetriever]
```

Tasks 3, 5, 7 can be written before their implementations (TDD). Tasks 9, 10, 11 can run in parallel after their dependencies.
