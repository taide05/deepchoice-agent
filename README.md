# DeepChoice — AI 驱动的技术选型深度研究 Agent

DeepChoice 是一个基于 LangGraph 的多 Agent 研究系统，输入"FastAPI vs Flask 该选哪个"就能自动搜索 6 路数据源、给每篇信源打分、检测矛盾观点并用两阶段仲裁解决、最终输出有据可查的对比推荐报告。

## 为什么值得关注

技术选型搜索通常靠开发者自己翻博客、刷 GitHub、看文档，几个小时下来还不确定信源质量。DeepChoice 把这个过程自动化了——不只是搜，而是评分、对比、仲裁、自审，每一句推荐都能追溯到具体来源。

与 Perplexity/ChatGPT 的对比：它们给答案但不展示证据链和矛盾处理过程。DeepChoice 的输出是**可审计的**——你会看到每篇文章的信源评分、冲突观点是怎么仲裁的、结论为什么可信。

## 核心特性

- **6 路并行检索**：Tavily 网页搜索 + arXiv 论文 + GitHub 仓库 + ChromaDB 本地知识库 + StackExchange 社区 + 官方文档直连（当前 227 条：96 种子 + 131 运行时自学习入库），`asyncio.gather` 并发跑，单路挂了不炸全局
- **Tavily 密钥池故障转移**：多 key 轮换，401/432 自动拉黑并持久化到耗尽池（SHA256 哈希状态文件，28 天自动重探），429 限流瞬态退避不误杀，额度耗尽自动切换到仍有额度的 key
- **4 维信源评分**：Authority（官方文档 > 个人博客）、Timeliness（90 天内 > 2 年以上）、Consistency（多源一致 > 孤立观点）、Verifiability（有代码 > 纯观点），规则引擎打分，不靠 LLM 拍脑袋
- **两阶段冲突仲裁**：先让 flash 模型仲裁所有矛盾对（快），再挑出最模糊的一对交给 pro 模型深度重裁（准）。只给一对走 pro，费用可控
- **自审查 + 定向重试**：最后一环用 6 项清单审查报告质量，发现问题自动补搜知识缺口，区分小缺口（重走检索适配）和大缺口（重走全管道）
- **3 种报告格式**：What/Why/How 标准报告、Evidence-First 先给结论再列证据、5 维对比矩阵表。同一份数据，不同输出形式
- **前置澄清模块**：混合式多轮对话，帮用户把"帮我选个框架"这种模糊需求澄清到"团队 5 人、中等复杂度、后端 REST API、关注性能"再开始研究
- **可观测性与预算面板**：持久化节点尝试与 LLM/检索调用，展示耗时、重试、失败、Token 与预算余量；外呼先经过原子预算门，触顶时按最低证据生成受限报告或安全终止
- **确定性引用验证**：在结论合成后检查关键声明的引用绑定、规范 URL、公开可达性、数字/否定冲突和词法支持度，只给出 `verified` / `unsupported` / `unreachable` / `unknown`，不增加第二个 LLM 裁判
- **单一持久化人工决策门**：证据结构不足且推荐方向存在实质不确定性时暂停 durable run；用户可补充信息继续、基于现有证据生成明确标记的受限报告，或取消
- **报告阅读视图**：目录导航 + 引用角标→证据链卡片联动 + 信源编号，支持 Markdown/PDF 导出
- **运行契约与可复现清单**：研究请求、启动响应和错误采用 Pydantic 契约；每次运行生成不可变 `RunManifest`，记录模型、调用参数、Prompt 哈希、工作流、检索器和报告模板版本（不包含密钥或原始端点）
- **Durable 默认路径**：Streamlit 通过 `/api/v1/tasks/*` 创建与恢复任务，SSE 支持 `Last-Event-ID` replay/resync；重启恢复后的最终报告仍可查询与导出

## 快速开始

