# DeepChoice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 7-node LangGraph pipeline that takes a tech selection question, searches 6 information sources, evaluates source quality via a rule engine, arbitrates conflicts, and generates evidence-backed reports.

**Architecture:** Linear StateGraph pipeline (QueryAnalyzer -> MultiRetriever -> SourceEvaluator -> ConflictDetector -> EvidenceChain -> ReportGenerator -> SelfReviewer) with conditional back-edges for retry on low confidence. FastAPI SSE streams progress; Streamlit renders the single-page UI.

**Tech Stack:** Python 3.11+, LangGraph, DeepSeek V4 (Flash + Pro), Chroma + bge-m3, FastAPI + sse-starlette, Streamlit, httpx, pytest, Pydantic

## Global Constraints

- Python 3.11+, all async I/O via httpx (not requests)
- DeepSeek V4 Flash for routine LLM nodes, V4 Pro for ConflictDetector only
- Rule engine (SourceEvaluator) uses pure Python — no LLM, no external API
- All retrievers return `{source, status, results, error, latency_ms}` uniform envelope
- Research snapshot saved as JSON before report rendering; reports rendered from snapshot
- SSE events: one `running` + one `done` per node, phase name matches node name
- Retry: max 1 full-pipeline retry, triggered only when confidence=low
- Report format selected at task entry (`task.report_format`), not post-hoc
- EvidenceChain outputs: every conclusion must have >=1 source URL + snippet
- No TBD, TODO, or placeholder code in any implementation step

---

## File Structure

```
deepchoice/
  pyproject.toml
  src/
    __init__.py
    state.py              # ResearchState TypedDict (12 fields)
    task.py               # TaskConfig Pydantic model + load_task()
    agents/
      __init__.py
      orchestrator.py     # ChiefEditorAgent: StateGraph build + compile + ainvoke
      query_analyzer.py   # 5-dim decomposition + scene detection (LLM)
      multi_retriever.py  # asyncio.gather 6 retrievers, uniform envelope
      source_evaluator.py # Rule engine 4-dim scoring (pure Python, no LLM)
      conflict_detector.py# Claim extraction + contradiction detection + arbitration (LLM)
      evidence_chain.py   # Conclusion->source mapping + evidence strength (pure Python)
      report_generator.py # Dispatch to format renderer by task.report_format
      self_reviewer.py    # 6-item checklist + confidence + gap detection (LLM)
    retrievers/
      __init__.py         # Retriever registry + dispatch map
      base.py             # Abstract base with uniform return envelope
      tavily_search.py    # Tavily Search API
      chroma_kb.py        # Local Chroma + bge-m3
      github_api.py       # GitHub REST API (repo search, releases)
      arxiv_api.py        # ArXiv Search API
      community.py        # StackExchange + Reddit search
      official.py         # PyPI JSON + GitHub README fetch
    formats/
      __init__.py
      what_why_how.py     # Default format: 是什么/为什么/怎么做 (10 sections)
      evidence_first.py   # Evidence-first format: conclusion up front (7 sections)
    server/
      __init__.py
      app.py              # FastAPI app + 6 endpoints
      sse.py              # SSE event stream per task_id
      snapshot_store.py   # JSON file CRUD for research snapshots
    utils/
      __init__.py
      llm.py              # call_model() — DeepSeek OpenAI-compatible wrapper
      views.py            # print_agent_output() — console logging
      dedup.py            # URL + content deduplication
  frontend/
    app.py                # Streamlit single-page (input + progress + report)
  tests/
    __init__.py
    conftest.py           # Shared fixtures (mock LLM responses, sample state)
    test_state.py
    test_source_evaluator.py
    test_evidence_chain.py
    test_dedup.py
    test_retrievers.py
    test_pipeline.py      # Full pipeline integration with mocked LLM
    test_eval.py          # LLM-as-Judge evaluation runner
    test_cases/
      known_cases.json    # 100 hand-reviewed cases with ground truth
      taxonomy.json       # 5 categories x 50 subdomains x 3 scenes x 3 difficulties
      generator.py        # Programmatic test case generator
  chroma_kb/
    setup.py              # KB initialization: embed + ingest documents
    data/
      official/           # Official docs (markdown)
      blogs/              # Technical blogs (markdown)
      papers/             # ArXiv papers (markdown)
  outputs/
    {task_id}/
      research_snapshot.json
      report.md
```

---

### Task 1: Project Scaffolding

**Owner:** AI skeleton (write full code, user reviews)

**Files:**
- Create: `deepchoice/pyproject.toml`
- Create: `deepchoice/src/__init__.py`
- Create: `deepchoice.agents/__init__.py`
- Create: `deepchoice.retrievers/__init__.py`
- Create: `deepchoice.formats/__init__.py`
- Create: `deepchoice.server/__init__.py`
- Create: `deepchoice.utils/__init__.py`
- Create: `deepchoice/tests/__init__.py`
- Create: `deepchoice/tests/conftest.py`
- Create: `deepchoice/frontend/__init__.py`

**Interfaces:**
- Produces: Project directory tree, `pyproject.toml` with all dependencies, empty `__init__.py` files

- [ ] **Step 1: Create pyproject.toml with all dependencies**

```toml
[project]
name = "deepchoice"
version = "0.1.0"
description = "Tech Selection Deep Research Agent"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "langchain-community>=0.3.0",
    "openai>=1.50.0",
    "httpx>=0.27.0",
    "pydantic>=2.0",
    "chromadb>=0.5.0",
    "sentence-transformers>=3.0.0",
    "fastapi>=0.115.0",
    "sse-starlette>=2.0.0",
    "uvicorn>=0.30.0",
    "streamlit>=1.38.0",
    "loguru>=0.7.0",
    "json-repair>=0.30.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-mock>=3.14.0",
]
```

- [ ] **Step 2: Create all __init__.py files**

Run:
```bash
mkdir -p D:/deepchoice-agent/src/agents
mkdir -p D:/deepchoice-agent/src/retrievers
mkdir -p D:/deepchoice-agent/src/formats
mkdir -p D:/deepchoice-agent/src/server
mkdir -p D:/deepchoice-agent/src/utils
mkdir -p D:/deepchoice-agent/tests/test_cases
mkdir -p D:/deepchoice-agent/frontend
mkdir -p D:/deepchoice-agent/chroma_kb/data/official
mkdir -p D:/deepchoice-agent/chroma_kb/data/blogs
mkdir -p D:/deepchoice-agent/chroma_kb/data/papers
mkdir -p D:/deepchoice-agent/outputs
```

Then create each `__init__.py` as empty file:
```bash
touch D:/deepchoice-agent/src/__init__.py
touch D:/deepchoice-agent/src/agents/__init__.py
touch D:/deepchoice-agent/src/retrievers/__init__.py
touch D:/deepchoice-agent/src/formats/__init__.py
touch D:/deepchoice-agent/src/server/__init__.py
touch D:/deepchoice-agent/src/utils/__init__.py
touch D:/deepchoice-agent/tests/__init__.py
touch D:/deepchoice-agent/frontend/__init__.py
```

- [ ] **Step 3: Create tests/conftest.py with shared fixtures**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def sample_task():
    return {
        "query": "LangGraph vs CrewAI for building AI agents",
        "scene_context": "solo",
        "constraints": ["python-only", "low-cost"],
        "report_format": "what_why_how",
    }


@pytest.fixture
def sample_state(sample_task):
    return {
        "task": sample_task,
        "sub_questions": [],
        "search_results": [],
        "source_scores": [],
        "conflicts": [],
        "evidence_chains": [],
        "report": "",
        "confidence": "",
        "knowledge_gaps": [],
        "retry_count": 0,
        "partial_failures": [],
        "current_phase": "",
    }


@pytest.fixture
def sample_search_results():
    return [
        {
            "source": "tavily",
            "status": "success",
            "results": [
                {
                    "url": "https://blog.langchain.dev/langgraph-vs-crewai/",
                    "title": "LangGraph vs CrewAI Comparison",
                    "snippet": "LangGraph offers more flexibility while CrewAI provides better DX...",
                    "date": "2026-05-15",
                },
                {
                    "url": "https://reddit.com/r/LangChain/comments/abc123",
                    "title": "CrewAI review after 3 months",
                    "snippet": "CrewAI is great for simple workflows but breaks down at scale...",
                    "date": "2026-04-20",
                },
            ],
            "error": None,
            "latency_ms": 1200,
        },
        {
            "source": "arxiv",
            "status": "success",
            "results": [
                {
                    "url": "https://arxiv.org/abs/2401.12345",
                    "title": "A Survey of Multi-Agent Orchestration Frameworks",
                    "snippet": "We compare LangGraph, CrewAI, AutoGen, and AutoGPT across 12 dimensions...",
                    "date": "2026-01-15",
                }
            ],
            "error": None,
            "latency_ms": 800,
        },
    ]


@pytest.fixture
def mock_call_model():
    """Mock LLM for deterministic agent tests."""
    mock = AsyncMock()
    mock.return_value = {"result": "mocked"}
    return mock
```

- [ ] **Step 4: Install dependencies and verify**

```bash
cd D:/deepchoice-agent && pip install -e ".[dev]"
```

Expected: all packages install without error.

- [ ] **Step 5: Commit**

```bash
git add deepchoice/
git commit -m "feat: scaffold DeepChoice project with pyproject.toml and directory tree
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: state.py + task.py

**Owner:** User (core architecture, interview-critical)

**Files:**
- Create: `deepchoice.state.py`
- Create: `deepchoice.task.py`
- Test: `deepchoice/tests/test_state.py`

**Interfaces:**
- Produces:
  - `ResearchState(TypedDict)` — 12 fields as defined below
  - `TaskConfig(BaseModel)` — Pydantic model with query, scene_context, constraints, report_format
  - `load_task(path: str) -> TaskConfig` — load task from JSON file

- [ ] **Step 1: Write state.py**

```python
from typing import TypedDict


class ResearchState(TypedDict):
    task: dict
    sub_questions: list[str]
    search_results: list[dict]
    source_scores: list[dict]
    conflicts: list[dict]
    evidence_chains: list[dict]
    report: str
    confidence: str
    knowledge_gaps: list[str]
    retry_count: int
    partial_failures: list[str]
    current_phase: str
```

- [ ] **Step 2: Write task.py**

```python
import json
from pathlib import Path
from pydantic import BaseModel, Field


class TaskConfig(BaseModel):
    query: str
    scene_context: str = "team"
    constraints: list[str] = Field(default_factory=list)
    report_format: str = "what_why_how"

    def model_post_init(self, __context):
        valid_scenes = {"solo", "team", "enterprise"}
        if self.scene_context not in valid_scenes:
            raise ValueError(f"scene_context must be one of {valid_scenes}")
        valid_formats = {"what_why_how", "evidence_first"}
        if self.report_format not in valid_formats:
            raise ValueError(f"report_format must be one of {valid_formats}")


def load_task(path: str) -> TaskConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaskConfig(**raw)
```

- [ ] **Step 3: Write test_state.py**

