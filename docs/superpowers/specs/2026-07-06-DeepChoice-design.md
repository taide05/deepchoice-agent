# DeepChoice — 技术选型 Deep Research Agent 设计方案

**日期**: 2026-07-06
**状态**: 设计完成，待实现
**前身**: 方案 A 起点文档（已合并吸收）

---

## 0. 项目定位

### 一句话

输入技术选型问题，Agent 从 6 路信息源交叉验证，生成带证据链和置信度评估的选型报告。

### 目标用户

技术选型有信息不对称的人——覆盖 AI/Agent、后端、基础设施、运维全栈，不限于 Agent 开发者。

### 成功标准

| # | 标准 | 度量方式 |
|:--:|------|---------|
| 1 | 结论可溯源 | 报告中每条结论 >=1 个来源 URL + snippet |
| 2 | 信息质量 > 信息量 | 每条来源经四维评分过滤 |
| 3 | 冲突被显式处理 | 矛盾不回避，标注、裁决、给置信度 |
| 4 | 诚实标注不确定性 | 信息缺口/低置信度显式标注 |
| 5 | 速度可用 | 完整流程 <= 90s |
| 6 | 覆盖广度 | 1000 用例覆盖 5 类别 50 子域 |

### 与 ChatBot / 搜索引擎的本质区别

- ChatBot：给你答案，不告诉你可靠程度
- 搜索引擎：给你链接，不帮你比较判断
- DeepChoice：带证据链的对比报告 + 冲突裁决 + 置信度 + 间隙声明

### 叙事定位

你不是技术专家，你是 Agent 系统设计者。Agent 的价值是"帮不太懂的人做出更好的技术决策"。

---

## 1. 系统架构

### 7 节点线性 Pipeline + 末端条件回边

```
ENTER
  [QueryAnalyzer]        5维分解 + 场景上下文 + 约束提取 + report_format
  [MultiRetriever]       6路并行 asyncio.gather(return_exceptions=True)
  [SourceEvaluator]      规则引擎四维打分（纯Python, 不调LLM）
  [ConflictDetector]     提取论断 -> 发现矛盾 -> 结构化裁决（LLM）
  [EvidenceChain]        结论 -> 来源 -> 溯源（纯Python, 不调LLM）
  [ReportGenerator]      按 format 参数渲染报告（LLM, 2种格式 MVP）
  [SelfReviewer]         6项检查单 + 置信度 + 定向补搜决策（LLM）
    |
    high/medium -> END
    low:
      gaps <= 2 -> 关键词直搜 Tavily -> 结果追加 -> ConflictDetector
      gaps > 2 -> 回 QueryAnalyzer(仅缺口) -> 完整重走 -> ConflictDetector
      retry_count++, 上限1次, 第2次low -> END标红
```

### State（12字段）

```
task: dict                   # {query, scene_context, constraints, report_format}
sub_questions: list[str]     # 5维分解后子问题
search_results: list[dict]   # 6路原始结果
source_scores: list[dict]    # 四维评分后排序
conflicts: list[dict]        # 矛盾检测+调和
evidence_chains: list[dict]  # 结论+证据+溯源
report: str                  # Markdown
confidence: str              # high/medium/low
knowledge_gaps: list[str]    # 信息缺口
retry_count: int             # 上限1
partial_failures: list[str]  # 降级记录
current_phase: str           # SSE通知用
```

### DeepChoice 自身技术选型

| 决策 | 选择 | 理由 |
|------|:--:|------|
| 编排框架 | LangGraph | GPT Researcher 同款, 面试展示 LangGraph 经验 |
| LLM | DeepSeek V4 (Flash + Pro 混合) | Flash 日常节点, Pro 冲突裁决 |
| 向量库 | Chroma + bge-m3 | 已熟练, 本地离线 |
| Web 框架 | FastAPI + Streamlit | 后端 SSE + Demo 前端 |
| 异步 HTTP | httpx | 原生异步, 6路并行 |

**LLM 节点分配**