```powershell
# 1. 克隆
git clone https://github.com/taide05/deepchoice-agent.git
cd deepchoice-agent
python -m venv .venv
# PowerShell：.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# Linux/macOS：./.venv/bin/python -m pip install -e ".[dev]"

# 2. 配置 API Key（不要提交 .env）
# DeepSeek 路径：DS_FLASH_API_KEY，或兼容名 DEEPSEEK_API_KEY
# Qwen 路径：QW_FLASH_API_KEY，或兼容名 LLM_API_KEY
# Tavily：TAVILY_API_KEYS（逗号分隔），或单个 TAVILY_API_KEY
# 可选：GITHUB_TOKEN、STACKEXCHANGE_API_KEY

# 3. 启动后端
.\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --reload

# 4. 开新终端，启动前端
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
# 浏览器打开 http://localhost:8501
```

可选网络配置包括 `LOCAL_PROXY`、`FWD_BASE`、`FWD_KEY`、`FWD_TARGETS`、
`OUTBOUND_CHANNELS` 和 `OUTBOUND_CHANNELS_COMMUNITY`。完整配置约定见
[`AGENTS.md`](AGENTS.md)。

Phase 3-2 已接入 durable 检索 SQLite TTL cache，以减少重复外部检索。
`RETRIEVAL_CACHE_ENABLED` 默认值为 `1`，设置为 `0` 可安全关闭缓存；缓存只存储通过
契约与来源校验的成功检索结果，不缓存失败结果或 LLM 响应，旧 `/research` 兼容路径继续绕过缓存。

新的客户端应使用 `POST /api/v1/tasks`。`POST /research` 仅保留一版兼容，会返回弃用响应头；它仍会校验已知字段并拒绝额外字段，成功响应保留
`task_id`/`status`，同时返回 `manifest_id` 供运行审计。API 错误保留兼容的
`detail` 字段，并增加稳定的 `error` 对象（类别、错误码、是否可重试和建议动作）。

Phase 1-A 已补齐任务与运行尝试的生命周期契约：两套状态枚举、完整转移矩阵、
终态与可重试结果集合，以及严格类型边界。失败或超时任务只能通过创建新 run
回到队列；已结束的 run 不会被重新打开。

Phase 1-B 的产品持久化基础使用 `outputs/deepchoice.db`，与 LangGraph 的
`outputs/checkpoints.db` 分离。`deepchoice.persistence` 提供可由启动流程调用的向前迁移 runner；
迁移版本、名称和校验和都会校验，SQLite 连接启用外键、WAL 与有界 busy timeout。
Phase 1-C 新增任务/运行记录的原子持久化、版本化状态更新、稳定分页和任务查询 API。
Phase 1-D 在此基础上增加了带 fencing epoch 的 lease/heartbeat、过期 lease 恢复、
取消与 deadline 优先级、interrupted resume、failed/timed-out retry 新 run，以及产品库中的
LangGraph checkpoint 引用。旧 run 和 manifest 保留用于审计；根 checkpoint namespace 固定为空，
每次 execution epoch 使用隔离的底层 checkpoint namespace 并在写入前校验 lease；resume
固定从产品库已接受且 schema 兼容的 checkpoint ID 起步。执行协调器与 API 的执行开关仍可关闭，
本阶段不承诺多进程调度、分布式锁服务或 checkpoint 内容本身的产品库复制。

Phase 1-E 将任务状态变更与公开 `task_events` 写入同一 SQLite 事务，并以全局单调
`event_id` 支持 `GET /api/v1/tasks/{task_id}/events` 的 `Last-Event-ID` 重放；游标不属于
当前任务或超前时返回 `resync_required` 和脱敏后的当前任务快照。启动流程会只读扫描旧
成功/失败 snapshot，以“相对路径 + SHA-256”幂等导入，不修改原文件；旧 `/research`
入口保持兼容，旧状态别名也可读取 durable task。取消、恢复和跨进程重启的事件历史均保留。

Phase 1-F 完成了 Phase 1 跨模块验收、旧 schema 实际升级、并发/CAS/fencing 故障测试和
运行规范固化；追加的 schema v5 收紧了 legacy import 的 task/run 绑定约束，未修改 v4
迁移历史。完整行为边界与恢复步骤见
[`docs/phase1-runtime-contract.md`](docs/phase1-runtime-contract.md)，验收结论和遗留风险见
[`docs/phase1-acceptance-report.md`](docs/phase1-acceptance-report.md)。

