# DeepChoice Agent Guide

This file is the project-level operating guide for AI coding assistants. It applies to the whole repository.

## Project and sources of truth

- DeepChoice is a Python/LangGraph research pipeline for evidence-backed technology selection.
- Treat the checked-out code, `pyproject.toml`, and executable tests as the primary source of truth.
- `README.md` describes the user-facing product. Benchmark figures in it are historical snapshots and must keep their dataset and date attached.
- Material under `D:\ai-career` is external career/project documentation. It is useful context, but it can lag behind this repository and must not override the current Git state or tests.
- Do not silently update resumes, interview material, or other external consumer documents while changing this repository. First establish and record the verified repository facts.

## High-priority execution rules: subtraction first (2026-10-11)

本节落实用户当前执行方向，优先于本文件及历史计划中与其冲突的默认增量做法。
用户最新指令始终优先；下述减法原则不授权绕过安全、事实核验、预算或持久化正确性边界。
接手先读 [Codex 复盘与接手约束](docs/agent-development-lessons.md)。旧八小时 N1–N4
已结案且内容未达标，不是活动计划；旧付费额度已结算，不推导下一轮授权。

- **成果优先**：首要成果是完整研究链路稳定生成有依据、回答关键取舍的报告。
  局部修复、测试通过、提交数和文档完成均不能代替这个成果；阶段按用户可见结果验收。
  先区分“任务运行并可查询报告”和“报告回答原问题且依据适用”；单例链路与内容尚未
  稳定时，不以批量/并发测量、控制器完善或测试数增长代替产品进展。
- **默认做减法**：同时排查完整数据流各阶段的不合理信息损失和独立阻断，优先删除无贡献处理、合并
  重复筛选/校验/转换/重建，收拢同一事实和判断的多套表示。不要把旧代码一律当成必须
  保留的前提，再叠一层补丁；也不要以净减行数为目标做无关清理或整仓重写。
  排查以活动代码/数据流和具体处理为主线，失败材料只作反向核对与回归，不限定全部范围。
  模块分离不等于重复；不预设合并模块，来源选择/问题判断的既有合并未证明内容收益。
- **实施前明确替代关系**：在现有工作卡或简短说明中写明拟删除/合并的旧逻辑、实际消费者、
  必须保留的边界和预期报告收益。说明足够具体即可，不另造审批、文档或审计流程。
  仅重命名、搬文件、抽取包装函数，未减少重复处理或信息损失，不算完成减法。
- **增量属于有依据的例外**：只有已确认的共性阻断无法通过删减、合并或复用解决时，才
  增加最小必要逻辑；同时说明为何不能更简单、它替代什么或如何限制新增复杂度。
  不将每次失败直接转成新分支、提示约束、关键词/别名表、例外、兜底层或模型调用。
  不为通过单个案例硬编码答案、来源或阈值。
- **停止补丁循环**：连续局部修补仍无完整回答改善，或新规则持续增长时，先重新检查
  责任划分和更简单的数据流，不继续在同一机制上叠加例外。保留原失败和有效成果，
  无收益的候选只留可回滚记录，不自动成为下一层修补的永久基础。
- **区分必要校验与重复否决**：保留来源身份与正文绑定、引用未知语义、安全外呼、秘密
  脱敏、预算、CAS/fencing、恢复、事务及必要兼容性。节点之间因恢复或不可信输入而需要的
  校验不能凭相似代码删除；词法命中、结构分数等启发式也不能冒充事实支持或语义反证。
- **验证随改动聚焦**：用真实失败材料和有独立回归价值的测试证明删并前后的传递与边界；
  每个修复包先通过相关测试并冻结运行身份，再用一份未经手修的真实报告判断本轮收益；
  完整工程套件与契约要求的独立复核在交付前完成，涉及特定高风险契约时仍按其门槛执行。
  沿用已有效的验证，不为文档变化重跑全套，不堆测试数量或反复抽样代替质量进展。
- **按问题批次迭代**：先在已保存的诊断材料上固定输入，逐阶段列出全部可观察损失，
  区分来源不足、模型遗漏、代码过滤、引用未知和渲染损失；按已确认的共同原因组成有限的
  修复包。实施中只做固定输入回放、节点级和相关回归；不要每修一处就启动完整研究报告。
  同批不夹带无关猜测或逐题例外。一个修复包完成并冻结代码与运行身份后，在已有额度内
  **只运行一份**预先绑定的全新题完整报告，按原问题评审运行成功与回答质量；失败保留并
  用于下一包诊断，不自动补跑。Codex 时期用过的所有题、案例及改写只保留历史取证用途，
  不作下一轮内容验收或成功分母。一份通过只证明该题可用；要声明稳定性或跨场景能力，
  待单例可用后另定更广的样本与授权。工程全套与独立复核仍按交付契约完成；新一轮付费
  授权须明确单例运行数量、总额度、身份边界与停止线，范围内不逐次重复请示，最终24仍封存。
