import chromadb
from chromadb.config import Settings
from .base import BaseRetriever
from ..utils.embedding import get_embedding_model


class ChromaKB(BaseRetriever):
    source = "chroma"

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path="./chroma_kb/chroma_db",
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection("tech_kb")

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        model = get_embedding_model()
        queries = adapted_queries if adapted_queries else [query] + sub_questions[:2]
        all_results = []
        seen_urls = set()

        for q in queries:
            q_embedding = model.encode(q).tolist()
            results = self.collection.query(
                query_embeddings=[q_embedding],
                n_results=max(3, max_results // len(queries)),
            )
            for i, doc_id in enumerate(results.get("ids", [[]])[0]):
                metadata = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
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
