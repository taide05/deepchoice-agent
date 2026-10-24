# Phase 5-2 工程基础整体验收报告

验收日期：2026-09-15

范围：Phase 0～Phase 5-1 已实现的默认 durable 路径及其迁移、恢复、预算、Trace、引用、缓存、
HITL、SSE、安全、兼容与部署配置。本报告不验收真实报告质量，不包含付费 benchmark、指标优化
或面试材料。

## 结论

DeepChoice 的工程基础通过跨模块审计、故障/恢复聚焦测试、完整测试套件、离线基线、静态检查
和独立复审。审计发现的预算拒绝竞态、等待决策 SSE 不收流、Tavily 出站旁路及 Python/Docker
配置漂移均已闭环。当前仓库可以作为后续真实 case 指标测量和针对性优化的工程基线。

该结论不表示研究效果已达到目标，也不表示面试交付版本已经完成。

## 本轮修复

| 等级 | 发现 | 收口结果 |
|---|---|---|
| 中 | 首次预算拒绝后，已越过快速检查的并发小额申请仍可能提交 | 在串行 admission 事务内重查 run 级 exhausted latch；其他 run 不受影响 |
| 中 | `waiting_for_input` 依赖 Streamlit 主动断开，SSE 服务端仍轮询 | 追平 `decision.required` 后由服务端结束本次响应；caught-up 重连空结束，resolve 后按 cursor 续接 |
| 中 | 默认 Retriever、冲突取证及 benchmark health-check 的 Tavily POST 绕过 outbound | 全部改由 `make_client("tavily")` 选路；静态 HEAD probe 不带 key/body，实际 POST 仍由 keypool 管理 |
| 中 | CI、benchmark workflow 和前端镜像的 Python 版本不一致 | CI 覆盖 3.11/3.12；benchmark、前后端镜像固定 3.12；前端 Streamlit 下限与项目一致 |
| 低 | 容器重建丢失 Tavily exhausted-key 状态 | Compose 默认将状态文件放入持久化的 `/app/outputs` volume |
| 低 | 部分 legacy 入口没有弃用响应头回归断言 | 补充创建、SSE/status 和 history 的代表性契约测试 |

Tavily 的 `self-forward` 被强制排除，因为现有 forward transport 不保留 POST method/body；默认
顺序为 `local-proxy,direct,direct-v6`。benchmark artifact 中的 `tavily_direct` 是为兼容保留的
历史字段名，不代表现在强制使用 direct channel。

## 跨模块审计

- migration 1～10 保持 append-only/forward-only；runner 的 checksum、并发串行化、失败回滚和
  未来 schema 拒绝均有测试。
- task/latest-run、用户事件、成功结果和 HITL 决策继续由 repository 事务维护；CAS 失败和旧
  fencing epoch 不产生状态、事件、预算或 checkpoint 副作用。
- lease、heartbeat、取消、超时、startup recovery、checkpoint compatibility 和单次 resume 的
  故障路径保持覆盖。
- Trace 仍为 best-effort；预算 ledger 属于 fail-closed 正确性路径。首次 admission denial 后
  不再允许同 run 的新 reservation 提交。
- citation verification 仍先过预算、规范 URL 去重并使用安全 fetch；cache 只保存成功且通过
  contract/provenance/大小检查的 retrieval result，hit/coalesced waiter 不消耗外呼预算。
- HITL 仍只包含 `evidence-insufficient`；等待态释放 lease/deadline/执行槽，七天过期并绑定
  accepted checkpoint。SSE 在等待态收流，但该状态仍可恢复且不是终态。
- 动态 URL 每跳重新执行 DNS/端口策略并固定 direct IP；报告 HTML/PDF 共用 sanitizer；公开
  error/event/Trace 继续执行 allowlist 与集中脱敏。
- `/research` 保留为独立、已弃用的一版兼容路径；新消费者继续只使用 `/api/v1/tasks/*`。

## 测试数量审计

