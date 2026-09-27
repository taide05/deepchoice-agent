# 当前执行状态与证据索引

最后完成研究：2026-09-27，serial-check-v1当前候选P04、P01、P08串行完成；随后严格安全门禁停止。
普通成本与阶段切换沿用用户持续授权；不再为此逐项停下确认，研究硬上限和安全门禁仍有效。
本文只维护最新状态和账本。后续目标见 [地图](current-roadmap.md)，操作方式见 [执行规则](optimization-execution.md)。

### 2026-09-27 来源语言与受限计划离线验收

针对 serial-check-v1 的 P01/P04 过度降级和 P04 行动缺口，已完成 synthesis v8 / citation v4
离线修复：决定性事实保留来源语言，中文保留需求和验证步骤；不做翻译等价推断，不调整词法
阈值。后台任务的固定受限计划具体到四阶段任务对账、故障矩阵、幂等副作用和隔离切换；仍不授权
生产变更。gist/pastebin 同时从合成引用绑定和最终来源解析排除，其他 GitHub 项目保持可用。

离线反例包含 P01/P04 已采集官方短句的来源语言/中文对照、数字和否定错误、缺少适用依据、
gist 编号与标题缩写碰撞、unknown 隐藏断言、固定计划篡改及历史身份兼容。232项聚焦/相关通过；
补充旧citation v3兼容反例后冻结生产代码与测试，全套 **2158 passed**（271.27秒，0 skipped）。
smoke-v1 12/12、pyflakes（src/tests/benchmarks/scripts）、vulture（src，100%）、pip check、
compileall及diff检查通过。smoke数据、案例结果和指标均未变，只更新实测时间、manifest、registry
与指纹。独立复审发现的标题重新绑定及unknown断言旁路均已修复，复核无阻断，新增文件独立16项通过。
本地环境为Windows/Python3.12，不声称运行过Linux/Python3.11 CI。

残余限制：原文词法命中不是语义证明，模型是否遵守新语言规则及中文报告可读性仍需真实报告检查；
通用文档不证明实际负载或部署演练通过，关键未知仍可能合理降级。被排除来源保留在原始证据投影，
目前显示unknown/source_limit，不能据此判为抓取失败或事实错误；不把这个投影原因计入运行失败。
本轮0研究、0健康探测、0模型调用，未打开保留集；账本仍103/156、53未分配，并发0。
离线验收完成后才建立后继串行测量卡；旧v1卡、停止根、引用计数和控制器保持原样。

### 2026-09-27 三案例串行诊断结果

当前候选已绑定到提交`4e7ce70`，新的`product-optimization-serial-check-v1`仅规划P04、P01、P08
各一次，固定顺序且并发为1。它将三份报告的运行时间、终态/成功率、重试/超时、调用与token、
报告完整性和行动安全、citation状态/reason、Winner/HITL以及来源/Trace/预算/telemetry放在同一
结果中检查。P01/P04若进入HITL会停在暂停处且不提交decision；P08才沿用冻结数据集的
`provide_context`，重复暂停转limited report，最多两次，第三次在POST前停止。补充内容不进入
公共事件。历史v6 baseline仅作背景，不能把本轮称为配对因果改善。

账本从100/156起；本卡分配并执行3格，当前为103/156，剩余53格未分配，并发授权/预留仍为0。协议已冻结为
`frozen`且`open-after-independent-review-and-offline-acceptance`。首次preflight通过五类来源和
Tavily POST，但collector顶层导入使LLM配置在私有环境安装前冻结，LLM在HTTP dispatch前以
`OpenAIError`停止：LLM attempts=0、research_runs_submitted=0。失败根
`outputs/product-optimization-serial-check-v1-preflight-20260927-v1/`不可复用；现已改为私有环境
安装后延迟导入，并增加独立进程回归。新协议byte SHA为
`77b2efce9df2a8ed18b40489b7f569d85159b6d1247c976306cc8550af1e55f5`。
21项新执行卡测试通过；包含这些测试及复用控制器/基线的166项相关测试通过，完整套件2133项
通过；smoke-v1 12/12，静态、依赖和编译检查通过。独立复审发现的两项HITL缺口已经修复并复核
通过。第二个preflight根与正式prepare通过；唯一正式run按P04→P01→P08执行，三例均completed，
报告、snapshot、终态和observability完整，hitl_resolutions均为0。三例wall分别117,250、50,500、
54,515ms；LLM为7/16/21次、检索均6次、总外部调用13/22/27次，全部成功；token为11,146、
18,541、21,356，总计51,043。P04 Chroma冷启动耗时88,249ms，后两例retrieval约9.7–9.9秒。

内容主评按冻结rubric暂定P04/P01/P08必答为3/6、4/6、6/6；三例未发现新增major，但该判断尚未
独立复核。P08正确输出context_dependent及条件分支；P01未给当前场景足够明确的SQLite倾向，P04只
列出阶段/幂等/回退缺口而没有形成具体阶段验证方案。三例自检为2/6、2/6、1/6，均被确定性引用
校验降为validation-only计划。citation合计4 verified、61 unsupported、4 unreachable、42 unknown；
其中每例18条citation_missing包含系统固定安全文本的误计。P08另有一个来自gist来源的citation
safe-fetch在HTTP前以`UnsafeUrlError/safety_rejected`拒绝；冻结控制器在已准入第三例完成后以
`TELEMETRY_strict_safe_fetch_failure`停止。根不可重跑或拼接，3次提交确定、无不确定账。

后续离线修复把引用策略升级为deterministic-citation-v3：精确匹配代码模板的validation-only计划
不再重复计为模型事实，无引用/无evidence绑定的纯unknown不再计为citation_missing；伪造模式和
任意计划仍严格检查。对现有三份snapshot做禁网络提取复算时，潜在citation_missing从每例18降为
3/4/3；这是新策略的离线计数证据，不追改v2原产物，也不证明P01/P04内容已改善。下一缺口是跨语言
决定性证据绑定和P04具体行动完整性，先做离线设计/反例，不自动启动新研究。
v3代码验收为196项相关、2137项全套（253.48秒）、smoke-v1 12/12，以及pyflakes、生产代码
vulture 100%、依赖、编译和diff检查；新的manifest/core-registry指纹已随离线基线更新。

### 2026-09-26 纠偏检查点

v6 正式根取得三份可查询报告和完整观测：P04、P01、P08 全部 completed，59/59 个 LLM/检索调用
成功，0 超时、0 重试、0 部分失败；耗时分别114.1、50.8、45.5秒，首例包含73.6秒 embedding
冷启动。运行链路在预热后相对稳定，但产品效果未通过：三例citation verified均为0，P04报告明显
偏短且自检3/6，P08在关键约束缺失时仍强制选择Redis。v6因P08两条pre-HTTP安全拒绝停止，不能
续跑或拼接。P08条件决策和P04行动完整性现已分别以确定性反例离线修复；150条引用检查进一步
分解为129条网络不确定、2条跨语言unknown和19条真正unsupported。引用安全抓取的最小可复现缺口
是超过64 KiB的普通页面被整页拒绝；现行`outbound-url-v5`只为引用验证开放64 KiB有界前缀，命中
可词法验证、未命中仍为unknown，其他调用继续fail closed。以上仍是离线证据，下一成果是完整工程
验收后用新串行身份验证报告净效果，不堆叠与报告价值无关的并发门控。本轮引用修复已通过157项
聚焦、2112项全套（236.43秒）、smoke-v1 12/12及静态/依赖/编译检查；未访问网络或提交研究任务。

工作树保留6个未提交代码/测试文件的性能措辞门控草稿，涉及引用验证、结论合成、manifest及其测试；
未纳入工程通过或候选身份，不删除、不暂存、不提交。其全套验证曾中断，不能引用旧结果为其背书。
纠偏前HEAD为 `5612dbb`；最近已提交生产改动 `d7e776d` 的2051项全套、smoke12/12和
独立复审记录仍只覆盖该已验证代码，不覆盖草稿。此次文档提交不重跑未变的工程基线。

