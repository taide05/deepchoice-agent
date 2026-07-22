from sentence_transformers import SentenceTransformer

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model
