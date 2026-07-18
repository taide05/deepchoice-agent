# DeepChoice — 前置查询澄清模块设计

**日期**: 2026-07-07
**状态**: 设计完成，待实现
**依赖**: [DeepChoice 整体设计](2026-07-06-DeepChoice-design.md) / [实现计划](2026-07-07-DeepChoice-clarify-plan.md)（待生成）

---

## 0. 问题陈述

当前 7 节点 LangGraph Pipeline 直接从 QueryAnalyzer 开始，假设用户输入已是清晰的技术选型问句。当用户输入模糊（如"我想做个AI应用，用什么框架好"），整个 Pipeline 只能产出低质量报告——因为连候选技术范围、业务场景、项目复杂度都没搞清。

**缺失环节**：进入研究管线之前的需求澄清。

---

## 1. 架构决策

### 两层分离

| 层 | 职责 | 位置 |
|----|------|------|
| 澄清层 | 多轮交互，探明必填前置条件 | FastAPI `/clarify/*` + 独立 Agent |
| 研究层 | 6 路检索 + 评分 + 冲突裁决 + 报告 | LangGraph Pipeline（现有，入口改为 MultiRetriever） |

**澄清模块不在 LangGraph 内部**。理由：澄清是多轮交互的，LangGraph 的 `interrupt` 机制能做但调试麻烦，且澄清逻辑本身不需要图编排——它是一个线性追问循环。

### 与 QueryAnalyzer 的关系

澄清模块**合并替代** QueryAnalyzer。澄清完成后直接产出 `sub_questions`，Pipeline 从 MultiRetriever 入口启动。QueryAnalyzer 的 5 维分解能力并入澄清模块的 `finalize` 步骤。

Pipeline 保留向后兼容：如果 State 无 `sub_questions`（直接调 API 的旧路径），仍然从 QueryAnalyzer 开始。

### 总体数据流

```
用户模糊输入
  → Streamlit 前端（clarify 阶段）
  → POST /clarify/start → ClarificationAgent
  → 多轮 POST /clarify/{id}/message ←→ Agent
  → finalize: 产出 clarified_task + sub_questions
  → 前端自动切到 research 阶段
  → POST /research (携带 clarified_task + sub_questions)
  → LangGraph Pipeline 从 MultiRetriever 入口
  → [MultiRetriever → SourceEvaluator → ConflictDetector
     → EvidenceChain → ReportGenerator → SelfReviewer]
  → SSE 推送进度 → Streamlit 渲染报告
```

---

## 2. 数据模型：SessionState

```python
class SessionState:
    session_id: str
    status: Literal["clarifying", "ready", "running", "done"]

    # 三类必填（目标状态）
    candidate_techs: list[str]          # 候选技术，如 ["FastAPI", "Flask"]，空 = 待探明
    scene: str | None                   # solo / team / enterprise
    complexity: str | None              # simple / medium / complex

    # 可选补充
    constraints: list[str]              # 语言/部署/成本/时间等
    unknown_techs: bool                 # 用户是否不懂技术（触发推荐模式）
    tech_recommendations: list[dict]    # Agent 推荐的候选技术

    # 追踪
    clarify_rounds: int                 # 已追问轮次，上限 3
    filled_required: list[str]          # 已明确的必填项名称
    missing_required: list[str]         # 仍缺失的必填项
    clarity_score: float                # 0-1，UI 展示用

    # 对话
    messages: list[dict]                # {"role": "user|assistant", "content": "..."}

    # 最终产出（finalize 后填充）
    clarified_task: dict | None         # 结构化任务
    sub_questions: list[str] | None     # 拆解后的子问题
```

### 字段行为规则

- `candidate_techs` 为空 + `unknown_techs=false` → 追问"你想比较哪些技术？"
- `candidate_techs` 为空 + `unknown_techs=true` → 触发推荐模式
- `scene` 为空 + 已追问 3 轮 → 软门禁，默认 "team"
- `complexity` 为空 + 已追问 3 轮 → 软门禁，默认 "medium"

---

## 3. 核心逻辑：ClarificationAgent

### 每轮动作类型

