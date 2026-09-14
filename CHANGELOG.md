# Changelog

## [Unreleased] - 2026-09-09

### Added
- Nine-node research workflow, six-source retrieval, multilingual reports, observability, token accounting, and the outbound channel layer accumulated during the optimization cycle
- 300-case mixed benchmark and deterministic metric/quality tooling
- Project-level `AGENTS.md` with repository safety, architecture, configuration, testing, and documentation rules
- Dependency compatibility smoke test covering FastAPI, Starlette, Streamlit, and pyarrow imports
- Product requirements and technical design documents for the next engineering-hardening stage, including phased delivery, test, review, migration, and rollback boundaries
- Product-owner decisions for the standard runtime budget, evidence-dependent budget exhaustion behavior, seven-day HITL expiry, and non-loopback API-key enforcement
- Pydantic research request/start-response contracts and a structured public error envelope that retains the legacy `detail` field
- Immutable per-run manifests covering effective model tiers, LLM call parameters, prompt hashes, workflow/state schema, retriever versions, and report template version without persisting credentials or raw endpoints
- Versioned retriever request/result contracts and a stable `retrieve()` port, with the existing `search()` entry point retained for compatibility
- Phase 1-A task/run lifecycle contracts with strict status boundaries, retry-as-new-run semantics, and complete transition behavior tests
- Phase 1-B product SQLite migration foundation with transactional schema history and contract coverage
- Phase 1-C durable task/run repository, queue-only task API, stable keyset pagination, and lifecycle CAS contract coverage
- Phase 1-D execution control and recovery: fenced leases/heartbeats, startup recovery, cancellation/deadline precedence, epoch-isolated checkpoint writes, interrupted resume, retry-as-new-run, and durable checkpoint references
- Phase 1-E durable task events and compatibility closeout: transactional lifecycle events, SSE replay/resync with `Last-Event-ID`, idempotent legacy snapshot import, durable cancel/resume event history, legacy status adapters, and restart recovery coverage
- Phase 1-F integrated acceptance: cross-module lifecycle review, real historical-schema upgrades, concurrency/fault checks, durable runtime/API-event contracts, recovery runbook, and an explicit residual-risk register
- Forward-only product schema v5, preserving valid v4 legacy-import audit rows while enforcing imported/error task/run binding invariants and rolling back safely on invalid historical rows
- Phase 1-G durable default path: immutable run results, atomic result/success/event finalization, restart-readable report/snapshot/annotated/export APIs, Streamlit durable SSE replay/resync, and cancel/resume controls
- Forward-only product schema v6 for immutable public run results and v7 for the single-runtime-instance lease
- Phase 2-A RunContext, Trace/Budget DTO and Protocol contracts, plus the forward-only schema v8 skeleton for run budget policies, node attempts, external calls, trace events, and budget ledger
- Manifest-verified paired product/checkpoint database backup, restore, and restore-drill tooling

### Changed
- LLM routing uses DeepSeek flash for high-frequency work and Qwen flash for synthesis/re-arbitration, with deterministic controls and per-tier concurrency
- Official-document coverage is 96 seeded entries plus 131 learned entries (227 total at this snapshot)
- Supported Python range is 3.11/3.12; setup now uses a project-local virtual environment
- FastAPI and Streamlit minimums now select the verified compatible dependency generation
- Verified Python 3.12 test baseline is 815 passed with no skips on 2026-09-14
- Research startup now returns a `manifest_id`, and the same manifest is carried through the initial workflow state for auditability
- Multi-source retrieval validates stable result envelopes and converts contract violations into visible failed-source results
- Product persistence is kept separate from LangGraph checkpoints; migrations serialize concurrent runners and reject drift/future schemas safely
- Execution coordination is guarded by an explicit enable switch; product persistence stores checkpoint references while LangGraph checkpoint payloads remain in the checkpoint store
- Streamlit now uses `/api/v1/tasks/*` for task creation, durable events, result queries, cancellation, and resume; `/research` remains for one deprecated compatibility version and returns deprecation headers
- Legacy snapshot import runs after readiness as a managed background task with candidate-count, I/O-time, and file-size budgets
- The SQLite runtime now rejects known multi-worker settings and a second live instance through a renewable product-database lease; Docker is fixed to Python 3.12 and one worker
- Coordinator shutdown now settles an in-flight lease acquisition and fenced finalization before propagating cancellation, closing the commit-before-grant ghost-running race
- New durable runs and retries atomically freeze `standard-observe-v1` and `unpriced-v1`; unknown prices remain unknown rather than being treated as zero. Historical runs are not backfilled and retain an unavailable internal policy projection for future APIs to report honestly
- Phase 2-A does not yet write Trace events, expose Trace APIs, or enforce budget reservation/settlement/hard limits; those remain Phase 2-B/2-C. Durable `task_events` remains the sole task/SSE correctness path, and `RunManifest` stays v1

### Fixed
- Community retriever concurrency test now follows the production HTTP client timeout contract
- Isolated the project from the conflicting global Python 3.13 environment; `pip check` is clean and frontend observability tests no longer skip because of Streamlit/Starlette incompatibility
- Updated frontend streaming for current httpx timeout validation and kept Streamlit rerun control flow outside network-error handling

## [0.2.0] - 2026-07-19

### Added
- LangGraph checkpoint (AsyncSqliteSaver) — each node execution auto-saves to `outputs/checkpoints.db`, resume with same thread_id
- `astream_research_task()` — async generator using LangGraph native `astream(stream_mode="updates")` for real-time node-by-node progress
- `GET /research/{id}/checkpoints` — return full checkpoint execution history
- `get_state()` / `get_state_history()` — async methods on ChiefEditorAgent for checkpoint inspection
- `status` endpoint now reads from checkpoint (`aget_state`) instead of polling dict

### Changed
- SSE streaming switched from 0.3s polling state_proxy dict to LangGraph native `astream` events
- `load_dotenv()` moved before deepchoice imports — HF_HUB_OFFLINE and API keys now loaded before sentence_transformers initializes

### Fixed
- `retry_count` infinite loop — moved increment from conditional edge function (can't persist to checkpoint) to self_reviewer node return (proper state update)

### Dependencies
- Added `langgraph-checkpoint-sqlite>=2.0.0`, `aiosqlite`

## [0.1.0] - 2026-07-18

### Added
- Initial release: 7-agent LangGraph pipeline for tech selection
- 6 retrievers (Tavily, Chroma KB, GitHub, ArXiv, Community, Official)
- 3 report formats (what-why-how, evidence-first, comparison-matrix)
- Clarification module (mixed mode + soft gate)
- Streamlit frontend with dark theme
- 87 test cases, 91/91 passing
