import time


def error_text(e: Exception) -> str:
    """Type-prefixed error text; httpx timeouts carry an empty str() message."""
    msg = str(e)
    return f"{type(e).__name__}: {msg}" if msg else f"{type(e).__name__}()"


class BaseRetriever:
    source: str = "base"

    async def search(self, query: str, sub_questions: list[str], max_results: int = 7,
                     adapted_queries: list[str] | None = None) -> dict:
        t0 = time.monotonic()
        try:
            results = await self._do_search(query, sub_questions, max_results,
                                            adapted_queries=adapted_queries or [])
            return {
                "source": self.source,
                "status": "success",
                "results": results,
                "error": None,
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }
        except Exception as e:
            return {
                "source": self.source,
                "status": "failed",
                "results": [],
                "error": error_text(e),
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        raise NotImplementedError