现行账本为103/156。serial-check-v1已停止且3格全部计入，另53格未分配；旧根未提交格不可借用。
用户已将并发测试从当前及近期目标中移除，历史48格路线不再是现行目标或预算预留。

| 项目 | 当前事实 |
|---|---|
| 工作分支 | 隔离工作树codex/measurement-v4承载v1–v6停止证据与后续产品效果修复；主工作树codex/baseline-readiness的六文件草稿继续保全，两者不得混合 |
| 已测量候选 / 控制身份 | repair-pair基线d23c948、旧候选d7e776d；当前诊断候选4e7ce70已有P04/P01/P08各一份真实报告；只作候选诊断，不构成配对 |
| 持续授权研究账本 | 已用103 / 现行上限156；另53格未分配；serial-check-v1及v1–v6停止根均不可重跑/拼接；并发不是当前目标且无预算预留 |
| 可用主诊断材料 | 当前候选serial-check-v1和v6 baseline-r2各有P04/P01/P08三份报告、完整snapshot/Trace/telemetry；S0身份、哈希和360行逐处原子关键声明已锁定 |
| 尚未完成 | P01/P04过度降级与具体行动完整性、串行有效局部配对和最终串行产品质量；保留集GPT-only盲评未验收 |
| 当前成果 | 当前候选3/3完成、预热后50–55秒、62/62业务调用成功；P08条件决策通过定向检查，但P01/P04仍不够有用，引用计数误差已有v3离线修复。不能声称产品效果稳定 |

### 历史授权与执行证据（各段数字只适用于所述时点）

2026-09-23 用户明确批准前瞻隔离 benchmark 派生比较模板、在现有来源范围审计并重冻
可信知识种子；批准“修复包局部12格＋预先整合S3/C1共48格”，累计研究上限
**134→152**，且以新协议冻结的配对 P01 回归替代第三次独立 P01 资格。
两臂须使用同一母种子内容身份的物理独立只读副本；旧知识库、历史报告/停止根原样保留，不读取 P09–P12 以准备新候选。
路线与上限的批准本身不等于工程或内容通过；后续已分别完成新种子和局部协议/执行器离线验收，
服务真实同窗口前置随后通过，但首个局部格在外部调用前因控制 manifest 身份不一致停止。目前新增
研究准入1、累计已用93；停止格不能重试或拼接，剩余额度仍须保留既定分母，不能自动补样。
2026-09-25 用户进一步批准累计上限 **152→153**，保持局部完整12格和最终/并发48格不变。
该批准只允许另冻 v2 执行身份，不允许删除或复用 v1 claim，也不降低内容/工程验收门槛。
v2 执行按冻结 telemetry 门禁停止后，用户又明确批准所有后续付费评测与再次测量复议：累计上限
**153→154**，v3 获得独立完整12格，最终/并发48格保持不变；该批准仍不允许重跑、改写或拼接
v1/v2，也不改变供应商、安全、数据集或验收门槛。
用户随后明确将最终人工门禁改为 GPT-only；本地固定P07受限与新P01迁移两份开发锚点，
独立 GPT 已先盲评再对照既有判断：P07 高严重度且旧报告不可直接用于决策，P01 重大数据完整性风险；
分别与历史严重度一致，P07 可用性判断更严格，详见 S0 问题表。不得把它记成人类校准或新产品效果；
最终保留集盲评仍须由未暴露其定义/结果的 GPT 评审者承担。

2026-09-25 的零网络 Q2 回放确认：旧 Chroma 每维只取3个 chunk 后按 URL 去重，P08 主查询
前三项全为 Redis，Memcached 位于第4/5名而无法进入；正式 v3 P04 快照也只留下 Celery 两页和
一页跨案例 Redis，漏掉 FastAPI。当前 Chroma v2 将 query dimensions 限为8、每维候选池限为
30–100，保留原问题并在有 adapted queries 时给其预留 `ceil(max_results/2)` 个结果槽，最终仍
最多7项且精确 URL 只计一次。source-score-v6 仅在精确 seed identity `9beba61d…` 与15项受审 target registry 下做
负向场景排除；正向 provenance 仍须在可见标题/摘要词法命中受审 target，未知 target fail closed。
三个 `_seed_*` 字段仅在图内使用，durable 与 deprecated legacy 公共投影递归剥离。冻结种子回放
经现有来源评估后保留 P01 7项、P04 3项、
P08 5项相关来源，并剔除 P04 4项/P08 2项跨案例来源。该结果是检索/准入覆盖证据，不是合成质量、
引用适用性或局部效果通过；500字 snippet 和同 URL 多 chunk 的远距离条件仍开放。本轮工程验收为
144项聚焦、2013项全套（225.05秒），smoke-v1 12/12且基线一致，pyflakes、生产代码
vulture100%、pip check、compileall、diff检查通过；独立复审关闭伪造准入、token边界和 legacy
投影问题，无阻断项。

随后以同一冻结种子、P01/P04/P08 原快照中的原始及 Chroma adapted dimensions 做禁网络 top-100
回放。当前1800字 chunk 的向量相似度与产品只透传其前500字不一致：PostgreSQL 并发正文位于
首段500字之后/重叠后段，Celery 确认、重投和幂等边界位于同 URL 的其他段；但同源前两段也会
选入导航、优化建议或无关特性，不能安全直接拼接。原回放为
`outputs/product-optimization-q2-multichunk-offline-20260925.json`（SHA-256 `de40db36…`），完整 top-100
排名原件为 `outputs/product-optimization-q2-original-rank-audit-20260925.json`（SHA-256 `0c5a525b…`）。

500字重分段反事实从234增至960段；存活 collection 已验证 `quick_check=ok`、960个有序ID及矩阵
SHA-256 `056c6bf6…`，另一种分批编码的 `fd6c4744…` 仅留作浮点/批次差异审计，没有替换存量向量。
在相同100候选池与7项合并规则下，按原冻结15-target registry 做离线同案例归属投影为
5/3/5，对照当前种子为7/3/5；P01 丢失 PostgreSQL 并发与 SQLite FTS5，P04 仍未选到确认/幂等段。
这不是 production admission：960段身份未获批准，实际 source-score-v6 对未知 seed identity 会 fail closed。
反事实原件为 `outputs/product-optimization-q2-500-counterfactual-replay-20260925.json`（SHA-256
`4a5bf5a5…`）。因此 Q2-01c 继续开放，naive top-k 与全库缩短 chunk 均被本轮反例否决；不改生产、
主种子或历史结果，无网络、LLM、付费或研究 run，累计仍为95/154。

开发请求投影只含 P01/P04/P08。历史 v1 及已冻结 v2 计划继续保持原字节身份；2026-09-24 的
v3 只把两份浅层 PostgreSQL 章节索引替换为 `mvcc-intro` 与 `textsearch-intro`，其余13项不变，
仍为15个精确深链（P01 7、P04 3、P08 5）。v3 byte SHA-256 为
`32ba72d093c986fa17d47c9aaeaba8101b6bc559ce0ef750efba204a732327af`，canonical SHA-256 为
`3bb61245eb0db520c05615a6471b08efbb727d8215fff05876ac5446eb3456b4`。加载器绑定开发请求、父目录
和 v1/v2 身份，不读取报告、快照、旧比较博客或 P09–P12。

专用采集器只接受冻结 target ID，并以无网络的 direct route admission 进入既有 SafeUrlPolicy、DNS
校验和 IP pinning；不再先探测 PyPI。每个目标只有一次30秒/2MiB有界请求，禁止重定向且最终 URL
必须逐字相等。15份正文均有 exact receipt/body；tracked review 的 byte/canonical SHA-256 分别为
`8a7cfe6bd9e3a79db51e5199c688a2a4427457f218047aec4ab107925cdc740e` /
`fd24fc558597b749566869ecaca0121ff50425bdf8aac5dd21c750291798419b`，共383,939 UTF-8 bytes。
批准仅限逐来源列明的产品行为主题；不支持独立性能、可靠性、成本、通用胜者或工作负载阈值推断。
两个浅层 v2 候选及先前 Python 首页继续隔离，旧库和历史结果未改。

