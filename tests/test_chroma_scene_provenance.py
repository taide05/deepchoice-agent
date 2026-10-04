"""Local-only scene projection and frozen-source selection; no network or LLM."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from deepchoice.agents.conclusion_synthesizer import _summarize_chains
from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.source_evaluator import SourceEvaluatorAgent
from deepchoice.retrievers import chroma_kb
from deepchoice.retrievers.contracts import RetrievalRequest
from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY


CELERY_URL = "https://docs.celeryq.dev/en/stable/userguide/tasks.html"
CELERY_TARGET = "p04-celery-task-semantics"
ANCHOR = "A task message is not removed from the queue"
BODY = (
    "Navigation and unrelated material.\n" + ANCHOR +
    " until acknowledged by a worker. A failure may cause redelivery. "
    "Task functions must account for repeated execution and idempotent side effects. " * 3 +
    "The actual deployment still requires verification.\nPrev\nNavigation follows."
)
NAV = "Synchronous subtasks and blocking calls. " * 20


def _meta(target=CELERY_TARGET, url=CELERY_URL):
    return {
        "target_id": target,
        "url": url,
        "source_type": "official",
        "seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY,
        "title": target,
    }


def _index():
    return {
        "nav": (CELERY_TARGET, CELERY_URL, hashlib.sha256(NAV.encode()).hexdigest()),
        "body": (CELERY_TARGET, CELERY_URL, hashlib.sha256(BODY.encode()).hexdigest()),
    }


def test_audit_index_requires_exact_frozen_file_hashes(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "chroma").mkdir()
    digest = hashlib.sha256(BODY.encode()).hexdigest()
    chunk_id = f"{CELERY_TARGET}:0000:{digest[:16]}"
    chunks = json.dumps([{
        "chunk_id": chunk_id, "source_id": CELERY_TARGET, "text_sha256": digest,
    }]).encode()
    manifest = json.dumps({"sources": [{
        "stable_id": CELERY_TARGET, "url": CELERY_URL, "source_kind": "official",
    }]}).encode()
    (root / "chunks.json").write_bytes(chunks)
    (root / "seed-manifest.json").write_bytes(manifest)
    monkeypatch.setattr(chroma_kb, "_AUDITED_CHUNKS_SHA256", hashlib.sha256(chunks).hexdigest())
    monkeypatch.setattr(chroma_kb, "_AUDITED_MANIFEST_SHA256", hashlib.sha256(manifest).hexdigest())
    assert chroma_kb._load_audited_index(str(root / "chroma")) == {
        chunk_id: (CELERY_TARGET, CELERY_URL, digest)
    }
    (root / "chunks.json").write_bytes(chunks + b" ")
    assert chroma_kb._load_audited_index(str(root / "chroma")) == {}


def test_body_selection_requires_need_content_and_exact_provenance():
    result = {"ids": [["body"]], "documents": [[BODY]], "metadatas": [[_meta()]]}
    selected = chroma_kb._audited_body_excerpts(result, ("task_recovery",), _index())
    assert list(selected) == [CELERY_URL]
    assert selected[CELERY_URL].startswith(ANCHOR)
    assert len(selected[CELERY_URL]) <= 800
    assert "Navigation follows" not in selected[CELERY_URL]
    assert chroma_kb._audited_body_excerpts(result, (), _index()) == {}
    assert chroma_kb._audited_body_excerpts(result, ("backup",), _index()) == {}
    assert chroma_kb._audited_body_excerpts(result, ("task_recovery",), {}) == {}
    for mutation in (
        {"url": "https://example.org/tasks"},
        {"target_id": "p04-other"},
        {"seed_identity_sha256": "f" * 64},
    ):
        changed = {"ids": [["body"]], "documents": [[BODY]],
                   "metadatas": [[{**_meta(), **mutation}]]}
        assert chroma_kb._audited_body_excerpts(changed, ("task_recovery",), _index()) == {}
    changed_text = {"ids": [["body"]], "documents": [[BODY + " altered"]],
                    "metadatas": [[_meta()]]}
    assert chroma_kb._audited_body_excerpts(changed_text, ("task_recovery",), _index()) == {}


@pytest.mark.parametrize("target,url,need,anchor", [
    ("p01-sqlite-backup", "https://sqlite.org/backup.html", "backup",
     "If a power failure or operating system failure occurs while copying"),
    ("p01-postgresql-backup", "https://www.postgresql.org/docs/18/backup.html", "backup",
     "As with everything that contains valuable data"),
    ("p01-postgresql-text-search-introduction",
     "https://www.postgresql.org/docs/18/textsearch-intro.html", "full_text_search",
     "Full Text Searching (or just text search) provides"),
    (CELERY_TARGET, CELERY_URL, "task_recovery", ANCHOR),
])
def test_each_target_requires_its_specific_original_capability(target, url, need, anchor):
    document = "Navigation\n" + anchor + " verified conditions and limitations. " * 16
    digest = hashlib.sha256(document.encode()).hexdigest()
    result = {"ids": [["reviewed"]], "documents": [[document]],
              "metadatas": [[_meta(target, url)]]}
    index = {"reviewed": (target, url, digest)}
    excerpt = chroma_kb._audited_body_excerpts(result, (need,), index)[url]
    assert excerpt.startswith(anchor)
    assert len(excerpt) <= 800
    assert chroma_kb._audited_body_excerpts(result, (), index) == {}


@pytest.mark.asyncio
async def test_verified_late_body_replaces_wrong_section_and_reaches_synthesis(monkeypatch):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    calls = 0

    def query(**_kwargs):
        nonlocal calls
        calls += 1
        doc_id, document = ("nav", NAV) if calls == 1 else ("body", BODY)
        return {"ids": [[doc_id]], "documents": [[document]], "metadatas": [[_meta()]]}

    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever.collection = SimpleNamespace(query=query)
    retriever._audited_index = _index()
    response = await retriever.retrieve(RetrievalRequest(
        query="FastAPI versus Celery",
        adapted_queries=("model search hint",),
        local_scene_needs=("task_recovery",),
        max_results=1,
    ))
    assert response.status == "success"
    assert calls == 2
    assert len(response.results) == 1
    assert response.results[0]["snippet"].startswith(ANCHOR)
    assert "idempotent" in " ".join(response.results[0]["_source_scope_sentences"])
    assert "Synchronous subtasks" not in " ".join(response.results[0]["_source_scope_sentences"])
    scored = (await SourceEvaluatorAgent().run({
        "task": {"candidate_techs": ["FastAPI", "Celery"]},
        "search_results": [response.model_dump()],
    }))["source_scores"]
    prompt, mapping = _summarize_chains(build_evidence_chain(scored, []))
    assert mapping == {1: CELERY_TARGET}
    assert "idempotent" in prompt
    assert "Synchronous subtasks" not in prompt


@pytest.mark.asyncio
async def test_model_hint_alone_cannot_promote_audited_body(monkeypatch):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever.collection = SimpleNamespace(query=lambda **_kwargs: {
        "ids": [["nav", "body"]], "documents": [[NAV, BODY]],
        "metadatas": [[_meta(), _meta()]],
    })
    retriever._audited_index = _index()
    results = await retriever._do_search(
        "No task recovery needed", [], 1,
        adapted_queries=["need restart recovery"], local_scene_needs=(),
    )
    assert results[0]["snippet"].startswith("Synchronous subtasks")


@pytest.mark.asyncio
async def test_unverified_selected_chunk_cannot_borrow_verified_same_url_body(monkeypatch):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever.collection = SimpleNamespace(query=lambda **_kwargs: {
        "ids": [["fake-nav", "body"]], "documents": [[NAV, BODY]],
        "metadatas": [[_meta(), _meta()]],
    })
    retriever._audited_index = {"body": _index()["body"]}
    results = await retriever._do_search(
        "FastAPI versus Celery", [], 1, local_scene_needs=("task_recovery",),
    )
    assert results[0]["snippet"] == NAV[:500]
    assert "_seed_excerpt_window" not in results[0]
    assert "_source_scope_sentences" not in results[0]


@pytest.mark.asyncio
async def test_replaced_audited_excerpt_clears_unavailable_new_chunk_scope(monkeypatch):
    monkeypatch.setattr(chroma_kb, "get_embedding_model", lambda: SimpleNamespace(
        encode=lambda _query: SimpleNamespace(tolist=lambda: [0.1, 0.2])
    ))
    large_body = BODY + " Additional documented conditions." * 90
    large_digest = hashlib.sha256(large_body.encode()).hexdigest()
    index = {
        "nav": _index()["nav"],
        "large-body": (CELERY_TARGET, CELERY_URL, large_digest),
    }
    calls = 0

    def query(**_kwargs):
        nonlocal calls
        calls += 1
        doc_id, document = ("nav", NAV) if calls == 1 else ("large-body", large_body)
        return {"ids": [[doc_id]], "documents": [[document]], "metadatas": [[_meta()]]}

    retriever = object.__new__(chroma_kb.ChromaKB)
    retriever.collection = SimpleNamespace(query=query)
    retriever._audited_index = index
    results = await retriever._do_search(
        "FastAPI versus Celery", [], 1,
        adapted_queries=["model search hint"], local_scene_needs=("task_recovery",),
    )
    assert len(results) == 1
    assert results[0]["snippet"].startswith(ANCHOR)
    assert "_source_scope_sentences" not in results[0]
