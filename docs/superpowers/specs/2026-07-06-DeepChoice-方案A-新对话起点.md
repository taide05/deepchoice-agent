# DeepChoice — 方案 A（线性 Pipeline + 末端重试）

**用途**：新对话设计起点
**日期**：2026-07-06
**状态**：待在新对话中由 brainstorming skill 重新设计

---

## 已确认的决策

### 项目定位

- **项目名**：DeepChoice — 技术选型 Deep Research Agent
- **一句话**：输入技术选型问题，Agent 从 6 路信息源交叉验证，生成带证据链和置信度评估的选型报告
- **叙事定位**：你不是技术专家，你是 Agent 系统设计者。Agent 的价值是"帮不太懂的人做出更好的技术决策"

### 场景选择

- **主 Demo**：技术选型（LangGraph vs CrewAI / Embedding 模型对比 / LLM 部署方案选型）
- Demo 不需要你懂所有技术细节——Agent 现场搜给你，你只需解释架构设计决策

### 核心能力优先级

1. **B 信息源可靠性评估**（规则引擎四维打分，不用 LLM）
2. **C 观点冲突调和**（检测矛盾 → 用分数做裁决依据 → 真假矛盾区分）
3. **D 引用链溯源**（每条结论绑出处 + snippet + 检索时间，双向可追溯）
B→C→D 形成完整证据质量管道

### P2 整合

- **冲突裁决（核心）**：两路来源矛盾时，用 SourceEval 四维分数 + 证据强度（有无代码/数据/复现步骤）做客观裁决，不用 LLM 主观判断
- **Reflection 驳回重审（核心）**：SelfReview 置信度=low → 定向补搜缺口主题 → 回到检索（最多 1 次）
- **ToT 对比（面提不实现）**：同一问题跑两路不同策略，对比质量/耗时/Token——面试叙事用
- **HITL 交互（面提不实现）**：用户标注"这里不对"→ Agent 重新检索该部分——面试叙事用

### 本地知识库策略

- 先放容易筛选的：官方文档 + 高引用论文摘要
- 不做数量要求
- 初始 10-20 篇跑通流程，后续随学习自然增长
- 定位：精选参考源（如图书馆管理员选书），不是"你的技术笔记"

---

## 方案 A 架构

### LangGraph 流程（线性的 7 节点）

```
ENTER
  ↓
[QueryAnalyzer]         ← 5维分解: 功能/性能/生态/体验/场景
  ↓
[MultiRetriever]        ← 6路并行 asyncio.gather
  ↓
[SourceEvaluator]       ← 规则引擎四维打分
  ↓
[ConflictDetector]      ← LLM: 提取论断 → 发现矛盾 → 用四维分数+证据强度裁决
  ↓
[EvidenceChain]         ← 纯组装: 结论→来源列表→snippet→检索时间
  ↓
[ReportGenerator]       ← LLM: Markdown 报告（强制8段模板）
  ↓
[SelfReviewer]          ← LLM: 6项检查单 + 置信度 + 信息缺口
  ↓
  ├─ high/medium → END
  └─ low + retry_count=0 → 定向补搜缺口 → ConflictDetector
     low + retry_count=1 → END（标红低置信度）
```

### State（11 字段）

```
task: dict
sub_questions: list[str]
search_results: list[dict]     # 6路原始结果
source_scores: list[dict]      # 四维评分后排序
conflicts: list[dict]          # 矛盾检测+调和结果
evidence_chains: list[dict]    # 结论+证据+溯源
report: str                    # Markdown
confidence: str                # high/medium/low
knowledge_gaps: list[str]      # 信息缺口
retry_count: int               # 全流程重试计数, 上限1
current_phase: str             # SSE 通知用
```

### 6 路检索

| 路 | 数据源 | 独特价值 | 超时 |
|----|--------|---------|------|
| 1 | Tavily Web Search | 广度最大 | 15s |
| 2 | Chroma 本地精选库 | 预先筛选,信源可靠度最高 | 5s |
| 3 | GitHub API | 客观数据(Star/Issue/Release) | 15s |
| 4 | ArXiv API | 同行评审,理论深度 | 15s |
| 5 | 社区搜索(StackOverflow/Reddit) | 真实使用体验,踩坑 | 15s |
| 6 | 官方渠道(README/Releases/Blog) | 维护者声明,最新动态 | 15s |

