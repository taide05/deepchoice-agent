# DeepChoice Agent Guide

This file is the project-level operating guide for AI coding assistants. It applies to the whole repository.

## Project and sources of truth

- DeepChoice is a Python/LangGraph research pipeline for evidence-backed technology selection.
- Treat the checked-out code, `pyproject.toml`, and executable tests as the primary source of truth.
- `README.md` describes the user-facing product. Benchmark figures in it are historical snapshots and must keep their dataset and date attached.
- Material under `D:\ai-career` is external career/project documentation. It is useful context, but it can lag behind this repository and must not override the current Git state or tests.
- Do not silently update resumes, interview material, or other external consumer documents while changing this repository. First establish and record the verified repository facts.

## Git safety

- Start every task with `git status --short --branch` and inspect the active branch.
- Preserve user changes. Do not discard, overwrite, reset, stash, amend, or rebase work unless explicitly requested.
- Before judging ahead/behind or merge status, refresh remote refs when network access is available. If fetch fails, report that remote state is unverified.
- Do not delete branches, reflogs, tags, or `refs/backup/*`, and do not run `git gc` or `git prune`, without explicit approval.
- Do not push, force-push, merge to `main`, or create releases without explicit approval.
- Keep implementation, tests, and directly affected documentation in the same change. Prefer focused commits with conventional prefixes such as `fix:`, `feat:`, `test:`, `docs:`, or `chore:`.
- Every completed change must have a corresponding Git commit before handoff so it can be traced and rolled back. Do not leave completed work only in the working tree.
- Every behavior change must add or update the relevant automated tests. Before delivery, run the affected tests and the full validation suite; all tests and required checks must pass. A passing full-suite result remains valid if only documentation, comments, or recorded test results change afterward. If production code, public contracts, migrations, tests, or runtime conditions change, rerun the affected tests and the full validation suite. If validation cannot pass, do not present the change as complete.

## Architecture map

- API application and research routes: `src/deepchoice/server/app.py`
- Durable lifecycle service and coordinator: `src/deepchoice/services/tasks.py`, `src/deepchoice/runtime/`
- Product SQLite schema, records, and repositories: `src/deepchoice/persistence/`
- Phase 1 API/event contract and recovery runbook: `docs/phase1-runtime-contract.md`
- LangGraph orchestration and nine-node workflow: `src/deepchoice/agents/orchestrator.py`
- Shared state contract: `src/deepchoice/state.py`
- Agent nodes: `src/deepchoice/agents/`
- Six-source retrieval and common result envelope: `src/deepchoice/retrievers/`
- Outbound routing, proxy, forwarding, probing, and audit: `src/deepchoice/outbound/`
- Clarification flow: `src/deepchoice/clarify/`
- Report rendering: `src/deepchoice/formats/`
- Streamlit frontend: `frontend/app.py`
- Offline evaluation: `benchmarks/`
- Automated tests: `tests/`

The normal research path is query analysis -> query adaptation -> multi-source retrieval -> source evaluation -> conflict detection -> evidence chains -> conclusion synthesis -> report generation -> self-review, with conditional retry routing in the orchestrator.

## Setup and commands

Use Python 3.11 or 3.12 in a project-local virtual environment. Python 3.13 is currently outside the supported range because the former global environment emitted a native `pyarrow` access-violation diagnostic during test discovery.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn deepchoice.server.app:app --reload
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

