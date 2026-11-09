# DeepChoice

**AI-powered tech-selection research agent** — give it a technology choice question and candidates, and it
retrieves evidence from multiple sources, compares them, and produces a readable, evidence-grounded report
that separates facts, inferences and unknowns.

[![CI](https://github.com/taide05/deepchoice-agent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/taide05/deepchoice-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2F3.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 中文简介

DeepChoice 是一个基于 Python / LangGraph 的技术选型深度研究 Agent。输入技术选型问题与候选技术后，
它从网页、官方文档、GitHub、arXiv、社区与本地知识库检索证据，完成来源评分、冲突仲裁、证据链组装，
生成带来源引用、区分事实/推断/未知的条件化报告，并在生成后自审。产品入口为 FastAPI 的
`POST /research`，配套 Streamlit 前端，支持进度流、历史记录与 Markdown/PDF 导出。

固定 200 例内部评测：完成 200/200，可用 199/200，决策级 179/200（内部 AI 辅助校准评审，非第三方验收；
详见 [EVALUATION.md](EVALUATION.md)）。

---

## Highlights

- **9-node LangGraph pipeline** — analyze → adapt → retrieve → score → detect conflicts → build evidence
  chains → synthesize → format → self-review.
- **Multi-source evidence** — web search, official documentation (with server-side extraction fallback),
  GitHub, arXiv, community sources and a local knowledge base; source failures and evidence conflicts are
  preserved instead of silently dropped.
- **Grounded reports** — sources are cited; facts, model inferences and unknowns are kept separate; when
  evidence is insufficient the report keeps an explicit gap and gives a conditional recommendation instead
  of inventing a conclusion.
- **Three report formats** — `what_why_how` (decision summary first), `evidence_first`, and a comparison
  matrix; Markdown / PDF export.
- **Operational features** — FastAPI backend, SSE progress stream, cancellation, history and snapshot
  queries, SQLite checkpointing, Streamlit frontend.
- **Reproducible evaluation harness** — fixed 200-case set, deterministic metrics and a documented
  evaluation protocol (see [EVALUATION.md](EVALUATION.md)).

## Architecture

```
                ┌───────────────────────────── FastAPI /research ─────────────────────────────┐
 query +        │  query_analyzer → query_adapter → multi_retriever → source_evaluator         │
 candidates ──▶ │      → conflict_detector → evidence_chain → conclusion_synthesizer           │
                │      → report_generator → self_reviewer                                     │
                └──────────────────────────────────────────────────────────────────────────────┘
                                   │                                          │
                         Markdown / PDF report                    SSE progress + history
```

| Node | Responsibility |
|---|---|
| `query_analyzer` | Parse the question, scene and candidates into a research task |
| `query_adapter` | Expand into sub-questions and retrieval queries |
| `multi_retriever` | Web / official docs / GitHub / arXiv / community / local KB |
| `source_evaluator` | Score sources and filter low-quality evidence |
| `conflict_detector` | Detect and arbitrate conflicting evidence |
| `evidence_chain` | Assemble claims with sources; mark unsupported claims |
| `conclusion_synthesizer` | Conditional recommendation, trade-offs, decision branches |
| `report_generator` | Render the chosen report format |
| `self_reviewer` | Check grounding, attribution, contradictions before delivery |

## Quick start

Requires **Python 3.11 / 3.12** and API credentials for an LLM endpoint and Tavily (the repo never stores keys).

```bash
git clone https://github.com/taide05/deepchoice-agent.git
cd deepchoice-agent
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # fill in your keys
```

Run the backend and the optional frontend:

```bash
# backend (default http://127.0.0.1:8000)
uvicorn deepchoice.server.app:app --host 127.0.0.1 --port 8000

# frontend (new terminal, Linux/macOS syntax; on Windows set $env:API_BASE first)
API_BASE=http://127.0.0.1:8000 streamlit run frontend/app.py
```

Start a research task:

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{
    "query": "We are choosing between Svelte and Vue for a new product. Compare them and tell us when to pick which.",
    "scene_context": "3-person team, no dedicated ops, fast launch matters.",
    "candidate_techs": ["Svelte", "Vue"],
    "constraints": ["3-person team", "fast launch", "limited budget"],
    "report_format": "what_why_how",
    "language": "en"
  }'
```

The response contains a `task_id`; poll `/research/{task_id}/status`, stream events from
`/research/{task_id}/stream`, and fetch the final report from `/research/{task_id}/report`.

### Key API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /research` | Start a research task |
| `GET /research/{task_id}/status` | Task status |
| `GET /research/{task_id}/stream` | SSE progress stream |
| `GET /research/{task_id}/report` | Final report (Markdown) |
| `GET /research/{task_id}/export?format=md\|pdf` | Export report |
| `GET /research/{task_id}/history`, `/snapshot` | History / snapshot |
| `POST /research/{task_id}/cancel` | Cancel a running task |
| `POST /clarify/start`, `/clarify/{sid}/message`, `/clarify/{sid}/finalize` | Optional pre-research clarification |
| `GET /health` | Health check |

## Configuration

All configuration is via environment variables (or a local `.env`, which is git-ignored).
See [`.env.example`](.env.example) for a template.

| Variable | Required | Description |
|---|---|---|
| `DS_FLASH_API_KEY` | yes | LLM endpoint key; aliases `FLASH_API_KEY` / `DEEPSEEK_API_KEY` accepted |
| `DS_FLASH_MODEL` / `DS_FLASH_BASE_URL` | no | Default `deepseek-v4-flash` / `https://api.deepseek.com/v1` |
| `TAVILY_API_KEYS` / `TAVILY_API_KEY` | yes | Web search / extraction; multiple keys comma-separated |
| `GITHUB_TOKEN` / `STACKEXCHANGE_API_KEY` | no | Higher rate limits for those sources |
| `LLM_DS_CONCURRENCY` | no | LLM concurrency limit (default 80) |
| `EVIDENCE_INPUT_BUDGET_CHARS` | no | Evidence budget per case (default 32,000) |
| `API_BASE` | frontend | Backend URL used by the Streamlit UI |
| `CHROMA_PATH` | no | Local knowledge-base path |
| `PRECODEX_LLM_MAX` / `PRECODEX_TAVILY_MAX` / `PRECODEX_WALL_MAX_S` | no | Local run stop lines (default 40 / 24 / 900) |
| `LEARNED_DOCS_READONLY` / `RETRIEVAL_CACHE_ENABLED` | no | Freeze knowledge-base writes / retrieval cache for evaluation runs |

## Evaluation

A fixed 200-case evaluation set is included in [`benchmarks/cases_formal_200.json`](benchmarks/cases_formal_200.json)
(200 cases across frontend/backend/database/infra/AI scenarios; Chinese and English inputs).

| Metric | Result |
|---|---|
| Completed | **200 / 200** |
| Usable† | **199 / 200** |
| Decision-grade‡ | **179 / 200** |
| Critical errors (C4) | **1 / 200** |

† A report is *usable* when it answers the question and contains no critical (decision-misleading) error.
‡ A report is *decision-grade* when it is usable and its key claims are evidence-comparable and conditions
are stated. Full protocol, definitions and limitations: [EVALUATION.md](EVALUATION.md).

> The numbers above are an **internal evaluation** (fixed set, fixed review protocol, AI-assisted calibrated
> content review). They are not a third-party audit or a human-signed acceptance record, and results should
> not be extrapolated beyond the fixed set. See [EVALUATION.md](EVALUATION.md) for methodology and residual risks.

## Known limitations

- Single-instance, trusted-network deployment: the API has no authentication or task ownership; do not expose
  it directly to the public internet.
- Citation `verified` means the page was reachable and passed lexical/citation checks — it does not validate
  model inferences or prove a deployment works.
- Official-doc fetching is bounded (page attempts, HTTP requests, response size, wall-clock deadline); sites
  that render content with JavaScript may only yield navigation pages. Such gaps stay visible in the retrieval
  record and the report.
- Evaluation quality depends on the review protocol; reported numbers are internal and fixed-set only.

## Repository layout

```
src/deepchoice/
├── agents/       # LangGraph nodes (analysis, retrieval, evaluation, synthesis, report, self-review)
├── retrievers/   # web / official docs / GitHub / arXiv / community / local KB
├── clarify/      # optional pre-research clarification
├── formats/      # report formats, citations, PDF export
├── server/       # FastAPI app + SSE
├── utils/        # LLM client, embeddings, evidence helpers
└── state.py      # ResearchState
frontend/         # Streamlit UI
benchmarks/       # evaluation cases and batch tooling
scripts/          # pair diagnostics / case sealing helpers
tests/            # test suite (pytest)
.github/          # CI workflows
```

## Development

```bash
pip install -e ".[dev]"
pytest -q                       # 902 tests
pyflakes src/ tests/            # static check (CI)
vulture src/                    # dead-code check (CI)
```

CI runs on Ubuntu (Python 3.12): install → `pytest -q` → `pyflakes` → `vulture`.

## License

MIT — see [LICENSE](LICENSE).
