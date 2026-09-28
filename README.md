# DeepChoice — AI 驱动的技术选型深度研究 Agent

DeepChoice 是一个基于 LangGraph 的多 Agent 研究系统，输入"FastAPI vs Flask 该选哪个"就能自动搜索 6 路数据源、给每篇信源打分、检测矛盾观点并用两阶段仲裁解决、最终输出有据可查的对比推荐报告。

## 当前产品优化状态

工程基础与若干稳定性、来源和行动安全修复已通过离线验证；真实报告的净改善和最终产品质量
仍未通过验收。并发测试已从当前及近期产品目标中移除，不设置并发门槛或预算预留；代码中的并发
采集能力保留，但不会阻塞串行产品效果优化。

2026-09-28 的 v3 三案例串行机器卡已绑定当前产品、旧 v2 停止根和 105→108/156
研究账本；独立控制复核、离线入口测试与禁网身份审计通过后，机器卡已前瞻激活。
该卡只安排 P04/P01/P08 各一例、并发 1；激活不等于前置连通性、真实报告质量通过，
也不会续跑旧根。

2026-09-27 的方向纠偏将“尽快得到稳定、有用的个人项目报告”放回首位：先验证现有修复，
再按报告证据选择最小改动；同批观察质量、完成率、耗时和token。暂停叠加未经实测的性能措辞
门控，不降低验收标准，不改变历史结果或保留集隔离。最终采用独立 GPT-only 盲评，不称人工验收。
repair-pair v6 在环境顺序修复、完整离线验收、零研究audit和新preflight通过后，串行完成
baseline-r2 的 P04、P01、P08 三例。任务3/3完成，41次LLM与18次检索全部成功，0超时、0重试、
0部分失败；耗时114.1、50.8、45.5秒，首例包含73.6秒本地embedding冷启动，说明预热后的运行时间
相对稳定。随后P08出现两条citation pre-HTTP安全拒绝，控制器按冻结门禁停止；v6为3 completed +
9 not_submitted，累计100/156，不可续跑或拼接，仍无候选配对。

当前主要问题是产品内容而非吞吐：三份报告的150条引用检查中verified=0；P04报告仅1,580字符、
自检3/6，阶段迁移和重复执行边界不足；P08在数据结构、持久化、负载及团队能力未知时仍强制选择
Redis。该P08结果属于历史baseline产品对象；当前候选已增加确定性保护：场景明确缺少关键条件且
冻结约束要求条件结论时，撤回具体Winner并保留条件分支；私有补充上下文会显式进入合成提示，
但不能替代产品事实的引用证据。合成prompt升级为v6，旧v5 run仍可读取但不能同run恢复。
P04也已完成零付费离线闭合：队列/恢复场景中的阶段性或过渡要求会确定性增加推进/中止和回退义务，
并明确区分broker消息持久化与result backend结果存储；`acks_late`可能重投，不能单独证明不丢失或
exactly-once，必须说明重复执行与幂等。受限的evidence-first计划只允许隔离验证，不再附加通用生产
原型提示；合成prompt现为v7、evidence-first为v5。引用验证也已支持只读取经过安全策略约束的
64 KiB页面前缀：前缀命中可判为词法verified，截断后未命中仍保守记为unknown。三项修复均只有
离线反例，尚未证明真实报告净改善。

`product-optimization-serial-check-v1`现已完成唯一一次正式执行并停止，不会重跑或拼接。P04、P01、
P08三例均产出可查询报告，62/62次LLM/检索调用成功，0超时、0重试、0部分失败；耗时117.3、
50.5、54.5秒，总计51,043 tokens。P04首例包含88.2秒本地Chroma冷启动，后两例运行时间接近。
内容诊断仍未通过：P08正确保留条件分支，P01/P04却都因决定性引用未通过而退化为低置信度受限
报告，P04的阶段推进、幂等验证和回退边界仍不够具体。三例引用结果合计4 verified、61 unsupported、
4 unreachable、42 unknown；P08另有一次citation安全抓取在HTTP前被拒，控制器按冻结规则在第三例
完成后停止。账本为103/156，余53未分配。