新 `product-optimization-knowledge-seed-v1` 从上述15份正文生成234个 paragraph-window-v2 chunk；
BGE-M3 固定 commit `5617a9f61b028005a4858fdac845db406aefb181`、强制 `local_files_only=True`，加载前后复核缓存
revision，并通过哈希一致的未打开副本原子发布。seed/manifest/admission/embedding SHA-256 依次为
`9beba61dbeabf253fda953fa9a3dd6b3a8a8ff51e46d923c1cfdeb888a2391d6`、
`c22ccad6d9fced3b36dd46ee55b5a5e0f2d6434ce3238ce3de38e2d8c7895348`、
`887af9a435b37b5842ad390a61accfe863f8dacfb5767897d3aa00e0f77fb06c`、
`ef1a033b0525fcd1bc421c87d84f033ecd03119ca9c365b8586a9bbfacaa2b94`；payload/artifact tree 为
`4e669b2eba886dfab6d06cf23ac4d8dbe0f40b41cea8669323a283a76756a3bc` /
`fa3c542d57e81d85d1f95597e0d77acfea7369a535ddc34b14b635837349a20a`。独立复审以 SQLite
immutable 模式确认 quick_check=ok、234行×1024维、持久化矩阵 SHA 相符且无 WAL/SHM。

知识种子验收为 **132 项聚焦**、**1941 项全套**测试（217.02秒）、smoke-v1 12/12、pyflakes、
vulture100%、pip check、diff 检查及独立复审通过。
保留集定义/报告未用于上述准备。同一目录两个构建器并发发布仍是非阻断单机竞态，Windows 会拒绝
而非覆盖；本次单次离线构建不受影响。

2026-09-25 的 v1 执行 claim 绑定 byte SHA `66676f58…`；首格控制停止后保持只读。代理 manifest
修复候选随后以 `a777e853…` 完成离线 audit，但未复用 v1 命名空间。用户扩额后另冻
`product-optimization-repair-pair-v2`：协议 byte/canonical SHA-256 为
`404ff295d0a66fdbaab610f96b6b85a6a0b1bcdebc6c588fd9475975b00e7117` /
`4b5c67253814cb9801da7b5cd852f643dff042dafa9e338705f38bf784ab0c73`，runner/loader SHA-256 为
`af954419da6359d37fa2eac345fb8369ec4d13d8ec5744fc39f29d7dbd3a7964` /
`ea0c21db98da29e39c1a4406424884b395bb17f51da13083c69c86676c5b7bbe`。固定顺序为 baseline-r2、
candidate-r2、candidate-r1、baseline-r1，每块仅 P01/P04/P08，共12格、串行单并发；配对 P01
回归替代第三次独立资格，任一停止不重试、不拼接。CLI 要求协议外 byte SHA，并在项目导入前校验
完整 TCB、批准路径及 import origin/shadow；两臂冻结 DeepSeek 端点、路由/代理、依赖、证书内容、
四份物理独立知识副本、authority/heartbeat/严格 telemetry 与完整终态用量。owned service 由 nonce、
`service_started` 和进程存活绑定；localhost 控制客户端禁用环境代理。全局 claim/cell ledger 在 POST
前持久化，崩溃窗口只报告已知最小/可能最大/不确定，不把可能已提交误报为0。

v1 修复候选已通过 **35 项控制器聚焦**、扩大相关 **251 项**、**1983 项全套**测试（234.05秒），
smoke-v1 12/12、pyflakes、生产代码 vulture100%、pip check、compileall、diff 检查。独立复审未发现
代码阻断，另跑42项 repair-pair、167项 controller/qualification/child、114项 proxy/manifest 测试，
并确认非 loopback probe fail closed；运行级阻断是旧全局 claim/cell ledger 正确拒绝任何再次付费执行。
此前复审保留的非阻断风险：恶意本地篡改仍需外部可信 launcher，依赖身份未覆盖全部
wheel/DLL/系统证书库字节，ignored ledger 可被有权限操作者删除且未显式 fsync 父目录，
`service_started`/alive 到 POST 仍有极小 TOCTOU，真实 child 竞态尚未集成演练。
这些是工程准入证据，不是局部效果、最终质量或12路并发通过。现行代理 manifest 修复提交
`8320a08` 的 post-commit 零网络 audit 已通过：baseline 精确 `d23c948`，端点、路由/代理、依赖、
两臂 manifest、种子及 SQLite `quick_check` 匹配，research_runs_submitted=0；其 baseline/P04
预测 `e7389bdb…` 与停止根实际 manifest 相同。该 audit 不会使已有全局 execution claim 可重用。

首次付费前置根 `outputs/product-optimization-repair-pair-preflight-20260925-v1/` 为不可变失败证据：
五条来源 route 均通过，Tavily POST 1/1 返回200，非 LLM HTTP 8次；LLM 在 HTTP dispatch 前以
`OpenAIError` 停止，LLM attempts=0、research_runs_submitted=0、金额 unavailable。根因是 audit
先导入协议依赖的项目模块、后安装私有环境，导致 LLM 配置缓存空值。现行修复改为“stdlib bootstrap
→双根验证→安装私有环境→加载协议/项目模块→qualification”，不修改产品候选或研究协议门槛。
失败根不得重跑、改名为通过或补样。第二个全新前置根
`outputs/product-optimization-repair-pair-preflight-20260925-v2/` 在前一协议 SHA 下通过：五条来源 route、
Tavily POST 及两类 DeepSeek 探测兼容，非 LLM HTTP 8、LLM 2、研究0；离线 prepare 随后完成四份
物理独立种子。它不能给现行新 SHA 或未来新执行身份授权；若测量复议放行，仍须新协议、新 ledger
命名空间和全新前置根。

首个正式根 `outputs/product-optimization-repair-pair-20260925-v1/` 在 baseline-r2/P04 创建任务后立刻
以 `FROZEN_MANIFEST_MISMATCH` 停止：实际任务为 queued，清理后 interrupted；LLM/retrieval/external
calls 均0，无 token、报告或快照。全局账本保守记录 attempted=1、known_admitted_min=1、
possibly_submitted_max=1、uncertainty=false，其余11格未提交。离线比对证明唯一差异是运行时已绑定
`safe_fetch_proxy_sha256`，而 ARM probe 在绑定可信代理前预计算 manifest；将实际字段置空后哈希精确
等于冻结预期。现行修复使 probe 与 child 同序设置 `SAFE_FETCH_TRUSTED_LOCAL_PROXY`，并有全新子进程
回归。停止根和 no-retry ledger 保持不变。用户已批准 **93＋12＋48＝153**；v2 使用新的协议 ID、
`RP2-*` 盲标签和 `...repair-pair-v2/` ledger，并前向绑定 v1 claim/cell/result 的安全路径、字节哈希
与最小不可重试语义；bootstrap 和每格准入前均重新验证。当前 v2 已通过47项聚焦、316项相关、
1988项全套（243.00秒）、smoke-v1、pyflakes、vulture100%、pip check 与 compileall；独立复审
无阻断，其两项非阻断测试建议也已覆盖。实现提交为 `5e6e88d`；提交后零研究 audit 已通过，冻结
baseline/P04 manifest 仍为 `e7389bdb…`，predecessor/TCB/种子/环境/代理身份一致。全新前置随后以
HTTP 8、LLM 2、Tavily POST 1 全部通过，五类来源健康，研究0；离线 prepare 冻结四个独立块。

