"""Offline tests for the isolated approved-source seed builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from benchmarks import product_optimization_seed_builder as builder
from benchmarks.product_optimization_source_review import (
    ApprovedDevelopmentSource,
    ApprovedSourceReview,
)


def _review(content: str = "First paragraph.\nSecond paragraph.\nThird paragraph.") -> ApprovedSourceReview:
    encoded = content.encode("utf-8")
    source = ApprovedDevelopmentSource(
        target_id="p01-sqlite-guide",
        parent_catalog_key="sqlite",
        case_ids=("P01",),
        approved_topics=("backup",),
        url="https://sqlite.org/guide.html",
        publisher="SQLite Project",
        scope_note="bounded-test-scope",
        receipt_sha256="a" * 64,
        raw_sha256="b" * 64,
        text_sha256=hashlib.sha256(encoded).hexdigest(),
        captured_at="2026-09-24T12:00:00+00:00",
        content=content,
        text_bytes=len(encoded),
    )
    return ApprovedSourceReview(
        review_id="review",
        canonical_review_sha256="c" * 64,
        byte_sha256="d" * 64,
        plan_id="plan",
        sources=(source,),
        total_text_bytes=len(encoded),
    )


class FakeModel:
    init_calls = []

    def __init__(self, *, model_name, revision, local_files_only):  # type: ignore[no-untyped-def]
        self.init_calls.append((model_name, revision, local_files_only))

    def encode(self, texts):  # type: ignore[no-untyped-def]
        return np.asarray(
            [[float(index + 1), float(len(text)), 0.5] for index, text in enumerate(texts)],
            dtype=np.float32,
        )


class FakeCollection:
    def __init__(self) -> None:
        self.ids = []
        self.documents = []
        self.metadatas = []
        self.embeddings = []

    def add(self, *, ids, documents, metadatas, embeddings):  # type: ignore[no-untyped-def]
        self.ids = list(ids)
        self.documents = list(documents)
        self.metadatas = list(metadatas)
        self.embeddings = list(embeddings)

    def count(self) -> int:
        return len(self.ids)


class FakeClient:
    def __init__(self, path: Path) -> None:
        path.mkdir(parents=True)
        with sqlite3.connect(path / "chroma.sqlite3") as connection:
            connection.execute("CREATE TABLE seed_test (value INTEGER)")
        self.collection = FakeCollection()
        self.collection_metadata = None
        self.closed = False

    def get_or_create_collection(self, name, metadata):  # type: ignore[no-untyped-def]
        assert name == "tech_kb"
        self.collection_metadata = dict(metadata)
        return self.collection

    def close(self) -> None:
        self.closed = True


def test_paragraph_window_chunks_are_bounded_deterministic_and_overlap(monkeypatch) -> None:
    monkeypatch.setattr(builder, "MAX_CHUNK_CHARS", 12)
    content = "alpha\nbeta\ngamma\ndelta"

    first = builder.paragraph_window_chunks("p01-demo", content)
    second = builder.paragraph_window_chunks("p01-demo", content)

    assert first == second
    assert [chunk.text for chunk in first] == ["alpha\nbeta", "beta\ngamma", "gamma\ndelta"]
    assert all(len(chunk.text) <= 12 for chunk in first)
    assert len({chunk.chunk_id for chunk in first}) == len(first)


def test_long_paragraph_is_split_without_loss(monkeypatch) -> None:
    monkeypatch.setattr(builder, "MAX_CHUNK_CHARS", 5)
    chunks = builder.paragraph_window_chunks("p01-demo", "abcdefghijk")

    assert "".join(chunk.text for chunk in chunks) == "abcdefghijk"
    assert [len(chunk.text) for chunk in chunks] == [5, 5, 1]


def test_build_at_creates_valid_manifest_collection_and_frozen_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder,
        "embedding_revision",
        lambda: builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
    )
    clients = []
    cache_clears = []
    monkeypatch.setattr(builder, "_clear_chroma_system_cache", lambda: cache_clears.append(True))

    def client_factory(path: Path) -> FakeClient:
        client = FakeClient(path)
        clients.append(client)
        return client

    result = builder._build_at(
        tmp_path / "seed",
        _review(),
        model_factory=FakeModel,
        client_factory=client_factory,
    )

    assert result.source_count == 1
    assert result.chunk_count >= 1
    assert len(result.seed_identity_sha256) == 64
    assert len(result.embedding_sha256) == 64
    assert len(result.payload_tree_sha256) == 64
    assert len(result.artifact_tree_sha256) == 64
    assert result.payload_tree_sha256 != result.artifact_tree_sha256
    assert (result.path / "data" / "official" / "p01-sqlite-guide.txt").read_text() == _review().sources[0].content
    assert json.loads((result.path / "learned_docs.json").read_text()) == {}
    record = json.loads((result.path / "build-record.json").read_text())
    assert record["seed_identity_sha256"] == result.seed_identity_sha256
    assert record["source_count"] == 1
    assert record["chunk_count"] == result.chunk_count
    assert clients[0].collection.count() == result.chunk_count
    assert clients[0].closed is True
    assert cache_clears == [True]
    assert all(item["source_type"] == "official" for item in clients[0].collection.metadatas)
    assert all(item["url"] == "https://sqlite.org/guide.html" for item in clients[0].collection.metadatas)
    assert FakeModel.init_calls[-1] == (
        builder.EXPECTED_EMBEDDING_IDENTITY["model"],
        builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
        True,
    )


def test_default_model_binds_frozen_revision_and_offline_mode(monkeypatch) -> None:
    calls = []
    sentinel = object()

    def fake_constructor(model_name, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((model_name, kwargs))
        return sentinel

    from deepchoice.utils import embedding

    monkeypatch.setattr(embedding, "SentenceTransformer", fake_constructor)

    assert builder._default_model(
        model_name=builder.EXPECTED_EMBEDDING_IDENTITY["model"],
        revision=builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
        local_files_only=True,
    ) is sentinel
    assert calls == [(
        builder.EXPECTED_EMBEDDING_IDENTITY["model"],
        {
            "revision": builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
            "local_files_only": True,
        },
    )]


def test_logical_seed_identity_is_reproducible_across_fresh_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder,
        "embedding_revision",
        lambda: builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
    )
    first = builder._build_at(
        tmp_path / "first", _review(), model_factory=FakeModel,
        client_factory=FakeClient,
    )
    second = builder._build_at(
        tmp_path / "second", _review(), model_factory=FakeModel,
        client_factory=FakeClient,
    )

    assert first.seed_identity_sha256 == second.seed_identity_sha256
    assert first.embedding_sha256 == second.embedding_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.admission_identity_sha256 == second.admission_identity_sha256


def test_build_rejects_embedding_revision_or_matrix_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "embedding_revision", lambda: "0" * 40)
    with pytest.raises(builder.SeedBuildError, match="revision"):
        builder._build_at(
            tmp_path / "wrong-revision", _review(), model_factory=FakeModel,
            client_factory=FakeClient,
        )

    monkeypatch.setattr(
        builder,
        "embedding_revision",
        lambda: builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
    )

    class BadModel:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def encode(self, texts):  # type: ignore[no-untyped-def]
            return np.asarray([1.0, 2.0], dtype=np.float32)

    with pytest.raises(builder.SeedBuildError, match="shape"):
        builder._build_at(
            tmp_path / "bad-shape", _review(), model_factory=BadModel,
            client_factory=FakeClient,
        )


def test_build_rechecks_cached_revision_after_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revisions = iter((builder.EXPECTED_EMBEDDING_IDENTITY["revision"], "0" * 40))
    monkeypatch.setattr(builder, "embedding_revision", lambda: next(revisions))

    with pytest.raises(builder.SeedBuildError, match="changed while"):
        builder._build_at(
            tmp_path / "changed-revision",
            _review(),
            model_factory=FakeModel,
            client_factory=FakeClient,
        )


def test_build_rejects_nonfresh_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "seed"
    root.mkdir()
    (root / "existing.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        builder,
        "embedding_revision",
        lambda: builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
    )

    with pytest.raises(builder.SeedBuildError, match="fresh"):
        builder._build_at(
            root, _review(), model_factory=FakeModel, client_factory=FakeClient
        )

    assert (root / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_public_builder_atomically_publishes_fixed_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    outputs = root / "outputs"
    outputs.mkdir(parents=True)
    parent = outputs / "product-optimization-seeds"
    destination = parent / builder.SEED_ID
    monkeypatch.setattr(builder, "ROOT", root)
    monkeypatch.setattr(builder, "SEED_PARENT", parent)
    monkeypatch.setattr(builder, "SEED_ROOT", destination)
    monkeypatch.setattr(builder, "load_approved_source_review", _review)

    def fake_build_at(path, review):  # type: ignore[no-untyped-def]
        assert path.parent == parent
        assert review.sources[0].target_id == "p01-sqlite-guide"
        (path / "marker.txt").write_text("complete", encoding="utf-8")
        artifact_tree = builder.tree_hash(path)
        return builder.BuiltSeed(
            seed_id=builder.SEED_ID,
            path=path,
            source_count=1,
            chunk_count=1,
            seed_identity_sha256="1" * 64,
            manifest_sha256="2" * 64,
            admission_identity_sha256="3" * 64,
            embedding_sha256="4" * 64,
            payload_tree_sha256="5" * 64,
            artifact_tree_sha256=artifact_tree,
        )

    monkeypatch.setattr(builder, "_build_at", fake_build_at)

    result = builder.build_frozen_seed()

    assert result.path == destination
    assert (destination / "marker.txt").read_text(encoding="utf-8") == "complete"
    assert not list(parent.glob(".pending-*"))


def test_real_chroma_build_publishes_through_hash_identical_unopened_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder,
        "embedding_revision",
        lambda: builder.EXPECTED_EMBEDDING_IDENTITY["revision"],
    )
    source = tmp_path / ".pending-seed"
    destination = tmp_path / "published"

    built = builder._build_at(source, _review(), model_factory=FakeModel)
    builder._publish_seed_copy(
        built.path, destination, tmp_path, built.artifact_tree_sha256
    )

    assert destination.is_dir()
    assert (destination / "build-record.json").is_file()
    assert builder.tree_hash(destination) == built.artifact_tree_sha256
    assert not list(tmp_path.glob(".publish-*"))
    if source.exists():
        assert source.name.startswith(".pending-")
