# O1-C 真实单例验真：前置停止记录

日期：2026-09-17。状态：**preflight_stopped，单例未执行，O1 仍 incomplete**。
随后用户授权定位两项阻断，见 [诊断记录](o1c-blocker-diagnosis.md)：新社区单源反馈确认
throttle_violation，并发现 probe 未带已配置的可选 key；离线时间断言存在时钟/打点契约错位。
后续诊断不倒填本次原件，也未修复或继续研究。
用户授权先验真一例；按任务卡选开发例 P01，最多一次提交，不重复、不自动恢复、不跑批次。
本轮未修改产品、测试、冻结案例、Prompt、路由或预算。

## 实际观察

- 执行候选：`51c7c21083da75e8411c1cb062df15a85c3f6322`（O1-B 已验收版本）。
- 数据集：product-baseline-v1 / 1.0.0 / 2026-09-16，SHA256
  `e0317ddeaa2b37526f5a7261d8df26217b75619d6c46bcd1bc8705895f16981f`。
- 一次真实检索前置检查，完成时间 2026-09-17 11:50:35.350290 UTC（北京时间 19:50:35）。
  五个网络来源健康项 **4/5 通过**：tavily/github/arxiv/official 为 local-proxy；
  community 选中 self-forward，但 `ok=false`。另行 routed Tavily 搜索 POST 通过。
  这不是研究六源的成功率：本地 ChromaKB 未测，研究内六源状态均 not_run。
- LLM/Tavily/GitHub 凭据存在检查通过，但不等于 LLM 连通或输出资格通过。
  LLM 探测、冷模型初始化、隔离服务、研究提交、报告、缓存 token 拆账均 **not_run**。
- 新建研究 run **0**，累计仍 **43/48**、剩余 5。健康检查已发生真实网络请求及 Tavily 搜索，
  其费用/重试总量未完整采集，金额 unknown；不能写成“本轮零费用”。无研究 token 观察。
- 主机前置可用内存约 2.9 GiB；读取到两条既往 WHEA-Logger 18（09-16 15:30、15:48）。
  没有真实研究峰值、心跳或冷启耗时样本；这些前置事实不证明硬件稳定或已修复。

## 阻断解释与证据边界

`outbound/resolver.py:health_check()` 仅在探测接受某通道后返回该 channel；当 provider gate
`unavailable()` 时仍保留 channel、把 `ok` 置 false 并标为 rate_limited。
`throttle.py:unavailable()` 表示已记录限流或冷却未结束；社区的反馈可来自 HTTP 429、
throttle_violation 或成功响应中的 backoff（见 `probe.py:ok_for()`、`throttle.py:observe()`）。

因此，**按冻结候选代码推断，此次 community 属 provider gate 不可用，不是转发断线的证据**。
安全检查产物只保留 ok/channel，未保留原 status、HTTP 状态、backoff/Retry-After；
具体触发原因与冷却期限 unavailable，不能断言实际收到 429，也不能判定限流补修无效。
下一次授权检查应保留 allowlisted status/安全限流分类，不保留响应正文、私有 URL 或凭据。

原件（本地保留、不提交 Git）：`outputs/o1c-control-20260917/retrieval-preflight.json`，SHA256
`6c88ef73320f591be26f438a0b77e3f97ecc691d0cc42e33dae3ae5b6b3e5e31`；
执行 helper `check-health.py` SHA256
`6f7795e9013e16d66823e3935da75788bc3d5e9aaa03ec42f4ea248ec9f7cc0f`。
脱敏事实投影见 [JSON 记录](o1c-preflight-observation.json)。未创建 `outputs/o1c-live-20260917`。

## 后续动作 / 停止线

1. 保留这次失败，不自动重跑健康、切路由、绕过冷却或提交 P01；没有进入 O1-D/O2。
2. 下一步先确认 community 可用性与安全限流反馈；若需改代码，另做有测试的最小修复。
3. 前置恢复后，重新明确授权 P01 一次提交，使用新空数据库对、同一知识快照与冻结预算；
   继续检查六源失败、缓存拆账、JSON/结构、冷启/心跳。再次失败或降级仍停止。
4. 单例成功只支持该例执行观察；不代表语义质量、硬件稳定、12-case 并发或 O1 闭环通过。

验证：O1-B 的 1238 全套通过（0 skipped）及 smoke 12/12 是该未变更候选的既往验收，
不是本轮全绿声明。本轮 outbound/限流离线回归 **53 passed / 1 failed**（22.25 秒）；
失败项 `test_mocked_twelve_cases_retain_six_source_results` 的缩放毫秒级请求间隔断言失败，
此前六源结果一致性断言通过。仅该项独立复查 **1 passed**（19.06 秒），不覆盖首次失败，
不据此确认根因或宣称 flaky 已修复。该测试完全使用合成 HTTP/本地 fixture，未调用真实服务。
JSON 原件哈希、脱敏投影、4/5 分母、无新研究目录及 git diff 检查通过；未产生测试临时目录。
本轮只补文档/事实投影，未改代码/测试；不重复未变更全套。后续应先定位这一时序不稳定，
修复后按契约跑聚焦和全套，再考虑真实单例准入。O1-C 不能呈现为完成或当前验证全绿。