Run the smallest relevant test first, then the full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/path_to_test.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.codex-test-tmp
```

During implementation, keep validation focused on the current change. Freeze production code,
migrations, and tests before the final full-suite run; do not repeat an unchanged full suite merely
because documentation, comments, or the recorded result changed afterward.

The verified clean-environment baseline on 2026-09-14 is 815 passed with no skips. Test counts are observations, not constants; update documentation only after collecting/running the current suite.

Benchmarks call paid/external services and can take several minutes per case. Do not run a benchmark batch unless the task explicitly requires it and API/network prerequisites are confirmed. Start with the health check:

```powershell
python -m benchmarks.run_baseline --health-check
```

## Configuration and secrets

- Never print, commit, rewrite, or expose `.env` values.
- DeepSeek tier: `DS_FLASH_API_KEY` or legacy `FLASH_API_KEY` / `DEEPSEEK_API_KEY`; optional model/base overrides use the corresponding `DS_FLASH_*`, `FLASH_*`, or `DEEPSEEK_BASE_URL` names.
- Qwen tier: `QW_FLASH_API_KEY` or legacy `PRO_API_KEY` / `LLM_API_KEY`; optional model/base overrides use `QW_FLASH_*`, `PRO_*`, or `LLM_BASE_URL`.
- Search services: `TAVILY_API_KEYS` (comma-separated) or `TAVILY_API_KEY`; optional `GITHUB_TOKEN` and `STACKEXCHANGE_API_KEY`.
- Outbound routing: `OUTBOUND_CHANNELS`, `OUTBOUND_CHANNELS_COMMUNITY`, `LOCAL_PROXY`, `FWD_BASE`, `FWD_KEY`, and `FWD_TARGETS`.
- Runtime state: `CHROMA_PATH`, `LEARNED_DOCS_PATH`, `LEARNED_DOCS_READONLY`, `TAVILY_KEY_STATE_PATH`, and `TAVILY_REPROBE`.
- Concurrency/behavior: `LLM_DS_CONCURRENCY`, `LLM_QW_CONCURRENCY`, and `DEEPCHOICE_SYNTH_THINKING`.
- Frontend: `API_BASE`.

When adding a setting, update the code default, tests, README configuration section, and Docker configuration together.

## Implementation contracts

- Keep network access in retrievers routed through `deepchoice.outbound`; do not add ad-hoc direct clients that bypass channel selection and health reporting.
- Preserve the `BaseRetriever.search()` signature and the uniform source/status/results/error envelope.
- Retrieval failure must remain visible as failed or partial failure; do not convert external errors into silent empty success.
- Keep LLM calls in `utils/llm.py` or use its helpers so retry, deterministic settings, diagnostics, and token accounting remain consistent.
- Update `ResearchState` deliberately when adding node outputs, and cover routing/state changes with tests.
- Benchmark case and ground-truth changes affect reported metrics. Keep them separate from production refactors when practical and document the evaluation rationale.

### Phase 1 durable runtime

- The Streamlit default path and full durable lifecycle contract use `/api/v1/tasks/*`. `POST /research` remains a deprecated, separate in-memory compatibility path for one compatibility version; do not add new consumers to it.
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

### Phase 2-A observability/budget contracts

- `RunContext`、Trace/Budget DTO/Protocol 和 schema v8 骨架表是契约层产出；骨架表包括
  `run_budget_policies`、`node_attempts`、`external_calls`、`trace_events`、`budget_ledger`。
- New durable runs/retries must atomically freeze `standard-observe-v1` and `unpriced-v1`.
  Unknown prices remain unknown, never zero. Historical runs are not backfilled; their internal
  policy projection remains unavailable, and future telemetry/budget APIs must report that absence.
- Phase 2-A 尚未接入 node/call wrapper、Trace 写入/API、预算预留结算或硬限制；这些属于
  Phase 2-B/2-C。`task_events` 仍是任务状态与 SSE 的唯一正确性路径，`RunManifest` 保持 v1。

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

### Current implementation scope

- `docs/current-roadmap.md` is the source of truth for work after Phase 6-A. The broader technical
  design remains historical design space and must not be interpreted as authorized current scope.
- The current sequence is Phase 2-B, Phase 2-C, Phase 3, Phase 4, then Phase 5. Keep each remaining
  phase to at most two implementation PRs and prioritize the durable default path.
- Do not add excluded enterprise scope—multi-user auth/RBAC, rate limiting, distributed workers,
  external queues, PostgreSQL/Redis/OTel platforms, generalized billing, or multi-gate HITL—unless
  the roadmap is explicitly revised again.

## Local and generated data

`.env`, `outputs/`, `chroma_db/`, benchmark runs, model caches, `.pytest_cache/`, `.ruff_cache/`, `.claude/`, and `.superpowers/` may contain local state even when Git reports a clean tree. Do not delete, normalize, or commit them unless the task names the exact target. Test-created temporary directories must be removed after verification.

## Documentation discipline

- Do not copy a metric without its case set, measurement date, and denominator.
- Distinguish the 300-case 2026-08-31 benchmark from later small Qwen adaptation runs; their citation metrics are not directly comparable.
- When architecture, environment variables, endpoint counts, test results, or benchmark behavior changes, update `README.md` and the top `CHANGELOG.md` section in the same change.
- Use current commit IDs only as audit metadata, never as permanent prose that claims a branch has been pushed or merged.