后续离线优化使用 synthesis v8：跨语言的决定性事实保留来源语言，中文保留需求、未知项与验证
说明，避免先翻译再因词法不匹配丢掉依据；不是翻译验证，也不把词法支持当成语义或场景适用性证明。
结论输入和最终引用解析共同排除 gist/pastebin，普通 GitHub 项目不受该规则排除；原始检索仍保留。
P04 类后台任务的受限计划改为任务对账、重启故障、重复执行/幂等、隔离切换四阶段，明确通过、
中止和禁止回退条件，仍不授权生产变更。新引用策略为 `deterministic-citation-v4`：只有精确固定
安全计划及精确无事实缺口模板可免于重复检查，不能用 unknown 标记隐藏技术断言。历史 v1–v3
可读但不能同 run 恢复。三模板升级为 what-why-how-v7 / evidence-first-v6 / comparison-matrix-v5。
后续串行反馈确认P04四阶段验证计划已呈现，但跨语言和证据适用性缺口仍在，不能称产品效果通过。

此前离线候选使用 synthesis v9 / `deterministic-citation-v5`，将自动恢复义务改为核对恢复机制、
前提和限制，不再要求文献证明用户已完成演练。用户明确要求的实际验收仍是关键条件；其他需求
及引用门禁不放宽。部署验收由运行时固定标为 `unverified`，操作型决策即使有选型依据也仅给
固定隔离验证计划，缺失/畸形模型计划不再单独否定选型。三模板为 what-why-how-v8 /
evidence-first-v7 / comparison-matrix-v6；历史身份可读但不能同 run 恢复。该修复不代表真实报告
已通过，后续先处理来源片段相关性及跨语言事实保留，不重用已停止的测量卡。

引用策略现升级为 `deterministic-citation-v7`，三模板为 what-why-how-v9 /
evidence-first-v8 / comparison-matrix-v7。跨语言检查尚未证明等价时，报告撤回模型写出的
需求解释和条件断言，改为明确待核查，并展示有上限的本次保存来源片段供核对；不增加引用
通过数，也不证明来源完整或适用于当前场景。2026-09-27 serial-check-v2 的 P01/P04 快照已
离线回放，两例原错误条件不再出现，但 P01 保存片段缺少足够的适用性限定；产品效果仍未通过
新串行测量，旧卡不会续跑。

v7 还对同语言的决定性断言检查原文条件和语气：不能把“某条件下可能受益”升级成无条件
“必须使用”，也不能拼接不同句子的词来取得 verified。此规则只是有界词法防线；即使保留
原文全部条件，也不自动证明这些条件已在用户场景成立。新报告效果仍需串行实测。

2026-09-28 的离线来源窗口修复仅针对身份已核对的官方本地种子：Chroma v3 在原500字后、
800字以内补齐当前来源行，合成 v10 只对再次核对的官方来源展示这段文字。冻结 P04
FastAPI Caveat 的“小任务可用 BackgroundTasks”限定语因此进入合成输入；P01 FTS5 仍是
目录/错段问题。此检查没有模型或付费研究，不能证明新报告已正确采用条件、引用通过或产品效果达标。

P01 的下一处离线修复为 Chroma v4：对场景中明确、未否定的一项需求，给本地检索增加至多一条
“候选名 + 原文需求短句”查询；在受审 SQLite FTS5 来源的现有候选池里，以真实概述正文代替同 URL
的目录或深层命令片段。冻结本地索引回放使 FTS5 概述进入合成输入，P04 关键片段仍保留。
没有新增网络或 LLM 生成调用、没有增加来源数；每次触发时最多增加一次本地 embedding/Chroma
查询。这仍不是新报告的条件采纳、引用通过或产品质量验收。

结论合成 v11 现把原始场景中明确提出的能力/运行要求逐项列入冻结判断：P01 的备份与基本全文检索
分别评估，P04 的重启后不能静默丢任务也是硬要求；“不想过早引入复杂设施”保留为可见偏好，
不会单独否决有依据的选择。漏评硬要求会撤回具体 Winner，但来源编号与词法引用仍不能证明
来源限定条件适用于实际工作负载。当前只有离线反例与结构回归，没有新模型报告、付费研究或
产品效果验收。

