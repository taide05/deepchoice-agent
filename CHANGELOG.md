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

### Changed
- LLM routing uses DeepSeek flash for high-frequency work and Qwen flash for synthesis/re-arbitration, with deterministic controls and per-tier concurrency
- Official-document coverage is 96 seeded entries plus 131 learned entries (227 total at this snapshot)
- Supported Python range is 3.11/3.12; setup now uses a project-local virtual environment
- FastAPI and Streamlit minimums now select the verified compatible dependency generation
- Verified Python 3.12 test baseline is 707 passed with no skips on 2026-09-14
- Research startup now returns a `manifest_id`, and the same manifest is carried through the initial workflow state for auditability
- Multi-source retrieval validates stable result envelopes and converts contract violations into visible failed-source results
- Product persistence is kept separate from LangGraph checkpoints; migrations serialize concurrent runners and reject drift/future schemas safely
- The new task API persists queued task/run records only; execution coordination remains planned for Phase 1-D

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
