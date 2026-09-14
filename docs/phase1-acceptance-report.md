# Phase 1 整体验收报告

验收日期：2026-09-14

范围：Phase 1-A～1-G（生命周期、SQLite、repository/service、执行恢复、事件、兼容与默认路径接入）

## 结论

Phase 1 的 **durable backend surface**（`/api/v1/tasks/*`）通过跨模块契约审计、迁移升级、
事务/CAS、lease/fencing、恢复、SSE replay/resync 和旧 snapshot 导入验收。状态写入与用户事件
保持同事务；失败 CAS/旧 epoch 不产生事件或 checkpoint 引用；真实 SQLite checkpoint 可跨
连接恢复。

Phase 1-G 已将 Streamlit 默认路径切换至 durable API，并让成功结果、成功终态与完成事件
原子提交。`POST /research` 仍是保留一版的已弃用内存兼容入口，不属于 durable 保证范围。

## 审计覆盖

- 状态枚举、Pydantic DTO、SQLite CHECK 和 task/latest-run 投影一致性
- `RunManifest` 身份、冻结内容及 same-run resume 兼容检查
- v1 起的向前 migration、历史 checksum、并发 runner、失败回滚和未来版本拒绝
- v4→v5 合法 legacy import 保留、非法历史行整体回滚，以及 imported/error 数据库约束
- repository 事务边界、CAS 冲突、cancel/deadline 优先级和 retry-as-new-run
- lease/heartbeat/fencing epoch、epoch 隔离 checkpoint 和 stale-run startup recovery
- lease 已提交但 grant 尚未返回时的 shutdown/cancel 竞态，以及单次 interrupted 收尾
- durable `task_events` 的顺序、幂等、安全 payload、SSE replay/resync/终态关闭
- 旧成功/失败 snapshot 的只读、SHA-256 幂等导入和冲突隔离
- 新 API 与旧 status 别名的兼容回归
- durable result 原子提交、公开字段 allowlist、报告/快照/阅读/导出查询
- Streamlit `Last-Event-ID`、resync、cancel/resume 与默认路径不回退旧创建接口
- 产品库实例 lease、worker 配置拒绝、后台 legacy import 预算和成对数据库恢复演练

## 验证证据

- Phase 1-F 初轮聚焦验收：48 passed；取消竞态修复后的 migration/coordinator/acceptance
  聚焦回归：32 passed（2026-09-14）。
- 仓库全量测试：799 passed、0 skipped（2026-09-14）；另有 1 个既有 Starlette/anyio
  弃用警告，不影响结果。
- 付费/联网 benchmark：未运行；本阶段未修改研究算法或 benchmark 数据。
- 独立复审：跨轮发现并闭环 lease 竞态、SSE resume replay、结果嵌套敏感字段、legacy
  containment、WAL/SHM restore/rollback 和实例租约失效边界；最终聚焦复审未发现阻断项。

## 遗留风险

| 等级 | 风险 | 处理建议 |
|---|---|---|
| 中 | 旧 `POST /research` 创建/SSE 仍是内存实现 | 保留一版并标记弃用；不再增加消费者，下一兼容窗口移除 |
| 中 | SQLite runtime 不支持多 worker/多主机 | 启动检查与 DB lease 强制单实例；扩容前引入独立 coordinator/queue |
| 中 | 产品 DB 与 checkpoint DB 无跨库事务 | 成对备份；仅从产品库已接受且实际可读的 checkpoint 恢复 |
| 中 | durable API 尚无认证、租户隔离和 task ownership | 仅限单用户可信网络；禁止裸露公网，远程部署置于认证反代后；多用户化前补齐授权模型 |
| 低 | pre-v6 completed rows 无可信 result 可回填 | 保留只读历史；结果查询返回 `TASK_RESULT_UNAVAILABLE`，需要时创建新 run |
| 低 | 后台 legacy import 可能在预算触顶后留有未处理文件 | readiness 不受影响；在维护窗口缩小范围后分批导入 |
| 低 | 旧 v1-v3 task 升级后没有历史事件回填 | 客户端先 GET task snapshot；只对升级后的新状态变化提供事件 |
| 低 | SSE 暂无 keepalive 和 retention | 依靠 `Last-Event-ID` 重连；生产代理接入时补 keepalive/断档策略 |
| 低 | schema 不提供 destructive downgrade | 发布前备份；回退时恢复成对数据库，不手工改 migration history |

## 验收门槛

进入 Phase 2 前必须保持：工作区有可追溯提交、聚焦及全量测试通过、独立复审闭环、文档
测试计数与实际结果一致。Phase 2 的 trace/预算写入不得进入 task state/event 的原子正确性路径。