- **测试也要做减法**：测试数量臃肿属于当前精简范围。删除重复覆盖、仅复述实现细节、
  过时路径和无运行消费者的辅助代码所绑定的测试；可合并重复准备与无独立故障意义的参数。
  删前指出保留测试如何覆盖同一行为，保留有独立价值的安全/事实/恢复负例。不用大参数
  组合或重复端到端启动抬高数量，也不把参数藏进循环来制造数量下降；核对实际覆盖与耗时。
- **进度与时间如实报告**：分别说明工程状态和内容状态；仍主要是增量修补时应直接说明，
  不能称为已完成精简。旧十小时和八小时计划均已关闭，历史工时、失败与研究账本保留；
  不把旧余额或“持续授权”延续到下一轮。代码精简为主线，相关测试精简同包，不能另开
  测试数量专项。后续时间及付费额度按用户新委托明确，超限不自动续时。
  每个检查点简报已产出的用户结果、工程/内容分别达到什么程度、实耗时间和外呼成本、
  未解决阻断及下一动作；不要让多次“继续”只累积过程而看不见交付进度。

## Git safety

- Start every task with `git status --short --branch` and inspect the active branch.
- Preserve user changes. Do not discard, overwrite, reset, stash, amend, or rebase work unless explicitly requested.
- When handing work between agents or worktrees, verify each checkout's branch, HEAD, worktree
  status, and actual uncommitted changes. Treat `.git/info/*` and shared Git configuration as
  repository-wide state; keep test shims and virtual environments local to the owning worktree.
  Specify one integration owner and reconcile changes from an older worktree against the current
  base rather than assuming its branch or handoff text is current.
- Before judging ahead/behind or merge status, refresh remote refs when network access is available. If fetch fails, report that remote state is unverified.
- Do not delete branches, reflogs, tags, or `refs/backup/*`, and do not run `git gc` or `git prune`, without explicit approval.
- Do not push, force-push, merge to `main`, or create releases without explicit approval.
- A push is allowed only after a publication audit of the **entire outgoing commit range** against
  freshly fetched remote refs. Identify the exact remote, destination branch, base commit, and every
  outgoing commit; inspect each commit's changed paths and relevant contents, including files added
  and later deleted or renamed. A clean worktree, `.gitignore`, and the latest diff do not prove that
  earlier commits are safe to publish. If remote refs cannot be refreshed or the outgoing range
  cannot be established, do not push; report the unverified state.
- Push only files needed for the intended code, tests, required configuration, maintained user or
  runtime documentation, and minimal reviewed evaluation evidence. Do not push session handoffs,
  temporary plans, debugging diaries, raw reports or traces, generated outputs, caches, local
  environment files, credentials, personal material, or unrelated historical documents. Treat
  already-tracked files the same way; being tracked is not a reason to publish them.
- If any outgoing commit contains an unnecessary or questionable file, stop the push and show the
  path, commit, and reason to the user. Prepare a reviewable clean publication range while preserving
  the original local history; do not assume a later deletion removes a file from pushed history.
  Do not amend, rebase, reset, force-push, or discard commits to clean the range without explicit
  authorization. Re-audit the final range before the separately authorized push.
- Keep implementation, tests, and directly affected documentation in the same change. Prefer focused commits with conventional prefixes such as `fix:`, `feat:`, `test:`, `docs:`, or `chore:`.
- Every completed change must have a corresponding Git commit before handoff so it can be traced and rolled back. Do not leave completed work only in the working tree.
- Every behavior change must add or update the relevant automated tests. Before delivery, run the affected tests and the full validation suite; all tests and required checks must pass. A passing full-suite result remains valid if only documentation, comments, or recorded test results change afterward. If production code, public contracts, migrations, tests, or runtime conditions change, rerun the affected tests and the full validation suite. If validation cannot pass, do not present the change as complete.

## Architecture map

- API application and research routes: `src/deepchoice/server/app.py`
- Durable lifecycle service and coordinator: `src/deepchoice/services/tasks.py`, `src/deepchoice/runtime/`
- Product SQLite schema, records, and repositories: `src/deepchoice/persistence/`
- Phase 1 API/event contract and recovery runbook: `docs/phase1-runtime-contract.md`
- LangGraph orchestration, research nodes, and deterministic citation validation: `src/deepchoice/agents/orchestrator.py`
- Shared state contract: `src/deepchoice/state.py`
- Agent nodes: `src/deepchoice/agents/`
- Six-source retrieval and common result envelope: `src/deepchoice/retrievers/`
- Outbound routing, proxy, forwarding, probing, and audit: `src/deepchoice/outbound/`
- Clarification flow: `src/deepchoice/clarify/`
- Report rendering: `src/deepchoice/formats/`
- Streamlit frontend: `frontend/app.py`
- Offline evaluation: `benchmarks/`
- Automated tests: `tests/`