Phase 1-G 把 Streamlit 默认路径切换到 durable task API，增加 immutable `run_results`，并将
公开结果、成功终态和完成事件放在同一事务提交；报告、快照、阅读视图和导出均可在重启后
查询。产品 schema 现为 v10：v8 建立 Phase 2-A 的 RunContext、Trace/Budget 契约及
观测/预算骨架表；Phase 2-C 后新 durable run/retry 原子冻结 `standard-enforced-v1` 与
`unpriced-v1`，已有 `standard-observe-v1` run 在同 run 恢复时保持原策略，价格未知不按零成本
处理；v9 新增 retrieval-only TTL cache；v10 增加唯一 evidence-insufficient 决策的持久化表。旧
snapshot 导入已移到 readiness 之后的受管后台任务，并具有候选数、I/O 时间和文件大小预算。
`POST /research` 与旧 SSE 只作为一版弃用兼容保留。

Phase 2-A 只冻结运行上下文、Trace/Budget DTO/Protocol、版本化预算策略和产品 schema
骨架（`run_budget_policies`、`node_attempts`、`external_calls`、`trace_events`、
`budget_ledger`）。旧 run 不回填，内部 policy 投影为 unavailable；后续查询 API 必须如实显示
该缺失状态。Phase 2-B 已接入默认 durable 路径的节点/外部调用 Trace，并提供
`GET /api/v1/tasks/{task_id}/observability`；查询只返回最新 run 的 allowlisted 摘要，旧 run、
无 Trace 和无 latest run 明确标记 unavailable。latest run、run epoch/status 与 Trace 在同一 SQLite
read snapshot 中读取；调用显示安全节点归属、run 内节点尝试序号和整数 retry 序号。过期 started
记录投影为 interrupted/unknown。Token 聚合保留缺失字段并标记完整性，未知值不按零处理。
Streamlit 展示 durable 节点、调用、重试、失败及已知 token；查询失败或不可用时回退已有
snapshot panels。Trace 写入仍是 best-effort，不影响 task lifecycle/SSE；`task_events` 仍是
状态与 SSE 正确性的唯一事实源。Phase 2-B 已通过完整测试和独立 Review。

Phase 2-C 已在默认 durable 路径接入 fenced、append-only 的预算预留与结算：每次实际 LLM
重试、每个 Retriever 来源和冲突证据工具调用都先通过原子预算门，并发不能超发；未知用量按
预留上界记为 `unknown_spend`。标准档为 60,000 total token、96 次 LLM、72 次检索和 900 秒
active-time，80% 时提示。60,000 token 与 900 秒分别给用户提供的历史上界（约 20,000 token、
约 6 分钟）保留约 3 倍和 2.5 倍余量；这是保守的项目经验配置，不是付费健康集的 95% 实测。
触顶后若已有至少三条非争议可用证据链、两个有效 HTTP(S) host 且含一条 moderate/strong
证据，则不再外呼并生成明显标注的受限报告；否则稳定失败。Observability API 与 Streamlit
展示 settled/unknown/reserved 用量、剩余额度和软/硬限制状态。`RunManifest` 仍为 schema v1，
但现在冻结每个 LLM call 的 `max_output_tokens`，旧 manifest 会安全拒绝同 run 恢复。

Phase 6-A 已收敛默认安全边界：所有受管 URL 外呼使用 `SafeUrlPolicy`/安全 fetch，仅允许
HTTP(S)、80/443、无 userinfo，并在 DNS、direct-IP 连接及每一跳 redirect 上重新验证公网地址、
端口和响应限制；无法证明安全的 proxy/forward 动态 URL fail closed。forward 目标采用完整
hostname 精确匹配或显式 `*.example.com` 子域匹配。HTTP body 上限为 128 KiB，query、候选、
澄清和聚合输入另有字段/数量限制。日志、错误、Trace 和 LLM diagnostics 统一脱敏，后者只保留
hash、length、usage 和 error type。报告继续提供 Markdown，并由服务端生成经过 sanitizer 的
`report_html`；PDF 复用同一 sanitizer，前端不把未清洗正文插入 `unsafe_allow_html`。
本阶段不包含认证/API key、rate limiting，也不声称所有静态 provider 已迁移到安全 fetch。

