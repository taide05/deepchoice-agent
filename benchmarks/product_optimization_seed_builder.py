"""Build one isolated Chroma seed from the approved development sources.

The legacy ``chroma_kb`` tree is never read or modified.  The public builder
has one fixed ignored destination, publishes atomically, and refuses overwrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any, Callable

from benchmarks.product_baseline_experiment import embedding_revision, tree_hash
from benchmarks.product_optimization_seed import (
    EXPECTED_BUILDER_IDENTITY,
    EXPECTED_CHUNKING_IDENTITY,
    EXPECTED_COLLECTION_IDENTITY,
    EXPECTED_EMBEDDING_IDENTITY,
    EXPECTED_NORMALIZATION_IDENTITY,
    SCHEMA_VERSION,
    validate_seed_manifest,
)
from benchmarks.product_optimization_source_review import (
    ApprovedSourceReview,
    ROOT,
    load_approved_source_review,
)


SEED_ID = "product-optimization-knowledge-seed-v1"
BUILDER_POLICY_VERSION = "1"
MAX_CHUNK_CHARS = 1800
OVERLAP_PARAGRAPHS = 1
MAX_CHUNKS = 1024
SEED_PARENT = ROOT / "outputs" / "product-optimization-seeds"
SEED_ROOT = SEED_PARENT / SEED_ID
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")


class SeedBuildError(ValueError):
    """Body-free seed-build rejection."""


@dataclass(frozen=True, slots=True)
class SeedChunk:
    chunk_id: str
    source_id: str
    chunk_index: int
    text: str
    text_sha256: str


@dataclass(frozen=True, slots=True)
class BuiltSeed:
    seed_id: str
    path: Path
    source_count: int
    chunk_count: int
    seed_identity_sha256: str
    manifest_sha256: str
    admission_identity_sha256: str
    embedding_sha256: str
    payload_tree_sha256: str
    artifact_tree_sha256: str


def _fail(message: str) -> "Any":
    raise SeedBuildError(message)


def _is_redirected(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x0400
    ) or bool(hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _split_units(content: str) -> list[str]:
    units: list[str] = []
    for paragraph in (line for line in content.splitlines() if line):
        if len(paragraph) <= MAX_CHUNK_CHARS:
            units.append(paragraph)
            continue
        units.extend(
            paragraph[offset:offset + MAX_CHUNK_CHARS]
            for offset in range(0, len(paragraph), MAX_CHUNK_CHARS)
        )
    return units


def paragraph_window_chunks(source_id: str, content: str) -> tuple[SeedChunk, ...]:
    """Deterministic paragraph-window v2: 1800 chars, one-paragraph overlap."""

    if not _SAFE_ID.fullmatch(source_id) or not content or "\x00" in content:
        _fail("source identity or content is invalid for chunking")
    units = _split_units(content)
    if not units:
        _fail("source has no chunkable text")
    texts: list[str] = []
    start = 0
    while start < len(units):
        end = start
        length = 0
        while end < len(units):
            addition = len(units[end]) + (1 if end > start else 0)
            if end > start and length + addition > MAX_CHUNK_CHARS:
                break
            length += addition
            end += 1
        text = "\n".join(units[start:end])
        if not text or len(text) > MAX_CHUNK_CHARS:
            _fail("chunking exceeded its deterministic bound")
        texts.append(text)
        if end == len(units):
            break
        start = end - OVERLAP_PARAGRAPHS if end - start > OVERLAP_PARAGRAPHS else end
    chunks = tuple(
        SeedChunk(
            chunk_id=f"{source_id}:{index:04d}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}",
            source_id=source_id,
            chunk_index=index,
            text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        for index, text in enumerate(texts)
    )
    if not chunks or len(chunks) > MAX_CHUNKS:
        _fail("source chunk count exceeds the builder limit")
    return chunks


def _manifest(review: ApprovedSourceReview) -> dict[str, Any]:
    sources = []
    for source in review.sources:
        captured = datetime.fromisoformat(source.captured_at)
        if captured.tzinfo is None:
            _fail("approved source capture timestamp is not timezone-aware")
        retrieved_at = captured.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sources.append({
            "stable_id": source.target_id,
            "path": f"official/{source.target_id}.txt",
            "url": source.url,
            "source_kind": "official",
            "publisher": source.publisher,
            "retrieved_at": retrieved_at,
            "content_sha256": source.text_sha256,
            "encoding": "utf-8",
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "builder": dict(EXPECTED_BUILDER_IDENTITY),
        "normalization": dict(EXPECTED_NORMALIZATION_IDENTITY),
        "chunking": dict(EXPECTED_CHUNKING_IDENTITY),
        "embedding": dict(EXPECTED_EMBEDDING_IDENTITY),
        "collection": dict(EXPECTED_COLLECTION_IDENTITY),
        "sources": sources,
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)


def _prepare_inputs(root: Path, review: ApprovedSourceReview):
    data_root = root / "data"
    official_root = data_root / "official"
    official_root.mkdir(parents=True)
    for source in review.sources:
        _write_exclusive(
            official_root / f"{source.target_id}.txt", source.content.encode("utf-8")
        )
    manifest = _manifest(review)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    _write_exclusive(root / "seed-manifest.json", manifest_bytes)
    admitted = validate_seed_manifest(manifest, data_root)
    return admitted


def _chunk_review(review: ApprovedSourceReview) -> tuple[SeedChunk, ...]:
    chunks = tuple(
        chunk
        for source in review.sources
        for chunk in paragraph_window_chunks(source.target_id, source.content)
    )
    if not chunks or len(chunks) > MAX_CHUNKS or len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        _fail("aggregate chunk identity is empty, duplicated, or oversized")
    return chunks


def _embedding_matrix(model: Any, texts: list[str]):
    try:
        import numpy as np

        matrix = np.asarray(model.encode(texts), dtype="<f4")
    except Exception as exc:
        raise SeedBuildError("embedding model could not encode the approved chunks") from exc
    if matrix.ndim != 2 or matrix.shape[0] != len(texts) or matrix.shape[1] <= 0:
        _fail("embedding matrix shape is invalid")
    if not np.isfinite(matrix).all():
        _fail("embedding matrix contains non-finite values")
    return matrix


def _seed_identity(
    review: ApprovedSourceReview,
    admitted: Any,
    chunks: tuple[SeedChunk, ...],
    embedding_sha256: str,
) -> str:
    identity = {
        "seed_id": SEED_ID,
        "builder_policy_version": BUILDER_POLICY_VERSION,
        "review": {
            "byte_sha256": review.byte_sha256,
            "canonical_sha256": review.canonical_review_sha256,
        },
        "admission": {
            "manifest_sha256": admitted.manifest_sha256,
            "identity_sha256": admitted.admission_identity_sha256,
        },
        "chunking": {
            **dict(EXPECTED_CHUNKING_IDENTITY),
            "max_chunk_chars": MAX_CHUNK_CHARS,
            "overlap_paragraphs": OVERLAP_PARAGRAPHS,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "source_id": chunk.source_id,
                    "chunk_index": chunk.chunk_index,
                    "text_sha256": chunk.text_sha256,
                }
                for chunk in chunks
            ],
        },
        "embedding": {
            **dict(EXPECTED_EMBEDDING_IDENTITY),
            "matrix_sha256": embedding_sha256,
        },
        "collection": dict(EXPECTED_COLLECTION_IDENTITY),
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_model(*, model_name: str, revision: str, local_files_only: bool):
    from deepchoice.utils.embedding import SentenceTransformer

    return SentenceTransformer(
        model_name,
        revision=revision,
        local_files_only=local_files_only,
    )


def _default_client(path: Path):
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=str(path), settings=Settings(anonymized_telemetry=False)
    )


def _clear_chroma_system_cache() -> None:
    """Release Chroma's process-global System references before Windows rename."""

    try:
        from chromadb.api.client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception as exc:
        raise SeedBuildError("Chroma system cache could not be released") from exc


