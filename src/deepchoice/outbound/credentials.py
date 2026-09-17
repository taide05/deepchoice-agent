"""Request-local optional credentials shared by provider probes and retrieval."""
import os


def stackexchange_params(params: dict) -> dict:
    """Copy non-secret parameters; never retain the key in a static probe spec."""
    result = dict(params)
    if key := os.getenv("STACKEXCHANGE_API_KEY", ""):
        result["key"] = key
    return result