v2 唯一执行在 baseline-r2/P04 完成后停止。该格使用8次 LLM、6次 retrieval、14次 Trace 口径
external call，8458 tokens，Trace logical-call failed_calls=0、终态用量完整、报告/快照均存在；但
独立的 transport telemetry 在块末先看到两次
`operation=other` 的成功 POST 200，后又看到四次 `UnsafeUrlError/response_rejected` 与一次未分类
safe-fetch 错误，因此依冻结规则停止全部新准入。结合前置已确认 community 使用 self-forward，
两次 unclassified POST 很可能是已冻结转发端点但 telemetry 未分类；因 URL 按设计不落盘，此点只是
推断。即使修正该分类，五次 safe-fetch 失败仍会独立触发当前停止规则，不能把本次重标为有效配对。
v2 claim/cell/observation/result SHA-256 分别为 `4f77600f…` / `bde2aedf…` / `c991d96d…` /
`2c8cfe8…`；结果固定为1格 completed、11格 not_submitted、无不确定提交。v2停止时研究为
**94/153**，最终/并发48完整保留；局部11格余量不能解释为 v2 可续跑。后续复议与扩额只授权
新的 v3 协议/身份/ledger，不能删除旧 claim 或拼接停止根。
复审保留的新增非阻断盲区：控制器级 fresh-subprocess 测试直接覆盖有效 IPv4 loopback，但未逐项参数化
baseline checkout、IPv6、缺失/恶意 `LOCAL_PROXY` 或冲突预置 SAFE 值；底层代理合约和独立负测已
覆盖核心拒绝行为。真实服务启动到首个 safe fetch 的端到端一致性尚未在修复后付费复验。

现行 `product-optimization-repair-pair-v3` 协议 byte/canonical SHA-256 为
`47bfeffa01893b6077a480b06dd6ff4254d6c121d110614747a3fc2f9db9c268` /
`59d3649601c8985c944452f2caff05996659469c4d2a22b31ad5ac663981cd69`。runner/child/control/loader
SHA-256 分别为 `6ce9ea1247a68e8a053469622d143170f7eec8056c97127d119c95bc87f36f1a` /
`598e429d045fc9825b56ff0d7753a9599901c756b2390ec2f443a55473dedaf0` /
`955f9fc22169f9f0a9fb4573032343d135e64485552cbb7a05be2cdc9ff96013` /
`022fb88afbc782ff15d38e4c91b6805c57500d24f26f2de6bf5057440375b959`。v3 使用 `RP3-*` 标签及
独立 ledger，bootstrap 与每格准入都验证 v1 安全前驱和 v2 的 claim/cell/observation/result 路径、
字节哈希及1格完成/11格未提交语义。只有规范化 scheme/IDNA host/port/path/query 全部等于冻结
`FWD_BASE` 的 POST 才记为 `self_forward`；匹配的 forward/POST/2xx–3xx 可继续。citation verifier
通过专属进程内 provenance 与共用同一 resolver 的 official retriever 区分；只有前者的已知
safe-fetch 策略/传输失败可在终态与来源门禁完整时降级为 unknown。`safety_rejected`、429、普通
5xx、检索/预算/租约/身份及未知失败仍停止。产品、种子、顺序、单并发、阈值、供应商、安全边界和
P09–P12 禁读均未变。工程候选通过121项聚焦、453项相关、1996项全套（223.87秒）、smoke-v1
12/12且基线一致、pyflakes、vulture100%、pip check、compileall与diff检查。研究仍为 **94/154**；
独立复审发现 official retriever 与 citation fetch provenance 混淆阻断后，专属 ContextVar/alias
绑定与成对反例已关闭该问题；定向复核无剩余 blocker。未以 fake resolver 实际调用安装后 alias 是
非阻断测试盲区，当前运行时 globals 检查确认绑定有效。实现提交 `d527ab6` 的 post-commit 零研究
audit 已通过：baseline/candidate 提交、双臂 manifests、v1/v2 前驱、TCB、种子/SQLite、依赖、环境与
代理身份均匹配，`research_runs_submitted=0`。全新前置随后以 HTTP 8、LLM 2、Tavily POST 1/1
（200）、五类来源健康和研究0通过；离线 prepare 冻结四块。

v3 唯一正式执行只完成 baseline-r2/P04：10,975 tokens、12次LLM、6次retrieval、18次Trace
external call，failed_calls=0、终态用量完整、报告/快照存在；其余11格 not_submitted，ledger 为
attempted/known_min/possible_max=1/1/1、uncertainty=false。`self_forward` 两次均准确记录为
forward/POST/200；已知 citation `route_unsupported` / `response_rejected` 按协议继续。最早严格停止
触发是 telemetry 第64行：`citation_safe_fetch_official` / `citation` 的 `OtherError`、failure=null；
第78行还有同类事件。未知错误不得事后重分类或降级，因此结果固定为 stop reason
`TELEMETRY_strict_safe_fetch_failure`。claim/cell/observation/result/execution-binding SHA-256 依次为
`97b8ff04d8b8d1d4554625914f07de04617bb9cfef9fff9d0e119941941d1f56` /
`3468896e934298d49d9db2faeb56d605af318e48fb038da7b9a870daf89ed7fb` /
`43fdd654c103b39c7dd05a8daab9fefc6fc6760d82b248861449dc3044040c15` /
`2dcb6d5fcb1d61feff0ef349095ef081ec161bac4f3b970e614abb9c963ead7f` /
`005c0fd34ac972ff313df90366e68b5331d2ad00beb7da37404b6651deccc7db`。研究累计 **95/154**，
telemetry SHA-256 为 `8945c564aed60db5f3ab1778c5d8e022f4bcd8fc8892a9d2b8faadcb459a1343`。独立复审确认 claim/binding、collector journal、runs、
observation/result 的 task/run/status 一致，停止正确；403 与200响应后都出现过 `OtherError`，无法安全
归为普通403或既知 transport，允许继续将扩大 fail-closed 边界。最终/并发48完整保留；三次付费停止
规则已触发测量复议，不能自动追加 v4、复用旧根或据单份 baseline 报告声称局部效果改善。

三次停止后的初始测量复议检查点：v1 是零外呼控制身份停止；v2/v3 都只完成同一个 baseline-r2/P04，
没有产生配对候选证据。v3 的两个 `OtherError` 分别出现在已收到403和200响应之后，冻结遥测不足以
确定真实异常类型；HTTPX 的 `StreamClosed`、`StreamConsumed`、`ResponseNotRead` 等 stream 状态
又不属于 `TransportError`，旧 observer 会统一压成 `OtherError`。现阶段不把任何 stream 状态自动
改判为可降级 transport；该检查点当时也不追加 v4。后续增强 observer 只能通过全新文件和协议身份前瞻保留
这些脱敏类型；当前冻结 observer 仍把它们归为 `OtherError`，控制器继续 fail closed。既有 P04
报告41/41 citation 为 unknown，只能用作问题诊断，不能作为质量通过或新基线。

复议后的离线代码审计另确认一个独立、可复现的产品边界：HTTPX 在已验证响应的打开或正文消费阶段
抛出的 `StreamError` 未统一进入 safe-fetch 脱敏失败类别。前瞻实现将其收敛为
`UnsafeUrlError(response_rejected)`，明确不属于可重试 transport，并把新 run 安全身份升为
`outbound-url-v4`；v1–v3 manifest 仅保持历史可读。离线注入覆盖响应打开和正文迭代。该缺口
本身成立，但冻结 v3 遥测仍不足以证明两个实际 `OtherError` 就是 stream 异常，也不授权付费
repair-pair v4 或产生产品效果证据。
最终验收为120项聚焦、337项相关、**2024 passed**（215.78秒）、smoke-v1 12/12且基准一致，
pyflakes、生产代码vulture100%、pip check、compileall和diff检查通过；独立复审关闭捕获作用域问题后
无遗留项。本轮未联网、未增加研究格，累计仍为95/154。

2026-09-26 的后续测量复议把“产品safe-fetch的response-stream收敛”和“评测控制器能否识别该类
终态unknown”分开处理。最小控制缺口是旧observer丢失异常类型与发生阶段，使v3只能记录
`OtherError`。新控制层前瞻保留`safe_fetch_phase`，并只接受citation safe-fetch在HTTP dispatch后
出现的`StreamClosed`、`StreamConsumed`或`ResponseNotRead`；其余边界仍fail closed。v1/v2/v3
校验保持原语义，v3作为新增latest predecessor按claim/cell/observation/result路径、字节哈希、
1 completed + 11 not_submitted、10,975 tokens/12 LLM/6 retrieval/18 external calls绑定。

