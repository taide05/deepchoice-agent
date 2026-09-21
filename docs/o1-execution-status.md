# 当前执行状态与证据索引

最后实际研究：2026-09-21。2026-09-22 S1 新增一轮前置：8 次非 LLM HTTP（含 1 次 Tavily POST），
0 次 LLM HTTP、0 次研究；前置在 LLM 客户端初始化失败，未进入资格或局部配对。
本文只维护最新状态和账本。后续目标见 [地图](current-roadmap.md)，操作方式见 [执行规则](optimization-execution.md)。

| 项目 | 当前事实 |
|---|---|
| 工作分支 | codex/baseline-readiness；当前实现与已测量产品候选不能混为一谈 |
| 已测量候选 / 控制身份 | d23c948 / 7d16d28；原 P01 助手暂定资格仅覆盖该身份，S1 产品修改需要新资格 |
| 持续授权研究账本 | 90/134，剩余 44；不是项目全部历史分母 |
| 可用主诊断材料 | 同候选 github-retry 根 serial-r1 的 8 development 报告；S0 身份、哈希和 360 行逐处原子关键声明已锁定 |
| 尚未完成 | S1 新候选资格/局部配对、最终产品验收、两轮并发；保留集/人类校准未验收 |
| 当前成果 | S1 单例资格控制链已补齐；唯一前置因入口配置加载顺序停止，根保持只读；尚无新资格/局部配对 |

执行适配核对发现：原 PR2B 控制器写死旧产品与 12 例整批，S1 协议校验本身不提供可用的
新候选执行器。当前补齐独立绑定的 P01 单例资格入口，复用原安全监控但禁止资格自动取消/
决策/恢复；十二格双产品配对执行与锁分门禁仍需适配，不能直接用旧串并发 comparator。
原协议哈希与产品身份未改变。2026-09-22 无网络本地审计确认依赖、路由配置、代理身份、
模型端点和 embedding revision 与冻结环境一致，启动内存线满足；这不是连通性证明。
资格适配离线验收：98 项聚焦、全套 1664 passed（190.92 秒）、smoke-v1 12/12、静态/依赖
检查及独立只读复审通过。运行器残余风险：旧 launcher 身份读取失败后的 terminate/wait
没有二次 kill fallback；复审定为非阻断，若实际启动异常，须核对进程归属并对账，不能重跑根。

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
失败前置摘要/请求台账保持原样，未补跑或使用失败证据放行。Tavily 前置额度已用满；
后续真实执行需明确处理前置停止及新的证据/预算绑定，不能把控制器修复当成原前置通过。

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

## 最近一次研究及收尾

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

## 当前授权与证据边界

先前外传授权继续覆盖冻结查询/候选/必要上下文、DeepSeek/Tavily/GitHub API/StackExchange API/
arXiv/PyPI/官方来源、已配置 local-proxy/self-forward 路由及公共 HTTP(S) 引用安全抓取。
134 硬上限未提高；S1 协议已冻结为 product-optimization-s1-constraint-aware-v1（SHA-256
1e771a7beb8c551df2c4eafc49d5c2a3f0d16845ca678f54f391018b0686d391），
最多 1 次候选资格 + 12 次局部配对，研究准入尚未启动；本轮前置已按上文停止。
不从额度余额推定可立即执行；最终串行与并发整合方案仍未冻结。
阶段切换不单独创造审批；只有实质边界变化按执行规则集中处理。S1 已改变产品身份，原资格不覆盖新实现。

- [当前 P01 资格与冻结](o1c-single-case-verification.md)。
- [完整执行历史与先前各独立分母](archive/product-optimization-20260921/execution-history.md)。
- [冻结 v4](archive/product-optimization-20260921/evaluation-protocol-v4.md)。
- 主诊断根：`outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/`。
- 最新停止根：`outputs/o1-pr2b-pair-20260921-7d16d28-cap134/`。

原始输出/数据库未修改或移动。不得按归档中的“当前”“下一步”执行，也不得以本页简表代替原始 run 身份。
