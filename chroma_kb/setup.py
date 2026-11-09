"""Initialize the Chroma knowledge base with documents from data/ directories."""
import os
import sys
from pathlib import Path

# Force offline mode before any HF imports
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import chromadb
from chromadb.config import Settings

# Use project's shared embedding module (handles offline mode)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from deepchoice.utils.embedding import get_embedding_model

KB_DIR = Path(__file__).parent
DB_DIR = KB_DIR / "chroma_db"

# Each directory carries its own provenance. `benchmark_answers` holds documents
# generated from the benchmark set's ground-truth answers (see
# populate_benchmark_kb.py); they remain indexed for evaluation reproduction but
# are marked so the research path can keep them out of its evidence basis.
# A document whose provenance is not recorded here is indexed as `unknown` and is
# never described as a published source.
DATA_DIRS = {
    "official": KB_DIR / "data" / "official",
    "blogs": KB_DIR / "data" / "blogs",
    "papers": KB_DIR / "data" / "papers",
    "benchmark_answers": KB_DIR / "data" / "benchmark_answers",
}
PROVENANCE_BY_DIR = {
    "benchmark_answers": "benchmark_ground_truth",
}


def provenance_for(source_type: str, content: str) -> str:
    """Where a document came from. Unknown stays unknown."""
    if source_type in PROVENANCE_BY_DIR:
        return PROVENANCE_BY_DIR[source_type]
    # A misplaced generated document still identifies itself in its own text.
    if "**Provenance**: benchmark ground-truth answer" in content:
        return "benchmark_ground_truth"
    return "unknown"


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
                    "provenance": provenance_for(source_type, content),
                    # The channel the document actually came through. A local
                    # file is local; it is not a public web source, and the
                    # field says so rather than leaving it blank.
                    "channel": "local_kb",
                    "url": f"file://{file_path}",
                    # No date is recorded for these files. Unknown stays unknown.
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

    model = get_embedding_model()
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

    # Upsert, so re-running after a provenance change updates the record instead
    # of failing on the existing id.
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    print(f"Ingested {len(documents)} documents into Chroma DB at {DB_DIR}")
    by_provenance: dict[str, int] = {}
    for meta in metadatas:
        key = str(meta.get("provenance", "unknown"))
        by_provenance[key] = by_provenance.get(key, 0) + 1
    print("  by provenance:", by_provenance)


if __name__ == "__main__":
    main()
