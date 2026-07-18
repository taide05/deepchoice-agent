# 导读 04：Agent 管道（下）—— 编排器 → 自审查 → 报告生成

## 覆盖文件
- `src/deepchoice/agents/orchestrator.py` (95行)
- `src/deepchoice/agents/self_reviewer.py` (71行)
- `src/deepchoice/agents/report_generator.py` (37行)

## 模块概述

这三个文件是管道的**后半段和控制层**——Orchestrator 编排全部节点和重试逻辑，ReportGenerator 调用格式渲染器生成最终报告，SelfReviewer 做质量把关并决定是否需要重试。

```
EvidenceChain → ReportGenerator (格式渲染)
              → SelfReviewer (质量审查)
              → Orchestrator._route_after_review (路由: 结束 / 小重试 / 大重试)
```

---

## 一、orchestrator.py — LangGraph 编排器

### 类结构与初始化

```python
from langgraph.graph import StateGraph, END
from ..state import ResearchState

class ChiefEditorAgent:
    def __init__(self, task, websocket=None, stream_output=None, headers=None):
        self.task = task
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers or {}
        self.task_id = str(int(time.time()))
```

**设计决策：类名为什么叫 ChiefEditorAgent 而不是 OrchestratorAgent？**

这个名字是故意的——"主编"暗示这个 Agent 的角色是"协调编辑团队"，不只是"编排节点"。这是 OpenAI Swarm 和 GPT Researcher 的命名惯例，让代码读起来像在描述一个工作流。

### _initialize_agents — 工厂方法

```python
def _initialize_agents(self) -> dict:
    return {
        "query_analyzer": QueryAnalyzerAgent(self.websocket, self.stream_output, self.headers),
        "multi_retriever": MultiRetrieverAgent(self.websocket, self.stream_output, self.headers),
        "source_evaluator": SourceEvaluatorAgent(self.websocket, self.stream_output, self.headers),
        "conflict_detector": ConflictDetectorAgent(self.websocket, self.stream_output, self.headers),
        "evidence_chain": EvidenceChainAgent(self.websocket, self.stream_output, self.headers),
        "report_generator": ReportGeneratorAgent(self.websocket, self.stream_output, self.headers),
        "self_reviewer": SelfReviewerAgent(self.websocket, self.stream_output, self.headers),
    }
```

**设计决策：为什么把 websocket/stream_output/headers 传给每个 Agent？**

这三个是**基础设施依赖**——它不应该硬编码在每个 Agent 里。通过构造函数注入，Agent 不需要知道 websocket 是怎么创建的，只需要用它发送消息。这是**依赖注入**的简化版。

### _create_workflow — 建图

```python
def _create_workflow(self, agents, start_from="query_analyzer"):
    workflow = StateGraph(ResearchState)

    # 注册 7 个节点
    workflow.add_node("query_analyzer", agents["query_analyzer"].run)
    workflow.add_node("multi_retriever", agents["multi_retriever"].run)
    workflow.add_node("source_evaluator", agents["source_evaluator"].run)
    workflow.add_node("conflict_detector", agents["conflict_detector"].run)
    workflow.add_node("evidence_chain", agents["evidence_chain"].run)
    workflow.add_node("report_generator", agents["report_generator"].run)
    workflow.add_node("self_reviewer", agents["self_reviewer"].run)

    # 入口点
    workflow.set_entry_point(start_from)

    # 主线：线性边
    if start_from == "query_analyzer":
        workflow.add_edge("query_analyzer", "multi_retriever")
    workflow.add_edge("multi_retriever", "source_evaluator")
    workflow.add_edge("source_evaluator", "conflict_detector")
    workflow.add_edge("conflict_detector", "evidence_chain")
    workflow.add_edge("evidence_chain", "report_generator")
    workflow.add_edge("report_generator", "self_reviewer")

    # 条件路由：SelfReviewer 之后的分支
    workflow.add_conditional_edges(
        "self_reviewer",
        self._route_after_review,
        {
            "end": END,
            "retry_small": "conflict_detector",  # 小重试：从冲突检测重新开始
            "retry_full": "query_analyzer",      # 大重试：从问题分解重新开始
        },
    )
    return workflow
```

