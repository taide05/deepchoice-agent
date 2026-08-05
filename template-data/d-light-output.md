# DeepChoice D-light：首次复盘（1-6节）

> 执行时间：2026-08-05 | 数据来源：git log（25 commits）+ README + 核心源码 + 面试深挖手册
> 本输出为 E→C→D-full→I→V→R→A→B 链路的起始输入。

---

## 1. 设计决策审计（5条）

### 决策 #1：9 Agent LangGraph 管线 vs 单次巨型 Prompt

- **决策**：将技术选型研究拆成 9 个独立 Agent 节点，用 LangGraph StateGraph 串成有向图管线
- **当时理由**：技术选型研究是多阶段认知任务——拆解问题→搜索证据→评估信源→仲裁矛盾→综合结论→质量审查——每个阶段需要不同的推理逻辑和工具。拆成独立 Agent 让每个节点只做一件事，出错边界清晰、每个节点可独立优化。巨型 prompt 做所有事质量不可控，错误传播无边界
- **代码证据**：`src/deepchoice/agents/orchestrator.py:60-93` — `_create_workflow()` 方法定义了 9 节点 + 条件路由，`_route_after_review()` 实现三级路由（end/retry_small/retry_full），max retry_count=1
- **替代方案 B**：单次 ReAct Agent 循环（一个 Agent 反复调用工具直到满意）——对简单对比任务可能更快（少一轮 Agent 间序列化开销），但复杂多源任务的质量不可控
- **重来判定**：还是会选 A。9 Agent 的模块化边界让后续优化（如冲突检测 LLM 替代否定词匹配、conclusion_synthesizer flash→pro）只需改一个节点，不波及全局
- **可测试断言**：
  - 9 Agent 管线在无 retry 触发时，P50 延迟应在 150-200s 区间（来自当前基准 184s）
  - retry_small（回 query_adapter）触发时，延迟增加应 < 60s（仅多一次检索适配+检索+审查）
  - retry_full 触发率应 < 5%（反映多数 case 不需要重新拆解问题）
- **面试价值**：9/10。面试官会问"为什么 9 个而不是 3 个或 15 个？""拆分粒度怎么决定的？""如果有一个 Agent 挂了怎么处理？"

### 决策 #2：信源评分用规则引擎而非 LLM

- **决策**：Authority/Timeliness/Consistency/Verifiability 四维评分全部用 URL 模式匹配 + 日期计算 + 关键词检测（规则引擎），不调 LLM
- **当时理由**：评分需要确定性和可复现性。用 LLM 评分会引入幻觉风险——它可能给一篇 CSDN 博客打 9 分。量化评估场景下，确定性比灵活性更重要
- **代码证据**：`src/deepchoice/agents/source_evaluator.py:4-9` — `WEIGHTS` 字典定义四维权重（authority 0.35/timeliness 0.25/consistency 0.20/verifiability 0.20）；`:11-27` — `AUTHORITY_MAP` 和 `VERIFIABILITY_MAP` 纯规则映射（official_doc→10, reddit→4, code→10, opinion→2）
- **替代方案 B**：LLM 逐条打分——对非标准来源（小众论坛、个人 Wiki）可能更灵活，但评分不可复现、成本高、且 LLM 对来源权威性的判断受训练数据偏差影响
- **重来判定**：核心逻辑保留规则引擎。但可加一个 LLM fallback——来源类型无法被 `classify_source_type()` 识别时（返回 "tech_blog" 兜底），用 LLM 做一次权威性判断，覆盖规则引擎的盲区。当前 100% 依赖 URL 模式——`arxiv.org`→arxiv_paper、`github.com`→github 等——对未知域名一律归为 tech_blog（authority=7），可能高估小众论坛的可信度
- **可测试断言**：
  - 同一批 50 case 跑两次评分，分数应完全一致（确定性验证）
  - 已知 official_doc 类来源（如 fastapi.tiangolo.com）的 Authority 分应为满分 10
  - 已知低质量来源（如 CSDN 博客、个人 Medium）的 Authority 分应 ≤ 5