| 动作 | 触发条件 | 行为 |
|------|---------|------|
| `ask` | 有必填缺口，轮次 < 3 | 生成一个聚焦的追问，补齐最关键的缺口 |
| `recommend` | 缺口是 `candidate_techs` + `unknown_techs=true` | 基于已有信息推荐 3-5 个候选技术，供用户勾选 |
| `confirm` | 必填已齐（正常）或轮次达上限（降级） | 输出完整需求摘要，让用户确认或修改 |
| `finalize` | 用户确认 | 关门，拆解子问题，产出 clarified_task + sub_questions |

### 优先级：每次只探一个缺口

```
scene > candidate_techs > complexity
```

场景优先——因为场景决定了后续推荐的技术范围。候选技术第二——没有候选技术，检索没有目标。复杂度第三——影响报告深度但不阻塞检索。

### System Prompt 结构

```
你是技术选型需求分析师。通过多轮对话，帮用户把模糊的技术选型问题逐步澄清。

当前已探明：
- 候选技术：{candidate_techs}
- 业务场景：{scene}
- 项目复杂度：{complexity}
- 已知约束：{constraints}
- 用户技术水平：{unknown_techs ? "不太懂技术，可能需要推荐" : "了解技术"}

仍需探明的必填项：{missing_required}
当前轮次：{clarify_rounds} / 3

动作规则：
1. missing_required 非空且轮次<3 → 针对最关键的缺口，问一个聚焦的问题。每次只问一个维度
2. candidate_techs 缺失且 unknown_techs=true → 推荐候选技术，给出选项
3. 必填已齐 → 输出完整需求摘要，请用户确认
4. 轮次>=3 仍有缺口 → 使用默认值填充，告知用户，进入确认

约束：
- 每次只问一个问题，不要太长
- 不要一次问多个维度
- 如果用户回答含糊，换一种问法追问同一维度
- 输出 JSON 格式，包含 action 和 payload
```

### 推荐模式

`unknown_techs` 的判定：第一轮用户输入里如无任何技术名词 → 标记 `unknown_techs=true`，走推荐分支。

推荐逻辑：静态映射表（硬编码，面试可解释）。根据 `scene` + `complexity` + 需求关键词匹配。

```
"做网站" + team + medium → React/Vue/Angular (前端), FastAPI/Django/Spring (后端)
"数据分析" + solo + simple → Pandas/Streamlit/Jupyter
"对话机器人" + solo + simple → LangChain/LlamaIndex/Dify/Coze/Semantic Kernel
"API 服务" + team + medium → FastAPI/Django/Spring/Express/Go-Gin
"移动端" + solo + simple → Flutter/React Native/UniApp
```

推荐输出格式：

```json
{
  "action": "recommend",
  "payload": {
    "message": "对话机器人方向，常见的框架有这些，你想比较哪几个？",
    "candidates": [
      {"name": "LangChain", "stars": "90k+", "desc": "灵活度最高，生态最大"},
      {"name": "LlamaIndex", "stars": "35k+", "desc": "数据索引强项"},
      {"name": "Dify", "stars": "50k+", "desc": "低代码，上手最快"},
      {"name": "Coze", "stars": "字节跳动", "desc": "国内生态好"},
      {"name": "Semantic Kernel", "stars": "21k+", "desc": "微软官方，企业级"}
    ]
  }
}
```

### 软门禁规则

| 轮次 | 缺口状态 | 行为 |
|:--:|------|------|
| 1-2 | 有缺口 | 正常追问 |
| 3 | 缺口 ≤ 1 | 默认值填充 → confirm |
| 3 | 缺口 > 1 | 全部默认值填充 → confirm，标注"以下为推测，可修改" |
| 用户点"就这样吧" | 任意 | 立即降级填充 → finalize |

默认值：scene → "team"，complexity → "medium"。

---

## 4. API 设计

### 端点

```
POST   /clarify/start                    创建澄清会话
POST   /clarify/{session_id}/message     发送用户回复
GET    /clarify/{session_id}/status      查询当前状态
POST   /clarify/{session_id}/finalize    强制执行最终确认
```

### POST /clarify/start

```
Request:  {query: "我想做个AI应用，用什么框架好"}
Response: {
  session_id: "clarify_abc123",
  answer: "你这个AI应用主要用来做什么？比如对话机器人、数据分析、还是内容生成？",
  next_action: "ask",
  clarity_score: 0.15,
  filled_required: [],
  missing_required: ["scene", "candidate_techs", "complexity"]
}
```

