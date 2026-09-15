# Phase 1 运行契约与恢复手册

本文固化 Phase 1-A～1-G 的 durable lifecycle 契约，并记录后续阶段对恢复、事件和持久化
决策的增量。代码、迁移历史和自动化测试仍是最终事实源；设计文档描述目标，不能覆盖这里
记录的实现边界。

## 1. 适用范围与兼容边界

具备完整 durable lifecycle 保证的是 `/api/v1/tasks/*`：任务和 run 写入产品 SQLite，
由 coordinator 执行，通过 durable `task_events` 对外发布状态。

Streamlit 默认创建、查询、事件、取消、恢复和结果读取均使用 `/api/v1/tasks/*`，并保存
`Last-Event-ID` 以支持断线 replay/resync。

`POST /research` 是一条已弃用的独立兼容路径，仍使用进程内 `_active_tasks` 和旧 SSE。
它创建的任务不会自动登记为 durable task，也不具备新 API 的取消、恢复、lease/fencing
或 durable replay 保证。旧接口保留一版并返回 `Deprecation`、`Warning` 和 successor `Link`
响应头；旧结果读取在本地文件不存在时只读 durable artifact，不会创建或重复执行任务。

## 2. 身份、状态与版本

- `task_id` 标识一次用户研究意图；`run_id` 标识绑定一个 `RunManifest` 的执行尝试。
- `tasks.latest_run_id` 指向当前尝试。当前 task 与 latest run 的状态必须一致。
- task/run 的 `version` 是乐观并发控制字段。读取后再写的生命周期操作必须做 CAS；
  CAS 失败返回冲突，不得覆盖赢家。
- `RunManifest` 冻结模型、LLM 参数、Prompt hash、workflow/state schema、retriever 和报告
  模板版本。当前新运行使用 `research-v3`/state schema v3，并冻结
  `deterministic-citation-v1` 与 `evidence-insufficient-v1` 策略；历史 v1/v2 manifest 仍可读取
  和校验身份，但不能在 v3 runtime 上续同一 run，须创建新 run。same-run resume 必须校验
  manifest ID 及当前运行时兼容性；不兼容时拒绝恢复。
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
| `GET /api/v1/tasks/{task_id}/snapshot` | 返回 latest successful run 的 immutable public result；运行中/失败终态使用不同结构化 `409` |
| `GET /api/v1/tasks/{task_id}/observability` | 返回 latest run 的 allowlisted Trace/usage 摘要；无 latest run、无 Trace 或历史策略缺失时以 `available`/`unavailable` 明确表达 |
| `GET /api/v1/tasks/{task_id}/decision` | 返回最新 HITL 决策的公开投影；不包含补充文本、checkpoint 或 fencing identity |
| `POST /api/v1/tasks/{task_id}/decisions/{decision_id}` | 携带当前 task version 的 `If-Match` 原子提交一个允许动作；相同 resolution 重放幂等 |
| `GET /api/v1/tasks/{task_id}/report` | 返回持久化报告，或从同一 public result 确定性渲染指定格式 |
| `GET /api/v1/tasks/{task_id}/annotated` | 返回带 TOC 和引用映射的阅读投影 |
| `GET /api/v1/tasks/{task_id}/export` | 从 durable result 导出 Markdown/PDF，不读取旧 snapshot 文件 |

## 3. 事务、lease 与 checkpoint

- 任务状态、latest run 状态和相应公开事件必须由 repository 在同一 `BEGIN IMMEDIATE`
  事务中提交。API、coordinator 和节点不得绕过 repository 直接改表。
- 成功 run 结束时，allowlisted `run_results`、task/run 成功终态和 `run.completed` 事件必须
  在同一事务提交。结果写入失败、过期 lease、旧 epoch、取消或 deadline 获胜时不得留下
  成功 artifact 或完成事件。产品结果不复制 checkpoint payload、运行所有权或原始异常。
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

### 3.1 Durable HITL 决策暂停与恢复