- **面试价值**：8/10。展示"知道什么时候用规则、什么时候用 LLM"的工程判断力

### 决策 #3：两阶段冲突仲裁（flash 批量 + pro 深裁）

- **决策**：冲突检测分两阶段——BGE-M3 标题余弦相似度预筛（>=0.6）→ flash 批量初裁所有矛盾对 → 取分数差距最小（最模糊）的 1 对给 pro 深度重裁
- **当时理由**：100 case 实测发现多数技术选型场景不存在直接矛盾（冲突检测率 2.2%），没必要对所有候选对用 pro 深度分析。flash 便宜且快（~3s/对），pro 精准但贵（300s timeout），只给最模糊的 1 对走 pro，费用可控
- **代码证据**：`src/deepchoice/agents/conflict_detector.py:15-16` — `FLASH_SEM = asyncio.Semaphore(30)`, `PRO_SEM = asyncio.Semaphore(10)` 并行度控制；`:22-45` — `ARBITRATION_PROMPT` 定义四结果（A_correct/B_correct/both_partial/insufficient_data）；commit `455e805` 将否定词匹配替换为 LLM 语义扫描
- **替代方案 B**：全部用 pro 深度仲裁——可能更准但 P95 延迟会爆炸（旧版 P95 410s 就是因为没有两阶段优化）。或全部用 flash——快但关键矛盾的裁决质量不够
- **重来判定**：选 A。两阶段是延迟-质量的最优折中。commit `455e805` 的实测数据：P50 162.6s→130.5s（-20%），P95 410.3s→164.2s（-60%），证明效果显著
- **可测试断言**：
  - 两阶段仲裁后 P95 延迟应 <= 250s（当前 248s，不应退化）
  - flash 初裁后进入 pro 重裁的比例应 <= 10%（只有最模糊的对才走 pro）
  - LLM 语义扫描不应产生假阳性（否定词匹配时代的 100% 假阳性问题已修复）
- **面试价值**：9/10。展示"成本感知的架构设计"——知道在哪用力、在哪省钱

### 决策 #4：前置澄清模块采用混合式+软门禁

- **决策**：在 9 Agent 管线前加一个多轮对话澄清模块，帮用户把"帮我选个框架"这种模糊需求澄清到"团队 5 人、中等复杂度、后端 REST API、关注性能"。软门禁——用户不知道该选什么时按类别推荐候选技术，不强求填满所有字段
- **当时理由**：技术选型场景的核心痛点是用户需求模糊。GPT Researcher 等竞品直接搜，结果和用户实际场景脱节。澄清让后续检索更有针对性。软门禁而非硬门禁——不强求用户填满所有维度，避免过度引导
- **代码证据**：`src/deepchoice/clarify/clarification_agent.py` + `clarify_routes.py` + `session_manager.py`；`src/deepchoice/agents/orchestrator.py:119-120` — `has_sub_questions = bool(task.get("sub_questions"))` 决定是否跳过 QueryAnalyzer 直接从 QueryAdapter 开始
- **替代方案 B**：硬门禁——强制填满所有维度后才开始研究。对新手用户更友好但可能过度引导，对有经验用户是负担。或不加澄清直接搜——快但结果可能和用户场景脱节
- **重来判定**：选 A。软门禁是合理的 UX 折中。但澄清模块的推荐逻辑（推荐候选技术）依赖 curated list，覆盖面有限，应在用户反馈中持续扩展
- **可测试断言**：
  - 有澄清 vs 无澄清的准确率差异应在 +5-10 个百分点（场景信息帮助检索定位）
  - 澄清模块在有明确 query（如"FastAPI vs Flask"）上不应增加超过 10s 延迟
  - 澄清模块对模糊 query（如"帮我选个后端框架"）应能推荐至少 3 个候选技术
- **面试价值**：7/10。展示"UX 感知的架构设计"——知道什么时候需要用户输入、什么时候不需要