### POST /clarify/{id}/message

```
Request:  {message: "对话机器人"}
Response: {
  answer: "对话机器人方向，常见的框架有这些，你想比较哪几个？",
  next_action: "recommend",
  payload: {
    candidates: [
      {name: "LangChain", stars: "90k+", desc: "灵活度最高"},
      ...
    ]
  },
  clarity_score: 0.40,
  filled_required: ["scene"],
  missing_required: ["candidate_techs", "complexity"]
}
```

### POST /clarify/{id}/finalize

```
Response: {
  next_action: "finalize",
  payload: {
    summary: "需求确认：为个人开发者(Solo)选择一个对话机器人搭建框架，追求低成本和快速上手。比较 LangChain、LlamaIndex、Dify。",
    clarified_task: {
      query: "为个人开发者选择对话机器人搭建框架",
      scene_context: "solo",
      constraints: ["python", "low-cost"],
      candidate_techs: ["LangChain", "LlamaIndex", "Dify"],
      complexity: "simple",
      report_format: "what_why_how"
    },
    sub_questions: [
      "LangChain vs LlamaIndex vs Dify 功能覆盖度对比",
      "三个方案的学习曲线和上手时间",
      "三个方案的社区活跃度和文档质量",
      "两个方案的性能对比（吞吐量、延迟）",
      "Solo 开发者场景下的部署复杂度和成本"
    ]
  }
}
```

### Session 存储

内存字典 `_clarify_sessions: dict[str, SessionState]`，不落盘。会话超时 30 分钟自动清理。

---

## 5. 前端设计

### 两阶段 UI

```
[clarify 阶段] → 聊天式 + 清晰度进度
    收到 finalize
        ↓
[research 阶段] → 进度条 + 报告渲染（现有）
```

### Clarify 阶段布局

```
┌─────────────────────────────────────────┐
│  DeepChoice — 技术选型 Deep Research      │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │ 对话区（scrolable）               │    │
│  │                                  │    │
│  │ 🤖: 你好，想选什么技术？随便说说。  │    │
│  │ 👤: 我想做个网站                   │    │
│  │ 🤖: 纯展示内容的还是需要登录？     │    │
│  │ ...                              │    │
│  └──────────────────────────────────┘    │
│                                          │
│  清晰度: ████████░░░░ 60%               │
│  已明确: 场景(solo)                       │
│  待探明: 候选技术 复杂度                   │
│                                          │
│  ┌─────────────────────────────┐         │
│  │ 输入你的回答...        [发送] │         │
│  └─────────────────────────────┘         │
│              [我不想聊了，就这样吧]        │
└─────────────────────────────────────────┘
```

### 三种 Agent 消息渲染

**1. ask（追问）**：普通聊天气泡

**2. recommend（推荐）**：聊天气泡 + 下方内嵌技术选择卡片。用户勾选后点"确认选择，继续"→ 发送选中技术列表。

```
│ 🤖: 对话机器人方向，常见的框架有这些。    │
│     点一下你想比较的，可以多选：           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ LangChain │ │LlamaIndex│ │  Dify   │ │
│  │ ⭐ 90k+   │ │ ⭐ 35k+  │ │ 低代码   │ │
│  │   [选]    │ │   [选]   │ │   [选]   │ │
│  └──────────┘ └──────────┘ └──────────┘ │
│              [确认选择，继续]              │
```

**3. confirm（确认）**：需求摘要卡片 + "确认，开始研究" / "我要修改" 两个按钮。

### 阶段切换

收到 `finalize` → 前端自动调用 `POST /research`（传入 `clarified_task` + `sub_questions`）→ 切换到 research UI（进度条 + SSE 监听）。"就这样吧"按钮触发 `POST /clarify/{id}/finalize`，得到 finalize 后再调 research。

---

## 6. 文件变更清单

### 新增

```
deepchoice/src/
  clarify/
    __init__.py
    session_manager.py       # SessionState CRUD + 超时清理（内存字典）
    clarification_agent.py   # LLM Agent（动作判定 + Prompt + 推荐映射表）
  server/
    clarify_routes.py        # /clarify/* 端点（start, message, status, finalize）
```