**LangGraph 的基本概念：**

| 概念 | 对应代码 | 含义 |
|------|---------|------|
| StateGraph | `StateGraph(ResearchState)` | 有状态的有向图，状态在节点间流转 |
| Node | `add_node("name", func)` | 图中的一个节点，func 接收 state dict，返回 dict（自动 merge） |
| Edge | `add_edge("A", "B")` | 固定边：A → B 总是执行 |
| Conditional Edge | `add_conditional_edges(...)` | 条件边：A → 根据返回值选择下一个节点 |
| Entry Point | `set_entry_point(...)` | 图的起始节点 |

### _route_after_review — 条件路由

```python
def _route_after_review(self, state: ResearchState) -> str:
    confidence = state.get("confidence", "medium")
    retry_count = state.get("retry_count", 0)
    gaps = state.get("knowledge_gaps", [])

    if confidence in ("high", "medium"):
        return "end"
    if retry_count >= 1:
        return "end"  # 最多重试一次，防止死循环

    state["retry_count"] = retry_count + 1
    if len(gaps) <= 2:
        return "retry_small"   # 缺口少 → 从冲突检测重来
    return "retry_full"        # 缺口多 → 从问题分解重来
```

**路由决策树：**

```
confidence = high/medium?  → end（满意，结束）
              ↓ No
retry_count >= 1?          → end（已重试过，强制结束）
              ↓ No
gaps <= 2?                 → retry_small（从 conflict_detector 重跑）
              ↓ No
                            → retry_full（从 query_analyzer 重跑）
```

**为什么 retry_count >= 1 强制结束？** 防止无限循环。LLM 可能每次都返回 low 置信度（对自己生成的内容过于谦虚），没有上限会导致永远在重试。

**为什么"缺口少"是 retry_small 而不是 retry_full？** 小缺口意味着大部分信息已经足够了，只是缺少个别维度。从 conflict_detector 开始重试即可（跳过 query_analyzer 和 multi_retriever，直接用已有的 search_results）。省 token 和时间。

### run_research_task — 入口

```python
async def run_research_task(self, task=None):
    task = task or self.task
    has_sub_questions = bool(task.get("sub_questions"))
    start_from = "multi_retriever" if has_sub_questions else "query_analyzer"

    workflow = self.init_research_team(start_from=start_from)
    chain = workflow.compile()
    initial_state = {"task": task}
    if has_sub_questions:
        initial_state["sub_questions"] = task["sub_questions"]
    result = await chain.ainvoke(initial_state)
    return result
```

**设计决策：start_from 动态选择。**

如果用户已经提供了子问题（clarify 模块预分解好了），跳过 QueryAnalyzer，直接从检索开始。这是**避免冗余 LLM 调用**——用户已经说清楚要比较什么了，不需要 LLM 再分解一遍。

### 盲区补课：LangGraph StateGraph 的工作机制

LangGraph 的核心概念：

```python
# 1. 定义状态类型
class ResearchState(TypedDict):
    task: dict
    report: str
    ...

# 2. 创建图
workflow = StateGraph(ResearchState)

# 3. 添加节点——每个节点是一个 async 函数
async def query_analyzer(state: ResearchState) -> dict:
    # 从 state 读取输入
    task = state["task"]
    # 处理后返回部分更新
    return {"sub_questions": [...]}

workflow.add_node("query_analyzer", query_analyzer)

# 4. 添加边——定义流转
workflow.add_edge("query_analyzer", "multi_retriever")

# 5. 编译 + 执行
chain = workflow.compile()
result = await chain.ainvoke({"task": {...}})
```