### 决策 #5：SelfReviewer 最多重试 1 次 + 三级缺口路由

- **决策**：SelfReviewer 做 6 项质量检查后分三级路由——high/medium 直接结束 → ≤2 个知识缺口回 QueryAdapter 补搜 → >2 个缺口回 QueryAnalyzer 重新拆解。最多重试 1 次
- **当时理由**：防止死循环。Agent 管线可能因为模型幻觉陷入无限重试——LLM 每次都说有缺口、每次都触发 retry。限制 1 次 + retry_count 递增打破循环。retry_small（回 QueryAdapter）比 retry_full（回 QueryAnalyzer）更轻量——补搜比重新拆解便宜
- **代码证据**：`src/deepchoice/agents/orchestrator.py:95-107` — `_route_after_review()` 方法实现三级路由；`src/deepchoice/agents/self_reviewer.py:40-48` — 6 项检查清单 + 三级信心评定
- **替代方案 B**：不限重试次数直到 confidence=high——理论质量更高但实际可能无限循环（LLM 不是确定性的）。或不重试直接接受 medium 结果——更快但可能输出质量下降
- **重来判定**：选 A。最多 1 次是正确选择——实测 3% 失败率中部分来自 SelfReviewer 间歇 `str.get` bug（不是重试次数不够），修 bug 比增加重试次数更有效
- **可测试断言**：
  - retry 触发率应在 5-15%（少数 case 需要补搜，不应是常态）
  - retry 后 medium→high 转化率应 > 50%（重试确实有帮助）
  - 不应出现同一 case 触发 2 次以上 retry（max 1 次设计）
- **面试价值**：8/10。展示"防死循环的工程意识"——Agent 系统不是一劳永逸的，需要安全边界

---

## 2. 模块清单 + 迭代历史

| 模块 | 职责（一句话） | 关键设计点 | 当前指标（来自 README） | git 改动次数 | 已知问题 |
|------|---------------|-----------|----------------------|:--:|---------|
| **QueryAnalyzer** | 模糊 query → 5 维子问题 | 功能/性能/生态/开发体验/场景适配五维拆解 | — | 2 | 拆解质量依赖 LLM，对非主流技术可能拆解不准 |
| **QueryAdapter** | 子问题 → 6 种检索器专用查询 | 语言感知（中文 query→中文搜索词），每个子问题生成 6 套格式 | — | 2 | 架构 v2 新增模块，较新 |
| **MultiRetriever** | 6 路并行搜索 | `asyncio.gather` 并发，单路挂不炸全局 | 6 路并行 | 2 | 无重试机制，单路超时直接丢结果 |
| **SourceEvaluator** | 四维规则打分 | Authority 0.35/Timeliness 0.25/Consistency 0.20/Verifiability 0.20 | — | 3 | 对未知域名一律归 tech_blog（authority=7），可能高估小众来源 |
| **ConflictDetector** | BGE-M3 预筛 + LLM 两阶段仲裁 | flash sem=30 / pro sem=10 / 证据收集 sem=3 | 冲突检测率 2.2% | **9**（最复杂模块） | 2.2% 反映真实场景缺乏矛盾，面试中难以展示价值 |
| **EvidenceChain** | 按分数分 strong/moderate/weak 三级 | 规则分级（strong>=8.0 且有支持源），提取争议 URL 集 | — | 2 | 预处理层，质量问题在上下游 |
| **ConclusionSynthesizer** | 综合证据链输出最终推荐 | pro 模型（从 flash 升级），含 Winner + 排名 + trade-off | — | 4 | 依赖上游证据质量，垃圾进垃圾出 |
| **ReportGenerator** | 3 种格式渲染 | 纯渲染层，数据一致性由格式层保证 | 3 种格式 | 3 | 语言感知在 format 层做，不在 report_generator |
| **SelfReviewer** | 6 项检查 + 三级信心评定 | 汇总上游 quality_signals，不重复扫描 | 报告质量 A 级 97% | 2 | 间歇 `str.get` bug 影响 ~3% 成功率 |
| **Clarify 模块** | 混合式多轮澄清 | 软门禁 + 候选技术推荐 + 最多 3 轮 | — | 1 | 推荐列表依赖 curated list，扩展性受限 |
| **6 路检索器** | Tavily/ArXiv/GitHub/Community/ChromaDB/Official | 统一 BaseRetriever 接口 | 信源召回率 34.8% | 3-6（不等） | Official retriever 覆盖面受限，Tavily 偏好 SEO 博客 |

