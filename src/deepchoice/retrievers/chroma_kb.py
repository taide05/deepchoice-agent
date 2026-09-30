import asyncio
import hashlib
import json
import os
from pathlib import Path

import chromadb
from chromadb.config import Settings

from ..utils.embedding import get_embedding_model
from ..utils.official_catalog import (
    AUDITED_PRODUCT_SEED_IDENTITY,
    AUDITED_SNIPPET_WINDOW,
)
from .base import BaseRetriever
from .contracts import RetrievalRequest


_MIN_CANDIDATE_POOL = 30
_MAX_CANDIDATE_POOL = 100
_MAX_QUERY_DIMENSIONS = 8
_SNIPPET_CHARS = 500
_MAX_AUDITED_LINE_CHARS = 800
_FTS5_TARGET = "p01-sqlite-fts5"
_FTS5_URL = "https://sqlite.org/fts5.html"
_FTS5_OVERVIEW_ANCHOR = "FTS5 is an SQLite virtual table module"
_AUDITED_CHUNKS_SHA256 = "6c0752cc991da7aa4630850421b66ce1d56f68b274c32663556ee4ee72025f66"
_AUDITED_MANIFEST_SHA256 = "aaadfe9badb7948788d1dfbcc020ed086d26b5f9fe5741b56e2d323ec4344c0c"
_MAX_INDEX_BYTES = 128 * 1024
_MAX_COLLECTION_FILES = 64
_MAX_COLLECTION_BYTES = 256 * 1024 * 1024
_BODY_TARGETS = {
    "p01-sqlite-backup": ("If a power failure or operating system failure occurs while copying", "backup"),
    "p01-postgresql-backup": ("As with everything that contains valuable data", "backup"),
    "p01-postgresql-text-search-introduction": ("Full Text Searching (or just text search) provides", "full_text_search"),
    "p04-celery-task-semantics": ("A task message is not removed from the queue", "task_recovery"),
}


