import time

from .. import outbound as _outbound
from ..utils.views import print_agent_output


def error_text(e: Exception) -> str:
    """Type-prefixed error text; httpx timeouts carry an empty str() message."""
    msg = str(e)
    return f"{type(e).__name__}: {msg}" if msg else f"{type(e).__name__}()"


class NoRetrievableMaterial(Exception):
    """The source has no research material to search — not a failure.

    Reported as ``status="empty"`` with a reason, so "the index holds nothing
    usable" is not confused with "the source broke". No model is loaded and no
    request is sent to discover this.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class BaseRetriever:
    source: str = "base"

    async def search(self, query: str, sub_questions: list[str], max_results: int = 7,
                     adapted_queries: list[str] | None = None,
                     candidate_techs: list[str] | None = None) -> dict:
        t0 = time.monotonic()
        try:
            results = await self._do_search(query, sub_questions, max_results,
                                            adapted_queries=adapted_queries or [],
                                            candidate_techs=candidate_techs or [])
            return {
                "source": self.source,
                "status": "success",
                "results": results,
                "error": None,
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }
        except NoRetrievableMaterial as empty:
            # Not an error: no external call was attempted and nothing failed.
            return {
                "source": self.source,
                "status": "empty",
                "results": [],
                "error": None,
                "empty_reason": empty.reason,
                "empty_detail": empty.detail,
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }
        except Exception as e:
            # A failed request may mean the routed channel died after probing
            # (proxy down, forward endpoint down, network blip). Tell the
            # channel layer so the next resolve() re-probes and re-routes;
            # harmless no-op for sources outside the channel layer (tavily).
            try:
                await _outbound.get_resolver().invalidate(self.source)
            except Exception as e:
                print_agent_output(f"Resolver invalidate failed for {self.source}: {e}", agent="RETRIEVER")
            return {
                "source": self.source,
                "status": "failed",
                "results": [],
                "error": error_text(e),
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        raise NotImplementedError