**迭代历史总结**（25 commits，b62abc3..42f82a8）：
- **阶段 1（Initial → v2 架构）**：基础 7 Agent 管线 → 加 QueryAdapter + ConclusionSynthesizer + quality_signals 贯穿（commit `41f2e26`）
- **阶段 2（冲突检测迭代）**：单阶段 LLM → 两阶段仲裁（`2180bc1`）→ 内联证据收集（`777f1c4`）→ 否定词检测扩展（`362ab49`）→ LLM 语义扫描替代否定词（`455e805`）— **4 次迭代，最频繁的模块**
- **阶段 3（质量打磨）**：conclusion_synthesizer flash→pro（`6631bbc`）→ benchmark 基础设施（`f571513`）→ 检索器层改进（`ab952c4`）→ 语言感知报告（`173b837`）
- **阶段 4（工程化）**：Docker 多阶段构建（`8d5773f`）→ 最新修复（`42f82a8`）

关键转折点：commit `455e805`（LLM 扫描替代否定词匹配）— 彻底消除了冲突检测的假阳性问题（100%→0%），同时 P95 延迟 -60%。

---

## 3. 踩坑记录（3条）

### 坑 #1：否定词匹配产生 100% 假阳性

- **现象**：早期冲突检测用否定词匹配（"not"/"but"/"however"）判断矛盾，100 case 中触发大量假阳性——两篇文章一个说"FastAPI is fast"另一个说"FastAPI is not slow"，被标记为矛盾对
- **根因**：否定词出现不代表语义矛盾。"not slow" = "fast"，两篇文章观点一致。纯关键词匹配不理解语义
- **修复 commit**：`362ab49` 将否定词检测从 title-only 扩展到 title+snippet（未解决根本问题）→ `455e805` 用 LLM 语义扫描（`CONTRADICTION_SCAN_PROMPT`）完全替代否定词匹配，彻底消除假阳性
- **如果一开始就知道**：不会在否定词匹配上浪费两次迭代（`362ab49` + `455e805`）。直接上 LLM 语义扫描——flash 模型对简单语义判断任务足够且便宜，没必要先尝试规则方案。规则方案只在"可穷举的模式"上有优势（如 URL→来源类型），语义判断一开始就该用 LLM
- **可测试断言**：LLM 语义扫描的假阳性率应为 0%（在已知非矛盾的 case 上验证——如两篇文章都推荐同一个技术，不应被标记为矛盾）

### 坑 #2：conclusion_synthesizer flash 模型输出质量不足

- **现象**：结论综合环节用 flash 模型时，输出有时不包含明确的 winner 名称（只说"推荐第一个选项"），且 trade-off 分析偏浅
- **根因**：flash 模型在需要综合多个证据链、比较多个维度时，推理深度不够。`e390400` 修了输出格式（强制输出 winner name），但格式修复不能解决推理深度问题
- **修复 commit**：`6631bbc` 将 conclusion_synthesizer 从 flash 升级为 pro 模型——这是管线中唯一升级到 pro 的节点（除冲突仲裁中只给最模糊一对走 pro 外）
- **如果一开始就知道**：管线中区分"需要推理深度"和"只需要速度"的节点——conclusion_synthesizer 是推理密集节点（综合所有上游证据做最终决策），一开始就该用 pro。QueryAnalyzer/MultiRetriever 等属于执行密集节点，flash 够用
- **可测试断言**：pro 模型输出的 winner name 提取成功率应为 100%（`extract_top_recommendation()` 能从报告中提取到有效技术名），vs flash 时代的 < 90%