### 修改

| 文件 | 改动 |
|------|------|
| `src/agents/orchestrator.py` | `init_research_team()` 支持动态 entry_point：State 有 `sub_questions` → 从 MultiRetriever 入口；否则走原路径 QueryAnalyzer |
| `src/server/app.py` | 注册 `clarify_routes` router |
| `frontend/app.py` | 两阶段 UI（clarify 聊天模式 + research 进度/报告模式） |

### 不改动

- `utils/llm.py` — 复用 `call_model()`
- State / TaskConfig — `clarified_task` 是 TaskConfig 的超集，Pydantic 忽略多余字段
- 6 路检索 / SourceEvaluator / ConflictDetector / EvidenceChain / ReportGenerator / SelfReviewer — 不受影响

---

## 7. SessionManager API

```python
class SessionManager:
    def create(self, query: str) -> SessionState          # 新建会话，首轮分析
    def process_message(self, session_id: str, message: str) -> dict  # 处理用户回复
    def get_status(self, session_id: str) -> dict          # 查询状态
    def finalize(self, session_id: str) -> dict             # 强制执行最终确认
    def _cleanup_expired(self) -> None                      # 清理 30min 超时会话
    def _extract_initial_state(self, query: str) -> SessionState  # 首轮分析
```

### ClarificationAgent API

```python
class ClarificationAgent:
    def decide_action(self, state: SessionState) -> str     # ask|recommend|confirm
    def generate_response(self, state: SessionState) -> dict  # LLM 调用，返回响应
    def generate_recommendations(self, state: SessionState) -> list[dict]  # 静态映射表查询
    def generate_sub_questions(self, state: SessionState) -> list[str]     # LLM 拆解
```

---

## 8. 风险与边界

### MVP 不做

- Session 持久化（重启丢失，MVP 接受）
- 用户身份认证
- 推荐映射表动态更新（硬编码，面试时可解释）
- 澄清对话历史导出
- 多语言支持
- 语音输入

### 退化场景

| 场景 | 处理 |
|------|------|
| 用户全程答"不知道" | 3 轮后软门禁降级，全部默认值 |
| 用户输入全是废话/离题 | Agent 引导回技术选型，3 轮后降级 |
| Session 超时 30min | 返回 404，前端提示重新开始 |
| LLM 调用失败 | 返回错误状态，前端显示重试按钮 |

### 面试叙事

> "这个模块解决了一个实际痛点：不懂技术的人做技术选型时，最大的障碍不是缺少信息，而是不知道该怎么问。澄清模块用多轮对话 + 推荐模式，把模糊需求转成结构化查询，然后再进入研究管线。"

---

## 9. 成本估算

澄清模块每轮一次 LLM 调用（deepseek-v4-flash），预估：

| 场景 | 轮次 | 单次成本 | 小计 |
|------|:--:|:--:|:--:|
| 需求清晰（1 轮） | 1 | ¥0.001 | ¥0.001 |
| 需求模糊（3 轮） | 3 | ¥0.001 | ¥0.003 |
| Finalize 拆解子问题 | 1 | ¥0.001 | ¥0.001 |
| **最差情况** | **4** | | **¥0.004** |

每用户最多 ¥0.004，Free Tavily (1000次/月) 足够开发期使用。

---

## 10. 与现有设计的整合点

原设计 7 节点 Pipeline 不变。唯一改动是 orchestrator.py 的动态入口：

```python
def _create_workflow(self, agents, start_from: str = "query_analyzer"):
    workflow = StateGraph(ResearchState)
    workflow.add_node("query_analyzer", agents["query_analyzer"].run)
    workflow.add_node("multi_retriever", agents["multi_retriever"].run)
    # ... 其余节点不变 ...

    workflow.set_entry_point(start_from)
    if start_from == "multi_retriever":
        # 跳过 query_analyzer，从检索开始
        workflow.add_edge("multi_retriever", "source_evaluator")
    else:
        workflow.add_edge("query_analyzer", "multi_retriever")
    # ... 其余边不变 ...
```

这样既支持新路径（澄清 → MultiRetriever），也保留旧路径（POST /research 直接调，经过 QueryAnalyzer）。