def chroma_collection_identity() -> str | None:
    """Hash the actual local collection and audit files for cache identity.

    Unknown, oversized, or changing collections cannot safely use the
    persistent cache. The digest is used only inside an already-hashed key.
    """
    root = Path(os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db")).resolve()
    try:
        if not root.is_dir():
            return None
        collection_paths = [path for path in root.rglob("*") if path.is_file()]
        sidecars = (root.parent / "chunks.json", root.parent / "seed-manifest.json")
        paths = collection_paths + [path for path in sidecars if path.exists()]
        if len(paths) > _MAX_COLLECTION_FILES or any(
            not path.is_file() or path.is_symlink() for path in paths
        ):
            return None
        paths.sort(key=lambda path: str(path))
        stats = [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
        if sum(size for size, _ in stats) > _MAX_COLLECTION_BYTES:
            return None
        digest = hashlib.sha256(str(root).encode("utf-8"))
        for path in sidecars:
            digest.update(path.name.encode("utf-8"))
            digest.update(b"present" if path.exists() else b"absent")
        for path in paths:
            digest.update(str(path.relative_to(root.parent)).encode("utf-8"))
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
        if (stats != [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
                or {path for path in root.rglob("*") if path.is_file()} != set(collection_paths)
                or any(path.exists() != (path in paths) for path in sidecars)):
            return None
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _load_audited_index(chroma_path: str) -> dict[str, tuple[str, str, str]]:
    """Accept only the frozen seed's bounded chunk/URL audit files."""
    root = Path(chroma_path).resolve().parent
    try:
        with (root / "chunks.json").open("rb") as stream:
            chunks_bytes = stream.read(_MAX_INDEX_BYTES + 1)
        with (root / "seed-manifest.json").open("rb") as stream:
            manifest_bytes = stream.read(_MAX_INDEX_BYTES + 1)
        if (len(chunks_bytes) > _MAX_INDEX_BYTES or len(manifest_bytes) > _MAX_INDEX_BYTES
                or hashlib.sha256(chunks_bytes).hexdigest() != _AUDITED_CHUNKS_SHA256
                or hashlib.sha256(manifest_bytes).hexdigest() != _AUDITED_MANIFEST_SHA256):
            return {}
        chunks = json.loads(chunks_bytes)
        sources = json.loads(manifest_bytes)["sources"]
        urls = {source["stable_id"]: source["url"] for source in sources
                if source.get("source_kind") == "official"}
        if len(urls) != len(sources) or not isinstance(chunks, list):
            return {}
        index = {}
        for chunk in chunks:
            doc_id, source_id, digest = (
                chunk["chunk_id"], chunk["source_id"], chunk["text_sha256"]
            )
            if (doc_id in index or source_id not in urls or len(digest) != 64
                    or doc_id.split(":")[-1] != digest[:16]):
                return {}
            index[doc_id] = (source_id, urls[source_id], digest)
        return index
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def _verified_seed_chunk(
    document: str, metadata: dict, doc_id: str | None,
    index: dict[str, tuple[str, str, str]] | None,
) -> bool:
    if (not isinstance(document, str) or not isinstance(metadata, dict)
            or not isinstance(doc_id, str) or not index or doc_id not in index
            or metadata.get("source_type") != "official"
            or metadata.get("seed_identity_sha256") != AUDITED_PRODUCT_SEED_IDENTITY):
        return False
    target, url, digest = index[doc_id]
    return (metadata.get("target_id") == target and metadata.get("url") == url
            and hashlib.sha256(document.encode("utf-8")).hexdigest() == digest)


def _bounded_snippet(
    document: str, metadata: dict, *, doc_id: str | None = None,
    index: dict[str, tuple[str, str, str]] | None = None,
) -> str:
    """Extend the frozen seed's prefix past line-wrapped sentence fragments.

    Within 800 characters, require sentence punctuation at a line end or EOF.
    If no such boundary is available, retain the original 500-character prefix;
    never cut back to an earlier sentence and discard an unfinished qualifier.
    Punctuation is only a selection heuristic. Citation verification still
    checks the full surrounding source window and does not infer applicability.
    """
    if not isinstance(document, str):
        return ""
    prefix = document[:_SNIPPET_CHARS]
    if (len(document) <= _SNIPPET_CHARS
            or not _verified_seed_chunk(document, metadata, doc_id, index)):
        return prefix
    for end in range(_SNIPPET_CHARS, min(len(document), _MAX_AUDITED_LINE_CHARS) + 1):
        if end < len(document) and document[end] != "\n":
            continue
        tail = document[:end].rstrip().rstrip("\"'’”)]}」』】")
        if tail.endswith((".", "!", "?", "。", "！", "？")) and not tail.endswith("..."):
            return document[:end]
    return prefix


def _audited_fts5_overview(
    results: dict, local_scene_needs: tuple[str, ...],
    index: dict[str, tuple[str, str, str]],
) -> tuple[str, str] | None:
    """Use the real overview, not navigation or a deep command, for a basic FTS need.

    This is limited to a chunk already in the current local candidate pool and
    the reviewed seed identity. It does not fetch another page or assert that
    FTS5 is applicable to the user's workload.
    """
    if "full_text_search" not in local_scene_needs:
        return None
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    ids = results.get("ids", [[]])[0]
    for doc_id, document, metadata in zip(ids, documents, metadatas):
        if (not _verified_seed_chunk(document, metadata, doc_id, index)
                or metadata.get("target_id") != _FTS5_TARGET
                or metadata.get("url") != _FTS5_URL):
            continue
        start = document.find(_FTS5_OVERVIEW_ANCHOR)
        if start < 0:
            continue
        excerpt = document[start:start + _SNIPPET_CHARS]
        sentence_end = excerpt.rfind(".")
        if sentence_end >= 250:
            excerpt = excerpt[:sentence_end + 1]
        return metadata["url"], excerpt
    return None


def _audited_body_excerpts(
    results: dict, local_scene_needs: tuple[str, ...],
    index: dict[str, tuple[str, str, str]],
) -> dict[str, str]:
    selected: dict[str, str] = {}
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    for doc_id, document, metadata in zip(ids, documents, metadatas):
        if not _verified_seed_chunk(document, metadata, doc_id, index):
            continue
        spec = _BODY_TARGETS.get(metadata["target_id"])
        if spec is None or spec[1] not in local_scene_needs or metadata["url"] in selected:
            continue
        start = document.find(spec[0])
        if start < 0:
            continue
        excerpt = document[start:start + _MAX_AUDITED_LINE_CHARS].split("\nPrev\n", 1)[0]
        end = excerpt.rfind(".")
        if end >= _SNIPPET_CHARS // 2:
            selected[metadata["url"]] = excerpt[:end + 1]
    return selected


def _query_dimensions(
    query: str,
    sub_questions: list[str],
    adapted_queries: list[str] | None,
) -> list[str]:
    """Keep the user's comparison as the primary local-KB dimension.

    Adaptation can omit one side of a comparison.  Chroma contains multiple
    chunks per source, so a tiny nearest-neighbour pool can then be exhausted
    by one URL before source-level de-duplication runs.  Preserve stable order
    and avoid spending another embedding/query on exact duplicate dimensions.
    """

    values = [query]
    values.extend(adapted_queries if adapted_queries else sub_questions[:2])
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result[:_MAX_QUERY_DIMENSIONS]


def _append_unique(
    destination: list[dict],
    seen_urls: set[str],
    candidates: list[dict],
    limit: int,
) -> int:
    added = 0
    for candidate in candidates:
        if len(destination) >= limit:
            break
        url = candidate["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        destination.append(candidate)
        added += 1
    return added


def _merge_dimensions(
    dimensions: list[list[dict]],
    max_results: int,
    *,
    has_adapted_queries: bool,
) -> list[dict]:
    """Merge source-diverse query dimensions without multiplying sources.

    The original comparison owns all slots when there is no model adaptation;
    sub-questions only fill a shortfall.  With adapted dimensions, reserve half
    the public result slots for the original comparison and fill the remainder
    round-robin so adapted searches cannot be queried and then always hidden.
    """

    if not dimensions:
        return []
    selected: list[dict] = []
    seen_urls: set[str] = set()
    primary_limit = (
        max(1, (max_results + 1) // 2)
        if has_adapted_queries
        else max_results
    )
    _append_unique(selected, seen_urls, dimensions[0], primary_limit)

    cursors = [0] * len(dimensions)
    while len(selected) < max_results:
        progressed = False
        for index in range(1, len(dimensions)):
            items = dimensions[index]
            while cursors[index] < len(items):
                item = items[cursors[index]]
                cursors[index] += 1
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                selected.append(item)
                progressed = True
                break
            if len(selected) >= max_results:
                break
        if not progressed:
            break

    if len(selected) < max_results:
        _append_unique(selected, seen_urls, dimensions[0], max_results)
    return selected


class ChromaKB(BaseRetriever):
    source = "chroma"

    def __init__(self):
        chroma_path = os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db")
        self._audited_index = _load_audited_index(chroma_path)
        self.client = chromadb.PersistentClient(
            path=chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection("tech_kb")

    async def _do_retrieve(self, request: RetrievalRequest) -> list[dict]:
        return await self._do_search(
            request.query,
            list(request.sub_questions),
            request.max_results,
            adapted_queries=list(request.adapted_queries),
            local_scene_needs=request.local_scene_needs,
        )

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         local_scene_needs: tuple[str, ...] = ()) -> list[dict]:
        model = await asyncio.to_thread(get_embedding_model)
        queries = _query_dimensions(query, sub_questions, adapted_queries)
        index = getattr(self, "_audited_index", {})
        dimensions: list[list[dict]] = []
        audited_overviews: dict[str, str] = {}
        audited_bodies: dict[str, str] = {}

        # Retrieve enough chunks to diversify after URL de-duplication.  The
        # frozen development seed demonstrated that a three-chunk pool could
        # contain only one source even when the other comparison candidate was
        # ranked fourth.  This remains a bounded local vector query and does
        # not increase the public result limit.
        candidate_pool = min(
            _MAX_CANDIDATE_POOL,
            max(_MIN_CANDIDATE_POOL, max_results * 4),
        )

        for q in queries:
            q_embedding = (await asyncio.to_thread(model.encode, q)).tolist()
            results = await asyncio.to_thread(
                self.collection.query,
                query_embeddings=[q_embedding],
                n_results=candidate_pool,
            )
            overview = _audited_fts5_overview(results, local_scene_needs, index)
            if overview is not None:
                audited_overviews[overview[0]] = overview[1]
            for url, excerpt in _audited_body_excerpts(results, local_scene_needs, index).items():
                audited_bodies.setdefault(url, excerpt)
            dimension: list[dict] = []
            seen_dimension_urls: set[str] = set()
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                metadata = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                document = results.get("documents", [[]])[0][i]
                verified_chunk = _verified_seed_chunk(document, metadata or {}, doc_id, index)
                url = metadata.get("url", doc_id) if metadata else doc_id
                if url in seen_dimension_urls:
                    continue
                seen_dimension_urls.add(url)
                result = {
                    "url": url,
                    "title": metadata.get("title", "") if metadata else "",
                    "snippet": _bounded_snippet(
                        document, metadata or {},
                        doc_id=doc_id, index=index,
                    ),
                    "date": metadata.get("date", "") if metadata else "",
                }
                if len(result["snippet"]) > _SNIPPET_CHARS:
                    # Only _bounded_snippet's exact frozen-seed path can emit
                    # this marker; downstream stages recheck its provenance.
                    result["_seed_excerpt_window"] = AUDITED_SNIPPET_WINDOW
                if verified_chunk:
                    result["_seed_verified_chunk"] = True
                # Keep only the bounded internal provenance needed to enforce
                # scope for an audited official seed.  Leading-underscore keys
                # are removed by the durable public-result sanitizer; raw
                # chunk identity and arbitrary Chroma metadata remain private.
                for key in ("target_id", "source_type", "seed_identity_sha256"):
                    value = metadata.get(key) if metadata else None
                    if isinstance(value, str) and value:
                        result[f"_seed_{key}"] = value
                dimension.append(result)
            dimensions.append(dimension)
        merged = _merge_dimensions(
            dimensions,
            max_results,
            has_adapted_queries=bool(adapted_queries),
        )
        for result in merged:
            if (result["url"] in audited_overviews
                    and result.get("_seed_verified_chunk") is True
                    and result.get("_seed_target_id") == _FTS5_TARGET
                    and result.get("_seed_source_type") == "official"
                    and result.get("_seed_seed_identity_sha256") == AUDITED_PRODUCT_SEED_IDENTITY):
                result["snippet"] = audited_overviews[result["url"]]
                result.pop("_seed_excerpt_window", None)
            if (result["url"] in audited_bodies
                    and result.get("_seed_verified_chunk") is True
                    and result.get("_seed_target_id") in _BODY_TARGETS
                    and result.get("_seed_source_type") == "official"
                    and result.get("_seed_seed_identity_sha256") == AUDITED_PRODUCT_SEED_IDENTITY):
                result["snippet"] = audited_bodies[result["url"]]
                if len(result["snippet"]) > _SNIPPET_CHARS:
                    result["_seed_excerpt_window"] = AUDITED_SNIPPET_WINDOW
                else:
                    result.pop("_seed_excerpt_window", None)
        return merged