### 坑 #3：Docker 构建——Windows wheels vs Linux 不兼容

- **现象**：在 Windows 上 `pip install -e .` 能跑，但 Docker 构建时 `pip install` 报错——部分包（如 chromadb 的 onnxruntime 依赖）没有对应 Linux wheel
- **根因**：开发环境 Windows、部署环境 Linux（Docker），`requirements.txt` 或 `pyproject.toml` 中包版本未区分平台。`chromadb` 在 Windows 上依赖 `onnxruntime`（有 Windows wheel），在 Linux 容器中需要 `onnxruntime-linux`
- **修复 commit**：`8d5773f`（Docker 多阶段构建）+ `42f82a8`（docker env vars 修复）。混合构建方案——wheels 本地 + 清华镜像兜底
- **如果一开始就知道**：开发初期就在 Linux 容器中验证 `pip install`，而不是等到要 Docker 化时才踩坑。或者在 `pyproject.toml` 中加平台条件依赖。核心教训：开发环境和部署环境的差异越早暴露越好
- **可测试断言**：`docker compose up` 后 `/health` 端点返回 HTTP 200 + `{"status":"ok"}`——每次 Dockerfile 修改后必跑

---

## 4. 替代方案对比矩阵

| 维度 | DeepChoice | GPT Researcher | Perplexity Deep Research | 手动 Google + ChatGPT |
|------|:--:|:--:|:--:|:--:|
| **结果可信度** | 4 — 四维评分+两阶段仲裁+自审查，可审计 | 3 — 多源搜索但评分机制不透明 | 3 — 有来源引用但无矛盾处理 | 2 — 依赖个人判断，无系统化评分 |
| **覆盖广度** | 4 — 6 路并行（学术+代码+社区+官方+本地+网页） | 3 — 主要网页搜索 | 4 — 网页+学术+部分结构化数据 | 3 — 取决于个人搜索范围 |
| **延迟** | 3 — P50 184s（~3 分钟） | 4 — 通常 < 60s | 5 — < 30s（商业基础设施） | 1 — 几小时到几天 |
| **成本** | 4 — DeepSeek API（flash 为主，pro 仅关键时刻） | 3 — 需 GPT-4 API | 5 — $20/月订阅 | 5 — 免费（除人力成本） |
| **可定制性** | 5 — 开源，全链路可控，每个节点可替换 | 3 — 开源但定制需深入源码 | 1 — 闭源，无定制 | 5 — 完全自由 |
| **溯源能力** | 5 — 97% 声明可追溯到具体来源 URL | 2 — 有来源但关联不紧密 | 3 — 有脚注但无证据强度分级 | 2 — 取决于个人笔记习惯 |

**综合**：DeepChoice 在可审计性和可定制性上领先，在延迟和成本上处于中上水平。最大差距是延迟（vs 商业产品）——但这是架构选择（9 Agent 管线）的必然代价，对研究类任务可接受。

---

## 5. 薄弱点自诊断

### 面试中最怕被追问的 3 个问题

**薄弱 #1："冲突检测率只有 2.2%，这个模块是不是白做了？"**
- 代码中的模糊地带：2.2% 说明多数技术选型场景的信源之间本就无直接矛盾。但面试官可能认为"做了一整套两阶段仲裁+证据收集基础设施，结果只检测到 2.2% 的矛盾，ROI 太低"
- 防御策略：100 case 全部是"X vs Y"二选一场景——不是"React 好不好"这种开放讨论（开放讨论的冲突率会高得多）。2.2% 恰恰证明管道没有制造假矛盾（过去否定词匹配的假阳性教训）。冲突检测模块的价值在"有矛盾时不翻车"，不在"没事时刷存在感"
- **可测试断言**：在"开放讨论"类 query（如"React 的优缺点"而非"React vs Vue"）上，冲突检测率应显著高于 2.2%（预期 15-30%），验证模块在真正有矛盾的场景下有效