Phase 3-1 在结论合成与报告渲染之间增加确定性引用验证。等价 URL 规范化后每轮最多安全
抓取一次，额外请求先预留 `http_calls`；检查结果随 immutable run snapshot 持久化，并由报告
和 Streamlit 证据卡展示。该状态是可解释的规则判断，不是语义事实证明：临时网络、DNS、
安全路由限制或跨语言难以判断时保持 `unknown`，不会被误写成错误引用。新运行冻结
`research-v2`、state schema v2 与 `deterministic-citation-v1`；历史 v1 manifest 可审计但须新建
run，不能在新工作流上续跑旧 checkpoint。

Phase 4-1 已为默认 durable 工作流加入单一 HITL 决策闭环：新运行冻结 `research-v3`、state
schema v3 与 `evidence-insufficient-v1`。该 gate 位于引用验证之后、报告渲染之前，只在证据
结构不足且推荐方向实质不确定时暂停。`GET /api/v1/tasks/{task_id}/decision` 读取当前决策；
`POST /api/v1/tasks/{task_id}/decisions/{decision_id}` 以 `If-Match` task version 提交动作。
三个动作是 `provide_context`、`limited_report` 和 `cancel`。决定与 run、产品库接受的
checkpoint、state schema 和暂停 epoch 绑定；相同请求幂等，冲突请求不覆盖已提交决定，7 天
未决后收敛为取消。暂停后 lease、deadline 与执行槽都会释放。重启恢复只会续接兼容的已解决
decision/checkpoint。补充文本不会进入公开 decision 响应或 `task_events`；checkpoint ID 和
fencing identity 也只保留在内部。旧 `/research` 兼容路径绕过该持久决策门。Phase 4-2 的
Streamlit 决策界面与恢复端到端验收仍待实施。

后续实施已按个人项目和面试展示目标重新收敛，当前事实源见
[`docs/current-roadmap.md`](docs/current-roadmap.md)：继续完成轻量检索去重/缓存、单一 HITL
和质量评估闭环；多租户认证、分布式基础设施及其他企业级扩展不在当前实施范围。

### 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.codex-test-tmp
```

项目支持 Python 3.11/3.12。2026-09-15 在项目隔离环境中验证结果为
**986 passed，0 skipped**。不要使用混装其他项目依赖的全局 Python 环境。

### Docker 部署

```bash
docker build -t deepchoice .
docker run -p 8000:8000 --env-file .env deepchoice
```

镜像构建为纯在线安装（清华镜像源），不依赖本地 wheels 目录。BGE-M3
嵌入模型在容器首次运行时自动下载（约 2GB，下载到 `/root/.cache/huggingface`），
建议挂载 volume 持久化模型缓存：

```bash
docker run -p 8000:8000 --env-file .env \
  -v deepchoice-hf-cache:/root/.cache/huggingface \
  -v deepchoice-outputs:/app/outputs \
  deepchoice