- 新运行的唯一人工决策门为 `evidence-insufficient`，位于引用验证之后、报告渲染之前；它只在
  证据结构不足且推荐方向实质不确定时触发。`POST /research` 及无 `RunContext` 执行不进入该
  durable 决策路径。
- schema v10 的 `hitl_decisions` 记录决策状态及其产品库接受的 checkpoint 引用、run、state
  schema 和暂停 execution epoch。LangGraph checkpoint payload 仍保存在 checkpoint store。
- 创建决策、task/run 进入 `waiting_for_input`、清除 lease/lease deadline，并追加
  `decision.required` 事件在一个产品库事务中提交。等待期间不持有 worker lease、active runtime
  deadline 或执行槽；pending decision 可跨进程重启保留。
- 允许的 resolution 为 `provide_context`（带 1–4000 字符补充内容）、`limited_report`（仅使用
  暂停前已收集证据并标记为受限）、`cancel`（不恢复图，task/run 进入 cancelled）。补充文本
  只作为 untrusted context 提供给恢复图，不得进入公开事件或 GET decision 响应。
- 每个 decision 在创建后 7 天过期。到期由 recovery 或 resolve 路径原子标记 decision expired，
  并将仍等待的 task/run 收敛为 cancelled；过期 resolution 不得恢复执行。
- resolve 需要当前 task version `If-Match`。decision 的 task/run 状态、已接受 checkpoint、
  state schema 和暂停 epoch 必须一致；同 body 重放返回原结果，不同 body 冲突。非取消动作
  原子地把 run/task 入队并保存 resolution，再由 coordinator 从绑定 checkpoint 恢复；只有已
  解决且匹配 checkpoint 的 resolution 可注入 LangGraph interrupt resume。
- cancellation 不恢复图。公开 `decision.required`、`decision.resolved`、`decision.cancelled`、
  `decision.expired` 事件只包含必要的 decision ID/kind、reason、gaps、allowed actions、expiry、
  action/status；不得暴露 supplement、checkpoint ID/namespace、execution epoch、lease owner、
  manifest 或完整 state。

#### Streamlit 交互与恢复验收（Phase 4-2）

- durable SSE 收到 `waiting_for_input` 或 `decision.required` 后，服务端在事件追平时结束本次
  SSE 响应，客户端呈现最新公开 decision projection；等待用户期间不维持 SSE 连接。决策提交后从最近收到的
  `Last-Event-ID` 续接；若 replay 返回 resync，则先读取公开 task/decision 快照，再恢复事件流。
- 页面展示 reason、evidence gaps、allowed actions 和 expiry，并提供补充信息继续、受限报告、取消。
  每次 resolve 携带当前 task version 的 `If-Match`。提交结果不确定时仅以相同 body 重试；版本或
  resolution 冲突后刷新状态，不自动替用户选择。
- 补充文本只允许暂存在用户输入控件及提交结果不确定时的私有 session 重试体；不得进入公开
  decision 投影、页面事件、日志或错误信息。checkpoint/fencing identity、lease owner、manifest
  和完整研究 state 同样不得进入这些公开表面。页面渲染报告仍须使用服务端提供的安全 HTML。
- 端到端恢复验收使用独立产品 SQLite 与 LangGraph checkpoint SQLite、真实 StateGraph/checkpoint
  saver，验证 pending decision 重启保留、相同提交幂等、不同提交/旧版本冲突、七天过期、取消不
  resume，以及合法 resolution 从绑定 checkpoint 恢复同一 run 且只恢复一次。

## 4. Durable task events 与 SSE

`task_events.event_id` 是数据库级全局单调 cursor；`seq` 只在单个 task 内从 1 单调递增。
两者含义不可互换。常见事件包括：

- `task.queued`、`run.started`、`run.progress`
- `task.cancel_requested`、`task.cancelled`、`run.cancelled`
- `run.resumed`、`run.retry_queued`、`run.auto_resumed`
- `run.completed`、`run.completed_with_warnings`、`run.failed`、`run.timed_out`、`run.interrupted`
- `legacy.imported`
- `decision.required`、`decision.resolved`、`decision.cancelled`、`decision.expired`