查询分析和适配 prompt 现为 v2：原始场景、候选、约束和冻结子问按字段送达模型，与粗场景分类、
重试/HITL当前目标分开，避免“基本全文检索”等只写在场景里的条件直接丢失。该 v2 输入修复
本身没有新增调用、检索维度或窗口；上下文送达不代表模型遵守、检索命中或报告质量通过。
旧 prompt v1 身份不可同 run 恢复。

后继serial-check-v2机器卡已接入现有串行执行器：绑定该产品对象、P04/P01/P08固定顺序和独立
账本。该卡唯一正式执行在P04/P01完成后因引用429停止，P08未提交，不可补跑；当前继续离线优化。
付费flags不能绕过身份及停止规则，后继运行须另冻新卡。使用与激活边界见
[测量工具说明](benchmarks/README.md)，工程验收及实际audit证据见[执行状态](docs/o1-execution-status.md)。

- [整体任务地图](docs/current-roadmap.md)：目标、优先级、完成标准和下一成果。
- [执行与协作规则](docs/optimization-execution.md)：纠偏依据、反馈闭环及连续执行方式。
- [实际执行状态](docs/o1-execution-status.md)：候选、用量、预留和停止证据。
- [文档索引](docs/README.md)：维护契约、诊断与历史证据的阅读边界。

## 为什么值得关注

技术选型搜索通常靠开发者自己翻博客、刷 GitHub、看文档，几个小时下来还不确定信源质量。DeepChoice 把这个过程自动化了——不只是搜，而是评分、对比、仲裁、自审，每一句推荐都能追溯到具体来源。

与 Perplexity/ChatGPT 的对比：它们给答案但不展示证据链和矛盾处理过程。DeepChoice 的输出是**可审计的**——你会看到每篇文章的信源评分、冲突观点是怎么仲裁的、结论为什么可信。

## 核心特性

- **6 路并行检索**：Tavily 网页搜索 + arXiv 论文 + GitHub 仓库 + ChromaDB 本地知识库 + StackExchange 社区 + 官方文档直连（当前 227 条：96 种子 + 131 运行时自学习入库），`asyncio.gather` 并发跑；Chroma v4 保留原始比较维度、限制查询维度/候选池、按 URL 合并并给适配查询保留结果容量，针对一项明确场景需求增加有界本地查询，并在受审官方来源中保留有用正文/有界来源行；GitHub 幂等 GET 对 `RemoteProtocolError` / `ReadError` 最多重试 2 次，重试耗尽仍以失败 envelope 暴露
- **Tavily 密钥池故障转移**：多 key 轮换，401/432 自动拉黑并持久化到耗尽池（SHA256 哈希状态文件，28 天自动重探），429 限流瞬态退避不误杀，额度耗尽自动切换到仍有额度的 key
- **4 维信源评分**：Authority（官方文档 > 个人博客）、Timeliness（90 天内 > 2 年以上）、Consistency（多源一致 > 孤立观点）、Verifiability（有代码 > 纯观点），规则引擎打分，不靠 LLM 拍脑袋
- **两阶段冲突仲裁**：先用规则与 DeepSeek Flash 仲裁矛盾对，再对低置信度的一对补充取证，并用同一 DeepSeek Flash 重新裁决
- **自审查 + 定向重试**：最后一环用 6 项清单审查报告质量，发现问题自动补搜知识缺口，区分小缺口（重走检索适配）和大缺口（重走全管道）
- **3 种报告格式**：What/Why/How 标准报告、Evidence-First 先给结论再列证据、5 维对比矩阵表。同一份数据，不同输出形式
- **约束感知结论**：显式回答请求约束与子问题；关键未知或引用未通过检查时撤回确定胜者及排名，展示条件分支、待验证步骤和回退。用户受限报告与预算触顶报告遵循相同结论规则
- **前置澄清模块**：混合式多轮对话，帮用户把"帮我选个框架"这种模糊需求澄清到"团队 5 人、中等复杂度、后端 REST API、关注性能"再开始研究
- **可观测性与预算面板**：持久化节点尝试与 LLM/检索调用，展示耗时、重试、失败、Token 与预算余量；外呼先经过原子预算门，触顶时按最低证据生成受限报告或安全终止
- **确定性引用验证**：在结论合成后检查关键声明的引用绑定、规范 URL、公开可达性、数字/否定冲突和词法支持度，只给出 `verified` / `unsupported` / `unreachable` / `unknown`，不增加第二个 LLM 裁判
- **单一持久化人工决策门**：证据结构不足且推荐方向存在实质不确定性时暂停 durable run；用户可补充信息继续、基于现有证据生成明确标记的受限报告，或取消
- **报告阅读视图**：目录导航 + 引用角标→证据链卡片联动 + 信源编号，支持 Markdown/PDF 导出
- **运行契约与可复现清单**：研究请求、启动响应和错误采用 Pydantic 契约；每次运行生成不可变 `RunManifest`，记录模型、调用参数、Prompt 哈希、工作流、检索器和报告模板版本（不包含密钥或原始端点）
- **Durable 默认路径**：Streamlit 通过 `/api/v1/tasks/*` 创建与恢复任务，SSE 支持 `Last-Event-ID` replay/resync；重启恢复后的最终报告仍可查询与导出