```python
import json
import tempfile
import pytest
from pathlib import Path
from deepchoice.state import ResearchState
from deepchoice.task import TaskConfig, load_task


class TestTaskConfig:
    def test_defaults(self):
        tc = TaskConfig(query="test query")
        assert tc.scene_context == "team"
        assert tc.constraints == []
        assert tc.report_format == "what_why_how"

    def test_invalid_scene_raises(self):
        with pytest.raises(ValueError, match="scene_context"):
            TaskConfig(query="test", scene_context="invalid")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="report_format"):
            TaskConfig(query="test", report_format="invalid")

    def test_load_task_from_file(self):
        data = {
            "query": "FastAPI vs Flask",
            "scene_context": "solo",
            "constraints": ["python", "async"],
            "report_format": "evidence_first",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            tc = load_task(path)
            assert tc.query == "FastAPI vs Flask"
            assert tc.scene_context == "solo"
            assert tc.report_format == "evidence_first"
        finally:
            Path(path).unlink()


class TestResearchState:
    def test_empty_state_has_all_fields(self):
        state = ResearchState(
            task={},
            sub_questions=[],
            search_results=[],
            source_scores=[],
            conflicts=[],
            evidence_chains=[],
            report="",
            confidence="",
            knowledge_gaps=[],
            retry_count=0,
            partial_failures=[],
            current_phase="",
        )
        assert len(state) == 12
        assert state["retry_count"] == 0
```

- [ ] **Step 4: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_state.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add deepchoice.state.py deepchoice.task.py deepchoice/tests/test_state.py
git commit -m "feat: add ResearchState TypedDict and TaskConfig model
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Utils (llm.py, views.py, dedup.py)

**Owner:** AI skeleton (adapt from P1, user reviews)

**Files:**
- Create: `deepchoice.utils/llm.py`
- Create: `deepchoice.utils/views.py`
- Create: `deepchoice.utils/dedup.py`
- Test: `deepchoice/tests/test_dedup.py`

**Interfaces:**
- Produces:
  - `async call_model(prompt: list[dict], model: str, response_format: str | None = None) -> dict | str`
  - `print_agent_output(output: any, agent: str = "AGENT") -> None`
  - `deduplicate_results(results: list[dict], threshold: float = 0.85) -> list[dict]`

- [ ] **Step 1: Write utils/llm.py (adapted from P1 llms.py)**

```python
import os
import json_repair
from openai import AsyncOpenAI
from langchain_core.utils.json import parse_json_markdown


DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_PRO_MODEL = "deepseek-v4-pro"


def _get_client() -> AsyncOpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def call_model(
    prompt: list[dict],
    model: str = DEFAULT_FLASH_MODEL,
    response_format: str | None = None,
) -> dict | str:
    client = _get_client()
    kwargs = {"model": model, "messages": prompt, "temperature": 0}
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content

    if response_format == "json":
        return parse_json_markdown(content, parser=json_repair.loads)
    return content
```

- [ ] **Step 2: Write utils/views.py**

```python
from datetime import datetime


def print_agent_output(output: any, agent: str = "AGENT") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{agent}] {output}")
```

- [ ] **Step 3: Write utils/dedup.py**

```python
from sentence_transformers import SentenceTransformer
import numpy as np

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model


def deduplicate_results(results: list[dict], threshold: float = 0.85) -> list[dict]:
    if len(results) <= 1:
        return results

    model = _get_model()
    snippets = [r.get("snippet", r.get("title", "")) for r in results]
    if not any(snippets):
        return results

    embeddings = model.encode(snippets)
    kept = []
    kept_embeddings = []

    for i, (result, emb) in enumerate(zip(results, embeddings)):
        is_dup = False
        for kept_emb in kept_embeddings:
            sim = np.dot(emb, kept_emb) / (np.linalg.norm(emb) * np.linalg.norm(kept_emb))
            if sim >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(result)
            kept_embeddings.append(emb)

    return kept
```

- [ ] **Step 4: Write test_dedup.py**

```python
from deepchoice.utils.dedup import deduplicate_results


class TestDedup:
    def test_empty_list(self):
        assert deduplicate_results([]) == []

    def test_single_result(self):
        results = [{"title": "Test", "snippet": "content"}]
        assert deduplicate_results(results) == results

    def test_duplicate_removed(self):
        results = [
            {"title": "A", "snippet": "LangGraph is a framework for building agents"},
            {"title": "B", "snippet": "LangGraph is a framework for building agents"},
            {"title": "C", "snippet": "Completely different topic here"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 2

    def test_all_unique(self):
        results = [
            {"title": "A", "snippet": "Python async programming guide"},
            {"title": "B", "snippet": "Rust memory safety explained"},
            {"title": "C", "snippet": "Kubernetes deployment tutorial"},
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 3
```

- [ ] **Step 5: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_dedup.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add deepchoice.utils/ deepchoice/tests/test_dedup.py
git commit -m "feat: add llm.py (DeepSeek wrapper), views.py, dedup.py utilities
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: source_evaluator.py (Rule Engine)

**Owner:** User (core architecture, interview-critical — "不用LLM的四维评分引擎")

**Files:**
- Create: `deepchoice.agents/source_evaluator.py`
- Test: `deepchoice/tests/test_source_evaluator.py`

**Interfaces:**
- Consumes: `research_state["search_results"]` — list of `{source, status, results: [{url, title, snippet, date}]}`
- Produces: `{"source_scores": list[dict]}` — each with `{url, source_type, scores: {authority, timeliness, consistency, verifiability}, total_score, evidence_type, rank}`

- [ ] **Step 1: Write the failing test for authority scoring**

```python
import pytest
from datetime import datetime, timedelta
from deepchoice.agents.source_evaluator import (
    SourceEvaluatorAgent,
    score_authority,
    score_timeliness,
    score_consistency,
    score_verifiability,
    compute_total_score,
)

class TestScoreAuthority:
    def test_official_docs_get_10(self):
        assert score_authority("official_doc") == 10

    def test_paper_gets_10(self):
        assert score_authority("arxiv_paper") == 10

    def test_well_known_blog_gets_7(self):
        assert score_authority("tech_blog") == 7

    def test_github_gets_6(self):
        assert score_authority("github") == 6

    def test_stackoverflow_gets_5(self):
        assert score_authority("stackoverflow") == 5

    def test_reddit_gets_4(self):
        assert score_authority("reddit") == 4

    def test_anonymous_gets_2(self):
        assert score_authority("anonymous") == 2

    def test_unknown_gets_4_default(self):
        assert score_authority("something_unknown") == 4


class TestScoreTimeliness:
    def test_less_than_3_months(self):
        recent = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        assert score_timeliness(recent) == 10

    def test_3_to_6_months(self):
        mid = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
        assert score_timeliness(mid) == 8

    def test_6_to_12_months(self):
        older = (datetime.now() - timedelta(days=270)).strftime("%Y-%m-%d")
        assert score_timeliness(older) == 6

    def test_1_to_2_years(self):
        old = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
        assert score_timeliness(old) == 4

    def test_over_2_years(self):
        ancient = (datetime.now() - timedelta(days=800)).strftime("%Y-%m-%d")
        assert score_timeliness(ancient) == 2

    def test_missing_date_defaults_5(self):
        assert score_timeliness(None) == 5
        assert score_timeliness("") == 5


class TestScoreConsistency:
    def test_two_sources_agree(self):
        assert score_consistency(["source_a", "source_b"]) == 10

    def test_one_source_only(self):
        assert score_consistency(["source_a"]) == 6

    def test_isolated_no_others(self):
        assert score_consistency([]) == 4

    def test_contradiction(self):
        assert score_consistency([], has_contradiction=True) == 2


class TestScoreVerifiability:
    def test_runnable_code(self):
        assert score_verifiability("code") == 10

    def test_benchmark_data(self):
        assert score_verifiability("benchmark") == 8

    def test_has_citations(self):
        assert score_verifiability("citation") == 6

    def test_pure_opinion(self):
        assert score_verifiability("opinion") == 2

    def test_unknown_default(self):
        assert score_verifiability("something_else") == 4


class TestComputeTotalScore:
    def test_weighted_formula(self):
        scores = {"authority": 10, "timeliness": 10, "consistency": 10, "verifiability": 10}
        total = compute_total_score(scores)
        assert total == 10.0

    def test_zero_scores(self):
        scores = {"authority": 0, "timeliness": 0, "consistency": 0, "verifiability": 0}
        total = compute_total_score(scores)
        assert total == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_source_evaluator.py -v
```

Expected: FAIL — module not found or functions not defined.

- [ ] **Step 3: Write source_evaluator.py implementation**

```python
from datetime import datetime, timedelta

# Weight configuration
WEIGHTS = {
    "authority": 0.35,
    "timeliness": 0.25,
    "consistency": 0.20,
    "verifiability": 0.20,
}

AUTHORITY_MAP = {
    "official_doc": 10,
    "arxiv_paper": 10,
    "tech_blog": 7,
    "github": 6,
    "stackoverflow": 5,
    "reddit": 4,
    "anonymous": 2,
}

VERIFIABILITY_MAP = {
    "code": 10,
    "benchmark": 8,
    "citation": 6,
    "opinion": 2,
}


def classify_source_type(url: str, source: str) -> str:
    url_lower = url.lower()
    if "arxiv.org" in url_lower:
        return "arxiv_paper"
    if "github.com" in url_lower:
        return "github"
    if "stackoverflow.com" in url_lower or "stackexchange.com" in url_lower:
        return "stackoverflow"
    if "reddit.com" in url_lower:
        return "reddit"
    if source == "official" or "readthedocs" in url_lower or "docs." in url_lower:
        return "official_doc"
    if source == "chroma":
        return "official_doc"
    if "blog" in url_lower or "medium.com" in url_lower or "dev.to" in url_lower:
        return "tech_blog"
    return "tech_blog"


def classify_evidence_type(snippet: str) -> str:
    snip_lower = snippet.lower()
    if any(kw in snip_lower for kw in ["```", "def ", "import ", "pip install", "npm install", "code example"]):
        return "code"
    if any(kw in snip_lower for kw in ["benchmark", "throughput", "latency", "rps", "accuracy", "f1 score", "tokens/s"]):
        return "benchmark"
    if any(kw in snip_lower for kw in ["according to", "cited by", "reference", "see also", "[1]", "[2]"]):
        return "citation"
    if any(kw in snip_lower for kw in ["i think", "in my opinion", "i prefer", "i like", "i believe"]):
        return "opinion"
    return "citation"


def score_authority(source_type: str) -> int:
    return AUTHORITY_MAP.get(source_type, 4)


def score_timeliness(date_str: str | None) -> int:
    if not date_str:
        return 5
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        age = (datetime.now() - d).days
        if age < 90:
            return 10
        if age < 180:
            return 8
        if age < 365:
            return 6
        if age < 730:
            return 4
        return 2
    except (ValueError, TypeError):
        return 5


def score_consistency(supporting_sources: list[str], has_contradiction: bool = False) -> int:
    if has_contradiction:
        return 2
    if len(supporting_sources) >= 2:
        return 10
    if len(supporting_sources) == 1:
        return 6
    return 4


def score_verifiability(evidence_type: str) -> int:
    return VERIFIABILITY_MAP.get(evidence_type, 4)


def compute_total_score(scores: dict[str, int]) -> float:
    return round(
        scores["authority"] * WEIGHTS["authority"]
        + scores["timeliness"] * WEIGHTS["timeliness"]
        + scores["consistency"] * WEIGHTS["consistency"]
        + scores["verifiability"] * WEIGHTS["verifiability"],
        1,
    )


class SourceEvaluatorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        all_results = []
        for channel in research_state.get("search_results", []):
            source = channel.get("source", "unknown")
            for r in channel.get("results", []):
                all_results.append({**r, "_source": source})

        source_scores = []
        for result in all_results:
            url = result.get("url", "")
            source = result.get("_source", "unknown")
            source_type = classify_source_type(url, source)
            evidence_type = classify_evidence_type(result.get("snippet", ""))

            scores = {
                "authority": score_authority(source_type),
                "timeliness": score_timeliness(result.get("date")),
                "consistency": score_consistency([url]),
                "verifiability": score_verifiability(evidence_type),
            }
            total = compute_total_score(scores)

            source_scores.append({
                "url": url,
                "title": result.get("title", ""),
                "source_type": source_type,
                "scores": scores,
                "total_score": total,
                "evidence_type": evidence_type,
                "supporting_sources": [],
                "contradicting_sources": [],
            })

        source_scores.sort(key=lambda x: x["total_score"], reverse=True)
        for i, s in enumerate(source_scores):
            s["rank"] = i + 1

        # Update consistency scores now that we have all scored results
        for s in source_scores:
            similar = [x["url"] for x in source_scores if x["url"] != s["url"] and x["total_score"] >= 6.0]
            s["supporting_sources"] = similar[:3]
            s["scores"]["consistency"] = score_consistency(similar)
            s["total_score"] = compute_total_score(s["scores"])

        source_scores.sort key=lambda x: x["total_score"], reverse=True)
        for i, s in enumerate(source_scores):
            s["rank"] = i + 1

        return {"source_scores": source_scores}