事件 envelope 可以包含 `id`、`seq`、公开 `run_id`、`created_at`；payload 只允许稳定的
`status`、`node`、`reason` 等最小公开字段。decision events 可额外包含公开 decision ID/kind、
evidence gaps、allowed actions、expiry 和用户选择的 action，但禁止写入补充文本、lease owner、
epoch、checkpoint ID/namespace、manifest 内容、原始异常、密钥、完整请求、完整研究 state 或
报告正文。

SSE 规则：

1. 无 `Last-Event-ID` 或值为 `0` 时从头 replay。
2. header 必须是非负、未带符号的十进制整数；非法值返回结构化 `422`。
3. cursor 不属于当前 task、已不存在或超前时，服务发送 `resync_required` 和公开 task
   snapshot。客户端必须用 snapshot 覆盖本地投影，再从返回的最新 ID 继续。
4. 当前状态为 completed/failed/timed-out/cancelled/interrupted 且事件已追平时连接关闭。
   `waiting_for_input` 也会结束本次连接，但仍是可恢复的非终态；decision resolve 后客户端从最后
   event ID 新建连接。`interrupted` 后若发生 resume，客户端同样重新连接读取后续事件。
5. SSE 不依赖 Phase 2 trace。当前未实现事件 retention 和空闲 keepalive；代理断线后依靠
   浏览器重连及最后收到的 event ID 恢复。

## 5. Migration 与旧 snapshot

- 产品 schema migration 只向前追加；已经提交的 migration 内容、名称和 checksum 禁止修改。
- runner 在 `BEGIN IMMEDIATE` 下串行执行，验证连续版本、名称和 checksum；失败整体回滚。
- 当前产品 schema 为 v10：v4 引入 `task_events`/`legacy_imports`，v5 在不修改 v4 checksum
  的前提下重建 `legacy_imports`，强制 imported 行绑定非空 task/run，error 行不得绑定实体；
  已绑定的 imported 审计行以 `RESTRICT` 防止删除其 task/run 后形成悬空记录。v6 增加
  immutable `run_results`；v7 增加产品库单实例租约；v8 建立 Phase 2-A 的预算/Trace
  表 `run_budget_policies`、`node_attempts`、`external_calls`、`trace_events` 和
  `budget_ledger`。Phase 2-B 已将节点尝试和 LLM/检索调用写入 Trace 表并提供只读摘要查询；
  Phase 2-C 已接入预算预留、结算、硬限制、受限结果和预算摘要；v9 增加带 TTL 的
  `retrieval_cache` 表；v10 增加唯一 `evidence-insufficient` 决策门的 `hitl_decisions`。这些
  表均属于产品数据库，现有成对备份中的产品库副本会一并包含缓存与决策元数据。
- v6 不臆测或回填旧 completed row 的报告；无法从可信来源重建的 pre-v6 成功记录保留为
  只读历史，并在结果查询时返回 `TASK_RESULT_UNAVAILABLE`。v6 后的新成功收尾和带有效报告的
  legacy success import 都必须同时写入 `run_results`。
- 新 migration 必须覆盖：空库安装、上一版本升级、保留已有数据、重复执行、并发 runner、
  失败回滚、未来版本和历史漂移拒绝。
- 旧 snapshot importer 在 readiness 完成后作为受管后台任务运行，只扫描 `outputs` 的直接
  合法 task 子目录并拒绝 symlink/junction 越界；成功文件优先。原文件永不改写，`_error`、
  非 allowlist 字段和私有运行 state 不进入产品库；有效公开报告及渲染所需公开字段会作为
  immutable `run_result` 导入。
- 导入以相对路径和 SHA-256 幂等；内容变化或 task/run 冲突只记录安全错误，不覆盖现有数据。
  默认最多检查 1000 个候选、总 I/O 预算 5 秒、单文件上限 64 MiB；超限文件先按元数据
  拒绝，不为完整哈希继续读取。预算触顶明确记录 `budget_exhausted`，不得伪装为完整扫描。
  I/O 时间预算在目录枚举、读取块和解析步骤之间协作检查；单次底层文件系统调用若永久阻塞，
  Python 线程无法强制中止它。导入已移出 readiness，因此不会阻塞服务就绪；对不可信或远程
  存储应在独立进程或离线维护窗口执行。