def _checkpoint_sqlite(chroma_root: Path) -> None:
    database = chroma_root / "chroma.sqlite3"
    if not database.is_file():
        _fail("Chroma did not create its SQLite database")
    try:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    except sqlite3.Error as exc:
        raise SeedBuildError("Chroma SQLite checkpoint failed") from exc
    if (chroma_root / "chroma.sqlite3-wal").exists():
        _fail("Chroma seed retained a WAL after checkpoint")


def _build_at(
    root: Path,
    review: ApprovedSourceReview,
    *,
    model_factory: Callable[..., Any] = _default_model,
    client_factory: Callable[[Path], Any] = _default_client,
) -> BuiltSeed:
    if _is_redirected(root.parent):
        _fail("seed destination must be under a regular parent")
    if root.exists():
        if _is_redirected(root) or not root.is_dir() or any(root.iterdir()):
            _fail("seed destination must be fresh")
    else:
        root.mkdir()
    admitted = _prepare_inputs(root, review)
    chunks = _chunk_review(review)
    frozen_model = EXPECTED_EMBEDDING_IDENTITY["model"]
    frozen_revision = EXPECTED_EMBEDDING_IDENTITY["revision"]
    if embedding_revision() != frozen_revision:
        _fail("cached embedding revision differs from the frozen identity")
    try:
        model = model_factory(
            model_name=frozen_model,
            revision=frozen_revision,
            local_files_only=True,
        )
    except Exception as exc:
        raise SeedBuildError("frozen embedding model could not be loaded locally") from exc
    if embedding_revision() != frozen_revision:
        _fail("cached embedding revision changed while the model was loaded")
    matrix = _embedding_matrix(model, [chunk.text for chunk in chunks])
    embedding_sha256 = hashlib.sha256(matrix.tobytes(order="C")).hexdigest()
    seed_identity = _seed_identity(review, admitted, chunks, embedding_sha256)
    by_source = {source.target_id: source for source in review.sources}
    metadatas = []
    for chunk in chunks:
        source = by_source[chunk.source_id]
        metadatas.append({
            "title": source.target_id,
            "source_type": "official",
            "url": source.url,
            "date": source.captured_at[:10],
            "target_id": source.target_id,
            "publisher": source.publisher,
            "scope_note": source.scope_note,
            "source_sha256": source.text_sha256,
            "review_sha256": review.canonical_review_sha256,
            "seed_identity_sha256": seed_identity,
            "chunk_index": chunk.chunk_index,
            "chunk_count": sum(item.source_id == chunk.source_id for item in chunks),
        })
    chroma_root = root / "chroma"
    client = client_factory(chroma_root)
    collection = client.get_or_create_collection(
        EXPECTED_COLLECTION_IDENTITY["name"],
        metadata={
            "seed_identity_sha256": seed_identity,
            "review_sha256": review.canonical_review_sha256,
        },
    )
    collection.add(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=metadatas,
        embeddings=matrix.tolist(),
    )
    if collection.count() != len(chunks):
        _fail("Chroma collection count differs from the frozen chunks")
    del collection
    try:
        client.close()
    except Exception as exc:
        raise SeedBuildError("Chroma client could not be closed") from exc
    del client
    _clear_chroma_system_cache()
    gc.collect()
    _checkpoint_sqlite(chroma_root)
    _write_exclusive(root / "learned_docs.json", b"{}\n")
    chunk_index = [
        {
            "chunk_id": chunk.chunk_id,
            "source_id": chunk.source_id,
            "chunk_index": chunk.chunk_index,
            "text_sha256": chunk.text_sha256,
            "text_chars": len(chunk.text),
        }
        for chunk in chunks
    ]
    _write_exclusive(
        root / "chunks.json",
        (json.dumps(chunk_index, sort_keys=True, indent=2) + "\n").encode("utf-8"),
    )
    payload_tree_sha256 = tree_hash(root)
    record = {
        "schema_version": 1,
        "seed_id": SEED_ID,
        "status": "frozen",
        "source_review_sha256": review.canonical_review_sha256,
        "source_review_byte_sha256": review.byte_sha256,
        "source_count": len(review.sources),
        "chunk_count": len(chunks),
        "manifest_sha256": admitted.manifest_sha256,
        "admission_identity_sha256": admitted.admission_identity_sha256,
        "embedding": dict(EXPECTED_EMBEDDING_IDENTITY),
        "embedding_sha256": embedding_sha256,
        "seed_identity_sha256": seed_identity,
        "payload_tree_sha256": payload_tree_sha256,
    }
    _write_exclusive(
        root / "build-record.json",
        (json.dumps(record, sort_keys=True, indent=2) + "\n").encode("utf-8"),
    )
    return BuiltSeed(
        seed_id=SEED_ID,
        path=root,
        source_count=len(review.sources),
        chunk_count=len(chunks),
        seed_identity_sha256=seed_identity,
        manifest_sha256=admitted.manifest_sha256,
        admission_identity_sha256=admitted.admission_identity_sha256,
        embedding_sha256=embedding_sha256,
        payload_tree_sha256=payload_tree_sha256,
        artifact_tree_sha256=tree_hash(root),
    )