```

- [ ] **Step 4: Fix syntax error (missing parenthesis) and run tests**

Fix line `source_scores.sort key=lambda` to `source_scores.sort(key=lambda`:

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_source_evaluator.py -v
```

Expected: 17 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add deepchoice.agents/source_evaluator.py deepchoice/tests/test_source_evaluator.py
git commit -m "feat: add SourceEvaluator — rule engine 4-dim scoring, pure Python no LLM
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: query_analyzer.py

**Owner:** User (core architecture — 5-dim decomposition + scene detection)

**Files:**
- Create: `deepchoice.agents/query_analyzer.py`
- Test: `deepchoice/tests/test_query_analyzer.py` (integration test with mock LLM)

**Interfaces:**
- Consumes: `research_state["task"]` — dict with `query, scene_context, constraints, report_format`
- Produces: `{"sub_questions": list[str], "scene_context": str, "constraints": list[str]}`

- [ ] **Step 1: Write query_analyzer.py**

```python
from ..utils.llm import call_model
from ..utils.views import print_agent_output

DECOMPOSITION_PROMPT = """You are a technical research analyst. Decompose the user's technology selection question into 5 analysis dimensions.

User query: {query}
User context: {scene_context}
Known constraints: {constraints}

For EACH of these 5 dimensions, generate 1-2 specific sub-questions:
1. 功能 (Functionality): Feature coverage, API completeness, capability fit
2. 性能 (Performance): Throughput, latency, resource consumption
3. 生态 (Ecosystem): Community activity, plugins/extensions, documentation quality
4. 体验 (Developer Experience): Learning curve, debugging difficulty, productivity
5. 场景 (Scenario Fit): Applicability boundaries, anti-patterns, context match

Scene context classification:
- "solo": solo developer / startup (1-5 people) — prioritize simplicity, learning curve, cost
- "team": mid-size team (20-100 people) — prioritize reliability, ecosystem, team productivity
- "enterprise": large org (500+ people) — prioritize compliance, SLA, security, scalability

If the user's scene_context is "unspecified" or missing, default to "team".

Return ONLY a JSON object (no markdown, no explanation):
{{
  "sub_questions": ["q1", "q2", "..."],
  "scene_context": "solo|team|enterprise",
  "constraints": ["c1", "c2", "..."]
}}"""


class QueryAnalyzerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        task = research_state["task"]
        print_agent_output(f"Analyzing query: {task['query']}", agent="QUERY_ANALYZER")

        prompt = [{
            "role": "user",
            "content": DECOMPOSITION_PROMPT.format(
                query=task["query"],
                scene_context=task.get("scene_context", "unspecified"),
                constraints=", ".join(task.get("constraints", [])) or "none",
            ),
        }]

        result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")

        return {
            "sub_questions": result.get("sub_questions", []),
            "scene_context": result.get("scene_context", task.get("scene_context", "team")),
            "constraints": result.get("constraints", task.get("constraints", [])),
        }
```

- [ ] **Step 2: Write test_query_analyzer.py**

```python
import pytest
from unittest.mock import AsyncMock, patch
from deepchoice.agents.query_analyzer import QueryAnalyzerAgent


class TestQueryAnalyzer:
    @pytest.mark.asyncio
    async def test_decomposes_query_into_sub_questions(self):
        state = {
            "task": {
                "query": "FastAPI vs Flask for REST API",
                "scene_context": "solo",
                "constraints": ["python"],
                "report_format": "what_why_how",
            }
        }
        mock_response = {
            "sub_questions": [
                "FastAPI async performance vs Flask sync throughput comparison",
                "FastAPI auto-docs vs Flask plugin ecosystem",
                "FastAPI learning curve vs Flask simplicity for solo developer",
                "FastAPI Pydantic validation vs Flask Flask-RESTful flexibility",
                "FastAPI vs Flask deployment complexity on cloud platforms",
            ],
            "scene_context": "solo",
            "constraints": ["python"],
        }

        agent = QueryAnalyzerAgent()
        with patch("deepchoice.agents.query_analyzer.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent.run(state)

        assert len(result["sub_questions"]) >= 3
        assert result["scene_context"] == "solo"
        assert "python" in result["constraints"]

    @pytest.mark.asyncio
    async def test_defaults_scene_to_team_when_unspecified(self):
        state = {
            "task": {
                "query": "test",
                "scene_context": "unspecified",
                "constraints": [],
                "report_format": "what_why_how",
            }
        }
        mock_response = {"sub_questions": ["q1"], "scene_context": "team", "constraints": []}

        agent = QueryAnalyzerAgent()
        with patch("deepchoice.agents.query_analyzer.call_model", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent.run(state)

        assert result["scene_context"] == "team"
```

- [ ] **Step 3: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_query_analyzer.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add deepchoice.agents/query_analyzer.py deepchoice/tests/test_query_analyzer.py
git commit -m "feat: add QueryAnalyzer — 5-dim decomposition with scene context detection
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---


### Task 6: Retrievers (6 sources + multi_retriever dispatcher)

**Owner:** AI skeleton (write full code, user reviews — Tavily + Chroma + ArXiv deep, GitHub + Community + Official shallow)

**Files:**
- Create: `deepchoice.retrievers/base.py`
- Create: `deepchoice.retrievers/tavily_search.py`
- Create: `deepchoice.retrievers/chroma_kb.py`
- Create: `deepchoice.retrievers/github_api.py`
- Create: `deepchoice.retrievers/arxiv_api.py`
- Create: `deepchoice.retrievers/community.py`
- Create: `deepchoice.retrievers/official.py`
- Modify: `deepchoice.retrievers/__init__.py` (registry + dispatch)
- Create: `deepchoice.agents/multi_retriever.py`
- Test: `deepchoice/tests/test_retrievers.py`

**Interfaces:**
- Each retriever: `async def search(self, query: str, sub_questions: list[str], max_results: int = 7) -> dict` returning `{source, status, results: [{url, title, snippet, date}], error, latency_ms}`
- MultiRetriever: `async run(research_state: dict) -> dict` returning `{search_results: [...], partial_failures: [...]}`

- [ ] **Step 1: Write retrievers/base.py — abstract base with uniform envelope**

```python
import time


class BaseRetriever:
    source: str = "base"

    async def search(self, query: str, sub_questions: list[str], max_results: int = 7) -> dict:
        t0 = time.monotonic()
        try:
            results = await self._do_search(query, sub_questions, max_results)
            return {
                "source": self.source,
                "status": "success",
                "results": results,
                "error": None,
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }
        except Exception as e:
            return {
                "source": self.source,
                "status": "failed",
                "results": [],
                "error": str(e),
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        raise NotImplementedError
```

- [ ] **Step 2: Write retrievers/tavily_search.py**

```python
import os
import httpx
from .base import BaseRetriever


class TavilySearch(BaseRetriever):
    source = "tavily"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        api_key = os.environ.get("TAVILY_API_KEY", "")
        queries = [query] + sub_questions[:2]

        async with httpx.AsyncClient(timeout=15) as client:
            all_results = []
            for q in queries:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": q,
                        "search_depth": "basic",
                        "max_results": max(3, max_results // len(queries)),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                for r in data.get("results", []):
                    all_results.append({
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("content", ""),
                        "date": r.get("published_date", ""),
                    })
            return all_results[:max_results]
```

- [ ] **Step 3: Write retrievers/chroma_kb.py**

```python
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from .base import BaseRetriever


class ChromaKB(BaseRetriever):
    source = "chroma"

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path="./deepchoice/chroma_kb/chroma_db",
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection("tech_kb")
        self.model = SentenceTransformer("BAAI/bge-m3")

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        queries = [query] + sub_questions[:2]
        all_results = []
        seen_urls = set()

        for q in queries:
            q_embedding = self.model.encode(q).tolist()
            results = self.collection.query(
                query_embeddings=[q_embedding],
                n_results=max(3, max_results // len(queries)),
            )
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                metadata = results.get("metadatas", [[]])[0][i]
                url = metadata.get("url", doc_id) if metadata else doc_id
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append({
                    "url": url,
                    "title": metadata.get("title", "") if metadata else "",
                    "snippet": (results.get("documents", [[]])[0][i] or "")[:500],
                    "date": metadata.get("date", "") if metadata else "",
                })
        return all_results[:max_results]
```

- [ ] **Step 4: Write retrievers/github_api.py (shallow)**

```python
import httpx
from .base import BaseRetriever


class GitHubSearch(BaseRetriever):
    source = "github"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.lower().replace(" vs ", " ").replace(" versus ", " ").split()
        stopwords = {"for", "and", "or", "in", "the", "a", "of", "to", "with", "using", "building"}
        repos = [w for w in keywords if w not in stopwords]

        results = []
        async with httpx.AsyncClient(timeout=15) as client:
            for repo_name in repos[:3]:
                resp = await client.get(
                    "https://api.github.com/search/repositories",
                    params={"q": repo_name, "sort": "stars", "per_page": 3},
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("items", [])[:2]:
                    results.append({
                        "url": item.get("html_url", ""),
                        "title": item.get("full_name", ""),
                        "snippet": (
                            f"Stars: {item.get('stargazers_count', 0)}, "
                            f"Forks: {item.get('forks_count', 0)}, "
                            f"Updated: {item.get('updated_at', '')}"
                        ),
                        "date": item.get("updated_at", ""),
                    })
        return results[:max_results]
```

- [ ] **Step 5: Write retrievers/arxiv_api.py**

```python
import httpx
import xml.etree.ElementTree as ET
from .base import BaseRetriever


class ArxivSearch(BaseRetriever):
    source = "arxiv"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.replace(" vs ", " ").replace(" versus ", " ")[:200]
        url = (
            f"https://export.arxiv.org/api/query"
            f"?search_query=all:{keywords}&max_results={max_results}&sortBy=relevance"
        )

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        results = []
        for entry in root.findall("atom:entry", ns)[:max_results]:
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            link_el = entry.find("atom:id", ns)
            published_el = entry.find("atom:published", ns)
            results.append({
                "url": link_el.text.strip() if link_el is not None else "",
                "title": title_el.text.strip() if title_el is not None else "",
                "snippet": (summary_el.text or "")[:500].strip() if summary_el is not None else "",
                "date": (published_el.text or "")[:10] if published_el is not None else "",
            })
        return results
```

- [ ] **Step 6: Write retrievers/community.py (shallow)**

```python
import httpx
from .base import BaseRetriever


class CommunitySearch(BaseRetriever):
    source = "community"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.replace(" vs ", " ").replace(" versus ", " ")[:150]
        results = []

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.stackexchange.com/2.3/search",
                params={
                    "q": keywords, "site": "stackoverflow",
                    "pagesize": max(2, max_results // 2),
                    "order": "desc", "sort": "votes",
                },
            )
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    results.append({
                        "url": item.get("link", ""),
                        "title": item.get("title", ""),
                        "snippet": f"Score: {item.get('score', 0)}",
                        "date": item.get("creation_date", ""),
                    })

            resp2 = await client.get(
                "https://www.reddit.com/search.json",
                params={"q": keywords, "limit": max(2, max_results // 2)},
                headers={"User-Agent": "DeepChoice/0.1"},
            )
            if resp2.status_code == 200:
                for item in resp2.json().get("data", {}).get("children", []):
                    d = item["data"]
                    results.append({
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "title": d.get("title", ""),
                        "snippet": f"r/{d.get('subreddit', '')}, Score: {d.get('score', 0)}",
                        "date": d.get("created_utc", ""),
                    })
        return results[:max_results]
```

- [ ] **Step 7: Write retrievers/official.py (shallow)**

```python
import httpx
from .base import BaseRetriever


class OfficialSearch(BaseRetriever):
    source = "official"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int) -> list[dict]:
        keywords = query.lower().replace(" vs ", " ").split()
        results = []

        async with httpx.AsyncClient(timeout=15) as client:
            for kw in keywords[:3]:
                if len(kw) < 3:
                    continue
                resp = await client.get(f"https://pypi.org/pypi/{kw}/json")
                if resp.status_code != 200:
                    continue
                info = resp.json().get("info", {})
                results.append({
                    "url": info.get("package_url", f"https://pypi.org/project/{kw}/"),
                    "title": f"{kw} (PyPI)",
                    "snippet": f"Version: {info.get('version', 'N/A')}, Summary: {info.get('summary', '')}",
                    "date": "",
                })
        return results[:max_results]
```

- [ ] **Step 8: Write retrievers/__init__.py — registry**

```python
from .tavily_search import TavilySearch
from .chroma_kb import ChromaKB
from .github_api import GitHubSearch
from .arxiv_api import ArxivSearch
from .community import CommunitySearch
from .official import OfficialSearch

RETRIEVER_REGISTRY = {
    "tavily": TavilySearch,
    "chroma": ChromaKB,
    "github": GitHubSearch,
    "arxiv": ArxivSearch,
    "community": CommunitySearch,
    "official": OfficialSearch,
}

__all__ = [
    "TavilySearch", "ChromaKB", "GitHubSearch",
    "ArxivSearch", "CommunitySearch", "OfficialSearch",
    "RETRIEVER_REGISTRY",
]
```

- [ ] **Step 9: Write agents/multi_retriever.py**

```python
import asyncio
from ..retrievers import RETRIEVER_REGISTRY
from ..utils.views import print_agent_output


class MultiRetrieverAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        query = research_state["task"]["query"]
        sub_questions = research_state.get("sub_questions", [])
        print_agent_output(f"Searching 6 sources for: {query}", agent="MULTI_RETRIEVER")

        tasks = []
        for name, cls in RETRIEVER_REGISTRY.items():
            retriever = cls()
            tasks.append(retriever.search(query, sub_questions))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        search_results = []
        partial_failures = []
        for name, result in zip(RETRIEVER_REGISTRY.keys(), raw_results):
            if isinstance(result, Exception):
                search_results.append({
                    "source": name, "status": "failed",
                    "results": [], "error": str(result), "latency_ms": 0,
                })
                partial_failures.append(name)
            else:
                search_results.append(result)
                if result["status"] == "failed":
                    partial_failures.append(name)

        return {"search_results": search_results, "partial_failures": partial_failures}
```

- [ ] **Step 10: Write test_retrievers.py**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from deepchoice.retrievers.tavily_search import TavilySearch
from deepchoice.agents.multi_retriever import MultiRetrieverAgent


class TestTavilySearch:
    @pytest.mark.asyncio
    async def test_returns_uniform_envelope(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [{
                "url": "https://example.com", "title": "Test",
                "content": "Snippet", "published_date": "2026-01-01",
            }]
        }
        retriever = TavilySearch()
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await retriever.search("test query", [])
        assert result["source"] == "tavily"
        assert result["status"] == "success"
        assert len(result["results"]) > 0

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        retriever = TavilySearch()
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = Exception("API timeout")
            result = await retriever.search("test query", [])
        assert result["status"] == "failed"


class TestMultiRetriever:
    @pytest.mark.asyncio
    async def test_aggregates_all_sources(self):
        state = {
            "task": {"query": "test", "scene_context": "solo", "constraints": [], "report_format": "what_why_how"},
            "sub_questions": [],
        }

        class MockRetriever:
            source = "mock"
            async def search(self, query, sub_questions, max_results=7):
                return {"source": self.source, "status": "success", "results": [], "error": None, "latency_ms": 100}

        agent = MultiRetrieverAgent()
        with patch("deepchoice.agents.multi_retriever.RETRIEVER_REGISTRY") as mock_registry:
            mock_registry.items.return_value = [("mock1", MockRetriever), ("mock2", MockRetriever)]
            result = await agent.run(state)
        assert len(result["search_results"]) == 2
```

- [ ] **Step 11: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_retrievers.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 12: Commit**

```bash
git add deepchoice.retrievers/ deepchoice.agents/multi_retriever.py deepchoice/tests/test_retrievers.py
git commit -m "feat: add 6 retrievers (Tavily, Chroma, GitHub, ArXiv, Community, Official) + MultiRetriever dispatch

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: evidence_chain.py

**Owner:** User (core architecture — pure Python assembly, no LLM)

**Files:**
- Create: `deepchoice.agents/evidence_chain.py`
- Test: `deepchoice/tests/test_evidence_chain.py`

**Interfaces:**
- Consumes: `research_state["source_scores"]`, `research_state["conflicts"]`
- Produces: `{"evidence_chains": list[dict]}` — each: `{conclusion, sources: [{url, snippet, score}], evidence_strength: strong|moderate|weak, disputed: bool}`

- [ ] **Step 1: Write evidence_chain.py**

```python
from ..utils.views import print_agent_output


def build_evidence_chain(source_scores: list[dict], conflicts: list[dict]) -> list[dict]:
    disputed_urls = set()
    for c in conflicts:
        disputed_urls.add(c.get("source_a", {}).get("url", ""))
        disputed_urls.add(c.get("source_b", {}).get("url", ""))

    chains = []
    for s in source_scores:
        if s["total_score"] < 4.0:
            continue

        evidence_sources = [{
            "url": s["url"],
            "title": s.get("title", ""),
            "snippet": s.get("snippet", ""),
            "score": s["total_score"],
        }]

        if s["total_score"] >= 8.0 and len(s.get("supporting_sources", [])) >= 1:
            strength = "strong"
        elif s["total_score"] >= 6.0:
            strength = "moderate"
        else:
            strength = "weak"

        disputed = s["url"] in disputed_urls
        chains.append({
            "conclusion": s.get("title", "Key finding"),
            "sources": evidence_sources,
            "evidence_strength": strength,
            "disputed": disputed,
        })
    return chains


class EvidenceChainAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        conflicts = research_state.get("conflicts", [])
        print_agent_output(
            f"Building evidence chains from {len(source_scores)} scored sources",
            agent="EVIDENCE_CHAIN",
        )
        chains = build_evidence_chain(source_scores, conflicts)
        return {"evidence_chains": chains}
```

- [ ] **Step 2: Write test_evidence_chain.py**

```python
from deepchoice.agents.evidence_chain import build_evidence_chain


class TestBuildEvidenceChain:
    def test_strong_evidence_when_high_score_and_supporting(self):
        scores = [{
            "url": "https://docs.example.com",
            "title": "Feature X is production-ready",
            "total_score": 8.5,
            "supporting_sources": ["https://other.com"],
        }]
        chains = build_evidence_chain(scores, [])
        assert len(chains) == 1
        assert chains[0]["evidence_strength"] == "strong"
        assert chains[0]["disputed"] is False

    def test_weak_evidence_when_low_score(self):
        scores = [{
            "url": "https://blog.example.com",
            "title": "Feature Y might work",
            "total_score": 5.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert chains[0]["evidence_strength"] == "weak"

    def test_filters_out_very_low_scores(self):
        scores = [{
            "url": "https://spam.example.com",
            "title": "Buy now!",
            "total_score": 2.0,
            "supporting_sources": [],
        }]
        chains = build_evidence_chain(scores, [])
        assert len(chains) == 0

    def test_marks_disputed_from_conflicts(self):
        scores = [{
            "url": "https://contested.example.com",
            "title": "Claim X",
            "total_score": 7.0,
            "supporting_sources": [],
        }]
        conflicts = [{
            "source_a": {"url": "https://contested.example.com"},
            "source_b": {"url": "https://counter.example.com"},
        }]
        chains = build_evidence_chain(scores, conflicts)
        assert chains[0]["disputed"] is True

    def test_empty_inputs(self):
        assert build_evidence_chain([], []) == []
```

- [ ] **Step 3: Run tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_evidence_chain.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add deepchoice.agents/evidence_chain.py deepchoice/tests/test_evidence_chain.py
git commit -m "feat: add EvidenceChain — pure Python conclusion-to-source mapping with strength labels

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: conflict_detector.py

**Owner:** User (core architecture, interview-critical — structured conflict arbitration)

**Files:**
- Create: `deepchoice.agents/conflict_detector.py`

**Interfaces:**
- Consumes: `research_state["source_scores"]`
- Produces: `{"conflicts": list[dict]}` — each: `{claim_a, claim_b, source_a, source_b, similarity, resolution, confidence, reasoning, key_factor}`

- [ ] **Step 1: Write conflict_detector.py**

```python
import numpy as np
from sentence_transformers import SentenceTransformer
from ..utils.llm import call_model
from ..utils.views import print_agent_output

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model

ARBITRATION_PROMPT = """You are an impartial technical arbitrator. Two sources make claims about the same topic but may disagree.

## Topic
{topic}

## Source A (score: {score_a}/10, authority: {authority_a}, evidence: {evidence_a})
Claim: {claim_a}

## Source B (score: {score_b}/10, authority: {authority_b}, evidence: {evidence_b})
Claim: {claim_b}

## Rules
1. If scores differ by >=2.5 points, the higher-scored source is more likely correct
2. If both have code/benchmark evidence, both may be partially right (different contexts)
3. If neither has strong evidence, declare "insufficient_data"
4. Your reasoning MUST cite the score difference or evidence type difference

Return ONLY a JSON object:
{{
  "resolution": "A_correct|B_correct|both_partial|insufficient_data",
  "confidence": "high|medium|low",
  "reasoning": "Specific reason citing score/evidence difference",
  "key_factor": "The single most decisive factor"
}}"""

NEGATION_WORDS = {"not", "no", "never", "fail", "worse", "slow", "bad", "broken", "cannot", "doesn't", "don't"}


def find_contradictions(source_scores: list[dict], threshold: float = 0.6) -> list[dict]:
    model = _get_model()
    high_score_sources = [s for s in source_scores if s["total_score"] >= 5.0]
    if len(high_score_sources) < 2:
        return []

    pairs = []
    for i in range(len(high_score_sources)):
        for j in range(i + 1, len(high_score_sources)):
            a = high_score_sources[i]
            b = high_score_sources[j]
            title_a = a.get("title", "")
            title_b = b.get("title", "")
            if not title_a or not title_b:
                continue

            emb_a = model.encode(title_a)
            emb_b = model.encode(title_b)
            sim = float(np.dot(emb_a, emb_b) / (np.linalg.norm(emb_a) * np.linalg.norm(emb_b)))

            if sim >= threshold:
                neg_a = any(w in title_a.lower() for w in NEGATION_WORDS)
                neg_b = any(w in title_b.lower() for w in NEGATION_WORDS)
                if neg_a != neg_b:
                    pairs.append({"source_a": a, "source_b": b, "similarity": round(sim, 3)})

    return pairs


class ConflictDetectorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        source_scores = research_state.get("source_scores", [])
        print_agent_output(
            f"Detecting conflicts among {len(source_scores)} sources",
            agent="CONFLICT_DETECTOR",
        )

        pairs = find_contradictions(source_scores)
        if not pairs:
            return {"conflicts": []}

        conflicts = []
        for pair in pairs:
            a = pair["source_a"]
            b = pair["source_b"]
            prompt = [{
                "role": "user",
                "content": ARBITRATION_PROMPT.format(
                    topic=research_state["task"]["query"],
                    score_a=a["total_score"],
                    authority_a=a["scores"]["authority"],
                    evidence_a=a["evidence_type"],
                    claim_a=a.get("title", ""),
                    score_b=b["total_score"],
                    authority_b=b["scores"]["authority"],
                    evidence_b=b["evidence_type"],
                    claim_b=b.get("title", ""),
                ),
            }]

            try:
                result = await call_model(prompt, model="deepseek-v4-pro", response_format="json")
                conflicts.append({
                    "claim_a": a.get("title", ""),
                    "claim_b": b.get("title", ""),
                    "source_a": {"url": a["url"], "score": a["total_score"]},
                    "source_b": {"url": b["url"], "score": b["total_score"]},
                    "similarity": pair["similarity"],
                    "resolution": result.get("resolution", "insufficient_data"),
                    "confidence": result.get("confidence", "low"),
                    "reasoning": result.get("reasoning", ""),
                    "key_factor": result.get("key_factor", ""),
                })
            except Exception as e:
                print_agent_output(f"Arbitration failed: {e}", agent="CONFLICT_DETECTOR")

        return {"conflicts": conflicts}
```

- [ ] **Step 2: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.agents.conflict_detector import ConflictDetectorAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice.agents/conflict_detector.py
git commit -m "feat: add ConflictDetector — semantic contradiction detection + LLM structured arbitration

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: report_generator.py + 2 report formats

**Owner:** AI skeleton (format rendering) + User (ReportGenerator dispatcher)

**Files:**
- Create: `deepchoice.formats/what_why_how.py`
- Create: `deepchoice.formats/evidence_first.py`
- Create: `deepchoice.agents/report_generator.py`

**Interfaces:**
- Format functions: `def render(state: dict) -> str` — returns Markdown string
- ReportGenerator: `async run(research_state: dict) -> dict` returning `{"report": str}`

- [ ] **Step 1: Write formats/what_why_how.py**

```python
def render(state: dict) -> str:
    task = state.get("task", {})
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])
    gaps = state.get("knowledge_gaps", [])

    lines = [
        f"# {task.get('query', 'Technology Selection')} — Decision Brief",
        "",
        "## What: Understanding the Candidates",
        "",
    ]

    # Candidate overview from top evidence
    strong_chains = [c for c in chains if c["evidence_strength"] == "strong"]
    for c in strong_chains[:5]:
        lines.append(f"- **{c['conclusion']}**")
        for src in c["sources"]:
            lines.append(f"  - Source: [{src['title']}]({src['url']}) (score: {src['score']})")

    lines.extend([
        "",
        "## Why: Evidence-Driven Judgment",
        "",
    ])

    # Evidence chain details
    for c in chains:
        tag = " [DISPUTED]" if c["disputed"] else ""
        lines.append(f"### {c['conclusion']}{tag}")
        lines.append(f"**Evidence strength:** {c['evidence_strength']}")
        for src in c["sources"]:
            lines.append(f"- [{src['title']}]({src['url']}) — score: {src['score']}")
        lines.append("")

    # Conflicts section
    if conflicts:
        lines.extend(["## Disputes & Resolutions", ""])
        for i, c in enumerate(conflicts):
            lines.append(f"### Conflict {i+1}: {c.get('resolution', 'unresolved')}")
            lines.append(f"- Claim A: {c.get('claim_a', '')} (score: {c.get('source_a', {}).get('score', 'N/A')})")
            lines.append(f"- Claim B: {c.get('claim_b', '')} (score: {c.get('source_b', {}).get('score', 'N/A')})")
            lines.append(f"- Resolution: {c.get('reasoning', '')}")
            lines.append(f"- Key factor: {c.get('key_factor', '')}")
            lines.append(f"- Confidence: {c.get('confidence', 'low')}")
            lines.append("")

    # Gaps
    if gaps:
        lines.extend(["## What We Don't Know Yet", ""])
        for g in gaps:
            lines.append(f"- {g}")
        lines.append("")

    lines.extend([
        "## How: Action Path",
        "",
        f"**Confidence:** {state.get('confidence', 'unknown')}",
        "",
        "### Starting Point",
        "Based on the evidence above, start with the highest-scored option that matches your scene context.",
        "",
        "### References",
    ])
    for c in chains:
        for src in c["sources"]:
            lines.append(f"- [{src['title']}]({src['url']})")

    return "\n".join(lines)
```

- [ ] **Step 2: Write formats/evidence_first.py**

```python
def render(state: dict) -> str:
    task = state.get("task", {})
    chains = state.get("evidence_chains", [])
    conflicts = state.get("conflicts", [])

    # Find strongest conclusion
    strong = [c for c in chains if c["evidence_strength"] == "strong"]
    top = strong[0] if strong else (chains[0] if chains else None)

    lines = [
        f"# {task.get('query', 'Technology Selection')} — Evidence Brief",
        "",
        "## Conclusion",
        f"{top['conclusion'] if top else 'Insufficient evidence to draw a conclusion.'}",
        "",
        "## Why Trust This Conclusion",
    ]

    if top:
        lines.append("### Strongest Evidence")
        for src in top["sources"]:
            lines.append(f"- [{src['title']}]({src['url']}) (score: {src['score']})")
        lines.append("")
        lines.append("### Supporting Evidence Chain")
        moderate = [c for c in chains if c["evidence_strength"] == "moderate"][:3]
        for c in moderate:
            lines.append(f"- {c['conclusion']}")

    lines.extend(["", "## Counter-Evidence", ""])
    disputed = [c for c in chains if c["disputed"]]
    if disputed:
        for c in disputed:
            lines.append(f"- {c['conclusion']} (disputed)")
    else:
        lines.append("No significant counter-evidence found in this search.")

    lines.extend(["", "## Disputes", ""])
    if conflicts:
        for c in conflicts:
            lines.append(f"- {c.get('resolution', 'unresolved')}: {c.get('reasoning', '')[:200]}")
    else:
        lines.append("No major disputes detected.")

    lines.extend([
        "",
        "## What We Don't Know",
        "",
        f"**Confidence:** {state.get('confidence', 'unknown')}",
    ])
    gaps = state.get("knowledge_gaps", [])
    for g in gaps:
        lines.append(f"- {g}")

    lines.extend([
        "",
        "## If You're Making a Decision",
        "",
        "1. Verify the strongest evidence source independently",
        "2. Check if the disputed claims affect your use case",
        "3. Run a quick prototype with the recommended option",
    ])

    return "\n".join(lines)
```

- [ ] **Step 3: Write agents/report_generator.py**

```python
from ..utils.views import print_agent_output
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first

FORMAT_RENDERERS = {
    "what_why_how": render_what_why_how,
    "evidence_first": render_evidence_first,
}


class ReportGeneratorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        fmt = research_state["task"].get("report_format", "what_why_how")
        print_agent_output(f"Generating report in format: {fmt}", agent="REPORT_GENERATOR")

        renderer = FORMAT_RENDERERS.get(fmt, render_what_why_how)
        report = renderer(research_state)

        return {"report": report}
```

- [ ] **Step 4: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.agents.report_generator import ReportGeneratorAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add deepchoice.formats/ deepchoice.agents/report_generator.py
git commit -m "feat: add ReportGenerator with what-why-how and evidence-first format renderers

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: self_reviewer.py

**Owner:** User (core architecture — 6-item checklist + confidence + retry decision)

**Files:**
- Create: `deepchoice.agents/self_reviewer.py`

**Interfaces:**
- Consumes: `research_state["report"]`, `research_state["evidence_chains"]`, `research_state["sub_questions"]`, `research_state["retry_count"]`
- Produces: `{"confidence": "high|medium|low", "knowledge_gaps": list[str]}`

- [ ] **Step 1: Write self_reviewer.py**

```python
from ..utils.llm import call_model
from ..utils.views import print_agent_output

REVIEW_PROMPT = """You are a rigorous quality reviewer. Evaluate this research report against a 6-item checklist.

## Report
{report}

## Evidence Chains
{evidence_chains}

## Original Sub-Questions
{sub_questions}

## Retry Count
{retry_count}

## Checklist — Answer YES or NO for each, with a brief note:
1. Does every conclusion have source support? (If not, list unsupported conclusions)
2. Are there any unsourced claims? (List them if yes)
3. Does the recommendation cover all 5 comparison dimensions? (Functionality, Performance, Ecosystem, Developer Experience, Scenario Fit)
4. Are there unlabeled information conflicts? (List them if yes)
5. Are any user sub-questions unanswered? (List which ones)
6. Are there counter-examples or negative findings not flagged? (List them if yes)

## Confidence Assessment
- high: 6/6 passed, all evidence chains have strong or moderate strength
- medium: 1-2 items failed, no critical gaps
- low: 3+ items failed OR critical information missing

## Gap Analysis
If confidence is not "high", list the specific information gaps. Each gap should be a specific search query that could fill the gap.

Return ONLY a JSON object:
{{
  "checks": [
    {{"item": 1, "passed": true, "note": "..."}},
    ...
  ],
  "passed_count": N,
  "confidence": "high|medium|low",
  "knowledge_gaps": ["gap query 1", "gap query 2"],
  "critical_gaps": ["critical gap"]
}}"""


class SelfReviewerAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        print_agent_output("Running self-review quality check", agent="SELF_REVIEWER")

        prompt = [{
            "role": "user",
            "content": REVIEW_PROMPT.format(
                report=research_state.get("report", ""),
                evidence_chains=str(research_state.get("evidence_chains", [])),
                sub_questions=str(research_state.get("sub_questions", [])),
                retry_count=research_state.get("retry_count", 0),
            ),
        }]

        result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")

        return {
            "confidence": result.get("confidence", "medium"),
            "knowledge_gaps": result.get("knowledge_gaps", []),
        }
```

- [ ] **Step 2: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.agents.self_reviewer import SelfReviewerAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice.agents/self_reviewer.py
git commit -m "feat: add SelfReviewer — 6-item checklist + confidence scoring + gap detection

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: orchestrator.py

**Owner:** User (core architecture, interview-critical — LangGraph StateGraph assembly)

**Files:**
- Create: `deepchoice.agents/orchestrator.py`

**Interfaces:**
- Consumes: `TaskConfig` (via `self.task`)
- Produces: Final `ResearchState` via `ainvoke({"task": task_config.model_dump()})`
- Imports all 7 agents and wires them into a StateGraph with conditional edges

- [ ] **Step 1: Write orchestrator.py**

```python
import time
from langgraph.graph import StateGraph, END
from ..state import ResearchState
from ..utils.views import print_agent_output
from .query_analyzer import QueryAnalyzerAgent
from .multi_retriever import MultiRetrieverAgent
from .source_evaluator import SourceEvaluatorAgent
from .conflict_detector import ConflictDetectorAgent
from .evidence_chain import EvidenceChainAgent
from .report_generator import ReportGeneratorAgent
from .self_reviewer import SelfReviewerAgent


class ChiefEditorAgent:
    def __init__(self, task: dict, websocket=None, stream_output=None, headers=None):
        self.task = task
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers or {}
        self.task_id = str(int(time.time()))

    def _initialize_agents(self):
        return {
            "query_analyzer": QueryAnalyzerAgent(self.websocket, self.stream_output, self.headers),
            "multi_retriever": MultiRetrieverAgent(self.websocket, self.stream_output, self.headers),
            "source_evaluator": SourceEvaluatorAgent(self.websocket, self.stream_output, self.headers),
            "conflict_detector": ConflictDetectorAgent(self.websocket, self.stream_output, self.headers),
            "evidence_chain": EvidenceChainAgent(self.websocket, self.stream_output, self.headers),
            "report_generator": ReportGeneratorAgent(self.websocket, self.stream_output, self.headers),
            "self_reviewer": SelfReviewerAgent(self.websocket, self.stream_output, self.headers),
        }

    def _create_workflow(self, agents):
        workflow = StateGraph(ResearchState)

        workflow.add_node("query_analyzer", agents["query_analyzer"].run)
        workflow.add_node("multi_retriever", agents["multi_retriever"].run)
        workflow.add_node("source_evaluator", agents["source_evaluator"].run)
        workflow.add_node("conflict_detector", agents["conflict_detector"].run)
        workflow.add_node("evidence_chain", agents["evidence_chain"].run)
        workflow.add_node("report_generator", agents["report_generator"].run)
        workflow.add_node("self_reviewer", agents["self_reviewer"].run)

        workflow.set_entry_point("query_analyzer")
        workflow.add_edge("query_analyzer", "multi_retriever")
        workflow.add_edge("multi_retriever", "source_evaluator")
        workflow.add_edge("source_evaluator", "conflict_detector")
        workflow.add_edge("conflict_detector", "evidence_chain")
        workflow.add_edge("evidence_chain", "report_generator")
        workflow.add_edge("report_generator", "self_reviewer")

        workflow.add_conditional_edges(
            "self_reviewer",
            self._route_after_review,
            {
                "end": END,
                "retry_small": "conflict_detector",
                "retry_full": "query_analyzer",
            },
        )

        return workflow

    def _route_after_review(self, state: ResearchState) -> str:
        confidence = state.get("confidence", "medium")
        retry_count = state.get("retry_count", 0)
        gaps = state.get("knowledge_gaps", [])

        if confidence in ("high", "medium"):
            return "end"
        if retry_count >= 1:
            return "end"

        state["retry_count"] = retry_count + 1
        if len(gaps) <= 2:
            return "retry_small"
        return "retry_full"

    def init_research_team(self):
        agents = self._initialize_agents()
        return self._create_workflow(agents)

    async def run_research_task(self):
        print_agent_output(
            f"Starting research for: {self.task.get('query', '')}",
            agent="ORCHESTRATOR",
        )
        workflow = self.init_research_team()
        chain = workflow.compile()
        result = await chain.ainvoke({"task": self.task})
        return result
```

- [ ] **Step 2: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.agents.orchestrator import ChiefEditorAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice.agents/orchestrator.py
git commit -m "feat: add ChiefEditorAgent orchestrator — 7-node LangGraph pipeline with retry routing

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: FastAPI Server + SSE + Snapshot Store

**Owner:** AI skeleton (write full code, user reviews)

**Files:**
- Create: `deepchoice.server/snapshot_store.py`
- Create: `deepchoice.server/sse.py`
- Create: `deepchoice.server/app.py`

**Interfaces:**
- `snapshot_store.py`: `save_snapshot(task_id, state) -> Path`, `load_snapshot(task_id) -> dict`, `save_report(task_id, report_md) -> Path`
- `sse.py`: `async def event_stream(task_id, state) -> AsyncGenerator`
- `app.py`: FastAPI app with 6 endpoints

- [ ] **Step 1: Write server/snapshot_store.py**

```python
import json
from pathlib import Path

OUTPUT_DIR = Path("./deepchoice/outputs")


def save_snapshot(task_id: str, state: dict) -> Path:
    task_dir = OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = task_dir / "research_snapshot.json"
    serializable = {k: v for k, v in state.items() if k != "current_phase"}
    snapshot_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return snapshot_path


def load_snapshot(task_id: str) -> dict | None:
    snapshot_path = OUTPUT_DIR / task_id / "research_snapshot.json"
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def save_report(task_id: str, report_md: str) -> Path:
    report_path = OUTPUT_DIR / task_id / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    return report_path


def list_history() -> list[dict]:
    if not OUTPUT_DIR.exists():
        return []
    history = []
    for task_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if task_dir.is_dir():
            snapshot = load_snapshot(task_dir.name)
            if snapshot:
                history.append({
                    "task_id": task_dir.name,
                    "query": snapshot.get("task", {}).get("query", ""),
                    "confidence": snapshot.get("confidence", ""),
                })
    return history[:50]
```

- [ ] **Step 2: Write server/sse.py**

```python
import json
import asyncio


async def event_stream(task_id: str, state_proxy: dict):
    """SSE event generator. state_proxy is a shared dict updated by the orchestrator."""
    phases = [
        "query_analysis", "retrieval", "source_evaluation",
        "conflict_detection", "evidence_chain", "report_generation", "self_review",
    ]

    last_phase = None
    while True:
        current = state_proxy.get("current_phase", "")
        if current != last_phase:
            if last_phase and last_phase != "complete":
                yield f"data: {json.dumps({'phase': last_phase, 'status': 'done'})}\n\n"
            if current and current != "complete":
                yield f"data: {json.dumps({'phase': current, 'status': 'running'})}\n\n"
            last_phase = current

        if current == "complete":
            yield f"data: {json.dumps({'phase': 'complete', 'status': 'done', 'confidence': state_proxy.get('confidence', '')})}\n\n"
            break

        await asyncio.sleep(0.3)
```

- [ ] **Step 3: Write server/app.py**

```python
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from ..agents.orchestrator import ChiefEditorAgent
from ..state import ResearchState
from .snapshot_store import save_snapshot, load_snapshot, save_report, list_history
from ..formats.what_why_how import render as render_what_why_how
from ..formats.evidence_first import render as render_evidence_first

app = FastAPI(title="DeepChoice API", version="0.1.0")

# In-memory state store
_active_tasks: dict[str, dict] = {}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/research")
async def start_research(task: dict):
    orchestrator = ChiefEditorAgent(task)
    task_id = orchestrator.task_id

    # Shared state proxy for SSE
    state_proxy = {
        "task": task,
        "sub_questions": [],
        "search_results": [],
        "source_scores": [],
        "conflicts": [],
        "evidence_chains": [],
        "report": "",
        "confidence": "",
        "knowledge_gaps": [],
        "retry_count": 0,
        "partial_failures": [],
        "current_phase": "",
    }
    _active_tasks[task_id] = state_proxy

    # Run research in background
    asyncio.create_task(_run_research(task_id, orchestrator, state_proxy))

    return {"task_id": task_id, "status": "started"}


async def _run_research(task_id: str, orchestrator: ChiefEditorAgent, state_proxy: dict):
    try:
        state_proxy["current_phase"] = "query_analysis"
        result = await orchestrator.run_research_task()

        for key in state_proxy:
            if key in result:
                state_proxy[key] = result[key]

        state_proxy["current_phase"] = "complete"
        save_snapshot(task_id, result)
        save_report(task_id, result.get("report", ""))
    except Exception as e:
        state_proxy["current_phase"] = "complete"
        state_proxy["confidence"] = "low"
        state_proxy["report"] = f"Research failed: {str(e)}"


@app.get("/research/{task_id}/stream")
async def stream_research(task_id: str):
    state_proxy = _active_tasks.get(task_id)
    if not state_proxy:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        phases = [
            "query_analysis", "retrieval", "source_evaluation",
            "conflict_detection", "evidence_chain", "report_generation", "self_review",
        ]
        last_phase = None
        while True:
            current = state_proxy.get("current_phase", "")
            if current != last_phase:
                if last_phase and last_phase != "complete":
                    yield {"event": "progress", "data": json.dumps({"phase": last_phase, "status": "done"}, ensure_ascii=False)}
                if current and current != "complete":
                    yield {"event": "progress", "data": json.dumps({"phase": current, "status": "running"}, ensure_ascii=False)}
                last_phase = current
            if current == "complete":
                yield {"event": "done", "data": json.dumps({"phase": "complete", "confidence": state_proxy.get("confidence", "")}, ensure_ascii=False)}
                break
            await asyncio.sleep(0.3)

    return EventSourceResponse(event_generator())


@app.get("/research/{task_id}/report")
async def get_report(task_id: str, format: str = ""):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")

    if format and format != snapshot.get("task", {}).get("report_format", ""):
        renderers = {"what_why_how": render_what_why_how, "evidence_first": render_evidence_first}
        renderer = renderers.get(format, render_what_why_how)
        report = renderer(snapshot)
    else:
        report_path = Path(f"./deepchoice/outputs/{task_id}/report.md")
        report = report_path.read_text(encoding="utf-8") if report_path.exists() else snapshot.get("report", "")

    return {"report": report, "format": format or snapshot.get("task", {}).get("report_format", "what_why_how")}


@app.get("/research/{task_id}/snapshot")
async def get_snapshot(task_id: str):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")
    return snapshot


@app.post("/research/{task_id}/regenerate")
async def regenerate_report(task_id: str, format: str = "what_why_how"):
    snapshot = load_snapshot(task_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Task not found")

    renderers = {"what_why_how": render_what_why_how, "evidence_first": render_evidence_first}
    renderer = renderers.get(format, render_what_why_how)
    report = renderer(snapshot)
    save_report(task_id, report)
    return {"report": report, "format": format}


@app.get("/history")
async def get_history():
    return {"tasks": list_history()}
```

- [ ] **Step 4: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.server.app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add deepchoice.server/
git commit -m "feat: add FastAPI server with SSE streaming, snapshot store, and 6 REST endpoints

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: Streamlit Frontend

**Owner:** AI skeleton (write full code, user reviews)

**Files:**
- Create: `deepchoice/frontend/app.py`

**Interfaces:**
- Single-page Streamlit app with 3 zones: input, progress, report + evidence side panel

- [ ] **Step 1: Write frontend/app.py**

```python
import time
import json
import streamlit as st
import httpx

st.set_page_config(page_title="DeepChoice", layout="wide")
st.title("DeepChoice — Tech Selection Deep Research")

API_BASE = "http://localhost:8000"

# === Input Zone ===
with st.container():
    col1, col2, col3 = st.columns([4, 1, 1])
    with col1:
        query = st.text_input("What technology choice are you evaluating?", placeholder="e.g., LangGraph vs CrewAI for building AI agents")
    with col2:
        scene = st.selectbox("Team size", ["solo", "team", "enterprise"], index=0)
    with col3:
        report_fmt = st.selectbox("Report format", ["what_why_how", "evidence_first"], index=0)

    if st.button("Start Research", type="primary", disabled=not query):
        with st.spinner("Starting..."):
            resp = httpx.post(f"{API_BASE}/research", json={
                "query": query,
                "scene_context": scene,
                "constraints": [],
                "report_format": report_fmt,
            }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                st.session_state["task_id"] = data["task_id"]
                st.session_state["running"] = True
                st.session_state["events"] = []
                st.rerun()

# === Progress Zone ===
if st.session_state.get("running"):
    task_id = st.session_state["task_id"]
    progress_placeholder = st.empty()
    status_placeholder = st.empty()

    with progress_placeholder.container():
        st.subheader("Research Progress")
        progress_bar = st.progress(0)
        phase_display = st.empty()

    phases = ["query_analysis", "retrieval", "source_evaluation", "conflict_detection", "evidence_chain", "report_generation", "self_review"]
    phase_idx = 0

    try:
        with httpx.stream("GET", f"{API_BASE}/research/{task_id}/stream", timeout=120) as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    event = json.loads(line[5:])
                    phase = event.get("phase", "")

                    if phase != "complete" and phase in phases:
                        phase_idx = phases.index(phase)
                        progress_bar.progress(phase_idx / len(phases))
                        phase_display.info(f"Running: {phase} — {event.get('status', '')}")

                    if phase == "complete":
                        progress_bar.progress(1.0)
                        phase_display.success(f"Complete! Confidence: {event.get('confidence', 'unknown')}")
                        st.session_state["running"] = False
                        st.session_state["complete"] = True
                        st.rerun()
    except Exception as e:
        st.error(f"Stream error: {e}")
        st.session_state["running"] = False

# === Report Zone ===
if st.session_state.get("complete"):
    task_id = st.session_state["task_id"]
    tab1, tab2 = st.tabs(["Report", "Evidence Panel"])

    with tab1:
        fmt = st.selectbox("View format", ["what_why_how", "evidence_first"], key="report_view_fmt")
        resp = httpx.get(f"{API_BASE}/research/{task_id}/report", params={"format": fmt}, timeout=10)
        if resp.status_code == 200:
            st.markdown(resp.json()["report"])
        else:
            st.error("Failed to load report")

    with tab2:
        resp = httpx.get(f"{API_BASE}/research/{task_id}/snapshot", timeout=10)
        if resp.status_code == 200:
            snapshot = resp.json()
            chains = snapshot.get("evidence_chains", [])
            for c in chains:
                with st.expander(f"{c.get('conclusion', 'Finding')} ({c.get('evidence_strength', 'N/A')})"):
                    for src in c.get("sources", []):
                        st.markdown(f"- [{src['title']}]({src['url']}) — score: {src['score']}")
                        if c.get("disputed"):
                            st.warning("Disputed")
```

- [ ] **Step 2: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "import ast; ast.parse(open('frontend/app.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice/frontend/app.py
git commit -m "feat: add Streamlit frontend — input zone, SSE progress, report + evidence panel

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14: Chroma KB Setup

**Owner:** AI skeleton (write setup script, user reviews + adds docs)

**Files:**
- Create: `deepchoice/chroma_kb/setup.py`
- Create: `deepchoice/chroma_kb/data/official/.gitkeep`
- Create: `deepchoice/chroma_kb/data/blogs/.gitkeep`
- Create: `deepchoice/chroma_kb/data/papers/.gitkeep`

- [ ] **Step 1: Write chroma_kb/setup.py**

```python
"""Initialize the Chroma knowledge base with documents from data/ directories."""
import os
import sys
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

KB_DIR = Path(__file__).parent
DB_DIR = KB_DIR / "chroma_db"
DATA_DIRS = {
    "official": KB_DIR / "data" / "official",
    "blogs": KB_DIR / "data" / "blogs",
    "papers": KB_DIR / "data" / "papers",
}


def load_documents() -> list[dict]:
    docs = []
    for source_type, data_dir in DATA_DIRS.items():
        if not data_dir.exists():
            continue
        for file_path in data_dir.glob("*.md"):
            content = file_path.read_text(encoding="utf-8")
            title = file_path.stem
            docs.append({
                "id": f"{source_type}/{file_path.name}",
                "content": content[:2000],
                "metadata": {
                    "title": title,
                    "source_type": source_type,
                    "url": f"file://{file_path}",
                    "date": "",
                },
            })
    return docs


def main():
    print(f"Loading documents from {KB_DIR / 'data'}...")
    documents = load_documents()
    print(f"Found {len(documents)} documents")

    if not documents:
        print("No documents found. Add .md files to chroma_kb/data/ directories.")
        return

    model = SentenceTransformer("BAAI/bge-m3")
    print("Encoding documents...")

    client = chromadb.PersistentClient(
        path=str(DB_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection("tech_kb")

    ids = [d["id"] for d in documents]
    texts = [d["content"] for d in documents]
    metadatas = [d["metadata"] for d in documents]
    embeddings = model.encode(texts).tolist()

    collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    print(f"Ingested {len(documents)} documents into Chroma DB at {DB_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "import ast; ast.parse(open('chroma_kb/setup.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice/chroma_kb/
git commit -m "feat: add Chroma KB setup script with bge-m3 embedding and 3-layer document pyramid

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: Test Cases (known_cases.json + taxonomy.json + generator.py)

**Owner:** User for 100 known_cases (4h), AI skeleton for taxonomy + generator

**Files:**
- Create: `deepchoice/tests/test_cases/taxonomy.json`
- Create: `deepchoice/tests/test_cases/generator.py`
- Create: `deepchoice/tests/test_cases/known_cases.json` (100 hand-reviewed entries — user writes)

- [ ] **Step 1: Write taxonomy.json**

```json
{
  "categories": {
    "ai_agent_frameworks": {
      "label": "AI/Agent Frameworks",
      "subdomains": [
        "agent_orchestration", "mcp_ecosystem", "tool_calling", "llm_invocation",
        "multi_agent_collaboration", "prompt_management", "rag_frameworks",
        "memory_systems", "safety_guardrails", "evaluation_frameworks"
      ]
    },
    "models_and_data": {
      "label": "Models & Data",
      "subdomains": [
        "llm_selection", "embedding_models", "reranker", "vector_databases",
        "graph_databases", "document_parsing", "data_pipelines",
        "prompt_strategies", "fine_tuning", "multimodal"
      ]
    },
    "backend_frameworks": {
      "label": "Backend Frameworks & API",
      "subdomains": [
        "web_frameworks", "api_paradigms", "auth_authorization", "serialization",
        "middleware", "dependency_injection", "async_solutions",
        "task_queues", "file_storage", "api_gateways"
      ]
    },
    "infrastructure": {
      "label": "Infrastructure",
      "subdomains": [
        "relational_db", "nosql", "caching", "message_queues",
        "search_engines", "object_storage", "service_discovery",
        "config_center", "distributed_coordination", "stream_processing"
      ]
    },
    "devops": {
      "label": "Deployment & Operations",
      "subdomains": [
        "container_orchestration", "cicd", "monitoring", "logging",
        "distributed_tracing", "cloud_platforms", "iac",
        "canary_releases", "security_scanning", "disaster_recovery"
      ]
    }
  },
  "scenes": ["solo", "team", "enterprise"],
  "difficulties": ["simple", "medium", "hard"],
  "variant_factors": ["language", "cost_sensitivity", "scale", "compliance"]
}
```

- [ ] **Step 2: Write generator.py**

```python
"""Programmatic test case generator from taxonomy."""
import json
import itertools
from pathlib import Path

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"


def load_taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


TEMPLATES = {
    "simple": "{tech_a} vs {tech_b} for a {scene_desc} project",
    "medium": "Comparing {tech_a} and {tech_b}: which is better for {scene_desc} with {variant} requirements?",
    "hard": "Full-stack technology selection for a {scene_desc} system: {tech_a} vs {tech_b} ecosystem comparison considering {variant}",
}

SCENE_DESC = {
    "solo": "solo developer",
    "team": "mid-size team",
    "enterprise": "enterprise-grade",
}

# Sample technology pairs per subdomain (illustrative — expand as needed)
TECH_PAIRS = {
    "agent_orchestration": [("LangGraph", "CrewAI"), ("AutoGen", "Semantic Kernel")],
    "web_frameworks": [("FastAPI", "Flask"), ("Django", "FastAPI"), ("Express", "NestJS")],
    "relational_db": [("PostgreSQL", "MySQL"), ("PostgreSQL", "SQLite")],
    "vector_databases": [("Chroma", "Pinecone"), ("Weaviate", "Qdrant"), ("Milvus", "Chroma")],
    "llm_selection": [("GPT-4o", "Claude Opus"), ("DeepSeek V4", "GPT-4o"), ("Claude Haiku", "Gemini Flash")],
    "container_orchestration": [("Kubernetes", "Docker Swarm"), ("Kubernetes", "Nomad")],
    "message_queues": [("RabbitMQ", "Kafka"), ("Redis", "RabbitMQ"), ("NATS", "Kafka")],
    "cicd": [("GitHub Actions", "GitLab CI"), ("Jenkins", "GitHub Actions")],
    "monitoring": [("Prometheus", "Datadog"), ("Grafana", "Datadog")],
    "caching": [("Redis", "Memcached"), ("Redis", "Dragonfly")],
}


def generate_cases(count: int = 1000) -> list[dict]:
    taxonomy = load_taxonomy()
    cases = []
    case_id = 0

    for cat_key, cat_data in taxonomy["categories"].items():
        for subdomain in cat_data["subdomains"]:
            pairs = TECH_PAIRS.get(subdomain, [("OptionA", "OptionB")])
            for tech_a, tech_b in pairs:
                for scene in taxonomy["scenes"]:
                    for difficulty in taxonomy["difficulties"]:
                        for variant in taxonomy["variant_factors"][:2]:
                            template = TEMPLATES[difficulty]
                            query = template.format(
                                tech_a=tech_a,
                                tech_b=tech_b,
                                scene_desc=SCENE_DESC[scene],
                                variant=variant,
                            )
                            cases.append({
                                "id": f"TC-{case_id:04d}",
                                "query": query,
                                "category": cat_data["label"],
                                "subdomain": subdomain,
                                "scene": scene,
                                "difficulty": difficulty,
                                "variant": variant,
                                "tech_a": tech_a,
                                "tech_b": tech_b,
                                "expected_winner": None,
                                "ground_truth_notes": "",
                            })
                            case_id += 1
                            if case_id >= count:
                                return cases
    return cases


if __name__ == "__main__":
    cases = generate_cases()
    output_path = Path(__file__).parent / "generated_cases.json"
    output_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(cases)} test cases -> {output_path}")
