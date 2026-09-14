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
- Every change must add or update the relevant automated tests. Before delivery, run the affected tests and the full validation suite; all tests and required checks must pass. If validation cannot pass, do not present the change as complete.

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

The verified clean-environment baseline on 2026-09-14 is 772 passed with no skips. Test counts are observations, not constants; update documentation only after collecting/running the current suite.

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

- The full durable lifecycle contract applies to `/api/v1/tasks/*`. `POST /research` remains a separate in-memory compatibility path until an explicit cutover; do not describe legacy-created or current Streamlit tasks as durable.
- Change task/latest-run state and append the corresponding `task_events` record through one repository transaction. API handlers, coordinators, and agents must not write lifecycle tables or events directly.
- Preserve CAS and fencing semantics: a losing task/run version check or stale `(lease_owner, execution_epoch)` must produce no state mutation, event, or checkpoint reference. Heartbeats renew ownership without user events.
- Treat lease acquisition and terminal finalization as cancellation-sensitive authority changes. Shutdown must let an in-flight acquisition settle, then fence/finalize any committed grant before propagating cancellation; never leave a committed `running` row merely because the caller was cancelled before receiving the grant.
- Keep task status aligned with its latest run. `interrupted` is recoverable and may resume the same compatible run; it is not an immutable terminal outcome. Failed/timed-out retries create a new run.
- Treat `RunManifest` as immutable run identity. Same-run resume must verify manifest identity plus workflow/state schema compatibility and use only a product-accepted checkpoint reference.
- Product task metadata and LangGraph checkpoint payloads stay in separate SQLite stores. Never infer product state by reading LangGraph private tables; back up and restore the two stores as a pair.
- `task_events.event_id` is the global SSE cursor and `seq` is task-local. Public event data may contain status/node/reason and public identifiers/timestamps, but never lease owners, epochs, checkpoint IDs, manifest contents, raw exceptions, secrets, full state, or report bodies.
- `Last-Event-ID` replay must resync foreign, missing, or future cursors with a public task snapshot. Durable SSE must not depend on optional trace/observability writes.
- Migrations are append-only and forward-only. Never edit the name, SQL, or checksum of a committed migration; add a new migration, test upgrades from the previous schema, and rely on pre-deploy backups rather than destructive downgrade.
- Legacy snapshot import stays read-only, direct-child scoped, path/hash idempotent, conflict-preserving, and bounded against malformed or oversized input. Never copy `_error`, reports, or full snapshot state into product events.
- Any lifecycle, migration, concurrency, checkpoint, SSE, or compatibility change requires focused fault/concurrency tests, the full suite, an update to `docs/phase1-runtime-contract.md`, and independent review.

## Local and generated data

`.env`, `outputs/`, `chroma_db/`, benchmark runs, model caches, `.pytest_cache/`, `.ruff_cache/`, `.claude/`, and `.superpowers/` may contain local state even when Git reports a clean tree. Do not delete, normalize, or commit them unless the task names the exact target. Test-created temporary directories must be removed after verification.

## Documentation discipline

- Do not copy a metric without its case set, measurement date, and denominator.
- Distinguish the 300-case 2026-08-31 benchmark from later small Qwen adaptation runs; their citation metrics are not directly comparable.
- When architecture, environment variables, endpoint counts, test results, or benchmark behavior changes, update `README.md` and the top `CHANGELOG.md` section in the same change.
- Use current commit IDs only as audit metadata, never as permanent prose that claims a branch has been pushed or merged.