| 节点 | 模型 | 理由 |
|------|------|------|
| QueryAnalyzer | deepseek-v4-flash | 分解任务, JSON输出 |
| ConflictDetector | **deepseek-v4-pro** | 需要强推理, 评分驱动裁决 |
| ReportGenerator | deepseek-v4-flash | 长文本渲染 |
| SelfReviewer | deepseek-v4-flash | 检查单核对 |

---

## 2. QueryAnalyzer — 查询分解与场景识别

### 5维分解

| 维度 | 分解方向 |
|------|---------|
| 功能 | 能力覆盖度、API完整性 |
| 性能 | 吞吐、延迟、资源消耗 |
| 生态 | 社区活跃度、插件、文档 |
| 体验 | 学习曲线、调试难度、开发效率 |
| 场景 | 适用边界、反模式、是否匹配上下文 |

### 场景上下文识别

- Solo/初创（1-5人）: 含"个人/学习/demo/solo"
- 中型团队（20-100人）: 含"团队/公司/业务/生产"
- 大型企业（500+人）: 含"企业/高并发/合规/金融/医疗"
- 不明确 -> 默认中型团队

### 约束条件提取

语言/生态约束、部署约束、成本约束、时间约束、合规约束。

### 输出

```json
{"sub_questions": ["...", "...", ...], "scene_context": "solo|team|enterprise", "constraints": ["...", ...]}
```

---

## 3. MultiRetriever — 6路并行检索

`asyncio.gather(*tasks, return_exceptions=True)`, 单路失败不阻断整体。

| # | 路名 | 数据源 | 超时 | 深度 |
|---|------|------|:--:|:--:|
| 1 | Tavily | Tavily Search API | 15s | 标准 |
| 2 | Chroma | 本地向量库(bge-m3) | 5s | **深** |
| 3 | GitHub | GitHub REST API | 15s | 浅 |
| 4 | ArXiv | ArXiv Search API | 15s | 标准 |
| 5 | 社区 | StackExchange + Reddit | 15s | 浅 |
| 6 | 官方渠道 | PyPI JSON + GitHub README | 15s | 浅 |

### 降级策略

每路返回 `{source, status: success|partial|failed, results, error, latency_ms}`。全部failed -> 返回错误。部分failed -> 记录 partial_failures, 继续。

### MVP 实现优先级

Tavily + Chroma + ArXiv 为必做（你已有深度），GitHub / 社区 / 官方渠道 3 路为浅度实现（我写骨架），全部 6 路在 MVP 中跑通。

---

## 4. SourceEvaluator — 规则引擎四维评分

纯 Python 函数, 不调 LLM。可复现、零成本、面试可逐行解释。

| 维度 | 权重 | 评分逻辑 |
|------|:--:|---------|
| 权威度 | 35% | 官方/论文=10, 知名博客=7, GitHub=6, SO=5, Reddit=4, 匿名=2 |
| 时效性 | 25% | <3月=10, 3-6月=8, 6-12月=6, 1-2年=4, >2年=2 |
| 一致性 | 20% | >=2源支持=10, 1源支持=6, 孤立=4, 矛盾=2 |
| 可验证性 | 20% | 可运行代码=10, 有基准数据=8, 有引用=6, 纯观点=2 |

### 输出结构

```json
{"url": "", "source_type": "", "scores": {}, "total_score": 0, "evidence_type": "", "supporting_sources": [], "contradicting_sources": [], "rank": 0}
```

---

## 5. ConflictDetector — 结构化冲突裁决

### 三步流程

1. **提取论断**（LLM）: 从每条来源提取可验证的技术命题
2. **发现矛盾**（纯规则）: sentence-transformers 语义相似度 + 极性判断
3. **结构化裁决**（LLM）: 输入双方四维分数 + 证据类型, 输出 `{resolution, confidence, reasoning, key_factor}`

### 裁决模板

Prompt 内置双方分数对比表, LLM 仅执行裁判。reasoning 必须引用分数差异。resolution: A_correct / B_correct / both_partial / insufficient_data。

### 去噪规则

- 相似度 < 0.6 -> 跳过
- 同源矛盾 -> 降级, 置信度 low
- 仅 1 条高质量来源 -> 跳过

---

## 6. EvidenceChain + ReportGenerator

### 6A — EvidenceChain（纯组装, 不调 LLM）

