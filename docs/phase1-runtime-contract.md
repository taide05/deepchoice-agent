# Phase 1 运行契约与恢复手册

本文固化 Phase 1-A～1-F 的已实现行为。代码、迁移历史和自动化测试仍是最终事实源；
设计文档描述目标，不能覆盖这里记录的实现边界。

## 1. 适用范围与兼容边界

具备完整 durable lifecycle 保证的是 `/api/v1/tasks/*`：任务和 run 写入产品 SQLite，
由 coordinator 执行，通过 durable `task_events` 对外发布状态。

`POST /research` 是一条独立的旧兼容路径，仍使用进程内 `_active_tasks` 和旧 SSE。
它创建的任务不会自动登记为 durable task，也不具备新 API 的取消、恢复、lease/fencing
或 durable replay 保证。当前 Streamlit 前端仍使用这条兼容路径；迁移前不得宣称默认
用户路径已经具备 Phase 1 的全部持久化保证。旧 status 别名可在内存记录不存在时读取
durable task，但这不等于旧创建路径已经切换。

## 2. 身份、状态与版本

- `task_id` 标识一次用户研究意图；`run_id` 标识绑定一个 `RunManifest` 的执行尝试。
- `tasks.latest_run_id` 指向当前尝试。当前 task 与 latest run 的状态必须一致。
- task/run 的 `version` 是乐观并发控制字段。读取后再写的生命周期操作必须做 CAS；
  CAS 失败返回冲突，不得覆盖赢家。
- `RunManifest` 冻结模型、LLM 参数、Prompt hash、workflow/state schema、retriever 和报告
  模板版本。same-run resume 必须校验 manifest ID 及当前运行时兼容性；不兼容时拒绝恢复。
- `completed`、`completed_with_warnings` 和 `cancelled` 是不可重开的 task 结果；
  `failed`、`timed_out` 可通过新 run 重试；`interrupted` 是可恢复状态，不是不可重开终态。

主要 durable API：

| API | 契约 |
|---|---|
| `POST /api/v1/tasks` | 原子创建 queued task/run，返回 `202` |
| `GET /api/v1/tasks/{task_id}` | 返回公开 task/latest-run 投影，不返回执行所有权或 checkpoint 字段 |
| `GET /api/v1/tasks` | 按 `(created_at, task_id)` 做稳定 cursor 分页 |
| `POST /api/v1/tasks/{task_id}/cancel` | 幂等；queued 直接 cancelled，running 先进入 cancelling |
| `POST /api/v1/tasks/{task_id}/resume` | 必须携带当前 task version 的 `If-Match`；兼容 checkpoint 可续同 run，否则按允许状态创建新 run |
| `GET /api/v1/tasks/{task_id}/events` | 从产品库 replay 公开事件，支持 `Last-Event-ID` |

## 3. 事务、lease 与 checkpoint

- 任务状态、latest run 状态和相应公开事件必须由 repository 在同一 `BEGIN IMMEDIATE`
  事务中提交。API、coordinator 和节点不得绕过 repository 直接改表。
- 同一 run 的执行权由 `(lease_owner, execution_epoch, lease_expires_at)` 决定。每次重新
  获取执行权都产生更高 epoch；旧 owner/epoch 的 heartbeat、checkpoint 引用或收尾写入
  必须被 fencing 拒绝。
- heartbeat 只续 lease，不产生用户事件。CAS/fencing 失败必须零状态变更、零事件、
  零 checkpoint 引用。
- 停机取消可能与 lease 提交竞态。coordinator 必须等待正在进行的 lease acquisition 落定；
  如果 grant 已提交，即使调用方尚未收到返回值，也要按该 owner/epoch 完成 fenced finalization，
  然后再传播取消，不能遗留幽灵 `running`。
- 产品库只保存已接受的 checkpoint 引用；LangGraph payload 保存在独立
  `outputs/checkpoints.db`。每个 epoch 使用隔离的物理 namespace，逻辑根 namespace 为空。
- checkpoint payload 与产品引用不可能跨两个 SQLite 文件原子提交。恢复只信任产品库中
  已接受且实际可读取、schema/workflow 兼容的引用；引用缺失或 payload 不可读时保持
  `interrupted` 或安全创建新 run，不得猜测状态。
- coordinator 在节点调用前后及 checkpoint 写入前检查执行权。已经发出的第三方请求不能
  被强制撤回；取消后不得继续调度后续节点，也不得由旧 epoch 提交结果。
- 已持久化 cancel request 优先于普通完成；deadline 到期优先投影为 `timed_out`；
  stale `cancelling` 在恢复时收敛为 `cancelled`。

## 4. Durable task events 与 SSE

`task_events.event_id` 是数据库级全局单调 cursor；`seq` 只在单个 task 内从 1 单调递增。
两者含义不可互换。常见事件包括：

- `task.queued`、`run.started`、`run.progress`
- `task.cancel_requested`、`task.cancelled`、`run.cancelled`
- `run.resumed`、`run.retry_queued`、`run.auto_resumed`
- `run.completed`、`run.completed_with_warnings`、`run.failed`、`run.timed_out`、`run.interrupted`
- `legacy.imported`