```

- [ ] **Step 3: Write known_cases.json skeleton (first 5 entries as template, user fills remaining 95)**

```json
[
  {
    "id": "TC-0001",
    "query": "LangGraph vs CrewAI for building AI agents as a solo developer",
    "category": "AI/Agent Frameworks",
    "subdomain": "agent_orchestration",
    "scene": "solo",
    "difficulty": "medium",
    "tech_a": "LangGraph",
    "tech_b": "CrewAI",
    "expected_winner": "LangGraph",
    "ground_truth_notes": "LangGraph has lower-level control, better for solo dev who needs flexibility. CrewAI has higher-level abstractions but less customizability."
  },
  {
    "id": "TC-0002",
    "query": "FastAPI vs Flask for REST API in a mid-size team",
    "category": "Backend Frameworks & API",
    "subdomain": "web_frameworks",
    "scene": "team",
    "difficulty": "simple",
    "tech_a": "FastAPI",
    "tech_b": "Flask",
    "expected_winner": "FastAPI",
    "ground_truth_notes": "FastAPI has built-in async, auto-docs, Pydantic validation. Flask needs extensions. For team REST API, FastAPI is the modern default."
  },
  {
    "id": "TC-0003",
    "query": "PostgreSQL vs MySQL for enterprise financial data",
    "category": "Infrastructure",
    "subdomain": "relational_db",
    "scene": "enterprise",
    "difficulty": "medium",
    "tech_a": "PostgreSQL",
    "tech_b": "MySQL",
    "expected_winner": "PostgreSQL",
    "ground_truth_notes": "PostgreSQL has stronger ACID compliance, better analytical queries, richer extension ecosystem. MySQL better for simple read-heavy workloads."
  },
  {
    "id": "TC-0004",
    "query": "Chroma vs Pinecone for RAG vector database on a budget",
    "category": "Models & Data",
    "subdomain": "vector_databases",
    "scene": "solo",
    "difficulty": "simple",
    "tech_a": "Chroma",
    "tech_b": "Pinecone",
    "expected_winner": "Chroma",
    "ground_truth_notes": "Chroma is free, local, open-source. Pinecone is managed, costs money. For solo/small budget, Chroma wins. For scale/production, Pinecone."
  },
  {
    "id": "TC-0005",
    "query": "Kubernetes vs Docker Swarm for container orchestration in a team environment",
    "category": "Deployment & Operations",
    "subdomain": "container_orchestration",
    "scene": "team",
    "difficulty": "medium",
    "tech_a": "Kubernetes",
    "tech_b": "Docker Swarm",
    "expected_winner": "Kubernetes",
    "ground_truth_notes": "Kubernetes is industry standard, has massive ecosystem. Docker Swarm simpler but dying. For team setting, K8s is the long-term choice despite steeper learning curve."
  }
]
```

- [ ] **Step 4: Run generator and verify**

```bash
cd D:/deepchoice-agent && python tests/test_cases/generator.py
```

Expected: `Generated N test cases -> .../generated_cases.json` where N is approximately 600+.

- [ ] **Step 5: Commit**

```bash
git add deepchoice/tests/test_cases/
git commit -m "feat: add test case taxonomy, generator, and 5 known cases (template for 100)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16: Integration Tests (Full Pipeline)

