from threading import Lock

_model = None
_model_lock = Lock()


def SentenceTransformer(*args, **kwargs):
    """Load the native constructor only when an embedding model is requested."""
    from sentence_transformers import SentenceTransformer as constructor

    return constructor(*args, **kwargs)


def get_embedding_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer("BAAI/bge-m3")
    return _model