事件 envelope 可以包含 `id`、`seq`、公开 `run_id`、`created_at`；payload 只允许稳定的
`status`、`node`、`reason` 等最小公开字段。禁止写入 lease owner、epoch、checkpoint ID、
manifest 内容、原始异常、密钥、完整请求、完整研究 state 或报告正文。

SSE 规则：

1. 无 `Last-Event-ID` 或值为 `0` 时从头 replay。
2. header 必须是非负、未带符号的十进制整数；非法值返回结构化 `422`。
3. cursor 不属于当前 task、已不存在或超前时，服务发送 `resync_required` 和公开 task
   snapshot。客户端必须用 snapshot 覆盖本地投影，再从返回的最新 ID 继续。
4. 当前状态为 completed/failed/timed-out/cancelled/interrupted 且事件已追平时连接关闭。
   `interrupted` 后若发生 resume，客户端应重新连接读取后续事件。
5. SSE 不依赖 Phase 2 trace。当前未实现事件 retention 和空闲 keepalive；代理断线后依靠
   浏览器重连及最后收到的 event ID 恢复。

## 5. Migration 与旧 snapshot

- 产品 schema migration 只向前追加；已经提交的 migration 内容、名称和 checksum 禁止修改。
- runner 在 `BEGIN IMMEDIATE` 下串行执行，验证连续版本、名称和 checksum；失败整体回滚。
- 当前产品 schema 为 v5：v4 引入 `task_events`/`legacy_imports`，v5 在不修改 v4 checksum
  的前提下重建 `legacy_imports`，强制 imported 行绑定非空 task/run，error 行不得绑定实体；
  已绑定的 imported 审计行以 `RESTRICT` 防止删除其 task/run 后形成悬空记录。
- 新 migration 必须覆盖：空库安装、上一版本升级、保留已有数据、重复执行、并发 runner、
  失败回滚、未来版本和历史漂移拒绝。
- 旧 snapshot importer 只扫描 `outputs` 的直接合法 task 子目录；成功文件优先，只读取并
  验证 request 和最小 provenance。原文件、报告和 `_error` 原文永不写回或复制进产品库。
- 导入以相对路径和 SHA-256 幂等；内容变化或 task/run 冲突只记录安全错误，不覆盖现有数据。
  单文件内存上限为 64 MiB。为获得完整 SHA-256，超限文件仍会被流式读完，这是已知启动
  I/O 风险，部署前应隔离异常大文件。

## 6. 升级流程

1. 停止 API/coordinator，确认没有仍在写入的进程。
2. 成对备份 `outputs/deepchoice.db` 和 `outputs/checkpoints.db`；若存在 WAL/SHM，使用 SQLite
   一致性备份或在完全停止后连同 sidecar 一起保存。旧 snapshot 目录也保留只读副本。
3. 在备份副本或临时环境启动新版本，确认 migration history 连续、旧 task/run/checkpoint
   可读，并运行对应升级验收测试。若 v4 中存在违反 v5 imported/error 约束的手工数据，
   升级会整体回滚；应在副本中核对并修复来源，不能跳过 v5 或改 checksum。
4. 只启动一个新实例。启动顺序是：产品 DB migration → 旧 snapshot 只读导入 → checkpoint
   DB 初始化 → stale-run recovery。
5. 检查没有幽灵 `running`/`cancelling`、旧 owner 已被 fencing、SSE 能 replay；再恢复流量。

禁止 destructive downgrade、手工删除 `schema_migrations` 或修改 checksum。需要回退时停止
所有新进程，并成对恢复升级前的产品 DB/checkpoint DB 备份及原 snapshot；仅回滚代码而继续
使用新 schema，旧应用会因 future schema 检查而安全拒绝启动。

## 7. 故障处置

| 现象 | 安全动作 |
|---|---|
| `SCHEMA_MIGRATION_*` | 停止启动循环，保留数据库，核对应用版本和 migration history；不要改 checksum |
| `RUN_MANIFEST_*` | 不续旧 run；保留审计记录，使用当前运行时创建新 run |
| stale `running` | 确认旧实例停止并等待 lease 失效；单实例启动 recovery，验证旧 epoch 被拒绝 |
| stale `cancelling` | recovery 应收敛为 cancelled；不得强制改为 completed |
| checkpoint 引用不可读 | 保持 interrupted 或新 run 重试；禁止手工伪造 checkpoint ID |
| `LEGACY_SOURCE_CHANGED` / `LEGACY_ID_CONFLICT` | 保留原文件和现有 task，人工核对来源；不得覆盖导入 |
| 超大 legacy snapshot | 在启动前移出扫描目录并保留只读副本，确认来源后离线处理 |
| SSE `resync_required` | 用随事件返回的公开 snapshot 重建本地状态，再保存最新 event ID |

## 8. 当前运行边界

- SQLite/coordinator 只承诺单实例、单主机的低到中并发；不能把它当作分布式队列或锁。
- 产品 DB 与 checkpoint DB 必须作为一组备份和恢复。
- durable API 尚未成为 Streamlit 默认调用路径，这是 Phase 1 后最优先的集成遗留项。
- Phase 2 trace、预算账本和观测失败不得影响 task state 或 durable SSE 的正确性。