历史实施和验收记录见 [归档索引](docs/archive/README.md)，其中当时额度和待办不代表当前状态。

## 快速开始

正常产品启动使用下列命令。评估与单例资格工具的操作说明见 [评估入口](benchmarks/README.md)，
命令存在不代表本轮已获付费执行授权；当前候选资格见 [资格记录](docs/o1c-single-case-verification.md)。

```powershell
# 1. 克隆
git clone https://github.com/taide05/deepchoice-agent.git
cd deepchoice-agent
python -m venv .venv
# PowerShell：.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# Linux/macOS：./.venv/bin/python -m pip install -e ".[dev]"

# 2. 配置 API Key（不要提交 .env）
# 所有 LLM：DS_FLASH_API_KEY，兼容 FLASH_API_KEY / DEEPSEEK_API_KEY
# Tavily：TAVILY_API_KEYS（逗号分隔），或单个 TAVILY_API_KEY
# 可选：GITHUB_TOKEN、STACKEXCHANGE_API_KEY

# 3. 启动后端
.\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --reload

# 4. 开新终端，启动前端
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
# 浏览器打开 http://localhost:8501
```

可选网络配置包括 `LOCAL_PROXY`、`FWD_BASE`、`FWD_KEY`、`FWD_TARGETS`、
`OUTBOUND_CHANNELS`、`OUTBOUND_CHANNELS_COMMUNITY` 和 `OUTBOUND_CHANNELS_TAVILY`；Tavily
需要保留 POST body，因此该 source 的路由会拒绝 `self-forward`。Docker Compose 中
`TAVILY_KEY_STATE_PATH` 默认位于 `/app/outputs/tavily_key_state.json`，随 `outputs` volume
持久化；可通过同名宿主机环境变量覆盖。完整配置约定见
[`AGENTS.md`](AGENTS.md)。

动态 safe-fetch 的代理信任独立使用 `SAFE_FETCH_TRUSTED_LOCAL_PROXY`，默认空值（关闭），
单独设置 `LOCAL_PROXY` 不会放开动态目标。
该新增能力仅用于具有冻结 manifest/RunContext 的 durable run；legacy `/research` 和无
RunContext 的执行仍拒绝代理动态 URL。
获批准后可将它设为与所选 `LOCAL_PROXY` 同一端点：仅
`http://<loopback-literal-IP>:<explicit-port>`，IPv6 使用方括号；禁止认证、尾部 `/`、
路径、query、fragment、scope ID 和空白。代理端口范围 1～65535，动态目标仅 HTTPS:443。
不支持 self-forward、远程/SOCKS/HTTPS 代理、认证或 HTTP 引用；不自动改路由。
Docker 传递同名设置，loopback 指容器自身；不得为容器便利而扩大信任为远程代理。
端点只以哈希进入 manifest，运行配置漂移会 fail closed；当前离线实施不授权实际启用端点。

