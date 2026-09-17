from sentence_transformers import SentenceTransformer
from threading import Lock

_model = None
_model_lock = Lock()


def get_embedding_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer("BAAI/bge-m3")
    return _model
