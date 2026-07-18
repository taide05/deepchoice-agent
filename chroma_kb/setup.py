"""Initialize the Chroma knowledge base with documents from data/ directories."""
import sys
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

KB_DIR = Path(__file__).parent
DB_DIR = KB_DIR / "chroma_db"
DATA_DIRS = {
    "official": KB_DIR / "data" / "official",
    "blogs": KB_DIR / "data" / "blogs",
    "papers": KB_DIR / "data" / "papers",
}


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
                    "url": f"file://{file_path}",
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

    model = SentenceTransformer("BAAI/bge-m3")
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

    collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    print(f"Ingested {len(documents)} documents into Chroma DB at {DB_DIR}")


if __name__ == "__main__":
    main()
