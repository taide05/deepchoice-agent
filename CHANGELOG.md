# Changelog

## [Unreleased] - 2026-10-26

### Changed（2026-10-26，报告与证据修复）

- 报告短标题 + 原问题 context 行；内部重试检索式不再进入“尚未可知”；导航链接按候选过滤并限 6 条。
- 子问题固定 5 条（与澄清流程和检索预算一致），单例 Tavily 调用从约 11 次降到 6–7 次，运行时间
  从约 280 s 降到约 120–190 s。
- 官方来源：抓取上限恢复为每轮 4 页/12 HTTP/1 MiB；导航根页可跟随一跳更深的文档页；官方根页在
  结构化正文不足时可接受其正文段落（显式标记 `official_root_intro`）；补充正式题集所用技术名的
  78 个官方文档映射；短产品名（Vue/Koa/dbt/uv 等）可按精确名称解析映射。
- 无候选问题时使用综合结果的 ranked_options 展示候选并标注“推断”。
- 测试同步更新；没有改写历史报告、评分或已用额度，正式指标尚未运行。

### Fixed（2026-10-26 夜间，缺陷修复）

- 决策状态契约：模型自报 conditional、推荐文本有明确分支且点名 ≥2 个声明候选时，即使
  `ranked_options` 结构坏/选项带版本后缀，也用声明候选重建 options 并保持 conditional；不猜
  winner，其它 invalid 与 hold 不受影响（`bd9defe`）。
- arXiv 来源：非 ML/学术选型题跳过 arXiv（空来源、不发请求）；学术题只保留命中候选名/候选 token
  的论文。离线重放 200 例预计移除约 96.7% 已保存 arXiv 引用（`4ab2b85`）。
- 全 200 例复检：内部检索式泄漏与无关导航链接的真实数量均为 0；此前 2/12 是分析启发式误报，
  `analyze_batch.py` 指标定义已更正。
- 批跑服务：官方抓取预算改为 8 页/24 HTTP（仅批跑配置，产品默认仍 4/12/1 MiB），并记录进程级
  LLM/Tavily 总用量；逐例并发隔离未做。
- 金标评估（0 API）：冻结 30 例分层抽样与答案键；修复前基线可接受/条件命中 24/30。

### Changed
- 重写活动工作文档为当前 DSH 工作方式：`AGENTS.md`、`HANDOFF.md`、`README.md` 改为恢复线
  （`precodex/deepseek-adapter`、`/research`）的工作规则、当前能力状态与下一步目标
  （先产出一份可展示报告，再谈稳定性与小样本指标）。移除 Codex 时期的流程性要求与
  失效的入口/模型描述。
- CI 使用受支持的 Python 3.12；benchmark workflow 改为手动触发且不再断言旧指标下限
  （旧 300-case 数字只作历史归档）。
- 没有改动产品代码、测试、运行、报告、seal、数据库、learned_docs 或用户数据；历史指标
  保留原日期与分母，不作为当前版本成绩。

## [Unreleased] - 2026-10-21