### 四维评分模型（规则引擎，不用 LLM）

| 维度 | 权重 | 评分逻辑 |
|------|:----:|---------|
| 权威度 | 35% | 官方文档/论文 10→知名博客 6→论坛 4→匿名 2 |
| 时效性 | 25% | <3月 10→3-6月 8→6-12月 6→1-2年 4→>2年 2 |
| 一致性 | 20% | 至少2源支持 10→1源部分支持 6→矛盾 2 |
| 可验证性 | 20% | 有数据/代码/引用 10→有示例无复现 6→纯观点 2 |

### 报告模板（8 段强制结构）

1. 研究概要
2. 候选方案概览
3. 多维度对比（功能/性能/生态/体验/场景）
4. 信息冲突与裁决
5. 推荐结论
6. 证据强度矩阵
7. 信息缺口（诚实声明）
8. 引用列表（完整溯源）

### SelfReview 检查单（6 项硬编码）

1. 每条结论是否都有来源支撑？
2. 是否有无来源的结论？
3. 推荐方案是否覆盖了所有对比维度？
4. 是否存在未标注的信息冲突？
5. 用户问题中是否有子问题未回答？
6. 是否有反例未标注？

---

## 现有资产复用清单

### 从 P1 (GPT Researcher) 照搬

| 文件 | 内容 | 用到哪 |
|------|------|--------|
| `agents/utils/llms.py` | call_model() | 所有 LLM 调用节点 |
| `agents/utils/views.py` | print_agent_output() | 日志输出 |
| `agents/writer.py` | Agent 类模式: __init__(websocket, stream_output, headers) + async run(state) | 7 个新 Agent |
| `orchestrator.py` | StateGraph + add_node/add_edge/add_conditional_edges + compile + ainvoke | 编排器 |
| `retrievers/__init__.py` | 检索器注册 __all__ | 6 路检索注册 |
| `labor_law/__init__.py` | SentenceTransformer 手动加载 + local_files_only=True | local_kb.py |
| `task.json` | 任务配置 JSON 模式 | task.json |

### 从 P2 (OpenHarness) 提取设计模式（不搬代码）

| P2 概念 | DeepChoice 映射 |
|---------|----------------|
| 冲突裁决（多视角碰撞） | ConflictDetector：用四维分数+证据强度裁决，不靠 LLM 直觉 |
| Reflection（驳回重审） | SelfReview→定向补搜→ConflictDetect 回边 |
| 架构诚实标注 | 报告第 7 段"信息缺口" + 置信度声明 |

### 不用的

- P1 劳动法 Agents（questionnaire/scan/law_search 等）
- GPT Researcher 20+ Web 检索器（只用 Tavily）
- P1 双循环编排（换为单 Pipeline + 定向重试）
- OpenHarness 代码（不 fork，只提取设计模式）

---

## 需在新对话中讨论的未决问题

1. 方案 A 的"定向补搜"具体怎么实现——搜什么、怎么搜、怎么合并到已有结果
2. ConflictDetector 的 LLM prompt 设计——如何让 LLM 做"证据强度比较"而非"主观判断"
3. 本地知识库第一批 20 篇的具体篇目
4. Demo 场景的最终敲定（LangGraph vs CrewAI / Embedding 模型 / LLM 部署）
5. FastAPI SSE 流式推送的事件格式
6. Streamlit 前端布局
7. 目录结构和文件命名
8. 实现任务的优先级和工时估算

---

## 新对话启动建议

```
/clear
我正在设计一个叫 DeepChoice 的技术选型 Deep Research Agent。
这是方案 A 的设计起点文档: docs/superpowers/specs/2026-07-06-DeepChoice-方案A-新对话起点.md
请用 brainstorming skill 从头开始设计。
已确认的决策在文档中，未决问题在最后一节。
请先完整阅读该文档和现有 P1 代码后再开始提问。
```