所有 LLM 调用（含结论综合、冲突再仲裁、澄清、官方来源补全和 benchmark 的在线 judge）统一使用
DeepSeek Flash。默认沿用 `deepseek-v4-flash` 与 `https://api.deepseek.com/v1`；
`DS_FLASH_MODEL` / `DS_FLASH_BASE_URL` 可覆盖，兼容 `FLASH_MODEL` / `FLASH_BASE_URL` 和
`DEEPSEEK_BASE_URL`。Docker 传递同样设置。Qwen 的 `QW_FLASH_*`、`PRO_*`、`LLM_*`
模型/端点/密钥变量不再用于 LLM 配置，不会将 Qwen 密钥作为 DeepSeek 后备凭据。

默认请求显式发送 `thinking.type=disabled`；`DEEPCHOICE_SYNTH_THINKING=1` 仅启用综合节点的
DeepSeek thinking，并在新 run manifest 中冻结。`LLM_DS_CONCURRENCY` 默认 `80`，控制冲突扫描、
仲裁与再仲裁的共享并发门，不是每分钟请求限额；`LLM_QW_CONCURRENCY` 不再生效。
旧 `call_model(model="qwen-flash")` 调用选择器及 `enable_thinking` 参数保留适配，但实际发往
DeepSeek；历史 Qwen run 可读取，不能在新模型配置下续跑同一 run，需创建新 run/任务。
本次是适配变更，报告效果需按[评估协议](docs/product-effectiveness-optimization.md)重新建立基线。

`CHROMA_PATH` 默认 `./chroma_kb/chroma_db`，同时约束 Chroma 检索与冲突工具的库路径；
`LEARNED_DOCS_PATH` 默认 `./learned_docs.json`，`LEARNED_DOCS_READONLY=1` 禁止自学习写回。
Docker 传递同名设置；覆盖容器路径时需自行提供相应挂载。O1 使用隔离知识快照，不改现有库。

O1-R 固定 conflict_scan 输出上限为 512（其他共享 LLM 调用仍 4096），请求/预算/manifest 一致；每 run 扫描和初次仲裁阶段各最多四路，并继续受全局 LLM 门约束。未增加环境变量或提高硬预算。仲裁 KB 工具复用默认 tech_kb/BGE 检索契约，不再访问旧 knowledge_base collection。实验服务单独关闭自动恢复，默认产品恢复不变；[修复与单次验证协议](docs/o1r-single-case-reliability.md)尚不构成稳定或质量验收。

2026-09-16 的 O1-R 最新候选仅测三个开发 case 各两次：6/6 正常完成、Trace token 完整，总计 143,354 token，1/78 逻辑检索失败（来源 degraded）。这是隔离/预热环境的单 case 执行观察，不是 12-case 基线、语义质量、并发或硬件稳定验收；所有真实付费批次仍暂停，详见上述协议。

O1 新观测增加模型输入缓存命中/未命中 token 已知小计、调用/运行完整性和 node-attempt CSV；Streamlit 与 observability 展示分项缺失，只有完整分项才计算命中率。它不是检索缓存，也不折扣 total-token 预算或伪造金额。旧六次 167 个 LLM 调用没有缓存分项，不能补算；输入 124,279、输出 19,075，冲突与合成占输入 87.8%，见 [拆账协议](docs/o1-cache-cost-accounting.md)。用户授权的 [开发报告助手核验](docs/o1-development-report-review.md)已发现来源错配、备份条件与性能适用性问题；非人工盲评，评分暂定，不宣布 O1/质量通过或进入 O2。

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
hostname 精确匹配或显式 `*.example.com` 子域匹配。动态抓取显式请求 identity content encoding；
无法解码、含未知编码或在打开/消费响应时发生 HTTPX stream 生命周期错误的响应，都按脱敏
`response_rejected` 关闭，不能作为可重试 transport 证据。新 run 冻结 `outbound-url-v5`：默认安全
抓取仍拒绝超过上限的正文；只有引用验证显式选择最多 64 KiB 的有界页面前缀，前缀命中可以获得
词法 `verified`，前缀未命中保持 `unknown/content_insufficient`，不能据此判为不支持。历史 v1–v4
manifest 仍可读取但不能按变化后的响应语义同 run 恢复。HTTP body 上限为 128 KiB，query、候选、
澄清和聚合输入另有字段/数量限制。日志、错误、Trace 和 LLM diagnostics 统一脱敏，后者只保留
hash、length、usage 和 error type。报告继续提供 Markdown，并由服务端生成经过 sanitizer 的
`report_html`；PDF 复用同一 sanitizer，前端不把未清洗正文插入 `unsafe_allow_html`。
本阶段不包含认证/API key、rate limiting，也不声称所有静态 provider 已迁移到安全 fetch。