```

后端镜像固定 Python 3.12 和单 worker。SQLite runtime 不支持多副本；检测到多 worker 配置
或另一实例仍持有产品库 lease 时会拒绝启动。数据库维护使用成对工具：

```bash
python scripts/runtime_db.py backup --product-db outputs/deepchoice.db --checkpoint-db outputs/checkpoints.db --destination backups/runtime-YYYYMMDD --maintenance-confirmed
python scripts/runtime_db.py verify --backup-dir backups/runtime-YYYYMMDD
python scripts/runtime_db.py exercise --backup-dir backups/runtime-YYYYMMDD --drill-dir restore-drill
```

两个数据库之间没有跨文件原子快照，执行 backup/restore 前必须停止服务或进入维护模式。

当前 Phase 1 部署模型是单用户、可信主机/可信网络，API 尚未提供身份认证、租户隔离或任务
所有权校验。Docker 虽监听 `0.0.0.0`，但不得直接暴露到公网；远程访问必须放在带认证与
访问控制的反向代理后。进入多用户部署前，API token/会话认证和 tenant ownership 是阻断项。

## 架构概览

```
用户输入 "FastAPI vs Flask"
        │
        ▼
   ┌──────────────┐
   │  澄清模块      │  多轮对话补齐场景/复杂度/约束（最多 3 轮）
   │  混合式+软门禁  │  用户不知道该选什么 → 按类别推荐候选技术
   └──────┬───────┘
          │ 澄清后的研究任务 + 5 个分解子问题
          ▼
   ┌──────────────────────────────────────────────────────┐
   │          LangGraph 研究管道 + 确定性验证               │
   │                                                      │
   │  [1] QueryAnalyzer      查询分解为 5 维子问题         │
   │         │                                            │
   │  [2] QueryAdapter       每个子问题 → 6 种检索词       │
   │         │                                            │
   │  [3] MultiRetriever     6 路并行搜索                  │
   │         │                                            │
   │  [4] SourceEvaluator    4 维加权评分（规则引擎）       │
   │         │                                            │
   │  [5] ConflictDetector   BGE-M3 检测矛盾 + 两阶段仲裁  │
   │         │                                            │
   │  [6] EvidenceChain      证据链组装 + 强弱标记          │
   │         │                                            │
   │  [7] ConclusionSynth    最终推荐 + 排序 + trade-off   │
   │         │                                            │
   │  [8] CitationValidator  URL/声明支持确定性检查          │
   │         │                                            │
   │  [9] ReportGenerator    3 种格式选一渲染               │
   │         │                                            │
   │ [10] SelfReviewer       6 项质量审查                  │
   │         │              confidence < high → retry ──┐  │
   │         ▼                                         │  │
   │       END  ◄──────────────────────────────────────┘  │
   └──────────────────────────────────────────────────────┘
          │
          ▼
   FastAPI SSE 流式输出 → Streamlit 前端（中/英/日/韩）
```

**两阶段仲裁细节**：
```
所有冲突对 → flash 初裁（~3s/对）
                     │
    低置信度对 → 取分数差距最小的 1 对
                     │
            重裁（300s timeout，独立并发闸）
