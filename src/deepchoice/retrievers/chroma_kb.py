import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from .base import BaseRetriever


class ChromaKB(BaseRetriever):
    source = "chroma"

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path="./chroma_kb/chroma_db",
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
