# 当前执行状态与证据索引

最后完成研究：2026-09-22，修复候选 83852d8 的 P01；2026-09-25 的 v1 首格准入后在零外部调用时控制停止。
普通成本与阶段切换沿用用户持续授权；不再为此逐项停下确认，研究硬上限和安全门禁仍有效。
本文只维护最新状态和账本。后续目标见 [地图](current-roadmap.md)，操作方式见 [执行规则](optimization-execution.md)。

| 项目 | 当前事实 |
|---|---|
| 工作分支 | codex/baseline-readiness；当前实现与已测量产品候选不能混为一谈 |
| 已测量候选 / 控制身份 | 原基线 d23c948 / 7d16d28；最新产品 83852d8 在实际 checkout 60485b6 执行 P01，内容门禁未放行 |
| 持续授权研究账本 | 已用 93 / 现行上限 153，尚可准入 60；新局部 v2 预留12，整合S3/C1预留48；旧 v1 首格已计入93且不可重试；不是项目全部历史分母 |
| 可用主诊断材料 | 同候选 github-retry 根 serial-r1 的 8 development 报告；S0 身份、哈希和 360 行逐处原子关键声明已锁定 |
| 尚未完成 | v2 本地提交、提交后审计、全新前置与完整局部12格、最终质量与两轮并发48格；保留集 GPT-only 盲评未验收 |
| 当前成果 | 行动安全、已知占位、source-score-v5身份分类及事务入口取消修复已离线验收；窗口原型未推广；固定开发锚点独立 GPT 复核已完成；P01/P04/P08 官方正文、隔离种子及双臂执行器已验收；v1 首格控制停止已修复并保留，v2 离线工程验证与独立复审已通过，产品仍未实测 |

2026-09-23 用户明确批准前瞻隔离 benchmark 派生比较模板、在现有来源范围审计并重冻
可信知识种子；批准“修复包局部12格＋预先整合S3/C1共48格”，累计研究上限
**134→152**，且以新协议冻结的配对 P01 回归替代第三次独立 P01 资格。
两臂须使用同一母种子内容身份的物理独立只读副本；旧知识库、历史报告/停止根原样保留，不读取 P09–P12 以准备新候选。
路线与上限的批准本身不等于工程或内容通过；后续已分别完成新种子和局部协议/执行器离线验收，
服务真实同窗口前置随后通过，但首个局部格在外部调用前因控制 manifest 身份不一致停止。目前新增
研究准入1、累计已用93；停止格不能重试或拼接，剩余额度仍须保留既定分母，不能自动补样。
2026-09-25 用户进一步批准累计上限 **152→153**，保持局部完整12格和最终/并发48格不变。
该批准只允许另冻 v2 执行身份，不允许删除或复用 v1 claim，也不降低内容/工程验收门槛。
用户随后明确将最终人工门禁改为 GPT-only；本地固定P07受限与新P01迁移两份开发锚点，
独立 GPT 已先盲评再对照既有判断：P07 高严重度且旧报告不可直接用于决策，P01 重大数据完整性风险；
分别与历史严重度一致，P07 可用性判断更严格，详见 S0 问题表。不得把它记成人类校准或新产品效果；
最终保留集盲评仍须由未暴露其定义/结果的 GPT 评审者承担。

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
无阻断，其两项非阻断测试建议也已覆盖。提交后 audit 和全新前置仍待完成，尚未准入 v2 研究。
复审保留的新增非阻断盲区：控制器级 fresh-subprocess 测试直接覆盖有效 IPv4 loopback，但未逐项参数化
baseline checkout、IPv6、缺失/恶意 `LOCAL_PROXY` 或冲突预置 SAFE 值；底层代理合约和独立负测已
覆盖核心拒绝行为。真实服务启动到首个 safe fetch 的端到端一致性尚未在修复后付费复验。

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

本节保留旧协议及当时134上限的审计记录；现行152上限、12+48路线和准入状态仅以上文状态表为准。

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
