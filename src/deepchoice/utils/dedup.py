from sentence_transformers import SentenceTransformer
import numpy as np

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model


def deduplicate_results(results: list[dict], threshold: float = 0.85) -> list[dict]:
    if len(results) <= 1:
        return results

    model = _get_model()
    snippets = [r.get("snippet", r.get("title", "")) for r in results]
    if not any(snippets):
        return results

    embeddings = model.encode(snippets)
    kept = []
    kept_embeddings = []

    for i, (result, emb) in enumerate(zip(results, embeddings)):
        is_dup = False
        for kept_emb in kept_embeddings:
            sim = np.dot(emb, kept_emb) / (np.linalg.norm(emb) * np.linalg.norm(kept_emb))
            if sim >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(result)
            kept_embeddings.append(emb)

    return kept