**Owner:** AI skeleton (write integration tests, user reviews)

**Files:**
- Create: `deepchoice/tests/test_pipeline.py`

**Interfaces:**
- Tests full 7-node pipeline with mocked LLM and mocked retrievers
- Verifies: correct state transitions, retry logic, report generation, snapshot save

- [ ] **Step 1: Write test_pipeline.py**

```python
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from deepchoice.agents.orchestrator import ChiefEditorAgent


MOCK_QUERY_RESULT = {
    "sub_questions": [
        "Comparison of async performance and throughput",
        "Ecosystem and community activity comparison",
        "Learning curve and developer experience",
        "Scenario fit for API development",
        "Deployment complexity comparison",
    ],
    "scene_context": "solo",
    "constraints": ["python"],
}

MOCK_SEARCH_RESULTS = [{
    "source": "tavily",
    "status": "success",
    "results": [
        {"url": "https://example.com/1", "title": "A is faster than B in benchmarks", "snippet": "Benchmark results show...", "date": "2026-06-01"},
        {"url": "https://example.com/2", "title": "B has better developer experience", "snippet": "DX comparison...", "date": "2026-05-15"},
    ],
    "error": None,
    "latency_ms": 500,
}]

MOCK_SOURCE_SCORES = [{
    "url": "https://example.com/1",
    "title": "A is faster than B in benchmarks",
    "source_type": "tech_blog",
    "scores": {"authority": 7, "timeliness": 10, "consistency": 6, "verifiability": 8},
    "total_score": 7.5,
    "evidence_type": "benchmark",
    "supporting_sources": [],
    "contradicting_sources": [],
    "rank": 1,
}]

MOCK_CONFLICTS = []

MOCK_EVIDENCE_CHAINS = [{
    "conclusion": "A is faster than B in benchmarks",
    "sources": [{"url": "https://example.com/1", "title": "A vs B benchmark", "score": 7.5}],
    "evidence_strength": "moderate",
    "disputed": False,
}]

MOCK_REPORT = "# Test Report\n\nThis is a test report."

MOCK_REVIEW = {"confidence": "high", "knowledge_gaps": []}


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_completes_with_high_confidence(self):
        task = {
            "query": "TestA vs TestB for API development",
            "scene_context": "solo",
            "constraints": ["python"],
            "report_format": "what_why_how",
        }

        orchestrator = ChiefEditorAgent(task)

        # Mock all agent runs
        async def mock_query_analyzer_run(state):
            return MOCK_QUERY_RESULT

        async def mock_multi_retriever_run(state):
            return {"search_results": MOCK_SEARCH_RESULTS, "partial_failures": []}

        async def mock_source_evaluator_run(state):
            return {"source_scores": MOCK_SOURCE_SCORES}

        async def mock_conflict_detector_run(state):
            return {"conflicts": MOCK_CONFLICTS}

        async def mock_evidence_chain_run(state):
            return {"evidence_chains": MOCK_EVIDENCE_CHAINS}

        async def mock_report_generator_run(state):
            return {"report": MOCK_REPORT}

        async def mock_self_reviewer_run(state):
            return MOCK_REVIEW

        with (
            patch("deepchoice.agents.orchestrator.QueryAnalyzerAgent.run", new=mock_query_analyzer_run),
            patch("deepchoice.agents.orchestrator.MultiRetrieverAgent.run", new=mock_multi_retriever_run),
            patch("deepchoice.agents.orchestrator.SourceEvaluatorAgent.run", new=mock_source_evaluator_run),
            patch("deepchoice.agents.orchestrator.ConflictDetectorAgent.run", new=mock_conflict_detector_run),
            patch("deepchoice.agents.orchestrator.EvidenceChainAgent.run", new=mock_evidence_chain_run),
            patch("deepchoice.agents.orchestrator.ReportGeneratorAgent.run", new=mock_report_generator_run),
            patch("deepchoice.agents.orchestrator.SelfReviewerAgent.run", new=mock_self_reviewer_run),
        ):
            result = await orchestrator.run_research_task()

        assert result["confidence"] == "high"
        assert result["report"] == MOCK_REPORT
        assert len(result["evidence_chains"]) == 1
        assert result["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_pipeline_triggers_retry_on_low_confidence(self):
        task = {"query": "test", "scene_context": "team", "constraints": [], "report_format": "evidence_first"}

        orchestrator = ChiefEditorAgent(task)
        call_count = {"self_review": 0}

        async def mock_run(state):
            return MOCK_QUERY_RESULT

        async def mock_search(state):
            return {"search_results": MOCK_SEARCH_RESULTS, "partial_failures": []}

        async def mock_eval(state):
            return {"source_scores": MOCK_SOURCE_SCORES}

        async def mock_conflict(state):
            return {"conflicts": []}

        async def mock_evidence(state):
            return {"evidence_chains": MOCK_EVIDENCE_CHAINS}

        async def mock_report(state):
            return {"report": MOCK_REPORT}

        async def mock_low_review(state):
            call_count["self_review"] += 1
            if call_count["self_review"] == 1:
                return {"confidence": "low", "knowledge_gaps": ["gap1"]}
            return {"confidence": "medium", "knowledge_gaps": []}

        with (
            patch("deepchoice.agents.orchestrator.QueryAnalyzerAgent.run", new=mock_run),
            patch("deepchoice.agents.orchestrator.MultiRetrieverAgent.run", new=mock_search),
            patch("deepchoice.agents.orchestrator.SourceEvaluatorAgent.run", new=mock_eval),
            patch("deepchoice.agents.orchestrator.ConflictDetectorAgent.run", new=mock_conflict),
            patch("deepchoice.agents.orchestrator.EvidenceChainAgent.run", new=mock_evidence),
            patch("deepchoice.agents.orchestrator.ReportGeneratorAgent.run", new=mock_report),
            patch("deepchoice.agents.orchestrator.SelfReviewerAgent.run", new=mock_low_review),
        ):
            result = await orchestrator.run_research_task()

        assert result["retry_count"] >= 1
```

