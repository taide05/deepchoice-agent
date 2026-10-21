# Changelog

## [Unreleased] - 2026-10-21

### Added
- One outbound `safe_fetch_page` entry owns configuration-only direct-route selection, validated-IP pinning, redirects, total deadline and read-time limits; the official retriever no longer constructs its own HTTP client. Page attempts and dispatched HTTP requests (including redirects; no network probe is made) have separate cumulative caps.
- Official-fetch budgets are keyed by the existing `run_limits` research identity: re-entry within one research accumulates, a different research starts fresh, and client/transport construction failures do not consume a dispatched-request slot. `fetch_stats` is recorded in the official search envelope; the default graph currently retrieves once.
- Official source discovery now covers both declared candidates and decisive platform names extracted from constraints. It reuses the already-paid ordinary-search rows and curated/learned mappings before the existing LLM fallback; a URL must pass a host/path identity gate and the fetched page must name the same owner before it is citable. Multi-word names may concatenate into a host label or split across an owned vendor host and path; lookalike domains and URL-only identity do not pass. `source_owner`/`source_kind` are recorded on each official row.
- Official fallback LLM usage is captured through the existing `call_model(usage=...)` path and merged into `ResearchState["token_usage"]` by the retriever node. Source result rows and actual HTTP/page counters remain separate; missing HTTP counters stay unknown.
- A small offline case-sealing helper (`scripts/seal_case.py`) copies the complete prepared case into a new independent directory, records file/canonical/query hashes and the frozen evaluation environment, refuses to overwrite a seal, and can re-verify it after post-run notes are written elsewhere.
- Structural page-text extraction and prose admission for official pages; detected pure navigation/menu/login pages are navigation-only, while unusual low-link prose pages may still be misclassified (documented limitation). Source provenance now carries `body_url`, page/stored/input character counts and separate page/stored/input truncation flags into the source registry, synthesis and self-review.
- Strict six-item review accounting (`checks` must be six booleans covering item numbers 1-6 exactly once; `passed_count` must match, 0-6) with an explicit `review_status`/validation error and `passed_count=None` when the review is unavailable.

### Changed
- The confidence rationale is no longer overwritten with a pass-count summary. The substantive synthesis reason is retained; a usable review that changes the level appends a clearly separated adjustment note, and reviewer corrections to `confidence_rationale` take precedence. Failed, malformed or incomplete reviews cannot apply corrections or fabricate counts.
- Synthesis and self-review now share one evidence package and one total input budget (`EVIDENCE_INPUT_BUDGET_CHARS`, default 24,000 chars). Complete saved bodies are passed when the total fits; only an over-budget package selects bounded excerpts with recorded source ranges, omission markers and context/qualifier windows. The old per-source 1,600-character cut is removed.
- The run launcher explicitly freezes `LEARNED_DOCS_READONLY=1` and `RETRIEVAL_CACHE_ENABLED=0` so evaluation does not silently learn new mappings or read a mutable retrieval cache.

### Security
- Dynamic official fetches reject proxy/forward routes, private/multicast/reserved/NAT64/IPv4-mapped/Teredo/6to4 addresses, mixed DNS answers, unsafe redirects, missing/unsupported content types, non-identity compression, and over-limit bodies at read time. Each redirect is re-resolved and re-pinned to a validated address. `bytes_read` records bytes consumed from the stream (including the block that crosses the cap), while `bytes_retained` records the truncated bytes kept.

### Tests
- Test session blocks external DNS/TCP from session start (loopback services remain available); added negative coverage for pinning, redirect revalidation, total deadline, budgets/counts, compression rejection before decompression, research re-entry/isolation, client-construction accounting, candidate/platform source identity, lookalike-domain rejection, fallback token capture, full evidence inclusion and bounded excerpt ranges, seal copy/tamper verification, navigation/login pages, truncation propagation, item coverage/duplication, and strict confidence accounting.

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
