# 当前执行状态与证据索引

最后实际研究：2026-09-22，修复候选 83852d8 的 P01 已完成执行；2026-09-23 锁定内容资格不通过。
普通成本与阶段切换沿用用户持续授权；不再为此逐项停下确认，研究硬上限和安全门禁仍有效。
本文只维护最新状态和账本。后续目标见 [地图](current-roadmap.md)，操作方式见 [执行规则](optimization-execution.md)。

| 项目 | 当前事实 |
|---|---|
| 工作分支 | codex/baseline-readiness；当前实现与已测量产品候选不能混为一谈 |
| 已测量候选 / 控制身份 | 原基线 d23c948 / 7d16d28；最新产品 83852d8 在实际 checkout 60485b6 执行 P01，内容门禁未放行 |
| 持续授权研究账本 | 已用 92 / 现行上限 152，尚可准入 60；其中新局部配对至多12、整合S3/C1预留48，均尚未执行；不是项目全部历史分母 |
| 可用主诊断材料 | 同候选 github-retry 根 serial-r1 的 8 development 报告；S0 身份、哈希和 360 行逐处原子关键声明已锁定 |
| 尚未完成 | 新知识种子、协议/执行器离线验收、局部12格、最终质量与两轮并发48格；保留集盲评/人类校准未验收 |
| 当前成果 | 行动安全、已知占位、source-score-v5身份分类及事务入口取消修复已离线验收；窗口原型未推广；新知识/测量方向已批准但未实施或付费，新产品未实测 |

2026-09-23 用户明确批准前瞻隔离 benchmark 派生比较模板、在现有来源范围审计并重冻
可信知识种子；批准“修复包局部12格＋预先整合S3/C1共48格”，累计研究上限
**134→152**，且以新协议冻结的配对 P01 回归替代第三次独立 P01 资格。
两臂须使用同一母种子内容身份的物理独立只读副本；旧知识库、历史报告/停止根原样保留，不读取 P09–P12 以准备新候选。
这批准路线与上限，**不是**已通过新种子审计、协议/执行器故障矩阵、服务健康、内容门禁或付费
准入：目前新增研究0、仍已用92；60次全部已有分母去向，不能以重试补齐停止样本。
人类校准由用户指定另一位评审，评审身份和实际判断尚未提供；本地已固定P07受限与新P01迁移
两份开发锚点，不能由助手填报。最终保留集盲评须由未暴露其定义/结果的评审者承担。

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
的人工支持分布为 supported 71、partial 179、unsupported 35、unknown 22、uncited 53，
完整支持率 micro 19.7%、macro 19.4%；来源质量为 eligible 0、ineligible 304、unknown 56，
micro/macro 均为 0。确定性引用投影 0 verified / 94 unsupported /
342 unknown，与人工语义判断分开。

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
