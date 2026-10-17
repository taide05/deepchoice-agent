import asyncio

import chromadb
from chromadb.config import Settings

from ..utils.embedding import get_embedding_model
from .base import BaseRetriever

# Provenance values that are evaluation material rather than research sources.
# A document generated from a benchmark set's own ground-truth answer cannot be
# cited as evidence for the question that set is meant to evaluate. This is a
# provenance filter on recorded metadata, not a keyword or title blacklist.
NON_RESEARCH_PROVENANCE = ("benchmark_ground_truth",)


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

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        model = get_embedding_model()
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]
        all_results = []
        seen_urls = set()

        for q in queries:
            q_embedding = (await asyncio.to_thread(model.encode, q)).tolist()
            # Fetch extra, because non-research material is filtered out below.
            results = self.collection.query(
                query_embeddings=[q_embedding],
                n_results=max(3, max_results // len(queries)) * 2,
            )
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