```

## 关键技术决策

**信源评分用规则引擎而非 LLM**。Authority/Timeliness/Consistency/Verifiability 四个维度通过 URL 模式匹配、日期计算、关键词检测来评分，结果是确定性的、可复现的。用 LLM 评分会引入幻觉风险——它可能给一篇 CSDN 博客打 9 分。做量化评估的时候，确定性比灵活性更重要。

**冲突检测走嵌入相似度 + LLM 语义扫描**。BGE-M3 先算标题余弦相似度（>= 0.6 的才是潜在冲突对），再用 LLM 语义扫描识别推荐差异、权衡分歧和厂商偏见（而非仅判断"直接事实矛盾"），confirmed 对走两阶段仲裁。300 case 终测冲突检测率 28.8%——其中 keyword 预筛部分（确定性）低于 200 case 的 56.4%，主因是新增 case 的 known_contradictions 标注不足（检测靶子少），下一步优化方向是预筛召回而非仲裁质量。

## 量化指标（300 case 混合基准，2026-08-31 终测）

150 对比场景（TC）+ 150 开放场景（OS），覆盖技术选型对比与真实业务需求描述两类输入。300 case 按 TC/OS 交错重排、拆 3 批跑（每批 50 TC + 50 OS），超时/变体补跑后合并。

| 指标 | 值 | 说明 |
|------|-----|------|
| Top-1 准确率 | **92.0%**（287 可判定） | 推荐排名第一的技术匹配人工标注正确答案（13 个 TC 为 context_dependent 标注——无单一正确答案，按设计不计入 Top-1） |
| 任务成功率 | **100%**（300/300） | 零失败——str.get bug 已根除（`llm.py` 兜底）+ 超时补跑 |
| 声明溯源率 | **93.0%** | 历史精确口径（claim_citation_rate）：每条事实声明带 `[Source: title]` 且 title 真实存在于证据链；**伪造引用 0**（后置校验剔除幻觉引用）。该 2026-08-31 指标不包含后来加入的在线可达性/词法支持验证 |
| 信源召回率 | **66.7%** | official_doc 65.6% / github_repo 73.0% / package_registry 50% / academic+community ~100%（300 case，与 200 case 66.2% 持平） |
| official_doc 召回率 | **65.6%**（346/528） | 官方文档直连 222 条（91 种子 + 131 运行时自学习入库，2026-08-31 种子化） |
| 端到端延迟 P50 | **342.1s** | 中位数——约 5.7 分钟完成一次技术选型研究 |
| 端到端延迟 P95 | **445.3s** | 95 分位——480s 预算内 |
| 报告质量 A 级 | **99%**（297/300） | 5 项确定性质检（不调 LLM） |

> **数据来源**：以上数字来自 300 case 混合基准（`benchmarks/cases_eval_300.json` = 150 TC + 150 OS）。采集分 3 批（`--batch 1/2/3 --batch-size 100`），超时/变体集中补跑（`cases_retry_all.json`）后按 case_id 替换合并。评测覆盖经 3 轮审计修正（case 标注缺陷 T1/T2/T3 修正、OS acceptable 补齐托管维度、变体 query 双场景矛盾清除）。**诚实口径**：Top-1 92.0% 是修正评测覆盖后的真实值——剩余 miss 为真·两难（标注无共识，按设计保留）、模型主流偏差、以及模型真错（详见 case 审计记录）。2026-08-31 终测归档；当前代码测试基线见上方“测试”小节，不能用后续测试数量反推历史 benchmark 指标。

```bash
# 重现 300 case 混合基准（3 批 + 合并）
cd D:\deepchoice-agent
python -m benchmarks.run_baseline --cases-file benchmarks/cases_eval_300.json --batch 1 --batch-size 100 --concurrency 12
python -m benchmarks.run_baseline --cases-file benchmarks/cases_eval_300.json --batch 2 --batch-size 100 --concurrency 12
python -m benchmarks.run_baseline --cases-file benchmarks/cases_eval_300.json --batch 3 --batch-size 100 --concurrency 12
# 合并（自写脚本：runs-batch01/02/03 + 补跑 runs-full 按 case_id 替换，不用内置 merge）
```

**已知局限**：端到端延迟较高（P50 342.1s/P95 445.3s），主要来自矛盾检测、仲裁和证据收集——这是深度研究的代价，480s 预算内。300 case 终测暴露一个信号：**冲突检测率 28.8%**——新增 case 的 known_contradictions 标注不足，预筛召回是杠杆。Tavily 月配额仍是外部约束，但密钥池（多 key 轮换 + 耗尽池持久化 + 28 天自动重探）已把单 key 耗尽从故障降级为吞吐波动。

## 技术栈

LangGraph（研究/生成节点 + 确定性引用验证与单一 HITL 决策门 + checkpoint + 条件路由） · FastAPI + SSE · Streamlit（深色主题 + 4 语言 + 观测面板） · Qwen（DashScope，qwen3.8-flash） · BGE-M3 嵌入 · ChromaDB · Tavily（密钥池） · GitHub/ArXiv/StackExchange API · xhtml2pdf（PDF 导出） · Pydantic v2 · pytest

## 项目结构

```
src/deepchoice/
├── agents/          # 研究/生成节点与确定性引用验证节点
├── citations/       # 引用状态契约、规范 URL 与确定性支持度验证
├── contracts/       # API、结构化错误与不可变 RunManifest
├── retrievers/      # 6 路检索器（稳定 retrieve 契约 + 兼容 search 接口）
├── outbound/        # 出站通道路由、代理/转发、探测与审计
├── clarify/         # 前置澄清模块
├── formats/         # 3 种报告格式
├── server/          # FastAPI（29 端点：app.py 25 + clarify_routes 4，含 durable decision、Trace 摘要与 SSE）
├── state.py         # ResearchState TypedDict
└── utils/           # LLM 客户端 / BGE-M3 嵌入

benchmarks/
├── metrics.py             # 7 指标计算（GSM 框架）
├── run_baseline.py        # 分批 + checkpoint + 趋势对比
├── merge_checkpoints.py   # 中断跑批的 checkpoint 合并工具
├── report_quality.py      # 5 项确定性质检（A/B/C/D 评级）
├── cases_200.json         # 200 对比场景 case（50 标注 + 150 变体）
├── cases_eval_200.json    # 200 混合基准（100 TC + 100 OS）
├── run_all_batches.ps1    # 分批运行脚本
├── locustfile.py          # 基础并发负载测试
└── annotated_cases.json   # 50 手标注 case
```

## License

MIT