新的`product-optimization-repair-pair-v4`绑定baseline `d23c9480b9f368f8ec75ec44ee7e25c64146d4be`
与candidate `d7e776dffced8d1ddb90d03b924b1217ea766ddb`，保留P04/P08目标、P01回归、两臂各两次、
单并发、原种子/盲评/停止/验收门槛。初始提交是`proposed`且研究准入关闭；授权字段记录
现行154、提议155、当时有效154。runner在付费preflight、prepare和run的网络/写入前统一拒绝
未批准状态。该检查点没有执行付费前置或研究run，账本为95/154。
离线验收为231项聚焦、**2072 passed**（225.67秒）、smoke-v1 12/12且基准一致，pyflakes、
生产代码vulture100%、pip check、compileall与diff检查通过。首次受限沙箱全套只有legacy路由因无法在
工作树创建`./outputs/checkpoints.db`失败；同例在专用可写目录通过，最终全套在正常可写工作树条件
全绿。该环境诊断不改变产品结论或研究账本。

提交`feb649aa3e3e514f54d2b2911c04bf26033e3e4e`后的提案态零研究audit通过：baseline严格为
`d23c9480b9f368f8ec75ec44ee7e25c64146d4be`，candidate产品对象严格为d7e776d绑定的
`d0975326b164659fc5601a1987ba5a5cf0265122`，两臂manifest、core registry、endpoint、依赖、
配置、代理、v1–v3前任证据及种子SQLite quick_check均匹配，`research_runs_submitted=0`。
提案byte SHA为`1dcc06ed63a7beed4a99823ddd8c3c412612806db1ffb7b0273ecdf0261724b3`。

审计前发现主工作区名义`product-optimization-knowledge-seed-v1`树哈希已为`20e3845a…`，不再是
批准的`fa3c542d…`；复制件逐文件与它一致，因此不是复制损坏。未修改该目录或任何历史根。
v2/v3历史实验仍保有多个物理独立的精确`fa3c542d…`副本；审计使用v3 candidate-r1副本的物理复制，
并再次验证完整树哈希。后续激活/prepare必须保留隔离工作树中的精确副本，不能从已漂移主目录重拷，
也不能把已运行的baseline-r2副本当作干净种子。

随后用户在2026-09-26明确批准累计上限154→155，并要求完整局部12格、最终/并发48格及全部
验收门槛保持不变。v4现为`frozen`、`open-after-offline-runner-acceptance`，授权`approved`、
有效上限155；当前实耗95/155。激活协议byte SHA为
`dd6814e128c9e40b7b4f70b6a2b1e6db2434f4243876e783f5a20a1a25a3a6c6`。本轮状态切换本身没有执行
付费preflight或研究run。激活离线
验收为231项聚焦、**2072 passed**（229.54秒）、smoke-v1 12/12且基准指纹一致，pyflakes、生产
代码vulture100%、pip check、compileall和diff检查通过。

激活提交`b656c24187d8e2816c438e4d9a360e646fc5191c`后的新零研究audit通过：baseline HEAD/anchor
严格为`d23c9480b9f368f8ec75ec44ee7e25c64146d4be`，candidate HEAD为`b656c241…`且产品源码对象仍为
`d0975326…`；双臂manifest、core registry、endpoint、依赖、配置、代理、v1–v3前任证据、批准种子
`fa3c542d…`与SQLite quick_check全部匹配，`research_runs_submitted=0`。当前实耗仍为95/155。
下一步是单独执行有界付费preflight；只有通过后才离线prepare并一次性执行冻结12格，不重试或拼接。

同日有界付费preflight通过：8次HTTP、2次LLM、1次Tavily POST，五类来源健康，
`research_runs_submitted=0`；随后离线prepare冻结4个独立块和12个计划格。一次性正式run只提交并完成
baseline-r2/P04：8,622 tokens、8 LLM、6 retrieval、14个可观测外部调用、0失败、0节点重试，
观测与token用量完整。完成后控制器以`TELEMETRY_strict_safe_fetch_failure`停线，其余11格均未提交。

安全遥测包含4条citation `UnsafeUrlError/response_rejected`和2条citation `OtherError`，均发生在
`response_received`阶段；TLS证书要求、主机名检查和主机匹配均成功。已知`response_rejected`本身符合
冻结白名单，真正阻断是两条无法精确归类的`OtherError`。因此不能把它们追认为解码或流生命周期异常，
也不能降级继续。v4结果为1 completed + 11 not_submitted，账本确定、无不确定提交，累计实耗96/155。
运行结果SHA256为`c9ae68174c9382332b92dec2f44831647da597d5f6d4d529368dd06a2c116ab1`，遥测SHA256为
`5b85c3f6cab8f2917a732fb65001a107b4365d26c107ce5169706211efd59e10`。该根不可重试、续跑或拼接，
仍无有效配对；下一步仅能是新的安全/测量复议，而不是直接追加运行。

同日后续复议以原 baseline 安全外呼和冻结本地代理，对 v4 涉及的6个唯一 citation URL 做了一次
零模型、零研究诊断；输出只保留 URL hash 和异常类别。结果精确为4条
`UnsafeUrlError/response_rejected`与2条`httpx.DecodingError`，全部在response_received阶段；
TLS、证书要求、主机名检查与匹配均成功。它把未知类型闭合为响应解码失败，但不追溯重标v4。

用户随后明确批准累计上限**155→156**。新的`product-optimization-repair-pair-v5`使用薄适配器，
只在评测observer中将HTTP dispatch后的`DecodingError`和既有`StreamError`收敛为脱敏
`response_rejected`；dispatch前、普通RequestError及全部原停止线不变。v5绑定v4 claim、cell、
observation、result与telemetry精确哈希/语义，采用RP5盲标签和独立ledger，产品、种子、12格顺序、
验收门槛、单run预算及48格预留均未变化。离线验收通过152项相关、2081项全套（219.34秒）、
smoke-v1 12/12且基准一致、pyflakes、生产代码vulture100%、pip check、compileall与diff检查。
冻结协议byte SHA为`13e8bd9ef2e6877c4c8465db22c3ab0bc1b11f3f386e704b7b314a45ef0fd796`。
提交`0c4edec0c64dc087218d6b786a13f8087f5e7477`后的零研究audit已通过：baseline/candidate、产品源码
对象、v1–v4前序证据、TCB、依赖、环境/代理及批准种子`fa3c542d…`/SQLite quick_check全部匹配，
`research_runs_submitted=0`。随后v5付费preflight通过（8 HTTP、2 LLM、1 Tavily POST、五类来源健康、
零研究提交），prepare冻结4块。正式根只提交并完成baseline-r2/P04：9,372 tokens、10 LLM、
6 retrieval、16个成功外部调用、0失败、0节点重试，用量与同根observation/collection record完整。
7条citation失败全部为允许的post-response `UnsafeUrlError/response_rejected`，最终telemetry
`anomaly=false`。下一格前，Chroma已在使用中改写当前块3个同长度持久化文件；全块seed哈希复核
因此报`prepared block drift`。父catch又把已落盘record从最终result丢失为`records=[]`/started=0，
但ledger确定attempted=known=possible=1且无提交不确定性。result/claim/cell/observation/runs/telemetry
SHA-256依次为`94b2e72b…`/`ddf54d10…`/`1dbe01ad…`/`e8918c80…`/`66012a77…`/`e86bbfca…`。
v5不可重试、续跑或拼接；累计97/156，仍无有效配对。最小后继只需约束已用块Chroma漂移并保全
完成record，产品、seed起点、顺序、来源、安全和内容门槛均不变。