LangGraph 内部会自动：
1. 把 `ainvoke` 的初始 state 传给入口节点
2. 每个节点返回的 dict **merge** 进 state（不是替换）
3. 按边定义的顺序执行节点
4. 条件边根据返回值选择下一个节点

---

## 二、self_reviewer.py — 质量审查

### Prompt 设计

```python
REVIEW_PROMPT = """You are a rigorous quality reviewer. Evaluate this research report
against a 6-item checklist.

## Report
{report}

## Evidence Chains
{evidence_chains}

## Original Sub-Questions
{sub_questions}

## Checklist — Answer YES or NO for each:
1. Does every conclusion have source support?
2. Are there any unsourced claims?
3. Does the recommendation cover all 5 comparison dimensions?
4. Are there unlabeled information conflicts?
5. Are any user sub-questions unanswered?
6. Are there counter-examples or negative findings not flagged?

## Confidence Assessment
- high: 6/6 passed, all evidence chains have strong or moderate strength
- medium: 1-2 items failed, no critical gaps
- low: 3+ items failed OR critical information missing

## Gap Analysis
If confidence is not "high", list specific information gaps as search queries.

Return ONLY JSON: {{"checks": [...], "passed_count": N, "confidence": "...",
  "knowledge_gaps": [...], "critical_gaps": [...]}}"""
```

### 6 项检查清单的设计逻辑

| 检查项 | 防止什么问题 | 为什么排这个顺序 |
|--------|------------|----------------|
| 1. 每个结论有来源？ | 幻觉——LLM 编造结论 | 最致命，排第一 |
| 2. 有无来源的断言？ | 同上，侧重未标注的 | 和 #1 互补覆盖 |
| 3. 覆盖五维？ | 报告偏科（如只讲性能） | 完整性检查 |
| 4. 未标记的冲突？ | ConflictDetector 漏了 | 质量把关 |
| 5. 子问题全回答了？ | 用户问题被忽略 | 用户需求满足 |
| 6. 反面发现未标注？ | 选择性报告（只说好话） | 客观性检查 |

### run 方法

```python
class SelfReviewerAgent:
    async def run(self, research_state: dict) -> dict:
        prompt = [{
            "role": "user",
            "content": REVIEW_PROMPT.format(
                report=research_state.get("report", ""),
                evidence_chains=str(research_state.get("evidence_chains", [])),
                sub_questions=str(research_state.get("sub_questions", [])),
                retry_count=research_state.get("retry_count", 0),
            ),
        }]
        result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
        return {
            "confidence": result.get("confidence", "medium"),
            "knowledge_gaps": result.get("knowledge_gaps", []),
        }
```

**设计决策：为什么 SelfReviewer 用自己的 LLM 审查报告，而不是直接用规则？**

报告是自然语言文本，检查"结论是否有来源"、"是否有反面发现"需要语义理解。规则可以检查格式（有没有引用标记），但检查不出来"这个结论是编造的"。LLM 审查 LLM 输出是**幻觉检测**的常用模式——让另一个 LLM 做事实核查。

**为什么 SelfReviewer 用 flash 而不是 pro？** 审查是"对照检查清单打钩"，不需要深度推理。flash 足够。

### 盲区补课：Self-Review / Self-Critique 模式

这是 LLM Agent 领域的常见模式：

```
LLM 生成 → 同一个/另一个 LLM 审查 → 反馈 → 重新生成（可选）
```

DeepChoice 的实现：
```
ReportGenerator(flash) → SelfReviewer(flash) → 路由决策 → 可能重试
```

**为什么不直接让 ReportGenerator 用 pro 模型一次生成高质量报告？** 因为"生成 + 审查 + 修正"比"一次高质量生成"更可控——审查有明确的 checklist，生成质量可以量化（passed_count），而且重试机制让系统有机会弥补信息缺口。

---

## 三、report_generator.py — 格式路由

### 完整代码

