# 当前执行状态与证据索引

最后实际研究：2026-09-21；本次规划/归档新增研究、健康、LLM 调用均为 0。
本文只维护最新状态和账本。后续目标见 [地图](current-roadmap.md)，操作方式见 [执行规则](optimization-execution.md)。

| 项目 | 当前事实 |
|---|---|
| 工作分支 | codex/baseline-readiness；文档 HEAD 与产品候选不能混为一谈 |
| 产品候选 / 控制身份 | d23c948 / 7d16d28；P01 助手暂定资格有效 |
| 持续授权研究账本 | 90/134，剩余 44；不是项目全部历史分母 |
| 可用主诊断材料 | 同候选 github-retry 根 serial-r1 的 8 development 报告；全组 12 报告 |
| 尚未完成 | 当前完整质量台账、最终产品验收、两轮并发；保留集/人类校准未验收 |
| 下一成果 | S0 离线全面诊断与验收卡；本会话只做规划归档和交接 |

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
134 硬上限未提高；新地图的小样本、最终串行与并发整合方案尚待冻结，不从额度余额推定可立即执行。
阶段切换不单独创造审批；只有实质边界变化按执行规则集中处理。当前产品未因文档归档改变。

- [当前 P01 资格与冻结](o1c-single-case-verification.md)。
- [完整执行历史与先前各独立分母](archive/product-optimization-20260921/execution-history.md)。
- [冻结 v4](archive/product-optimization-20260921/evaluation-protocol-v4.md)。
- 主诊断根：`outputs/o1-pr2b-pair-20260921-f6d6089-d23c948-github-retry/`。
- 最新停止根：`outputs/o1-pr2b-pair-20260921-7d16d28-cap134/`。

原始输出/数据库未修改或移动。不得按归档中的“当前”“下一步”执行，也不得以本页简表代替原始 run 身份。