v6最小控制修复现已实现：只允许已尝试块的3个已观察Chroma文件在清单和大小不变时发生内容漂移；
未尝试块及其他文件仍完整复核。父结果遗漏的完成record只能由同根append-only observation与
collection record唯一匹配恢复，并继续经过原停止门禁。离线验收通过13项v6聚焦、393项相关、
2094项全套（127.63秒）、smoke-v1 12/12基准一致、pyflakes、生产代码vulture100%、pip check和
compileall。用户随后明确先稳定产品效果、再验证并发；协议当时重冻为单并发串行12格、并发授权为0，
仍使用156硬上限，若完整执行预计余47。冻结协议byte SHA为
`65e8216e…`；提交`2ca5dfd`后的零研究audit通过。随后首次preflight的8次HTTP和Tavily POST正常，
但v6 bootstrap在私有环境安装前导入LLM配置，SDK在dispatch前以`OpenAIError`停止：LLM尝试0、
研究提交0。该preflight根不可复用。v6入口现先安装私有环境再加载协议/项目模块；修复通过14项聚焦、
394项相关、2095项全套（117.86秒）、smoke-v1与静态/依赖/编译检查。新协议byte SHA为
`393dd11655b92d8e35683bdcbfdac1fe683f5df63ecc99a59dfdd0a7a0ceb64c`。提交
`e05bb6b35ad2b10b8d999cde77c5f8c9de282bdd`后的零研究audit已通过：双臂产品对象、v1–v5前序、
TCB、依赖、环境/代理与种子/SQLite身份匹配，`research_runs_submitted=0`；该时点新preflight尚未执行。

新preflight随后通过：8次HTTP、2次LLM、1次Tavily POST、五类来源健康，研究提交0；prepare冻结
4个独立块和12个计划格。正式根
`outputs/product-optimization-repair-pair-v6-20260926-v1/`串行完成baseline-r2的P04、P01、P08，
其余9格未提交。三例wall为114,140/50,812/45,531ms；首例的Chroma 82.9秒中包含73.6秒成功的
本地embedding冷启动。总计41次LLM、18次检索，59个Trace外部调用全部成功，token分别为
8,029/15,101/12,641，0调用失败、0 LLM重试、0节点重试、0 collector timeout，观测和token完整。
三例六路检索均success，community均为0结果但未伪装失败；报告均落盘。

产品效果审计不通过：P01/P04/P08引用检查分别为0 verified + 7/10/2 unsupported +
33/41/57 unknown，总计verified=0；自检分别5/6、3/6、4/6。P04报告仅1,580字符，缺少充分的
分阶段迁移与重复执行边界；P08在数据结构、持久化、负载和团队能力未知时仍给出Redis Winner，
违反该case的条件性决策核心。控制器在P08观察到一条`UnsafeUrlError/safety_rejected`和一条
`UnsafeUrlError/route_unsupported`，均为citation `before_http`，因此按冻结安全门禁停止。
result/runs/telemetry SHA-256依次为`446dc3e7…`/`f975528e…`/`924d13a6…`；账本
attempted=known=possible=3且无提交不确定性。v6为3 completed + 9 not_submitted，累计100/156，
不可续跑、重试或拼接，也不能形成候选配对。

用户随后明确把并发测试从当前及近期目标中移除：代码中的并发采集能力保留，但不再冻结并发协议、
设置并发门槛或预留研究格。余下56格均未分配。当前只做产品效果稳定化：先离线修复P08条件门控、
P04报告/行动边界和全例citation verified=0，再决定是否建立新的串行测量身份；没有开放的付费运行。

P08的首个离线修复已闭合。v6的强制Redis来自历史baseline对象，不代表当前候选此前完全没有
约束感知逻辑；最小剩余缺口是scene context中的明确缺项没有进入确定性门控。当前实现只在“场景
明确缺少关键输入”与“冻结约束明确要求条件结论”同时成立时撤回Winner/排名，保留条件分支、记录
未知并把行动计划限制为隔离验证；普通未知措辞不触发。HITL私有补充上下文现在显式进入合成提示，
只定义用户条件，不作为产品事实证据。synthesis prompt升级为v6，历史v5身份可读但不能同run恢复。
该结果通过112项聚焦、2102项全套（117.21秒）、smoke-v1 12/12及静态/依赖/编译检查；smoke
case输出与指标未变，只更新有意变化的asset/manifest身份和artifact fingerprint。它仍只有离线
反例和兼容性回归证据，未追加付费运行、未形成配对，也未改变100/156账本。下一项转向P04完整性
与行动边界，之后处理citation verified=0。

P04的离线修复随后闭合。历史baseline报告的核心问题不是字符数本身，而是把result backend当成
任务持久化、把`acks_late`写成不丢任务保障，并在缺少幂等、重复执行、broker持久化、推进/中止和
回退证据时直接给出Redis+单worker生产方案。当前候选在队列/恢复语义存在时，才把“阶段性/过渡”
确定性扩展为推进/中止与回退义务，避免普通feature-flag rollout误触发；prompt明确result backend
只存结果状态、late acknowledgement可能重投，不能单独证明不丢失或exactly-once。缺少新增义务的
精确P04反例会撤回Winner、把A4/A5标为unknown并将生产切换替换为隔离验证。evidence-first v5在
action_plan_mode=validation_only时只显示禁止生产变更提示，不再附加“用推荐方案做快速原型”。
synthesis prompt为v7，旧prompt/template身份可读但不能同run恢复。验收为153项聚焦、2108项全套
（119.88秒）、smoke-v1 12/12及静态/依赖/编译检查；case输出和指标未变，只更新资产指纹。该结果
仍未追加付费运行或证明真实报告净改善，100/156账本不变；下一项仅处理citation verified=0。

实际安全采集首次验证时，React、Vue、Python 三个不同官网的 GET 均安全停止且没有落盘；对
React 的异常分类和 Python 的响应头诊断将共同根因定位到 gzip 解码不一致。定位后，safe-fetch
每跳改为显式请求 identity encoding，并把仍发生的
解码失败收敛为脱敏 `response_rejected`；聚焦安全/代理/采集回归通过。只对先前失败的 Python
官网做了一次有界复验，生成一份 `candidate_unapproved` 候选，原文/正文哈希与收据一致。
独立复审补出的合法 gzip 二次解码反例也已关闭：解码后清理旧表示头，大小上限继续作用于解码正文。
未知编码在清头和读取正文前 fail closed；新 run 冻结 `outbound-url-v3`，历史 v1/v2 manifest
保持可读但不能按变化后的传输语义同 run 恢复，旧上下文也会在路由前拒绝。
最终 **146 项聚焦**、**1906 项全套**、smoke-v1 12/12、静态/依赖检查均通过。这证明采集传输
闭环可用，不代表来源已批准、正文适用、新库完成或研究准入，账本仍为 **92/152**。

以下至文末为按发生日期保留的历史执行记录；其中“当前”仅指该记录当时，不覆盖上面的现行授权。

执行适配核对发现：原 PR2B 控制器写死旧产品与 12 例整批，S1 协议校验本身不提供可用的
新候选执行器。当时新增独立绑定的 P01 单例资格入口，复用原安全监控但禁止资格自动取消/
决策/恢复；该入口仅服务旧 v2 历史资格，不再用于新路线。现行十二格双产品配对执行与锁分门禁
仍需适配，不能直接用旧串并发 comparator。
原协议哈希与产品身份未改变。2026-09-22 无网络本地审计确认依赖、路由配置、代理身份、
模型端点和 embedding revision 与冻结环境一致，启动内存线满足；这不是连通性证明。
资格适配离线验收：98 项聚焦、全套 1664 passed（190.92 秒）、smoke-v1 12/12、静态/依赖
检查及独立只读复审通过。运行器残余风险：旧 launcher 身份读取失败后的 terminate/wait
没有二次 kill fallback；复审定为非阻断，若实际启动异常，须核对进程归属并对账，不能重跑根。

## S1 修复候选 P01：2026-09-22

新根 outputs/s1-qualification-20260922-uncertain-analysis-v1/，产品 83852d8、实际 checkout
60485b6，使用冻结协议 v2 及原知识种子。前置五类来源、Tavily POST、DeepSeek JSON/tool
通过：非 LLM HTTP 8/20（含 Tavily POST 1/1）、LLM HTTP 2/4；研究前置准入 0，金额未知。
P01 于 18:47–18:49（UTC+08）唯一准入并 completed，run
9e195c91-ee28-446e-bf8a-8f592ac0da17，manifest
0eb4a0829510563b20de9396f425cc3e5387a692e07dd5738d2e96b296b6c648。
普通报告 1、HITL/取消 0，wall 134,094 ms；控制器未触发停止，cleanup/stop-final 完整，
服务 graceful exit 0，无未收尾任务。原始根只读，不补跑；累计由 91 增至 92。