- [ ] **Step 2: Run integration tests**

```bash
cd D:/deepchoice-agent && python -m pytest tests/test_pipeline.py -v
```

Expected: 2 tests PASS (pipeline completes, retry triggers on low confidence).

- [ ] **Step 3: Commit**

```bash
git add deepchoice/tests/test_pipeline.py
git commit -m "test: add full pipeline integration tests with mocked agents

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 17: Evaluation Framework + CI Script

**Owner:** AI skeleton (write eval runner, user reviews)

**Files:**
- Create: `deepchoice/tests/test_eval.py`

- [ ] **Step 1: Write test_eval.py**

```python
"""LLM-as-Judge evaluation runner for DeepChoice."""
import json
from pathlib import Path
from ..src.utils.llm import call_model

EVAL_PROMPT = """You are an impartial evaluator. Score this research report on 5 dimensions (1-5 each).

## Report
{report}

## Original Query
{query}

## Scoring Rubric
1. Factual Consistency (1-5): Are claims consistent with the cited sources? Deduct for hallucinated facts.
2. Evidence Sufficiency (1-5): Does each major claim have at least one source? Deduct for unsourced claims.
3. Reasoning Logic (1-5): Is the reasoning chain coherent? Deduct for logical gaps.
4. Honesty (1-5): Are gaps and uncertainties clearly stated? Deduct for overconfidence.
5. Completeness (1-5): Are all sub-questions answered? Deduct for missing dimensions.

Return ONLY a JSON object:
{{
  "factual_consistency": N,
  "evidence_sufficiency": N,
  "reasoning_logic": N,
  "honesty": N,
  "completeness": N,
  "total": N.N,
  "notes": "Brief justification"
}}"""