结论 -> 匹配来源 -> 检查冲突 -> 生成条目。证据强度: strong (>=2源, >=8分) / moderate (>=1源, >=6分) / weak（低分或 disputed）。

双向溯源：正向 结论->来源URL, 反向 来源标注"支撑了第X章第Y条结论"。

### 6B — ReportGenerator（LLM, 按 format 渲染）

报告格式在任务入口选定（`task.report_format`），不事后切换。报告从研究快照渲染。

**MVP 实现 2 种格式**:

#### what-why-how（是什么/为什么/怎么做 — 默认格式）

```markdown
# {技术选型主题} — 决策简报

## 是什么: 认识候选者
### 1. 每个候选方案的定位
### 2. 它们各自的运作方式
### 3. 关键差异速览表

## 为什么: 证据驱动的判断
### 4. 每条关键结论的证据链
### 5. 争议与裁决
### 6. 为什么不是另一个

## 怎么做: 落地路径
### 7. 推荐决策
### 8. 起步指南
### 9. 信息缺口与后续关注
### 10. 引用与溯源
```

#### evidence-first（证据优先 — 面试展示用）

```markdown
# {主题} — 证据优先简报

## 结论（1句话）
## 为什么信这个结论
### 最强的一条证据
### 支撑证据链
## 反向证据
## 争议点
## 我们还不知道的
## 如果你要做决策
```

**非 MVP，后续扩展**:
- `structured` — 8段正式报告
- `decision-tree` — 决策树条件分叉
- `one-pager` — 一页纸高管摘要

---

## 7. SelfReviewer — 质量门禁与定向补搜

### 6项硬编码检查单（LLM执行）

1. 每条结论是否都有来源支撑？
2. 是否有无来源的结论？
3. 推荐方案是否覆盖了所有5个对比维度？
4. 是否存在未标注的信息冲突？
5. 用户问题中是否有子问题未回答？
6. 是否有反例或负面信息未标注？

### 置信度判定

- high: 6/6 通过
- medium: 1-2项未通过, severity无critical
- low: >=3项未通过 OR 存在critical缺口

### 定向补搜

- gaps <= 2: 关键词直搜 Tavily -> 结果追加 -> ConflictDetector
- gaps > 2: 回 QueryAnalyzer(仅缺口) -> 完整重走 -> ConflictDetector
- retry_count++, 上限1, 第2次low -> END标红

---

## 8. 用例生成系统

### 顶层结构

5类别 x 10子域 x 3场景 x 3难度 x 变体因子 -> 1000+

### 50子域

| 类别 | 子域 |
|------|------|
| AI/Agent框架 | Agent编排, MCP生态, 工具调用, LLM调用层, 多Agent协作, Prompt管理, RAG框架, 记忆系统, 安全护栏, 评估框架 |
| 模型与数据 | LLM选型, Embedding模型, Reranker, 向量数据库, 图数据库, 文档解析, 数据管道, 提示策略, 微调方案, 多模态 |
| 后端框架与API | Web框架, API范式, 认证授权, 序列化, 中间件, 依赖注入, 异步方案, 任务队列, 文件存储, API网关 |
| 基础设施 | 关系型DB, NoSQL, 缓存, 消息队列, 搜索引擎, 对象存储, 服务发现, 配置中心, 分布式协调, 流处理 |
| 部署运维 | 容器编排, CI/CD, 监控, 日志, 链路追踪, 云平台, IaC, 灰度发布, 安全扫描, 灾备 |

### 场景 x 难度矩阵

| 难度 | Solo(1-5人) | 团队(20-100人) | 企业(500+人) |
|------|-----------|-------------|-----------|
| 简单 | 单点二选一,够用就行 | 性价比导向 | 合规性评估 |
| 中等 | 框架选型,考虑未来 | 同类横向对比,TCO | 企业级对比,SLA |
| 困难 | 全栈组合选型 | 跨层架构,多组件协调 | 平台级,合规/高可用/多团队 |

### 存储

- `tests/test_cases/known_cases.json` — 100精选用例（手工review, CI回归）
- `tests/test_cases/taxonomy.json` — 分类学+生成规则
- `tests/test_cases/generator.py` — 用例生成器（按需产出）