Phase 3-1 在结论合成与报告渲染之间增加确定性引用验证。等价 URL 规范化后每轮最多安全
抓取一次，额外请求先预留 `http_calls`；检查结果随 immutable run snapshot 持久化，并由报告
和 Streamlit 证据卡展示。该状态是可解释的规则判断，不是语义事实证明：临时网络、DNS、
安全路由限制或跨语言难以判断时保持 `unknown`，不会被误写成错误引用。获胜项仍有支持、但任一
模型生成的行动字段未通过引用检查时，系统保留获胜项并把整份计划替换为固定的隔离验证步骤，
不把未核验操作作为可执行建议。新运行冻结 `research-v3`、state schema v3 与
`deterministic-citation-v3`。v3不再把系统生成且逐字段匹配的固定validation-only计划当作模型事实
断言，也不把无引用/无evidence绑定的纯unknown声明计为`citation_missing`；任意或伪造计划仍按原
规则校验。历史 workflow v1/v2 和 citation-policy v1/v2 manifest 可审计但须新建run，不能在当前
工作流上续跑旧 checkpoint。

Phase 4-1 已为默认 durable 工作流加入单一 HITL 决策闭环：新运行冻结 `research-v3`、state
schema v3 与 `evidence-insufficient-v1`。该 gate 位于引用验证之后、报告渲染之前，只在证据
结构不足且推荐方向实质不确定时暂停。`GET /api/v1/tasks/{task_id}/decision` 读取当前决策；
`POST /api/v1/tasks/{task_id}/decisions/{decision_id}` 以 `If-Match` task version 提交动作。
三个动作是 `provide_context`、`limited_report` 和 `cancel`。决定与 run、产品库接受的
checkpoint、state schema 和暂停 epoch 绑定；相同请求幂等，冲突请求不覆盖已提交决定，7 天
未决后收敛为取消。暂停后 lease、deadline 与执行槽都会释放。重启恢复只会续接兼容的已解决
decision/checkpoint。补充文本不会进入公开 decision 响应或 `task_events`；checkpoint ID 和
fencing identity 也只保留在内部。旧 `/research` 兼容路径绕过该持久决策门。Phase 4-2 已完成
Streamlit 待决策界面及 SSE 等待断开/按 `Last-Event-ID` 续接，并以真实双 SQLite、
StateGraph/checkpoint 验证 pending 跨重启、幂等/冲突、过期、取消和绑定 checkpoint 的单次 resume。

Phase 5-1 已完成最小版本资产清单和离线 smoke/eval。当前契约限定为默认路径使用的 7 个
核心 Prompt hash/version、`research-v3`/state v3/workflow nodes、citation/HITL policy 及三个报告
模板版本；固定 12 个 fixture replay case 覆盖 query analysis、引用验证、结论后处理和报告渲染，
每项 3 个，不调用 LLM、judge 或网络。其 artifact 会记录数据集 hash/date、各指标分母、manifest、
registry 与 source health `not_run`/`degraded`。此测试只验证确定性代码和 fixture/报告结构，不能
作为真实模型语义质量或实时信源可用性的证明，也不改变历史 300-case benchmark 指标。测试数量、
死代码、默认路径一致性和完整 CI 的工程验收留在 Phase 5-2；真实 case 指标优化与面试交付不属于
当前 Phase 5。
运行命令、baseline 检查和指标解释见[Phase 5-1 离线评估说明](docs/phase5-offline-eval.md)。

工程基础整体验收已完成，证据见 [工程验收](docs/phase5-engineering-acceptance.md)。
产品优化的当前范围见 [任务地图](docs/current-roadmap.md)，评测口径见
[评估协议入口](docs/product-effectiveness-optimization.md)。企业级扩展不在当前范围。

