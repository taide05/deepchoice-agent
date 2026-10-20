# Changelog

## [Unreleased] - 2026-10-19

### Added
- Bounded official-page body fetch using the existing outbound route configuration, with a pinned-IP transport that preserves URL Host/TLS semantics. Page attempts and dispatched HTTP requests (including redirects; official route selection is configuration-only and makes no network probe) have separate cumulative caps and a recorded `fetch_stats` envelope.
- Structural page-text extraction and prose admission for official pages; detected pure navigation/menu/login pages are navigation-only, while unusual low-link prose pages may still be misclassified (documented limitation). Source provenance now carries `body_url`, page/stored/window character counts and separate page/stored/window truncation flags into the source registry, synthesis and self-review.
- Strict six-item review accounting (`checks` must be six booleans; `passed_count` must match, 0-6) with an explicit `review_status`/validation error and `passed_count=None` when the review is unavailable.

### Changed
- The confidence rationale is no longer overwritten with a pass-count summary. The substantive synthesis reason is retained; a usable review that changes the level appends a clearly separated adjustment note, and reviewer corrections to `confidence_rationale` take precedence. Failed, malformed or incomplete reviews cannot apply corrections or fabricate counts.
- The synthesis and self-review evidence window is one shared 1,600-character view, with page-extracted, stored-body and model-visible ranges kept distinct instead of treating a fully visible saved fragment as a whole page.

### Security
- Dynamic official fetches reject proxy/forward routes, private/multicast/reserved/NAT64/IPv4-mapped/Teredo/6to4 addresses, mixed DNS answers, unsafe redirects, missing/unsupported content types, and over-limit bodies at read time. Each redirect is re-resolved and re-pinned to a validated address.

### Tests
- Test session blocks external DNS/TCP from session start (loopback services remain available); added negative coverage for pinning, redirect revalidation, total deadline, budgets/counts, navigation/login pages, truncation propagation, and strict confidence accounting.

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