内容评分、major 和 36 原子分母见[资格记录](o1c-single-case-verification.md)，正式门禁保持
关闭。工程验收与执行完成均不能代替内容通过。原 v1、新 v2 各自保存，不合并为一个分母。
内容锁分后核对：14,493 tokens（输入 11,138 / 输出 3,355），11 LLM、6 retrieval，usage
完整，LLM/node retry 0；active 133,006 ms。标准资源 settled、reserved 0；另有 HTTP
**2 settled + 5 unknown_spend**，不能按采集器 HTTP=0 解释为未调用。7 次安全 fetch 中
2 成功、5 失败；Trace failed_calls=0 不代表底层 HTTP 全成功。61 个健康样本，最低可用内存
1,137,139,712 bytes、heartbeat failure/lease loss 0；产品/检查点库 quick_check 均 ok。
节点成本仅为本例归因：合成 7,639 tokens、冲突检测 2,878、自审 2,709、查询适配 1,030、
检索内 LLM 237；不是配对效率收益。价格不可用，不声称金额节省。

后续行动安全修复在2026-09-23通过136聚焦、全套1720测试（223.05秒）、smoke-v1 12/12、
静态/依赖/链接检查和独立复审；没有新增前置/研究外呼，账本仍92。新prompt/template身份
不能复用v2资格；先复核剩余证据缺口与测量设计，不把离线修复当作旧P01通过。

2026-09-25 进一步关闭确定性行动安全缺口：在获胜项和决定性判断仍通过时，任一非空但不完整、
缺检查或检查为 unsupported/unknown/unreachable 的模型行动字段都会使整份计划替换为固定的只读/
隔离验证步骤；完全缺失的必要操作计划、overflow 及其他整体撤回条件仍沿用原 fail-closed 路径。
新运行冻结 deterministic-citation-v2；历史 v1 manifest/结果可读但不能同 run 恢复。验证通过
87项阻断聚焦、250项相关和全套2051测试（223.66秒），smoke-v1 12/12基线一致，静态、死代码、
依赖、编译及diff检查通过；独立复审先发现不完整计划信号丢失，修复后复跑147项并确认无剩余问题。
这是工程与离线产品边界证据，不是实际报告质量改善；未新增前置/研究外呼，账本仍95/154。

随后完成零外呼开发证据审计及 source-score-v4 占位准入修复：158聚焦、完整1730 passed
（189.74秒）、smoke-v1 12/12且基准一致、静态/依赖/链接及独立复审通过。
仅使用已有开发快照只读重放，研究仍92/134，未调用前置/模型/新研究；未启动第三次资格。
范围与残余问题只维护在 S0 问题表；下一工作见地图，不从余额或离线通过推导付费准入。

2026-09-23 有界正文窗口原型完成离线比较，但未达到生产推广门槛；相关负面证据与独立复审
结论见 S0 问题表。最终仅保留 benchmarks 中的非生产定位器，输出始终不可绑定；没有生产、
manifest、数据集或 smoke 基准变更。139项相关回归及完整 **1753 passed**（219.66秒）通过，
smoke-v1 12/12且基准一致，pyflakes、vulture（100%）、pip check和本地链接检查通过。
独立复审确认隔离后无阻断；允许传入其他 limit 仅是离线函数能力，本次重放为600字符。
仍为92/134，无新增研究/模型/前置探测；局部真实改善、最终质量、人类校准及12路并发均未验收。

2026-09-23 source-score-v5 与验证中发现的事务入口取消缺陷完成验收：最终183项候选聚焦
（12.23秒），另117项运行/预算/Trace/迁移/真实恢复回归（75.45秒），冻结后全套
**1785 passed**（210.61秒）、0 skipped；smoke-v1 12/12且基准一致，pyflakes、vulture100%、
pip check及64本地链接通过。独立代码/契约/文档复审无阻断；只读分类重放与保守覆盖限制见S0。
首次全套曾1 failed/1774 passed：stop后run仍running；隔离11次通过未被视作豁免。
真实SQLite预算/Trace入口反例均稳定残留事务，修复后通过，并增加coordinator唯一终态事件、
实例租约、只读快照、排队BEGIN及二次取消覆盖。原失败精确调度点未被记录，数据库/worker
硬故障仍是既有恢复边界。未修改历史run或冻结知识，无外呼/新研究，账本仍92/134。
本次是工程验收，不是局部实效、最终质量、人类校准或12路并发通过；测量复议与新发现的
benchmark派生知识来源风险分别见评估边界/S0，不能自动第三次资格。

2026-09-25 三次付费停止后的测量复议完成：115项聚焦回归和冻结后全套
**2014 passed**（230.12秒）通过；smoke-v1 12/12 且基准一致，pyflakes、vulture（100%）、
pip check、compileall 及 diff check 通过。独立复审确认冻结 TCB 和历史结果未改；
文档一致性修正后无阻断。本轮未联网、未新增付费格，研究累计仍为95/154。

## S1 前置停止与离线修复

2026-09-22 00:52（UTC+08）在实际 checkout 5436dd1、产品 bcb4c87 上执行协议的一轮前置，
本地根 outputs/s1-qualification-20260922-constraint-aware-v1/。五类路由 5/5，Tavily POST
200；JSON 探测在创建客户端时返回 OpenAIError，HTTP status/usage 均 unavailable。台账
非 LLM HTTP 8/20、Tavily POST 1/1、LLM HTTP 0/4，研究 0；金额未知，不记为零费用。
没有创建实验服务、产品/检查点数据库或 task/run，研究账本仍 90/134。

只读复现确认是新增入口缺陷：在读取指定 .env 前导入 protocol → baseline → contracts
→ manifest → llm，TIERS 提前缓存空凭据；配置本身存在凭据。修复只在资格工具中延迟
protocol 导入至加载私有环境后，并在任何外呼前拒绝凭据缺失或缓存/有效配置不一致。
不改写 .env、不改产品 LLM 行为或候选身份；回归加入干净子进程中的真实导入顺序验证。
修复验收：103 项聚焦、全套 1669 passed（192.70 秒）、smoke-v1 12/12、静态/依赖检查及
独立复审通过；仅验证本地初始化与控制契约，不证明 DeepSeek 实际连通或 JSON/tool 兼容。
失败前置摘要/请求台账保持原样，没有使用失败证据放行。后续用户明确授权新的有界前置，
使用下述 fresh v2 根；原 v1 仍失败，不能把控制器修复当成原前置通过。

## S1 P01 执行成功、内容资格未通过：2026-09-22

新根 outputs/s1-qualification-20260922-constraint-aware-v2/，实际 checkout 74e91c8、产品
bcb4c87，沿用原协议及冻结知识种子。前置五类路由、Tavily POST、DeepSeek JSON/tool 均通过：
非 LLM HTTP 10/20（含 Tavily POST 1/1）、LLM HTTP 2/4。与先前失败前置分开记账，金额未知。

单次 P01 于 01:12–01:15（UTC+08）执行，run 93ad5041-f240-4bc5-8a94-4da52e6f2c13，
manifest d1f0ce9ddc3ab0bb6468393b6d0e62d9716f6bce74f8bb783fbd1ea9e46caf2b。
completed / 普通报告 1、无 HITL、取消或重试；wall 150,891 ms、active 148,331 ms，
21 LLM、6 retrieval、17,716 tokens（输入 13,879 / 输出 3,837），usage 完整。
标准四资源无 unknown_spend、最终 reserved 为 0；另有 **6 HTTP unknown_spend**，不能把
HTTP settled=0 或 Trace failed_calls=0 解释成未外呼/无失败。安全抓取失败为 4 response_rejected、
1 route_unsupported、1 timeout；HTTP 200 仅代表响应头成功，不证明响应体通过安全检查。
运行器执行成功、cleanup/stop-final 1/1、服务自然退出 0，未触发未知异常或新准入停止。