PR 5-2 开始时收集 **1022** 项，来自 61 个测试文件和 628 个 `test_*` 函数定义。仓库可核验的历史
快照为：工程改造前 309、Phase 0 后 353、Phase 1-A 后 684、Phase 1-G 后 799、Phase 2-A 后
815、Phase 2-B 后 863、Phase 2-C 后 895、Phase 3-1 后 937、Phase 3-2 后 967、
Phase 4-1 后 986、Phase 4-2 后 1011、Phase 5-1 后 1022。它们是各提交当时记录的观察值，
不是永久常量。

最大增量来自 `test_lifecycle_contracts.py` 的 331 个收集项。该文件不是 331 个手写函数，而是
三个 10×10 task/run 状态转移矩阵及边界用例的穷举参数化；它单独解释了 Phase 1-A 的
353→684 增长，应保留。其余主要增量对应 migration/CAS/recovery、预算并发、引用状态、缓存
single-flight、HITL checkpoint 恢复和安全边界，未发现足以支持“为缩小数字而删除”的低价值组。

发现一组可接受的分层重叠：repository CAS 测试验证单一赢家，Phase 1-F acceptance 又验证赢家
同时只有一组事件。两者有利于定位失败，暂不合并。少量测试直接检查私有 connection/usage
helper，属于重构耦合风险，但目前承担数据库副作用验证，不建议删除。

本 PR 为六项实际缺口新增 15 个 `test_*` 函数，参数化后增加 18 个收集项；最终为
**1040 passed**。测试数量本身不作为质量指标。

## 验证证据

- 跨模块迁移/恢复/预算/Trace/引用/cache/HITL/SSE/安全聚焦验收：221 passed。
- 合并修复后的直接受影响测试：98 passed；Tavily/配置复验 51 passed；benchmark health-check
  10 passed。
- Python 3.12 项目环境全量：1040 passed、0 skipped（2026-09-15）。
- Phase 5-1 离线 smoke：12/12 case、deterministic replay 12/12，checked-in fingerprint 匹配。
- `pyflakes src tests benchmarks`、`vulture src --min-confidence 100`、`pip check` 和
  `docker compose config --quiet` 通过。
- CI 定义覆盖 Python 3.11/3.12；本地主机只有 3.12，因此 3.11 等待远端 CI 实际执行。
- 独立复审：所有 medium finding 闭环后，未发现残留 blocker/high/medium/low 可操作问题。
- 未调用真实 LLM、Tavily 或其他外部服务，未运行付费 benchmark。

## 遗留风险

| 等级 | 边界 | 当前处理 |
|---|---|---|
| 中 | durable API 无认证、tenant ownership | 仅限单用户可信网络；远程使用必须置于认证反向代理后 |
| 中 | SQLite 仅支持单实例/单 worker；产品 DB 与 checkpoint DB 无跨库事务 | 启动 guard；两库成对备份/恢复并只接受产品库登记的 checkpoint |
| 中 | 尚无当前版本真实 case 的重点指标基线和优化结果 | Phase 5 不作效果结论；下一路线需先冻结 case/指标再优化 |
| 低 | TLS/SNI、压缩响应解压后限额、浏览器级 XSS 尚无真实端到端验证 | 现有 mock/pinned transport 与 sanitizer 单测继续作为基础；生产化前补齐 |
| 低 | SSE 没有 keepalive 和事件 retention | 依赖 `Last-Event-ID` 重连；接入真实反向代理前补齐 |
| 低 | 依赖使用范围约束且无 lock file，未来 clean install 可能解析漂移 | 3.11/3.12 CI 与 import smoke 提前暴露；发布制品化时再冻结 lock |
| 低 | legacy `/research` 仍在兼容窗口，部分静态 provider 未迁移到 safe-fetch | 不增加新消费者；动态 URL 继续强制 safe-fetch，后续按真实部署需要处理 |

## 后续门槛

当前实施路线在本 PR 后结束。下一阶段应先选择少量代表性真实 case，冻结重点指标、费用和运行
环境，形成可复现基线；再针对检索召回、冲突识别、结论正确性和报告质量做优化。只有真实指标与
演示结果稳定后，才进入架构讲解和面试材料整理。
