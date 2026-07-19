# Changelog

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