## 6. 升级流程

1. 停止 API/coordinator，确认没有仍在写入的进程。
2. 使用 `python scripts/runtime_db.py backup --product-db outputs/deepchoice.db
   --checkpoint-db outputs/checkpoints.db --destination <new-dir> --maintenance-confirmed`
   成对备份。脚本使用 SQLite backup API 并生成双文件哈希 manifest；旧 snapshot 目录另保留
   只读副本。两个 SQLite 文件之间没有跨库原子快照，因此确认维护模式是强制前提。
3. 在备份副本或临时环境启动新版本，确认 migration history 连续、旧 task/run/checkpoint
   可读，并运行对应升级验收测试。若 v4 中存在违反 v5 imported/error 约束的手工数据，
   升级会整体回滚；应在副本中核对并修复来源，不能跳过 v5 或改 checksum。
4. 只启动一个 worker/实例。启动顺序是：worker 配置检查 → 产品 DB migration → 获取实例
   lease → checkpoint DB 初始化 → stale-run recovery → readiness → 后台旧 snapshot 导入。
5. 检查没有幽灵 `running`/`cancelling`、旧 owner 已被 fencing、SSE 能 replay；再恢复流量。

禁止 destructive downgrade、手工删除 `schema_migrations` 或修改 checksum。需要回退时停止
所有新进程，并成对恢复升级前的产品 DB/checkpoint DB 备份及原 snapshot；仅回滚代码而继续
使用新 schema，旧应用会因 future schema 检查而安全拒绝启动。

恢复前先运行 `python scripts/runtime_db.py verify --backup-dir <dir>`；`restore` 默认只做 dry-run，
实际替换必须增加 `--apply --replace --maintenance-confirmed`，已有数据库会保留为带时间戳的
`.pre-restore-*.bak`；对应 `-wal`/`-shm` sidecar 也必须一并隔离或回滚，防止旧 WAL 回放到
新主库。发布演练使用 `exercise --backup-dir <dir> --drill-dir <new-dir>`，只恢复到
新目录并执行完整性检查，不接触产品文件。

## 7. 故障处置

| 现象 | 安全动作 |
|---|---|
| `SCHEMA_MIGRATION_*` | 停止启动循环，保留数据库，核对应用版本和 migration history；不要改 checksum |
| `RUN_MANIFEST_*` | 不续旧 run；保留审计记录，使用当前运行时创建新 run |
| stale `running` | 确认旧实例停止并等待 lease 失效；单实例启动 recovery，验证旧 epoch 被拒绝 |
| `RUNTIME_SINGLE_WORKER_REQUIRED` / `RUNTIME_INSTANCE_CONFLICT` | 修正 worker/副本配置或等待已确认停止的旧实例 lease 失效；不得绕过 guard |
| stale `cancelling` | recovery 应收敛为 cancelled；不得强制改为 completed |
| checkpoint 引用不可读 | 保持 interrupted 或新 run 重试；禁止手工伪造 checkpoint ID |
| `LEGACY_SOURCE_CHANGED` / `LEGACY_ID_CONFLICT` | 保留原文件和现有 task，人工核对来源；不得覆盖导入 |
| legacy import 预算触顶 | readiness 不受影响；查看安全汇总，缩小扫描目录或在维护窗口分批导入 |
| SSE `resync_required` | 用随事件返回的公开 snapshot 重建本地状态，再保存最新 event ID |

## 8. 当前运行边界

- SQLite/coordinator 通过产品库 lease 和启动配置检查强制单实例、单 worker；不能把它当作
  分布式队列或横向扩缩容机制。
- 当前 API 面向单用户、可信主机/可信网络，尚无认证、租户隔离和任务 ownership。不得把
  `0.0.0.0:8000` 直接暴露公网；远程部署必须由认证反向代理限制访问，多用户化前必须补齐
  API token/会话认证与 tenant ownership。