**薄弱 #2："信源召回率 34.8%，一半以上的预期来源找不到——这还能叫 Deep Research 吗？"**
- 代码中的模糊地带：must_find_sources 要求召回"官方文档域名"（fastapi.tiangolo.com / flask.palletsprojects.com 等），但 Tavily 搜索引擎天然偏好 SEO 优化的博客而非官方文档。Official retriever 已加 26 个技术官方文档直连映射（`42f82a8`），但覆盖面仍受限
- 防御策略：34.8% 是 must_find_sources 的严格匹配召回率（URL 包含指定域名才算找到）。实际研究效果——Tavily 搜到的博客文章引用了官方文档内容，信息本身不失真，只是来源间接了。改进方向：Official retriever 从 curated list 改为动态发现（从 Tavily 结果中提取官方域名→直接访问验证→加入映射）
- **可测试断言**：Official retriever 的 26 个技术映射应全部可达（HTTP 200）。新增 10 个随机技术后，至少 6 个能通过 Tavily 结果自动发现官方文档域名

**薄弱 #3："9 Agent 管线，每个节点等上一个——如果中间某个 Agent 超时了怎么办？"**
- 代码中的模糊地带：当前管线是严格顺序的（add_edge 链），虽然有 120s API timeout（`4017937`），但没有 Agent 级别的超时+优雅降级。如果 conflict_detector 超时，整个管线挂掉
- 防御策略：LangGraph 的 checkpoint 机制（AsyncSqliteSaver）持久化状态，超时后可以从断点恢复而非重头跑。但不优雅——理想方案是每个 Agent 有独立 timeout + fallback（如 conflict_detector 超时则跳过仲裁直接进 evidence_chain，标记"conflicts not resolved"）
- **可测试断言**：注入一个 5s 内必超时的 Agent（mock），管线应能优雅降级而非崩溃。恢复后从 checkpoint 继续应能完成剩余节点

### 如果给两周时间，优先级最高的 5 个改进

| 优先级 | 改进 | 量化目标 | 理由 | 改动文件 |
|:--:|------|---------|------|---------|
| 1 | 信源召回率提升 | 34.8% → 60%+ | 这是 README 中明确标注的"已知局限"，也是面试中最容易被攻击的点 | `retrievers/official.py`（动态官方文档发现）+ `retrievers/tavily_search.py`（增加 site: 限定搜索） |
| 2 | Agent 级 timeout + 优雅降级 | 每个 Agent 有独立 180s timeout | 薄弱 #3——当前管线无 Agent 级容错，一个挂了全挂 | `orchestrator.py`（加 timeout wrapper）+ 各 Agent 节点 |
| 3 | 200 case 全量 benchmark 跑通 | 完成 `run_full_200.py` | README 已有 `run_full_200.py` 文件但未实际跑过 200 case。E 模板执行时会产出数据 | `benchmarks/run_full_200.py` + `benchmarks/cases_200.json` |
| 4 | SelfReviewer `str.get` bug 修复 | 成功率 97% → 99%+ | 3% 失败直接吃掉 3 个 case，修复后 Top-1 计算基数增加 | `agents/self_reviewer.py`（检查 `dict.get` 调用是否安全） |
| 5 | Streamlit 前端加错误状态展示 | 用户能看到每个 Agent 状态 | 目前前端只展示最终结果，不展示中间 Agent 状态——面试官可能问"用户怎么知道管道在哪一步卡住了" | `frontend/app.py`（加 SSE 事件类型映射到 UI 状态） |

---

## 6. 可测试断言清单（给 E 的输入）

### 6a. 来自设计决策审计（第 1 节）