---

## 9. 评估体系

### 7维评估

| 维度 | 判断方式 |
|------|---------|
| 事实准确性 | LLM-as-Judge + 100精选用例人工 ground truth |
| 来源质量 | 人工抽查 top 5 来源评分 |
| 冲突裁决质量 | 人工评估裁决正确率 |
| 覆盖完整性 | 自动化: sub_questions vs 报告章节 |
| 证据可溯源性 | 自动化: URL有效 + snippet匹配 |
| 诚实度 | 人工评估间隙声明充分性 |
| 报告可读性 | LLM-as-Judge + 人工抽查 |

### LLM-as-Judge Rubric

5维评分(1-5), 每维: 事实一致性 / 证据充足性 / 推理逻辑 / 诚实度 / 回答完整度。及格线 total >= 3.5。

### 回归测试(CI)

每次 git push: 30个回归用例 -> LLM-as-Judge 自动评分 -> 对比基线。通过率下降 >10% = 阻断。

### 人工评估策略

- 开发期: 每次大改动抽 5 精选用例
- 评估期: 30精选 + 30生成（分层抽样）
- 面试前: 10 Demo用例确保不出错

---

## 10. SSE流式推送 + Streamlit前端

### FastAPI SSE 事件格式

```
data: {"phase": "query_analysis", "status": "running|done", ...}
data: {"phase": "retrieval", "status": "running", "channel": "tavily|chroma|...", ...}
data: {"phase": "source_evaluation", "status": "done", "high_quality_count": N}
data: {"phase": "conflict_detection", "status": "done", "conflicts_found": N}
data: {"phase": "report_generation", "status": "done"}
data: {"phase": "self_review", "status": "done", "confidence": "high|medium|low"}
data: {"phase": "complete", "report": "...", "snapshot_id": "..."}
```

每个节点 running -> done 两个事件, 前端据此控制进度条。

### API端点

```
GET  /health
POST /research
GET  /research/{task_id}/stream      SSE事件流
GET  /research/{task_id}/report      (支持 ?format= 切换)
GET  /research/{task_id}/snapshot    研究快照JSON
POST /research/{task_id}/regenerate  从快照换格式重新渲染
GET  /history
```

### Streamlit 前端（单页三区）

| 区域 | 功能 |
|------|------|
| 输入区 | query + 格式选择 + 场景选择 + 开始按钮 |
| 进度区 | 7节点实时状态, 失败时显示原因 |
| 报告区 | Markdown渲染 + 顶部工具栏(切换格式/下载/查看证据面板) |

### 证据侧面板

点击报告中任意结论旁的 [证据] -> 弹出: 来源URL, snippet, 四维评分明细, 证据强度, 原始链接。面试时点一下 -> 面试官直接看到"这个答案是怎么来的"。

---

## 11. 目录结构

```
deepchoice/
  src/
    state.py, task.py
    agents/
      query_analyzer.py, multi_retriever.py, source_evaluator.py,
      conflict_detector.py, evidence_chain.py, report_generator.py,
      self_reviewer.py, orchestrator.py
    retrievers/
      tavily_search.py, chroma_kb.py, github_api.py,
      arxiv_api.py, community.py, official.py
    formats/
      what_why_how.py, evidence_first.py
      (structured.py, decision_tree.py, one_pager.py — 后续)
    server/
      app.py, sse.py, snapshot_store.py
    utils/
      llm.py, views.py, dedup.py
  frontend/
    app.py
  tests/
    test_cases/ (known_cases.json, taxonomy.json, generator.py)
    test_agents.py, test_retrievers.py, test_pipeline.py, test_eval.py
  outputs/{task_id}/ (research_snapshot.json, report.md)
  chroma_kb/ (setup.py, data/ official/ blogs/ papers/)
```

---

## 12. 风险、边界与局限

### 风险面

| 风险 | 缓解 |
|------|------|
| 信息茧房 | 6路来源异构, 三层金字塔KB |
| 幻觉引用 | EvidenceChain 从检索结果取URL, LLM不编造 |
| 来源偏见 | 英文来源主导, GitHub Star不直接决定推荐 |
| 可验证性 | 证据侧面板 + 研究快照完整可审计 |