The normal research path is query analysis -> query adaptation -> multi-source retrieval -> source evaluation -> conflict detection -> evidence chains -> conclusion synthesis -> deterministic citation validation -> report generation -> self-review, with conditional retry routing in the orchestrator.

## Setup and commands

Use Python 3.11 or 3.12 in a project-local virtual environment. Python 3.13 is currently outside the supported range because the former global environment emitted a native `pyarrow` access-violation diagnostic during test discovery.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --reload
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

During implementation run the smallest relevant tests; run the full suite before delivery or when
a specific contract requires it earlier:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/path_to_test.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.codex-test-tmp
```

During implementation, keep validation focused on the current change. Freeze production code,
migrations, and tests before the final full-suite run; do not repeat an unchanged full suite merely
because documentation, comments, or the recorded result changed afterward.

The verified clean-environment baseline on 2026-09-15 is 1040 passed with no skips. Test counts are observations, not constants; update documentation only after collecting/running the current suite.

Benchmarks call paid/external services and can take several minutes per case. Do not run a benchmark batch unless the task explicitly requires it and API/network prerequisites are confirmed. Start with the health check:

```powershell
python -m benchmarks.run_baseline --health-check
```

## Configuration and secrets

- Never print, commit, rewrite, or expose `.env` values.
- DeepSeek tier: `DS_FLASH_API_KEY` or legacy `FLASH_API_KEY` / `DEEPSEEK_API_KEY`; optional model/base overrides use the corresponding `DS_FLASH_*`, `FLASH_*`, or `DEEPSEEK_BASE_URL` names.
- All LLM calls use the DeepSeek Flash tier, including synthesis, clarification and
  benchmark judges. Qwen `QW_FLASH_*`, `PRO_*` and `LLM_*` model/base/key variables are retired and
  must never supply fallback credentials to DeepSeek. The old `qwen-flash` call selector and
  `enable_thinking` argument remain compatibility adapters to DeepSeek, not a second provider.
- Search services: `TAVILY_API_KEYS` (comma-separated) or `TAVILY_API_KEY`; optional `GITHUB_TOKEN` and `STACKEXCHANGE_API_KEY`.
- Outbound routing: `OUTBOUND_CHANNELS`, `OUTBOUND_CHANNELS_COMMUNITY`,
  `OUTBOUND_CHANNELS_TAVILY`, `LOCAL_PROXY`, `FWD_BASE`, `FWD_KEY`, and `FWD_TARGETS`.
  Tavily must exclude `self-forward` because that transport does not preserve POST bodies.
- Runtime state: `CHROMA_PATH`, `LEARNED_DOCS_PATH`, `LEARNED_DOCS_READONLY`, `TAVILY_KEY_STATE_PATH`, `TAVILY_REPROBE`, and `RETRIEVAL_CACHE_ENABLED` (default `1`; set `0` to disable the retrieval cache).
- Concurrency/behavior: `LLM_DS_CONCURRENCY` (conflict scan gate, default 80)
  and `DEEPCHOICE_SYNTH_THINKING` (default 0). Requests explicitly disable DeepSeek thinking unless
  the synthesis option enables it. `LLM_QW_CONCURRENCY` is retired. Freeze native thinking parameters
  in new manifests; historical dual-provider runs remain readable but require a new compatible run.
- Frontend: `API_BASE`.

When adding a setting, update the code default, tests, README configuration section, and Docker configuration together.

## Implementation contracts

- Keep network access in retrievers routed through `deepchoice.outbound`; do not add ad-hoc direct clients that bypass channel selection and health reporting.
- Tavily route probing is a credential-free static HEAD. Its keypool POSTs in retrieval and benchmark health checks use the selected outbound client. The legacy artifact label
  `tavily_direct` does not mean direct routing is forced.
- Preserve the `BaseRetriever.search()` signature and the uniform source/status/results/error envelope.
- Retrieval failure must remain visible as failed or partial failure; do not convert external errors into silent empty success.
- Keep LLM calls in `utils/llm.py` or use its helpers so retry, deterministic settings, diagnostics, and token accounting remain consistent.
- Update `ResearchState` deliberately when adding node outputs, and cover routing/state changes with tests.
- Benchmark case and ground-truth changes affect reported metrics. Keep them separate from production refactors when practical and document the evaluation rationale.
- Before changing a dependency-facing wrapper or public port, inventory both current and deprecated entry points and any upstream deprecations. Keep required compatibility adapters covered by tests; do not silently remove them or broadly suppress unrelated warnings.

### Phase 3-2 retrieval cache

- Cache only successful retrieval results that pass the `RetrievalResult` contract and provenance validation. Do not cache failed, invalid, or oversized results.
- Use the product SQLite store with TTL. Cache keys are hashes over the normalized request, source, immutable run manifest identity, and cache-policy version; never persist plaintext requests in cache keys or cache metadata.
- Coalesce same-key in-flight retrievals within a run using process-local single-flight. Cache hits and coalesced waiters do not reserve `retrieval_calls` and do not create external-call Trace rows; only an actual outbound retrieval does.
- Bypass the cache for any execution without a `RunContext`. Preserve both `BaseRetriever.retrieve()` and the legacy `search()` interface.
- `RETRIEVAL_CACHE_ENABLED` defaults to `1`; setting it to `0` safely bypasses reads and writes. Pass it through Docker configuration. This cache is retrieval-only; do not add LLM response caching.

### Phase 1 durable runtime

- The Streamlit default path and full durable lifecycle contract use `/api/v1/tasks/*`. That is the only product interface: the one-version compatibility period for the old `POST /research`, `GET /research/*`, `GET /tasks/{task_id}` and `GET /history` paths ended on 2026-10-14 and those routes, their in-process task registry, their own SSE and the local snapshot store were removed. Do not reintroduce them or add new consumers to anything but `/api/v1/tasks/*`.
- Change task/latest-run state and append the corresponding `task_events` record through one repository transaction. API handlers, coordinators, and agents must not write lifecycle tables or events directly.
- Preserve CAS and fencing semantics: a losing task/run version check or stale `(lease_owner, execution_epoch)` must produce no state mutation, event, or checkpoint reference. Heartbeats renew ownership without user events.
- Treat lease acquisition and terminal finalization as cancellation-sensitive authority changes. Shutdown must let an in-flight acquisition settle, then fence/finalize any committed grant before propagating cancellation; never leave a committed `running` row merely because the caller was cancelled before receiving the grant.
- Keep task status aligned with its latest run. `interrupted` is recoverable and may resume the same compatible run; it is not an immutable terminal outcome. Failed/timed-out retries create a new run.
- Treat `RunManifest` as immutable run identity. Same-run resume must verify manifest identity plus workflow/state schema compatibility and use only a product-accepted checkpoint reference.
- Product task metadata and LangGraph checkpoint payloads stay in separate SQLite stores. Never infer product state by reading LangGraph private tables; back up and restore the two stores as a pair.
- Every new coordinator success or successful legacy import must commit its allowlisted public result, task/run terminal state, and completion event in one product-database transaction. Never publish a new successful terminal state without its queryable `run_results` artifact, and never copy private checkpoint state into that artifact. Pre-v6 successful rows are a read-only historical exception and return `TASK_RESULT_UNAVAILABLE` because no result can be reconstructed safely.
- The SQLite runtime is single-instance and single-worker. Keep the product-database instance lease and worker-count startup checks enabled; do not work around them to scale horizontally. Use an external queue/coordinator before adding workers or replicas.
- Phase 1 is a single-user trusted-network deployment: the durable APIs do not yet authenticate callers or enforce task ownership. Do not expose port 8000 directly to the public internet; require an authenticated reverse proxy for remote access, and add authentication plus tenant ownership before multi-user deployment.
- `task_events.event_id` is the global SSE cursor and `seq` is task-local. Public event data may contain status/node/reason and public identifiers/timestamps, but never lease owners, epochs, checkpoint IDs, manifest contents, raw exceptions, secrets, full state, or report bodies.
- `Last-Event-ID` replay must resync foreign, missing, or future cursors with a public task snapshot. Durable SSE must not depend on optional trace/observability writes.
- Migrations are append-only and forward-only. Never edit the name, SQL, or checksum of a committed migration; add a new migration, test upgrades from the previous schema, and rely on pre-deploy backups rather than destructive downgrade.
- Legacy snapshot import stays read-only, direct-child scoped, path/hash idempotent, conflict-preserving, and bounded by candidate count, I/O time, and file size. It runs after readiness as a managed background task. Never copy `_error`, reports, or full snapshot state into product events.
- Back up, verify, restore, and rehearse the product/checkpoint databases as one manifest-verified pair with `scripts/runtime_db.py`; restore requires a stopped service or maintenance mode and explicit confirmation.
- Any lifecycle, migration, concurrency, checkpoint, SSE, or compatibility change requires focused fault/concurrency tests, the full suite, an update to `docs/phase1-runtime-contract.md`, and independent review.

### Phase 2 observability and budget contracts

- `RunContext`、Trace/Budget DTO/Protocol 和 schema v8 骨架表是契约层产出；骨架表包括
  `run_budget_policies`、`node_attempts`、`external_calls`、`trace_events`、`budget_ledger`。
- New durable runs/retries must atomically freeze `standard-enforced-v1` and `unpriced-v1`.
  The standard hard limits are 60,000 total tokens, 96 LLM calls, 72 retrieval calls, and 900,000
  active milliseconds, with an 80% soft warning. Existing `standard-observe-v1` runs retain their
  frozen observe-only policy on same-run resume. Unknown prices remain unknown, never zero.
  Historical runs are not backfilled; their internal policy projection remains unavailable and the
  observability API must report that absence.
- Phase 2-B records default durable node attempts and LLM/retrieval external calls in the existing
  product-database Trace tables. Trace writes are best-effort and cannot change task state, results,
  or durable SSE correctness; `task_events` remains the sole lifecycle/SSE correctness path.
- `GET /api/v1/tasks/{task_id}/observability` returns only latest-run allowlisted node/call fields
  and aggregates from one product-database read snapshot that resolves `tasks.latest_run_id`, run
  status/epoch, policy, and Trace together. Calls include their safe node name and run-level node
  attempt ordinal; `retry_no` may be exposed only as a validated non-negative integer extracted
  from the request summary. Do not expose attempt/call IDs, epochs, lease owners, checkpoint
  references, manifest contents, raw exceptions, other request/result summaries, or report bodies.
  Read only the product SQLite database; never inspect LangGraph private checkpoint tables.
- Missing latest run, absent Trace, historical policy absence, and incomplete token usage must be
  explicit. Sum only known token fields, preserve unknown values as unknown (never zero), and report
  whether LLM token usage is complete. The Streamlit view falls back to snapshot panels when the
  endpoint errors or reports unavailable.
- Trace rows left `started` by recovery are projected as `interrupted` when their epoch is stale or
  the run itself is `interrupted`; current-epoch rows for other non-active runs are projected as
  `unknown`. Do not present stale/inconsistent started rows as actively running.
- Every default-path LLM retry, retriever source, and conflict evidence tool call must reserve its
  budget before dispatch. Reservation is an atomic bundle, is valid only for the current running
  lease owner/epoch, and must not oversubscribe under concurrency. Settlement and stale-reservation
  reconciliation remain append-only; missing or uncertain usage is charged conservatively as
  `unknown_spend`, never zero. Budget persistence failures fail closed and must not be swallowed by
  agent fallback logic. Trace remains best-effort and independent from this correctness path.
- The first enforced admission denial latches budget exhaustion for that run in serialized admission.
  A queued request that crossed the fast check but has not committed must recheck the latch and fail;
  reservations committed before the denial are not retroactively cancelled.
- On `RUN_BUDGET_EXCEEDED`, no further external call is allowed. A deterministic minimum-evidence
  gate may create a visibly restricted local report only with at least three undisputed usable
  chains, two distinct valid HTTP(S) hostnames, and one moderate/strong chain. This is structural
  sufficiency, not claim-level verification. The result, `completed_with_warnings` state, and event
  commit atomically; otherwise finalize failed with `BUDGET_EXCEEDED_INSUFFICIENT_EVIDENCE`.
- The observability API budget projection aggregates only the latest entry for each reservation and
  exposes configured limits, settled/unknown/reserved usage, remaining capacity, and soft/hard
  status. `admission_denied` is distinct from consumed spend reaching the limit: a next call may be
  rejected while some unusable remainder is still displayed. Never expose reservation/call IDs,
  execution epochs, summaries, or private errors.
- `RunManifest` remains schema v1 but now freezes `max_output_tokens` for each LLM call. Older v1
  manifests remain readable by historical identity and fail same-run compatibility safely.

### Phase 6-A security boundaries

- URL 外呼必须统一经过 `SafeUrlPolicy`/安全 fetch：只允许 HTTP(S)、端口仅 80/443、拒绝
  userinfo；DNS 解析后必须拒绝 loopback、private、link-local、reserved 和 multicast 地址，
  并在实际连接时固定到已验证的 direct IP（保留正确 Host/TLS SNI）。每一跳 redirect 都要
  重新执行完整策略和端口检查，并限制响应体大小、content-type、重定向次数与总耗时。
  无法证明安全的 proxy/forward 动态 URL 必须 fail closed。
- forward allowlist 必须按完整 hostname 精确匹配，或按显式 `*.example.com` 子域规则匹配；
  不能用字符串前缀代替 hostname 边界。
- 请求 body 的 admission 上限为 128 KiB；query、候选项、澄清文本、字段长度、候选数量和
  聚合输入必须分别受限。拒绝超限输入，不通过截断继续执行。
- 日志、结构化错误、Trace 与 LLM diagnostics 统一走集中脱敏。LLM diagnostics 只保留
  hash、length、usage 和 error type，不保存完整 prompt、响应、headers、URL 凭据或原始堆栈。
- 报告必须保留 Markdown 兼容输出，并由服务端生成经过 allowlist sanitizer 的 `report_html`；
  PDF 使用同一 sanitizer。前端不得把未清洗的报告正文放入 `unsafe_allow_html`。
- Phase 6-A 不包含认证/API key、rate limiting，也不声称所有静态 provider 已迁移到安全
  fetch；这些能力不在当前实施路线，除非后续明确重新修订范围。

### Phase 3-1 citation verification

- New runs freeze workflow `research-v3`, state schema v3, citation policy
  `deterministic-citation-v3`, and HITL policy `evidence-insufficient-v1`. Historical workflow v1/v2
  and citation-policy v1/v2 manifests remain readable and identity-valid, but are incompatible with
  same-run resume on the current runtime and must start a new run.
- Citation verification is deterministic and runs after conclusion synthesis and before report
  rendering; the sole evidence-insufficient HITL gate runs after citation verification and before
  report rendering. Do not add an LLM judge to the default path or describe lexical verification as
  semantic proof.
- If the recommendation choice remains supported but any model-authored action-plan field lacks a
  verified citation check, preserve the choice and replace the entire plan with the fixed isolated
  validation-only plan. Never present an unchecked operational procedure as an actionable proposal.
- The exact fixed validation-only plan generated by the deterministic safety boundary is not
  model-authored factual prose and is excluded from a second citation pass only when every field
  matches the built-in template. A forged mode or any non-matching plan remains fully checked.
  An uncited, evidence-unbound `unknown` requirement explanation records a gap rather than support;
  cited analysis beside an unknown remains subject to normal verification.
- Public citation status is limited to `verified`, `unsupported`, `unreachable`, and `unknown`.
  Temporary network, DNS, routing, proxy-safety, and cross-language uncertainty must remain
  `unknown`; they are not evidence that a claim is false.
- Dynamic citation URLs must use the bounded outbound safe-fetch path. Equivalent canonical URLs
  are fetched at most once per validation pass, each logical fetch reserves `http_calls` first, and
  no raw page body, exception, DNS/IP detail, or redirect trace may enter graph state or run results.
- Phase 3-1 stores its bounded checks and per-source projection in the immutable public run snapshot;
  it does not add a lifecycle table or treat verification warnings as task lifecycle events.

### Phase 5-1 versioned assets and offline evaluation

- The core asset registry is a small audit index, not a generalized prompt registry. Include only
  prompt hashes/versions used by the default workflow, `research-v3`, state schema v3, workflow
  nodes, citation/HITL policy versions, and the three report template versions. Never store prompt
  text or credentials in the registry.
- `smoke-v1` is a fixed 12-case fixture-replay suite: three cases each for query analysis, citation
  verification, conclusion post-processing, and report rendering. It must not call an LLM, judge, or
  network service. Its results validate deterministic code paths and fixture structure; they do not
  measure real-model semantic quality or live source availability.
- Evaluation artifacts must include the dataset ID/version/hash/freeze date, evaluation timestamp,
  case denominators, current manifest ID, core asset registry ID, and explicit source-health
  `not_run`/`degraded` status. Do not imply live sources were checked by fixture replay.
- Keep the historical 300-case benchmark and its dated metrics unchanged. Smoke-v1 results are a
  separate dataset and must not be merged with or compared as if they shared a denominator.
- Phase 5-1 does not include test-growth/default-path consistency audits; those belong to Phase 5-2.
  Real-case metric baselining and optimization, demonstrations, and the architecture/interview package
  are outside Phase 5 entirely and require a separately approved roadmap after engineering acceptance.

### Phase 5-2 engineering-foundation acceptance

- Phase 5-2 is an engineering acceptance pass, not final product-quality or interview acceptance.
  Review the durable default path across migrations, recovery, lifecycle, budget/Trace, citation
  verification, retrieval cache, HITL, security, SSE, and compatibility boundaries.
- Audit test-count growth, duplicate/low-value tests, dead code, deprecated upstream/public entry
  points, and documentation drift. Preserve tests that still carry distinct regression value; do not
  optimize for a smaller count.
- Run the complete CI and focused fault/recovery acceptance, obtain independent review, and record a
  concise engineering acceptance report plus residual-risk list.
- Do not run paid benchmarks, claim real-report quality, select interview demo cases, optimize key
  outcome metrics, or create interview/architecture presentation material in Phase 5-2.
- Completion means the repository is a reproducible engineering baseline ready for later real-case
  measurement and targeted optimization. It does not mean the product or interview package is final.

### Phase 4-1 single durable HITL decision gate

- Product schema v10 adds `hitl_decisions`. Migrations remain append-only and forward-only; never
  edit committed migrations. Decision data stays in the product SQLite store, separate from
  LangGraph checkpoint payloads.
- Only the `evidence-insufficient` gate is in scope. It can pause only when evidence is structurally
  insufficient and the recommendation is materially uncertain. It runs after citation verification
  and before report rendering; executions without `RunContext` bypass
  durable decisions.
- Supported actions are `provide_context` (required bounded supplemental text), `limited_report`
  (report from evidence already collected, clearly marked as restricted), and `cancel` (terminal,
  without graph resume). Supplemental text is untrusted context and must never enter public events,
  decision GET projections, or error details.
- A pending decision is bound internally to task/run, the accepted checkpoint reference, state schema,
  and pause fencing epoch. Public decision responses/events must not reveal checkpoint identity,
  execution epoch, lease owner, or supplemental text.
- Pausing atomically persists the decision and moves task/run to `waiting_for_input`, clears the lease
  and active deadline, and releases the execution slot. The decision expires after seven days; expiry
  atomically marks it expired and the waiting task/run cancelled. Startup/recovery must preserve
  pending decisions and resume only a valid resolved decision from its bound checkpoint.
- `GET /api/v1/tasks/{task_id}/decision` returns the latest public decision projection.
  `POST /api/v1/tasks/{task_id}/decisions/{decision_id}` resolves it using `If-Match` task-version
  CAS. Repeating the same resolution body is idempotent; a different body, stale task version,
  mismatched run/checkpoint, or expired decision conflicts/fails without resuming stale execution.
- Decision lifecycle events may expose only public status, decision ID/kind, reason, gaps, allowed
  actions, expiry, and action; never checkpoint/fencing identity, supplemental content, or private
  state.

### Phase 4-2 decision UI and recovery acceptance

- The Streamlit durable-task view displays only the public pending-decision projection: reason, evidence
  gaps, allowed actions, and expiry. It offers `provide_context`, `limited_report`, and `cancel`; every
  resolution sends the current task version in `If-Match`.
- On `waiting_for_input` / `decision.required`, end the current durable SSE response so the client does
  not hold a connection while awaiting the user. After resolution, reconnect from the last received
  `Last-Event-ID`; if replay requests resync, refresh the public task/decision snapshot before resuming
  the stream. Preserve the existing replay/resync behavior for all other task states.
- A retry after an uncertain submission must repeat the same action body. On a version/body conflict,
  refresh public state and require a new user action; do not silently rewrite or replay a different
  choice. Supplemental text may remain only in the user's input widget and the private session retry
  body while an outcome is uncertain; never copy it into public projections, events, logs, or errors.
  Never expose checkpoint identity, execution epoch, lease owner, manifest contents, or private state.
- Recovery acceptance must use separate real product and LangGraph checkpoint SQLite databases, a real
  `StateGraph`, and its checkpoint saver. Cover restart with a pending decision, same-body idempotency,
  conflicting resolution/version, seven-day expiry, cancellation without graph resume, and a valid
  resolution resuming the bound run exactly once from its accepted checkpoint.

### Current implementation scope

- Apply the high-priority subtraction-first rules above before choosing an implementation approach.
  Historical phase detail does not justify restoring an incremental patch loop.

- Read `docs/README.md` and `docs/agent-development-lessons.md` first, then `docs/current-roadmap.md`,
  `docs/product-effectiveness-optimization.md`, `docs/optimization-execution.md`, and
  `docs/o1-execution-status.md`. These own scope, quality criteria, work cadence, and actual state.
- The 2026-09-29 user direction is sustained overall selection quality and repeatability across
  supported scenarios. The former single-case/two-or-three-attempt stopping scope is retired;
  its failed/unassessed outcomes and closed run roots remain unchanged. Do not reactivate old
  12/24/48-run or concurrent protocols, and do not treat historical OPEN fields as authority.
- Optimize evidence relevance/completeness, conditional reasoning, decisive-source mapping and
  preservation of useful analysis through the report. Prefer simplifying low-value processing;
  permit evidence-backed local structural fixes. No case-answer hardcoding or cosmetic sampling.
- Separate runtime failures, critical content errors, evidence gaps and minor presentation issues.
  Test counts and lexical citation status do not prove report quality; useful conditional advice
  may pass without a unique Winner. Freeze case-specific expectations before observing outputs.
- `docs/product-effectiveness-optimization.md` defines content criteria; the next execution batch,
  sample size and budget have not been authorized or frozen. All Codex-used cases are historical only.
  `quality-selection-v1` is historical; its dataset, batch bindings and OPEN fields do not authorize
  current execution. New batch bindings must actually exist before execution; documentation is not
  proof of implementation.
  The actual cumulative research ledger and remaining resources live only in current status.
- Carry work within the current user request through without per-step permission requests.
  An explicit pause stops product repair, tests and report runs until resumed; a later
  documentation-only request authorizes only that document work. The former eight-hour round and
  paid research allocation are closed. Do not infer new paid admission from old continuous-authorization
  prose or remaining seconds on a historical card; freeze a newly authorized batch before admission.
- Use independent reviewers for final content acceptance, unexposed validation-case preparation
  and contract-required engineering review. Content/code review is read-only; case preparation
  writes only assigned evaluation materials. A document reorganization may receive one
  independent consistency review. Record exposure, disagreements and assistant-only limitations;
  do not claim human calibration. Default implementation stays focused rather than broadly delegated.
- Phase 3/4/5 and approved Phase 6-A engineering work is complete. Keep the durable/runtime,
  safety, budget and compatibility contracts; current version identities come from the checked-out
  manifest builder and maintained runtime contract. Phase-era version literals are historical
  snapshots, not instructions to downgrade the current workflow or asset policy.
- No new providers, multi-user auth/RBAC, rate limiting, distributed workers, external queues,
  PostgreSQL/Redis/OTel platforms, generalized billing, multi-gate HITL or default LLM judge.
  Validation packages and external career material remain deferred unless scope changes explicitly.
- Archive instructions and old qualifications are historical evidence. Open a specific archive
  only for a concrete fact; do not bulk-load historical roadmaps or session handoffs. Preserve
  immutable fixtures, machine-card hashes and original failure records. Notes hold local handoffs.
- New product measurements use durable APIs and frozen clean identities. Reuse compatible bounded
  preflight evidence; retrieval health alone does not validate LLM connectivity. Legacy direct-graph
  commands remain historical tools and cannot stand in for default-path quality acceptance.

## Local and generated data

`.env`, `outputs/`, `chroma_db/`, benchmark runs, model caches, `.pytest_cache/`, `.ruff_cache/`, `.claude/`, and `.superpowers/` may contain local state even when Git reports a clean tree. Do not delete, normalize, or commit them unless the task names the exact target. Test-created temporary directories must be removed after verification.

## Documentation discipline

- Do not copy a metric without its case set, measurement date, and denominator.
- Distinguish the 300-case 2026-08-31 benchmark from later small Qwen adaptation runs; their citation metrics are not directly comparable.
- When architecture, environment variables, endpoint counts, test results, or benchmark behavior changes, update `README.md` and the top `CHANGELOG.md` section in the same change.
- Use current commit IDs only as audit metadata, never as permanent prose that claims a branch has been pushed or merged.

### Documentation commits and publication

- Commit documentation for lasting project use: user/setup/configuration guides, maintained runtime
  contracts and runbooks, the current roadmap, concise acceptance reports and residual risks, and
  frozen evaluation protocols or minimal sanitized evidence needed to reproduce published claims.
  A document being useful to the current assistant session is not sufficient reason to commit it.
- Session handoffs, conversation-opening prompts, personal/interview planning, temporary task cards,
  debugging diaries and repeated execution logs stay in an ignored local area by default. Do not
  add them to `docs/`, stage them, or publish them unless the user explicitly requests repository
  inclusion. Keep raw reports, traces and generated artifacts local; publish only necessary,
  reviewed, sanitized summaries or fixtures under the applicable evaluation contracts.
- Prefer updating the relevant maintained document over adding one file per session, failure or
  implementation round. Record only the decisions, verified evidence and remaining risks needed by
  future maintainers; avoid duplicating the same timeline across multiple documents.
- Historical PRDs/designs may retain useful rationale. When archival is authorized, mark them as
  historical, identify the current source of truth and keep them outside the active documentation
  path where practical. Do not present excluded design space as approved implementation scope.
- Before committing, inspect the staged file list and documentation diff. For each added/changed
  document, check its intended reader, lasting maintenance/reproduction value, overlap with existing
  sources, and public suitability. Use explicit paths when staging; do not sweep local session
  material into a commit merely because it is under `docs/` or already tracked.
- The Git safety publication gate above applies to documents as well as code. A document must have
  lasting public value and a reviewed, sanitized purpose before it enters the outgoing range.
- Public documents must not expose credentials, private endpoints, raw provider errors/payloads,
  supplemental user input or unnecessary personal context. Retain required dataset/date/denominator
  and identity metadata for evidence; sanitization alone does not make every artifact worth publishing.
- This policy does not authorize deleting, moving, untracking or rewriting existing documents or
  commits. Existing-document cleanup requires a separately scoped user request; prefer a normal
  follow-up commit for authorized cleanup and never amend/rebase/force-push published history
  without explicit approval. If sensitive material was published, stop and request a separately
  approved remediation plan rather than treating an ordinary deletion as removal from history.
- A local documentation commit is not permission to push. Documentation-only policy changes require
  content/diff checks, not paid benchmarks or an unchanged full-suite rerun; preserve the existing
  validation requirements whenever runtime behavior, tests or public contracts also change.