async def evaluate_report(query: str, report: str) -> dict:
    prompt = [{"role": "user", "content": EVAL_PROMPT.format(query=query, report=report)}]
    result = await call_model(prompt, model="deepseek-v4-flash", response_format="json")
    return result


async def run_regression_suite(known_cases_path: str, report_getter) -> dict:
    """Run evaluation on known cases. report_getter is async fn(query) -> report str."""
    cases = json.loads(Path(known_cases_path).read_text(encoding="utf-8"))
    results = []

    for case in cases[:30]:  # CI runs 30 cases
        report = await report_getter(case["query"])
        scores = await evaluate_report(case["query"], report)
        results.append({"case_id": case["id"], "scores": scores, "query": case["query"]})

    avg_total = sum(r["scores"]["total"] for r in results) / len(results) if results else 0
    return {
        "cases_evaluated": len(results),
        "average_total_score": round(avg_total, 2),
        "pass_threshold_3_5": avg_total >= 3.5,
        "results": results,
    }


if __name__ == "__main__":
    import asyncio
    # Standalone test: evaluate a sample report
    sample_query = "LangGraph vs CrewAI for AI agent orchestration"
    sample_report = "# Test\n\nThis is a sample report."
    result = asyncio.run(evaluate_report(sample_query, sample_report))
    print(json.dumps(result, indent=2))
```

- [ ] **Step 2: Run syntax check**

```bash
cd D:/deepchoice-agent && python -c "from deepchoice.tests.test_eval import evaluate_report; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add deepchoice/tests/test_eval.py
git commit -m "feat: add LLM-as-Judge evaluation framework with 5-dim scoring rubric

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Implementation Order Summary

| Task | Owner | Depends On | Estimated Time |
|------|-------|-----------|:---:|
| 1. Scaffolding | AI | — | 15min |
| 2. state.py + task.py | User | 1 | 1h |
| 3. Utils | AI | 1 | 30min |
| 4. source_evaluator.py | User | 2 | 2h |
| 5. query_analyzer.py | User | 3 | 1.5h |
| 6. Retrievers (6+dispatcher) | AI | 2,3 | 1.5h |
| 7. evidence_chain.py | User | 4 | 1h |
| 8. conflict_detector.py | User | 4 | 2.5h |
| 9. report_generator + formats | AI+User | 7 | 1h |
| 10. self_reviewer.py | User | 9 | 2h |
| 11. orchestrator.py | User | 5,6,8,10 | 2h |
| 12. Server + SSE | AI | 11 | 1h |
| 13. Streamlit frontend | AI | 12 | 30min |
| 14. Chroma KB setup | AI | 1 | 20min |
| 15. Test cases | User+AI | 1 | 4h |
| 16. Integration tests | AI | 11 | 30min |
| 17. Evaluation framework | AI | 2,3 | 30min |

**Critical path:** 1 → 2 → 4 → 7→8 → 10 → 9 → 11 → 12 → 13
**Total estimated time:** ~23.5h (matches spec Chapter 15 estimate)