### 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.codex-test-tmp
```

项目支持 Python 3.11/3.12。最近代码验收为 2026-09-24、Windows/Python 3.12 的
**1941 passed**（217.02 秒）；官方深链 intake/capture/review/seed 132项聚焦、smoke-v1 12/12、
静态/依赖检查及独立复审通过。单例执行入口与边界见 [评估工具](benchmarks/README.md)。
详细证据见 [开发集诊断与修复记录](docs/product-optimization-s0-review.md)。
事务入口取消会在持锁时排空并回滚已派发的BEGIN；可观测性读快照仍使用deferred事务。
这修复取消后连接残留事务的缺陷，不承诺数据库/worker硬故障下无需恢复。
smoke-v1 是离线 fixture 验证；自动化测试不证明报告语义质量或并发效果。
不要使用混装其他项目依赖的全局 Python 环境。

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

后端与前端镜像固定 Python 3.12，后端保持单 worker。SQLite runtime 不支持多副本；检测到多 worker 配置
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

**冲突检测走嵌入相似度 + LLM 语义扫描**。BGE-M3 先算标题余弦相似度（>= 0.6 的才是潜在冲突对），再用 LLM 语义扫描识别推荐差异、权衡分歧和厂商偏见（而非仅判断"直接事实矛盾"），confirmed 对走两阶段仲裁。300 case 终测冲突检测率 28.8%——其中 keyword 预筛部分（确定性）低于 200 case 的 56.4%，当时归因为新增 case 的 known_contradictions 标注不足（检测靶子少）；这只是历史解释，当前优化方向须由新诊断确定。

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

上述 300-case 是 2026-08-31 的历史结果；当前模型、代码和评估路径已有变化，重跑旧案例不等于
重现当时数字。旧直连工具与停用批次脚本的边界见[评估入口说明](benchmarks/README.md)。
正式产品测量使用 durable API 和独立 product-baseline-v1 12-case 数据集；当前状态见
[执行记录](docs/o1-execution-status.md)，不得混入上述 300-case 分母。历史停止和修复经过见
[归档索引](docs/archive/README.md)。手动评估 workflow 仅运行 smoke-v1，不调用 LLM/检索服务。

**历史局限（2026-08-31，300-case）**：端到端延迟 P50 342.1s/P95 445.3s，原记录使用 480s
超时口径；冲突检测率为 28.8%，解释受当时 known_contradictions 标注覆盖影响。这些数据不代表
统一 Flash 后的耗时或冲突质量；当前 active-time 预算见运行契约。Tavily 配额仍是外部运行条件。

## 技术栈

O1 冻结/隔离的本地验证（2026-09-16，Python 3.12）：18 个聚焦测试及完整套件 1095 passed、0 skipped；
smoke-v1 12/12、fingerprint 匹配。以上是工程/fixture 验证，不是 12 个真实研究 case 的效果或成本。

LangGraph（研究/生成节点 + 确定性引用验证与单一 HITL 决策门 + checkpoint + 条件路由） · FastAPI + SSE · Streamlit（深色主题 + 4 语言 + 观测面板） · DeepSeek Flash（全部 LLM 调用） · BGE-M3 嵌入 · ChromaDB · Tavily（密钥池） · GitHub/ArXiv/StackExchange API · xhtml2pdf（PDF 导出） · Pydantic v2 · pytest

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
├── README.md             # 当前/历史评估入口及执行边界
├── run_baseline.py        # 显式选择的历史直连实验，非 durable 基线
├── merge_checkpoints.py   # 历史合并实现（CLI 停用）
├── report_quality.py      # 5 项确定性质检（A/B/C/D 评级）
├── cases_200.json         # 200 对比场景 case（50 标注 + 150 变体）
├── cases_eval_200.json    # 200 混合基准（100 TC + 100 OS）
├── run_all_batches.ps1    # 历史入口（已停用，不删除旧结果）
├── locustfile.py          # durable 只读 HTTP 负载，不测研究吞吐
└── annotated_cases.json   # 50 手标注 case
```

## License

MIT