- 产品 DB 与 checkpoint DB 必须作为一组备份和恢复。
- 旧 `/research` 创建/SSE 仅用于一版兼容，任何新消费者必须使用 durable API。
- SSE keepalive 和事件 retention 延后到真实反向代理或生产部署接入前完成。
- Phase 2 Trace 与观测失败不得影响 task state 或 durable SSE 的正确性；预算账本属于
  fail-closed 正确性路径，预留失败必须阻止外呼并使 run 进入可解释终态。
- Phase 2-C 后新 durable run/retry 原子冻结 `standard-enforced-v1` 与 `unpriced-v1`；已有
  `standard-observe-v1` run 在同 run resume 时保留原策略。标准硬上限为 60,000 total token、
  96 次 LLM、72 次 retrieval 和 900,000 active milliseconds，80% 触发软提示。
  价格未知保持 unknown，不得按零成本结算。旧 run 不回填，policy 投影在
  `GET /api/v1/tasks/{task_id}/observability` 中明确为 unavailable。该 endpoint 在同一个
  SQLite read transaction 中读取 task 的 latest run、该 run 的状态/epoch/policy 和 Trace，避免
  retry 时混读旧 run。Phase 2-B 写入节点尝试与 LLM/检索调用 Trace，并通过该 API 返回
  latest-run allowlist 摘要；调用包含安全的节点名、run 内节点尝试序号和可选的非负 `retry_no`，
  不公开内部 attempt/call ID、epoch、lease、checkpoint、manifest、原始异常或其他请求/结果摘要。
  跨 epoch 残留或 run 本身已 `interrupted` 的 started 记录投影为 `interrupted`；其他非活动 run
  当前 epoch 的 started 记录投影为 `unknown`，避免呈现为仍运行。无 Trace 返回 unavailable；Token 汇总只累加已知字段并标明是否
  完整，unknown 不当作零。预算摘要按每个 reservation 的最新 append-only 状态聚合 settled、
  unknown、reserved、剩余额度与软/硬限制；`admission_denied` 单独表示“仍有余额但不足以准入
  下一次调用”，不把它伪装成已消费到硬上限。不公开 reservation/call ID、epoch 或内部 summary。
  Streamlit 查询不可用时回退 snapshot panels。Trace 是可选观测，不影响 task state、结果或
  durable SSE；预算预留与结算按当前 lease/epoch fencing，并发不得超发。首次 admission denial
  会在串行事务内锁存该 run，已经越过快速检查但尚未提交的并发申请也必须拒绝。触顶后仅当确定性结构
  证据门满足（三条非争议可用链、两个有效 HTTP(S) host、至少一条 moderate/strong）时生成
  不再外呼的受限报告并以 `completed_with_warnings` 原子持久化，否则以
  `BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE` 失败。`RunManifest` 保持 schema v1，并冻结每个 LLM
  call 的 `max_output_tokens`；旧 manifest 按历史 identity 可读，但不能兼容恢复。
- Phase 6-A 的受管 URL 外呼只允许 HTTP(S)、80/443 和无 userinfo；DNS 解析、实际 direct-IP
  连接以及每一跳 redirect 都必须重新验证公网地址、hostname、端口和响应上限。无法证明安全的
  proxy/forward 动态 URL 必须拒绝。forward allowlist 只接受完整 hostname 精确匹配或显式
  `*.example.com` 子域匹配。
- 请求 body 上限为 128 KiB，query、候选项、澄清文本、字段和聚合输入另有数量/长度上限。
  日志、错误、Trace 和 LLM diagnostics 统一脱敏；LLM diagnostics 只保留 hash、length、usage
  和 error type。报告继续支持 Markdown，`report_html` 和 PDF 使用服务端同一 sanitizer；
  前端不得把未清洗报告放入 `unsafe_allow_html`。
- Phase 6-A 不包含认证/API key 或 rate limiting，也不声称所有静态 provider 已迁移到安全 fetch；
  这些仍是后续安全收口或独立适配任务。