def _publish_seed_copy(
    source: Path,
    destination: Path,
    parent: Path,
    expected_tree_sha256: str,
) -> None:
    """Publish through an unopened same-volume copy on Windows.

    Chroma's Rust/HNSW layer can retain source handles after ``Client.close``.
    A byte-identical copy has no such handles and can be atomically renamed.
    """

    if (
        destination.exists()
        or source.parent != parent
        or destination.parent != parent
        or not source.name.startswith(".pending-")
    ):
        _fail("seed publish paths are not fresh siblings")
    if tree_hash(source) != expected_tree_sha256:
        _fail("built seed tree changed before publication")
    publish = Path(tempfile.mkdtemp(prefix=".publish-", dir=parent))
    try:
        shutil.copytree(source, publish, dirs_exist_ok=True)
        if tree_hash(source) != expected_tree_sha256 or tree_hash(publish) != expected_tree_sha256:
            _fail("published seed copy differs from the built tree")
        publish.rename(destination)
    except Exception:
        try:
            shutil.rmtree(publish)
        except OSError:
            pass
        raise
    try:
        shutil.rmtree(source)
    except OSError:
        # The completed source remains under an ignored .pending-* name until
        # the process exits; the published copy is already hash-identical.
        pass


def build_frozen_seed() -> BuiltSeed:
    """Build and atomically publish the one current isolated seed artifact."""

    if SEED_ROOT != ROOT / "outputs" / "product-optimization-seeds" / SEED_ID:
        _fail("seed destination differs from the fixed ignored root")
    if SEED_ROOT.exists():
        _fail("seed destination already exists")
    if not SEED_PARENT.parent.is_dir() or _is_redirected(SEED_PARENT.parent):
        _fail("seed output parent is unavailable or redirected")
    SEED_PARENT.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=SEED_PARENT))
    try:
        built = _build_at(temporary, load_approved_source_review())
        _publish_seed_copy(
            temporary, SEED_ROOT, SEED_PARENT, built.artifact_tree_sha256
        )
    except Exception:
        try:
            shutil.rmtree(temporary)
        except OSError:
            pass
        raise
    return BuiltSeed(
        seed_id=built.seed_id,
        path=SEED_ROOT,
        source_count=built.source_count,
        chunk_count=built.chunk_count,
        seed_identity_sha256=built.seed_identity_sha256,
        manifest_sha256=built.manifest_sha256,
        admission_identity_sha256=built.admission_identity_sha256,
        embedding_sha256=built.embedding_sha256,
        payload_tree_sha256=built.payload_tree_sha256,
        artifact_tree_sha256=built.artifact_tree_sha256,
    )


__all__ = [
    "BuiltSeed",
    "SeedBuildError",
    "SeedChunk",
    "build_frozen_seed",
    "paragraph_window_chunks",
]