内容先独立锁分，之后才检查节点归因；运行器自动汇总曾显示总用量，因此不是全盲研究。
P01 内容资格未通过，分数/原子分母与限制仅维护在[资格记录](o1c-single-case-verification.md)。
本轮将研究累计从 90 增至 91；12 格配对仍为 0。原始根保持只读，不重写报告或回填评分。
当前修复会改变产品身份，旧机器协议仍只绑定 bcb4c87；新候选须完成离线验收、前瞻身份绑定
和资格门禁，不能复用这次执行通过标志进入正式配对，也不把现有剩余额度当成自动补跑。

解释保留修复的离线验收：157 项聚焦、8 项 smoke 入口测试、全套 **1695 passed**
（187.65 秒），smoke-v1 12/12、pyflakes/vulture/pip check、差异/文档链接检查及独立只读
复审通过。首次全套仅有两项旧 smoke 指纹检查失败；审阅确认案例/输出/hash/指标不变后，
只更新四项资产身份/时间/指纹记录，并在最终工作树重跑全套通过。没有调整质量阈值或
引用安全策略；本地验证不等同真实 P01 资格通过，后续不能重写本次失败报告。

## S0 离线诊断

2026-09-21 对主诊断根 serial-r1 的 P01–P08 完成锁分。必答 **32/48（66.7%）**，冻结冲突点
**16/16**；P04/P06/P08 有已确认 major，当前候选未达到产品质量目标。360 个逐处原子关键声明
的助手语义核验支持分布为 supported 71、partial 179、unsupported 35、unknown 22、uncited 53，
完整支持率 micro 19.7%、macro 19.4%；来源质量为 eligible 0、ineligible 304、unknown 56，
micro/macro 均为 0。确定性引用投影 0 verified / 94 unsupported /
342 unknown，与助手语义判断分开。

八例共 95,718 tokens、113 LLM、48 retrieval，usage 完整、0 failed calls、0 LLM retries。
冲突扫描占 66 次 LLM 与 34,620 tokens，但八份快照 conflicts 均为空；这是后续效率/效用问题，
不据此捏造事实冲突。P07 是唯一 completed_with_warnings/一次 limited-report resolution；
P08 为 completed、`hitl_resolutions=0`，不存在已提交 supplemental input 后恢复丢失的证据。

首个假设是强制 Winner/排名且关键约束与证据不足未形成决策强度门控。S1 计划目标 P04/P08、
回归 P01，并用 P07 做受限报告离线回归。完整证据见
[S0 诊断](product-optimization-s0-review.md)、[绑定](product-optimization-s0-bindings.json)和
[声明台账](product-optimization-s0-claims.csv)。独立复审不具保留集盲评资格，人类校准未运行；
没有读取 P09–P12 报告或快照。

## 前一轮 PR2B 停止与收尾（2026-09-21）

2026-09-21 最新执行：用户批准总上限 110 → 134 后，从累计 86 个 run 启动 fresh 根
`outputs/o1-pr2b-pair-20260921-7d16d28-cap134/`。产品候选 `d23c948`、控制器 `7d16d28`，
五类路由、Tavily POST、DeepSeek JSON/tool 前置通过。serial-r1 准入 4/12 后停止：
2 completed、1 completed_with_warnings、1 cancelled，3 份报告，cleanup/stop-final 4/4 完整，
服务 graceful exit 0、无控制服务残留；其他三个 profile 的 control/runtime 均仍为空。

停止原因是 2026-09-21 12:00:02.278050 UTC 的 `safe_fetch_official / official / GET / 521`；
12:00:04.542391 UTC 锁定 `PR2_EXTERNAL_HTTP_STOP`。离线重放 521 前缀前为通过，包含该响应
后为 `safe_fetch_official_failed`，排除上次 typed timeout 误判。85 个 health 样本均 200，
authority 有效，heartbeat failure/lease loss 为 0；最低可用内存 1,286,881,280 bytes，
峰值服务 RSS 2,263,379,968 bytes，makespan 189,332 ms。

4 个 run 的 ledger 为 49,610 settled tokens + 9,402 unknown_spend = 59,012 保守计入 tokens；
62 LLM、24 retrieval，全部 reserved 为 0；Trace 86 external calls、0 failed_calls、1 node retry。
取消 run 的 token/cache usage 不完整，Trace failed_calls 为 0 不能否定 HTTP 遥测中的 521。
累计 **90/134**、剩余 44；本根只读，不补跑或拼接。第一轮门禁、第二轮及 O1-PR3 unavailable；
若只考虑从当前点另起完整 48-run，算术最低总上限为 138；这不是当前推荐路线或执行授权。

独立只读复核确认上述停止与收尾，无阻断。521 后没有新准入，只有一次清理取消；全文件没有
external_http_failure/CancelledError。collector 的清理前 runs/experiment 仍把取消任务记为
running，最终态以 lifecycle-metrics/stop-final 为准；521 的外部成因仍未确定。

本根 serial-r1 的 profile-control / telemetry / stop-final / resource-health SHA256：
`05061c3e6bb3128a8f939d14216359f5427a672794fa4261e2f6ba204c46fc76`、
`8ae075f6f1a9d4a493c8b8f13403e01d229657562f99952e7fa9a4962a2c60a4`、
`4361a6a346a1e46ed5adbb9d3968163804a621532a3c89f36f98f8564ae8e4e3`、
`73ac962f2d8375f1ebbfc31e6b5b6a74fcfd143706fa94d3d07a11619a95f1c9`。

## 2026-09-22 当时授权与证据边界（已被 2026-09-23 新授权取代）

本节保留旧协议、当时134/152上限及12+48路线的审计记录；现行上限、阶段顺序和准入状态仅以上文状态表为准。

先前外传授权继续覆盖冻结查询/候选/必要上下文、DeepSeek/Tavily/GitHub API/StackExchange API/
arXiv/PyPI/官方来源、已配置 local-proxy/self-forward 路由及公共 HTTP(S) 引用安全抓取。
134 硬上限未提高；S1 协议已冻结为 product-optimization-s1-constraint-aware-v1（SHA-256
1e771a7beb8c551df2c4eafc49d5c2a3f0d16845ca678f54f391018b0686d391），
最多 1 次候选资格 + 12 次局部配对；候选资格已用 1 次，内容不通过，正式矩阵未启动。
当前用户授权持续推进必要修复及有界执行，无需因普通成本重问；不改变冻结历史、停止规则、
134 上限或最终验收的 24-run 预留。新产品身份与执行绑定仍须前瞻冻结；最终串并发方案未冻结。
解释修复产品已提交为 83852d8；新版 product-optimization-s1-constraint-aware-v2 前瞻绑定该身份，
哈希 21f561408e7bbaabd057785df685cf36a0271709d92cacc522ff5ac289625f65。从 91 起最多新增
1 次资格 + 12 格正式比较，到 104/134，保留 S3 的 24 次后余 6。现资格已用 1 次且内容不通过，
正式比较仍为 0；累计实耗92，不因原计划尚有12格而放行新采样。
新版资格脚本严格绑定 v2；离线校验器仍可复算原 v1，但禁止混合旧 ledger 与新产品身份。
v2 工具验证：109 项聚焦、全套 1701 passed（229.12 秒）、smoke-v1 12/12、静态/依赖与
文档链接检查通过，新候选/基线/历史 v1 的真实 Git 对象复算通过，独立只读复审无阻断。
新前置和 P01 已执行，内容结果见上文；离线通过不替代内容资格。
阶段切换不单独创造审批；只有实质边界变化按执行规则集中处理。S1 已改变产品身份，原资格不覆盖新实现。

- [当前 P01 资格与冻结](o1c-single-case-verification.md)。
- [完整执行历史与先前各独立分母](archive/product-optimization-20260921/execution-history.md)。
- [冻结 v4](archive/product-optimization-20260921/evaluation-protocol-v4.md)。
- 主诊断根：`outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/`。
- 最新停止根：`outputs/o1-pr2b-pair-20260921-7d16d28-cap134/`。

原始输出/数据库未修改或移动。不得按归档中的“当前”“下一步”执行，也不得以本页简表代替原始 run 身份。