### Added
- One outbound `safe_fetch_page` entry owns configuration-only direct-route selection, validated-IP pinning, redirects, total deadline and read-time limits; the official retriever no longer constructs its own HTTP client. Page attempts and dispatched HTTP requests (including redirects; no network probe is made) have separate cumulative caps.
- Official-fetch budgets are keyed by the existing `run_limits` research identity: re-entry within one research accumulates, a different research starts fresh, and client/transport construction failures do not consume a dispatched-request slot. `fetch_stats` is recorded in the official search envelope; the default graph currently retrieves once.
- Official source discovery now covers both declared candidates and decisive platform names extracted from constraints. It reuses the already-paid ordinary-search rows and curated/learned mappings before the existing LLM fallback; a URL must pass a host/path identity gate and, for non-curated learned/prior/fallback sources, the safe-fetched body must name the same owner before it is citable. Multi-word names may concatenate into a host label or split across an owned vendor host and path; lookalike domains, public-hosting user subdomains and URL-only identity do not pass. `source_owner`/`source_kind` are recorded on each official row.
- Official fallback LLM usage is captured through the existing `call_model(usage=...)` path and merged into `ResearchState["token_usage"]` by the retriever node. Source result rows and actual HTTP/page counters remain separate; missing HTTP counters stay unknown.
- Unified decision contract: `decision_status` distinguishes `recommended`, `conditional`, `insufficient_evidence` and invalid output; winner is present only for a supported recommendation. Removed automatic first-ranked-option fallback, constraint-fit winner override and renderer-side winner filling. Self-review can withdraw an unsupported recommendation into a hold (preserving candidate analysis/citations) but cannot replace the winner or turn invalid output into a valid hold. Historical records without the field render from existing winner only, without filling from ranked options.
- Decision-contract follow-up: withdrawal now removes citation bindings only for the replaced `recommendation`/`winner_rationale` fields and re-resolves citations in their new text through the existing binding entry; retained candidate analysis and trade-off citations stay. Decision normalization validates `ranked_options` structure before any len/traversal/render, and with an explicit candidate list requires exact candidate identity (case/whitespace-insensitive, symbols such as `C++`/`C#` preserved) for recommended winners and conditional options; malformed structures become invalid rather than crashing or filling a winner.
- A small offline case-sealing helper (`scripts/seal_case.py`) copies the complete prepared case into a new independent directory, records file/canonical/query hashes and the frozen evaluation environment, refuses to overwrite a seal, and can re-verify it after post-run notes are written elsewhere.
- A small paired comparison harness (`src/deepchoice/evaluation/simple_baseline.py`, default-offline `scripts/run_pair.py`) freezes shared evidence after retrieval/source scoring. The baseline runs deterministic evidence serialization, one synthesis and the existing citation/report rendering only; the candidate arm keeps conflict/evidence-chain/synthesis/self-review. Both arms use the same request, source bodies and evidence budget, with separate incremental token/quality records and shared retrieval counts.
- The real paired entry (`scripts/pair_worker.py` under `scripts/launch_pair.py`) performs one shared collection, saves its snapshot before any arm, and reuses `run_limits` plus the process guard for one 48-LLM/24-Tavily/1800-s total window (arms <=900 s each, shared remaining clock). Model authorization and supplemental search are separate; after freeze the candidate conflict tail cannot gather more evidence unless explicitly enabled. Source-envelope counts are named separately from dispatch-request counts; unverifiable retrieval HTTP totals stay unknown. Frozen source entry/number/body mismatches raise before model dispatch, and baseline synthesis, candidate synthesis, and self-review consumers are checked separately. Per-arm results are saved immediately so one failure does not discard the other original.
- Source acquisition now reuses retrieved document URLs before curated roots and model-proposed URLs; display titles need not equal the full candidate name, while candidate identity, page discussion and source authority remain separate checks. Comparative queries get one deterministic all-candidate coverage query, and candidate pages are attempted before platform-constraint pages.
- One bounded page read now owns both declared and unknown response lengths: an oversized `Content-Length` is streamed to the same cap and recorded as explicit truncation instead of a different hard-failure path. Extracted bodies contain prose paragraphs plus nearest heading context, not all visible navigation blocks; directory/link-dominated pages are navigation rather than capability evidence. Row-level source ownership/body-verification/fetch status travels through scoring, evidence chains, the shared package, synthesis/self-review rendering and coverage; URL words such as `docs.`/`readthedocs` no longer grant official authority, and same-URL snippet/navigation rows stay separate.
- Page extraction now treats the main region as content when one exists and keeps paragraphs plus lists, code/config blocks, tables/cells and nearest headings/qualifiers; navigation is excluded and a directory remains non-citable. The paired diagnostic launcher freezes 1 MiB retained response, 20,000 stored characters and 24,000 evidence-package characters, and the worker verifies the values actually loaded before `begin_run`. Successful, admission-rejected and transport-failed paths retain known bytes/declaration/truncation fields; unknown remains None.
- Structural page-text extraction and prose admission for official pages; detected pure navigation/menu/login pages are navigation-only, while unusual low-link prose pages may still be misclassified (documented limitation). Source provenance now carries `body_url`, page/stored/input character counts and separate page/stored/input truncation flags into the source registry, synthesis and self-review.
- Strict six-item review accounting (`checks` must be six booleans covering item numbers 1-6 exactly once; `passed_count` must match, 0-6) with an explicit `review_status`/validation error and `passed_count=None` when the review is unavailable.

### Changed
- The confidence rationale is no longer overwritten with a pass-count summary. The substantive synthesis reason is retained; a usable review that changes the level appends a clearly separated adjustment note, and reviewer corrections to `confidence_rationale` take precedence. Failed, malformed or incomplete reviews cannot apply corrections or fabricate counts.
- Synthesis and self-review now share one evidence package, one total input budget (`EVIDENCE_INPUT_BUDGET_CHARS`, default 24,000 chars) and one state-derived selection input including sub_questions. Complete saved bodies are passed when the total fits; only an over-budget package selects bounded excerpts and the serialized text plus omission markers stays within the budget, with recorded source ranges, omission markers and context/qualifier windows. The old per-source 1,600-character cut and the split selection input are removed, and no blind end-truncation is used.
- The run launcher explicitly sets `LEARNED_DOCS_READONLY=1` and `RETRIEVAL_CACHE_ENABLED=0` before imports so evaluation does not silently learn new mappings; the experimental tree currently has no additional retrieval-cache consumer, so the cache flag is a recorded freeze policy rather than measured cache behavior.

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