```python
from ..utils.views import print_agent_output
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first
from ..formats.comparison_matrix import render as render_comparison_matrix

FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
    "comparison_matrix": render_comparison_matrix,
}

class ReportGeneratorAgent:
    async def run(self, research_state: dict) -> dict:
        fmt = research_state["task"].get("report_format", "what_why_how")

        # 生成数据覆盖声明
        partial_failures = research_state.get("partial_failures", [])
        if partial_failures:
            total = len(research_state.get("search_results", [])) + len(partial_failures)
            available = total - len(partial_failures)
            research_state["data_source_note"] = (
                f"Data coverage: {available}/{total} sources available. "
                f"Unavailable: {', '.join(partial_failures)}. ..."
            )

        renderer = FORMAT_RENDERERS.get(fmt, render_what_why_how)
        report = renderer(research_state)
        return {"report": report}
```

### 设计决策

**1. FORMAT_RENDERERS 注册表——和 RETRIEVER_REGISTRY 同样的注册表模式。**

新增报告格式只需：① 写 render 函数 ② 在 FORMAT_RENDERERS 注册一行。ReportGenerator 零改动。这是项目中第三次出现注册表模式（retrievers、formats、prompts），面试时可以指出来——"项目中用了多次注册表模式，统一处理插件扩展。"

**2. data_source_note 的设计意图是什么？**

向用户诚实告知数据局限性。"本次结论基于 5/6 路来源，Tavily 不可用"比"这就是最优选择"更可信。这是**可观测性向用户侧透传**——不只是内部日志记录失败，而是显式告诉用户信息是有缺口。

**3. 为什么 ReportGenerator 不调 LLM？**

报告生成是**模板填充**——把 state 里的结构化数据（evidence_chains、conflicts、source_scores）按格式模板组织成 Markdown。不需要自然语言生成。三种格式渲染器都是纯函数，只做字符串拼接和格式化。

**4. 这和 GPT Researcher 的 ReportGenerator 有什么不同？**

GPT Researcher 的 ReportGenerator 调 LLM 生成完整的研究报告（长文本）。DeepChoice 改成了模板渲染——因为技术选型场景下，用户需要的是**可比较的数据**，不是散文。对比矩阵比叙事性报告更实用。

---

## 面试拷打

### Q1: LangGraph 的条件边和普通 if-else 有什么区别？
```python
# 普通 if-else：在节点内部
async def run(self, state):
    if state["confidence"] == "low":
        return {"phase": "retry"}
    return {"phase": "end"}

# LangGraph 条件边：在图的拓扑层
workflow.add_conditional_edges("self_reviewer", self._route_after_review, {...})
```

条件边的优势：**路由逻辑在图的拓扑层可见**。看图就知道 SelfReviewer 之后有三个可能的下一个节点。如果路由逻辑藏在节点内部，需要读完所有节点的代码才能理解完整的流转路径。

### Q2: 为什么 SelfReviewer 之后有两种重试（small/full），而不只是一种？
信息缺口的大小不同，修复成本不同。缺 1-2 个点可能是检索不充分，从 ConflictDetector 重跑即可（省 token）。缺 3+ 个点说明问题分解可能有问题，需要从 QueryAnalyzer 重新分解。分两级的目的是 **最小化重试成本**。

### Q3: retry_count 硬限制为 1 会不会太紧？
有争议的设计。1 次重试在大多数情况下足够——SelfReviewer 的 knowledge_gaps 会指导重试方向，第二次运行时有更明确的目标。但确实存在"重试后仍然 low confidence"的情况，当前会直接结束。这是**延迟和质量的权衡**——在交互式应用中，用户等不了 5 次重试。

### Q4: ReportGenerator 不调 LLM，那"推荐理由"从哪里来？
从 evidence_chains 来。每条 chain 有 conclusion 字段（来自搜索结果标题和摘要），由 EvidenceChain 组装，由 SourceEvaluator 评分过滤。推荐理由不是 LLM 生成的，而是"分数最高的那条结论作为首选依据"。这种方式比 LLM 生成的理由更可追溯——用户可以点开来源 URL 自己验证。