| # | 断言 | 来源 | E 怎么验 | 优先级 |
|:--:|------|:--:|---------|:--:|
| A1 | 9 Agent 管线无 retry 触发时 P50 延迟 150-200s | 决策 #1 | 跑 100+ case，筛选 retry_count=0 的 case，计算 P50 latency | P0 |
| A2 | retry_small 触发率 < 10% | 决策 #5 | 统计 200 case 中 retry_count > 0 的比例 | P1 |
| A3 | retry_full 触发率 < 5% | 决策 #1 | 统计 200 case 中进入 retry_full 路径的比例 | P1 |
| A4 | 同一 case 不应触发 > 1 次 retry | 决策 #5 | 检查 retry_count 最大值是否为 1 | P0 |
| A5 | 信源评分确定性——同批 case 跑两次分数完全一致 | 决策 #2 | 跑 10 case 两次，对比 source_evaluator 输出分数是否逐条一致 | P0 |
| A6 | 两阶段仲裁 P95 延迟 <= 250s | 决策 #3 | 从 E 产出计算 P95 latency，对比 README 当前值 248s | P0 |
| A7 | LLM 语义扫描假阳性率 = 0%（在已知非矛盾 case 上） | 决策 #3 | 取 10 个 annotated case 中 known_contradictions=[] 的 case，检查 conflict_detector 输出不应包含 | P1 |
| A8 | 有澄清 vs 无澄清：场景信息充足的 query 上准确率差异 < 3pp | 决策 #4 | 取 "scene" 明确的 case，对比有/无澄清模块的 Top-1 准确率 | P2 |
| A9 | 澄清模块对明确 query 不增加 > 10s 延迟 | 决策 #4 | 计时 clarify 模块的 session_manager + clarification_agent 总耗时 | P2 |

### 6b. 来自踩坑记录（第 3 节）

| # | 断言 | 来源 | E 怎么验 | 优先级 |
|:--:|------|:--:|---------|:--:|
| B1 | 结论中 winner name 提取成功率 100%（pro 模型） | 坑 #2 | 对 200 case 每个 report 跑 `extract_top_recommendation()`，统计非 None 比例 | P0 |
| B2 | Docker `/health` 端点返回 200 | 坑 #3 | `docker compose up -d && curl localhost:8000/health` | P0 |
| B3 | conflict_detector 的 LLM 语义扫描不产生假阳性 | 坑 #1 | 取 20 个明确非矛盾的 case（如两篇都推荐同一技术），验证冲突检测输出为空 | P1 |

### 6c. 来自薄弱点自诊断（第 5 节）

| # | 断言 | 来源 | E 怎么验 | 优先级 |
|:--:|------|:--:|---------|:--:|
| C1 | 在"开放讨论"类 query 上，冲突检测率应 > 15%（vs 当前 2.2% 在 X vs Y 场景） | 薄弱 #1 | 创建 5 个开放讨论 query（如"Is React good for enterprise apps?"），跑 pipeline 统计冲突检测率 | P1 |
| C2 | 信源召回率在 Official retriever 26 个映射覆盖的技术上应 >= 50% | 薄弱 #2 | 从 annotated case 中筛选 tech_a/tech_b 在 Official retriever curated list 中的 case，单独计算召回率 | P1 |
| C3 | Official retriever 26 个技术映射 URL 全部可达（HTTP 200） | 薄弱 #2 | 写脚本逐条 HEAD/GET Official retriever 中每个技术的官方文档 URL | P1 |
| C4 | SelfReviewer 不产生 `str.get` AttributeError | 薄弱 #4 | 跑 200 case，收集 error log，统计 str.get 相关报错次数 | P0 |
| C5 | Agent 超时后管线不崩溃（需先实现 Agent 级 timeout） | 薄弱 #3 | 注入 mock Agent（固定 5s 超时），验证 pipeline 不崩 + 能从 checkpoint 恢复 | P2 |

---

**断言来源覆盖自检：**
- 6a（设计决策）：9 条 ✅
- 6b（踩坑记录）：3 条 ✅
- 6c（薄弱点）：5 条 ✅
- 三来源齐全 ✅
