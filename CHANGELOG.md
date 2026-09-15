# Changelog

## [Unreleased] - 2026-09-15

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
- Phase 2-B default durable Trace recording for workflow node attempts and LLM/retrieval calls, plus a snapshot-consistent latest-run observability API with safe call-to-node/retry attribution and Streamlit panels for attempts, failures, durations, and known token usage
- Phase 2-C atomic fenced budget reservation and append-only settlement for LLM retries, retriever sources, conflict tools, and active runtime; conservative unknown-spend accounting; deterministic evidence-gated restricted reports; and budget usage/limit panels in the observability API and Streamlit
- Manifest-verified paired product/checkpoint database backup, restore, and restore-drill tooling
- Phase 6-A security boundary: SafeUrlPolicy with DNS/public-address and redirect revalidation, direct-IP pinning, bounded HTTP admission, forward hostname matching, centralized redaction, and sanitized report HTML/PDF output
- Phase 3-1 deterministic citation verification between synthesis and report rendering, with canonical-URL deduplication, bounded safe fetches, four honest public statuses, immutable result projection, and report/Streamlit warnings without an LLM judge
- Phase 3-2 retrieval-only SQLite TTL cache with manifest/policy-aware hashed keys, run-scoped single-flight, bounded expiry pruning, cache-before-Trace/budget behavior, Docker opt-out configuration, and preserved legacy retriever/API adapters
- Phase 4-1 single durable HITL decision gate on schema v10: research-v3/state v3 manifest policy, checkpoint/fencing-bound decisions, idempotent three-action resolution, seven-day expiry and recovery, with durable GET/resolve APIs; frontend acceptance remains pending

### Changed
- LLM routing uses DeepSeek flash for high-frequency work and Qwen flash for synthesis/re-arbitration, with deterministic controls and per-tier concurrency
- Official-document coverage is 96 seeded entries plus 131 learned entries (227 total at this snapshot)
- Supported Python range is 3.11/3.12; setup now uses a project-local virtual environment
- FastAPI and Streamlit minimums now select the verified compatible dependency generation
- Verified Python 3.12 test baseline is 986 passed with no skips on 2026-09-15
- Research startup now returns a `manifest_id`, and the same manifest is carried through the initial workflow state for auditability
- Multi-source retrieval validates stable result envelopes and converts contract violations into visible failed-source results
- Product persistence is kept separate from LangGraph checkpoints; migrations serialize concurrent runners and reject drift/future schemas safely
- Execution coordination is guarded by an explicit enable switch; product persistence stores checkpoint references while LangGraph checkpoint payloads remain in the checkpoint store
- Streamlit now uses `/api/v1/tasks/*` for task creation, durable events, result queries, cancellation, and resume; `/research` remains for one deprecated compatibility version and returns deprecation headers
- Legacy snapshot import runs after readiness as a managed background task with candidate-count, I/O-time, and file-size budgets
- The SQLite runtime now rejects known multi-worker settings and a second live instance through a renewable product-database lease; Docker is fixed to Python 3.12 and one worker
- Coordinator shutdown now settles an in-flight lease acquisition and fenced finalization before propagating cancellation, closing the commit-before-grant ghost-running race
- New durable runs and retries atomically freeze `standard-enforced-v1` and `unpriced-v1`; existing observe-only runs preserve their frozen policy on same-run resume. The standard limits are 60,000 total tokens, 96 LLM calls, 72 retrieval calls, and 900 seconds of active time with an 80% soft warning. Unknown prices and uncertain usage are never treated as zero
- Phase 2 observability reads only the product SQLite latest run and exposes allowlisted Trace and latest-reservation budget aggregates. Trace remains best-effort, while the budget gate fails closed. `RunManifest` remains schema v1 and now freezes each LLM call's maximum output tokens so older manifests fail incompatible resume safely
- Phase 6-A intentionally does not add authentication/API-key enforcement or rate limiting, and does not claim that every static provider has migrated to the safe-fetch path; those remain separate follow-up boundaries
- New runs use `research-v2` and state schema v2 with `deterministic-citation-v1`; historical `research-v1` manifests remain identity-readable but require a new run instead of incompatible same-run resume
- New runs use `research-v3` and state schema v3 with `deterministic-citation-v1` and `evidence-insufficient-v1`; historical v1/v2 manifests remain readable but require a new run instead of incompatible same-run resume
- Remaining implementation roadmap is narrowed to minimal Trace/budget, citation/cache, one HITL gate, and measurable project closeout; enterprise-only expansion is removed from the current Phase scope

### Fixed
- Scoped out Starlette 1.6.0's import-time `anyio.abc.BlockingPortal` deprecation warning until the already-corrected upstream code is released, without downgrading AnyIO or hiding unrelated warnings
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