### 边界（MVP不做）

HITL标注、ToT五分支对比、PDF/Word导出、多语言报告、流式逐字打字、用户登录、历史搜索、代码分析。

### 已知退化场景

极致小众技术（结果<5条）、极新技术（<1个月,无可交叉验证）、跨语言选型（中文信息不足）、无公开Benchmark场景、高度同质候选（难分高下）、query歧义。

每个退化场景在报告中诚实标注，SelfReviewer 触发 low 置信度，报告标红。

### 架构固有局限

单Pipeline线性流（不可自适应调节深度）、重试上限1次（可能仍不够）、不维护长期记忆（每次独立）、KB静态20篇（不自动更新）。

---

## 13. 从方案A保留的决策

- 项目定位+叙事方向（技术选型Deep Research Agent, 你不是技术专家）
- 双模报告 -> 改为: 入口选格式, 研究快照驱动, 5种格式逐步扩展
- P2 冲突裁决+Reflection 焊入（P2 不做了）
- 规则引擎四维评分（不用 LLM）
- 本地KB精选参考源, 非技术笔记
- Agent 类模式复用 P1（call_model, StateGraph 编排, 检索器注册）
- 本地 bge-m3 模型加载复用 P1
- FastAPI SSE 流式推送

### 不用的

- P1 劳动法 Agents
- GPT Researcher 20+ Web 检索器（只用 Tavily 模式）
- P1 双循环编排（换为单 Pipeline + 定向重试）
- OpenHarness 代码（不 fork）

---

## 14. 成本估算

### LLM（单次研究, DeepSeek V4 混合）

| 节点 | 模型 | 成本 |
|------|------|:--:|
| QueryAnalyzer | V4 Flash | ¥0.001 |
| ConflictDetector | V4 Pro | ¥0.029 |
| ReportGenerator | V4 Flash | ¥0.018 |
| SelfReviewer | V4 Flash | ¥0.009 |
| **合计** | | **¥0.057** |

### 外部 API

| API | 定价 | 开发期 | 评估期 |
|-----|------|:--:|:--:|
| Tavily | Free 1000次/月, Pro $30/月 | ¥0 (Free) | ¥216 (Pro x1月) |
| 其余5路 | 全免费 | ¥0 | ¥0 |

### 总成本

| 阶段 | Tavily | LLM | 小计 |
|------|:--:|:--:|:--:|
| 开发期(200试跑) | ¥0 | ¥11 | ¥11 |
| 评估期(1000用例) | ¥216 | ¥57 | ¥273 |
| **总计** | | | **¥284** |

---

## 15. 开发分工

### 你写（核心架构 + 面试必问部分）— 17h

| 模块 | 估时 | 面试价值 |
|------|:--:|:--:|
| state.py + task.py | 1h | 中 |
| orchestrator.py | 2h | 高 |
| query_analyzer.py | 1.5h | 中 |
| source_evaluator.py | 2h | 极高 |
| conflict_detector.py | 2.5h | 极高 |
| evidence_chain.py | 1h | 中 |
| self_reviewer.py | 2h | 高 |
| report_generator.py | 1h | 中 |
| known_cases.json (100用例) | 4h | 高 |

### 我骨架 + 你审查 — ~2.5h

6路检索器(Tavily+Chroma+ArXiv你已有深度, GitHub+社区+官方浅度实现) + multi_retriever调度 + 2种格式渲染 + FastAPI SSE + Streamlit前端 + 20用例

### 集成 — ~4h

KB 10篇入库 + 全链路联调 + 3个E2E用例

### 总耗时: ~23.5h, 3-4天

---

## 16. 实现顺序

| 天 | 上午(3h) | 下午(3h) |
|:--:|------|------|
| 7/6 | state+task+orchestrator | query_analyzer+source_evaluator |
| 7/7 | conflict_detector | evidence_chain+self_reviewer+report_generator |
| 7/8 | 审查检索器骨架+SSE+前端 | 集成联调+KB建库 |
| 7/9上午 | 100精选用例手写 | — |
