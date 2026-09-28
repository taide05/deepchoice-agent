import asyncio
import os
import re

import chromadb
from chromadb.config import Settings

from ..utils.embedding import get_embedding_model
from ..utils.official_catalog import (
    AUDITED_PRODUCT_SEED_IDENTITY,
    AUDITED_SNIPPET_WINDOW,
)
from .base import BaseRetriever


_MIN_CANDIDATE_POOL = 30
_MAX_CANDIDATE_POOL = 100
_MAX_QUERY_DIMENSIONS = 8
_SNIPPET_CHARS = 500
_MAX_AUDITED_LINE_CHARS = 800
_FTS5_TARGET = "p01-sqlite-fts5"
_FTS5_URL = "https://sqlite.org/fts5.html"
_FTS5_OVERVIEW_ANCHOR = "FTS5 is an SQLite virtual table module"
_CAPABILITY_CLAUSE_SPLIT = re.compile(
    r"[，,；;。\n]+|但(?:是)?|不过|并且|且|\b(?:but|however|and)\b", re.I,
)
_NEGATED_CAPABILITY = re.compile(
    r"不需要|无需|不要求|不必|不是必须|并非必须|非必须|不要|不能|禁止|避免|不使用|"
    r"\b(?:do not|does not|don't|doesn't|not|no|without|avoid|prohibit|must not)\b",
    re.I,
)


def _bounded_snippet(document: str, metadata: dict) -> str:
    """Finish one bounded source line only for the frozen official seed.

    The original 500-character prefix remains the fallback. A larger prefix is
    emitted only when its first post-boundary newline occurs within 800 chars.
    A line ending is not a semantic proof that all conditions were captured;
    the function never splices disconnected text or changes source authority.
    """
    if not isinstance(document, str):
        return ""
    prefix = document[:_SNIPPET_CHARS]
    if (len(document) <= _SNIPPET_CHARS
            or not isinstance(metadata, dict)
            or metadata.get("source_type") != "official"
            or metadata.get("seed_identity_sha256") != AUDITED_PRODUCT_SEED_IDENTITY
            or not isinstance(metadata.get("target_id"), str)):
        return prefix
    end = document.find("\n", _SNIPPET_CHARS, _MAX_AUDITED_LINE_CHARS + 1)
    return document[:end] if end >= 0 else prefix


def _audited_fts5_overview(results: dict, query: str) -> tuple[str, str] | None:
    """Use the real overview, not navigation or a deep command, for a basic FTS need.

    This is limited to a chunk already in the current local candidate pool and
    the reviewed seed identity. It does not fetch another page or assert that
    FTS5 is applicable to the user's workload.
    """
    if not any(
        any(term in clause.casefold() for term in ("全文检索", "full-text search", "full text search"))
        and not _NEGATED_CAPABILITY.search(clause)
        for clause in _CAPABILITY_CLAUSE_SPLIT.split(query)
    ):
        return None
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    for document, metadata in zip(documents, metadatas):
        if (not isinstance(document, str) or not isinstance(metadata, dict)
                or metadata.get("source_type") != "official"
                or metadata.get("target_id") != _FTS5_TARGET
                or metadata.get("seed_identity_sha256") != AUDITED_PRODUCT_SEED_IDENTITY
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
        self.client = chromadb.PersistentClient(
            path=os.environ.get("CHROMA_PATH", "./chroma_kb/chroma_db"),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection("tech_kb")

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        model = await asyncio.to_thread(get_embedding_model)
        queries = _query_dimensions(query, sub_questions, adapted_queries)
        dimensions: list[list[dict]] = []
        audited_overviews: dict[str, str] = {}

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
            overview = _audited_fts5_overview(results, q)
            if overview is not None:
                audited_overviews[overview[0]] = overview[1]
            dimension: list[dict] = []
            seen_dimension_urls: set[str] = set()
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                metadata = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                url = metadata.get("url", doc_id) if metadata else doc_id
                if url in seen_dimension_urls:
                    continue
                seen_dimension_urls.add(url)
                result = {
                    "url": url,
                    "title": metadata.get("title", "") if metadata else "",
                    "snippet": _bounded_snippet(
                        results.get("documents", [[]])[0][i], metadata or {},
                    ),
                    "date": metadata.get("date", "") if metadata else "",
                }
                if len(result["snippet"]) > _SNIPPET_CHARS:
                    # Only _bounded_snippet's exact frozen-seed path can emit
                    # this marker; downstream stages recheck its provenance.
                    result["_seed_excerpt_window"] = AUDITED_SNIPPET_WINDOW
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
                    and result.get("_seed_target_id") == _FTS5_TARGET
                    and result.get("_seed_source_type") == "official"
                    and result.get("_seed_seed_identity_sha256") == AUDITED_PRODUCT_SEED_IDENTITY):
                result["snippet"] = audited_overviews[result["url"]]
                result.pop("_seed_excerpt_window", None)
        return merged
