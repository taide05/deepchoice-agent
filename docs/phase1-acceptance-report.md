# Phase 1 整体验收报告

验收日期：2026-09-14

范围：Phase 1-A～1-F（生命周期、SQLite、repository/service、执行恢复、事件与兼容）

## 结论

Phase 1 的 **durable backend surface**（`/api/v1/tasks/*`）通过跨模块契约审计、迁移升级、
事务/CAS、lease/fencing、恢复、SSE replay/resync 和旧 snapshot 导入验收。状态写入与用户事件
保持同事务；失败 CAS/旧 epoch 不产生事件或 checkpoint 引用；真实 SQLite checkpoint 可跨
连接恢复。

验收是有边界的：当前 Streamlit 和 `POST /research` 仍走旧内存路径，因此不能把结论扩大为
“所有用户请求默认 durable”。后续应先完成前端/旧入口切换，再移除旧路径。

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

## 验证证据

- Phase 1-F 初轮聚焦验收：48 passed；取消竞态修复后的 migration/coordinator/acceptance
  聚焦回归：32 passed（2026-09-14）。
- 仓库全量测试：772 passed、0 skipped（2026-09-14）；另有 1 个既有 Starlette/anyio
  弃用警告，不影响结果。
- 付费/联网 benchmark：未运行；本阶段未修改研究算法或 benchmark 数据。
- 独立复审：首轮发现 lease commit-before-grant 取消竞态；修复及精确故障注入后复审闭环，
  未发现剩余阻断项。

## 遗留风险

| 等级 | 风险 | 处理建议 |
|---|---|---|
| 中 | Streamlit/`POST /research` 未切换 durable API | 作为下一阶段前置集成任务；切换前保留明确兼容标记 |
| 中 | SQLite lease/coordinator 不支持多 worker/多主机 | 部署固定单实例；扩容前引入独立 coordinator/queue |
| 中 | 产品 DB 与 checkpoint DB 无跨库事务 | 成对备份；仅从产品库已接受且实际可读的 checkpoint 恢复 |
| 中 | 超大 legacy snapshot 为完整 SHA-256 会增加启动 I/O | 部署前扫描/隔离大文件；后续把 importer 移出 readiness 路径或引入有界指纹 schema |
| 低 | 旧 v1-v3 task 升级后没有历史事件回填 | 客户端先 GET task snapshot；只对升级后的新状态变化提供事件 |
| 低 | SSE 暂无 keepalive 和 retention | 依靠 `Last-Event-ID` 重连；生产代理接入时补 keepalive/断档策略 |
| 低 | schema 不提供 destructive downgrade | 发布前备份；回退时恢复成对数据库，不手工改 migration history |

## 验收门槛

进入 Phase 2 前必须保持：工作区有可追溯提交、聚焦及全量测试通过、独立复审闭环、文档
测试计数与实际结果一致。Phase 2 的 trace/预算写入不得进入 task state/event 的原子正确性路径。
