import asyncio

import chromadb
from chromadb.config import Settings

from ..utils.embedding import get_embedding_model
from .base import BaseRetriever, NoRetrievableMaterial

# Provenance values that are evaluation material rather than research sources.
# A document generated from a benchmark set's own ground-truth answer cannot be
# cited as evidence for the question that set is meant to evaluate. This is a
# provenance filter on recorded metadata, not a keyword or title blacklist.
NON_RESEARCH_PROVENANCE = ("benchmark_ground_truth",)

# Why the source is empty. Distinct from a failed source in the envelope.
EMPTY_INDEX = "index_empty"
EMPTY_NO_RESEARCH_MATERIAL = "no_research_material"


class ChromaKB(BaseRetriever):
    source = "chroma"

    def __init__(self, db_path: str = "./chroma_kb/chroma_db"):
        self.client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection("tech_kb")

    @staticmethod
    def _is_research_source(metadata: dict) -> bool:
        """Whether this indexed document may be used as research material.

        A document whose provenance is unknown is not refused here: unknown is
        not the same as known-bad. What it must not do is pass as a published
        source — the envelope carries `provenance`/`channel` so downstream steps
        and the report can say what it actually is.
        """
        provenance = str((metadata or {}).get("provenance", "") or "").strip().lower()
        return provenance not in NON_RESEARCH_PROVENANCE

    def _research_material_state(self) -> str:
        """Decide from existing metadata whether anything can be retrieved.

        Runs before the embedding model is touched. When the index holds
        evaluation material only, or nothing at all, the source is reported empty
        without loading a model, encoding a query, or contacting the model hub.
        The documents themselves stay in the index — this reads metadata and
        never deletes or re-labels anything.
        """
        stored = self.collection.get(include=["metadatas"])
        metadatas = stored.get("metadatas") or []
        if not metadatas:
            return EMPTY_INDEX
        if not any(self._is_research_source(metadata) for metadata in metadatas):
            return EMPTY_NO_RESEARCH_MATERIAL
        return ""

    def _query(self, query_embedding: list[float], n_results: int) -> dict:
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        # Metadata first: an unusable index must cost no model load. The check and
        # the query are synchronous Chroma calls, so both run in a worker thread
        # and cannot block the service event loop.
        empty_reason = await asyncio.to_thread(self._research_material_state)
        if empty_reason:
            raise NoRetrievableMaterial(
                empty_reason,
                detail=("the knowledge base contains no indexed documents"
                        if empty_reason == EMPTY_INDEX
                        else "every indexed document is evaluation material"),
            )

        # Local loading is explicit and happens before research dispatch. Reaching
        # it here means the model is ready; if it is not, this raises immediately
        # and the source is reported unavailable — no hub resolution or download.
        model = await asyncio.to_thread(get_embedding_model)

        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]
        all_results = []
        seen_urls = set()

        for q in queries:
            q_embedding = (await asyncio.to_thread(model.encode, q)).tolist()
            # Fetch extra, because non-research material is filtered out below.
            results = await asyncio.to_thread(
                self._query, q_embedding, max(3, max_results // len(queries)) * 2)
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                metadata = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                url = metadata.get("url", doc_id) if metadata else doc_id
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                if not self._is_research_source(metadata):
                    # Kept in the index, out of the research basis.
                    continue
                all_results.append({
                    "url": url,
                    "title": metadata.get("title", "") if metadata else "",
                    "snippet": (results.get("documents", [[]])[0][i] or "")[:500],
                    "date": metadata.get("date", "") if metadata else "",
                    # Provenance travels with the source, so no downstream step
                    # has to guess where it came from or relabel it as public.
                    "source_type": metadata.get("source_type", "") if metadata else "",
                    "provenance": metadata.get("provenance", "unknown") if metadata else "unknown",
                    "channel": metadata.get("channel", "local_kb") if metadata else "local_kb",
                })
        return all_results[:max_results]
