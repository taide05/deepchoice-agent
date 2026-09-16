import re
import time

from .contracts import RetrievalRequest, RetrievalResult
from .. import outbound as _outbound
from ..budget_errors import BudgetError
from ..utils.views import print_agent_output


def error_text(e: Exception) -> str:
    """Return a stable public summary without reflecting provider payloads."""

    error_type = type(e).__name__
    msg = str(e)
    status = getattr(e, "status_code", None)
    if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
        status = None
        match = re.search(r"\bHTTP\s+(\d{3})\b", msg, re.IGNORECASE)
        parsed_status = int(match.group(1)) if match else None
        status = parsed_status if parsed_status is not None and 100 <= parsed_status <= 599 else None
    if status is not None:
        return f"{error_type}: HTTP {status}"
    return error_type if msg else f"{error_type}()"


class BaseRetriever:
    source: str = "base"

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Execute a retrieval using the stable request/result contracts."""
        request = RetrievalRequest.model_validate(request)
        t0 = time.monotonic()
        try:
            results = await self._do_search(
                request.query,
                list(request.sub_questions),
                request.max_results,
                adapted_queries=list(request.adapted_queries),
            )
            return RetrievalResult(
                source=self.source,
                status="success",
                results=results,
                error=None,
                latency_ms=round((time.monotonic() - t0) * 1000),
            )
        except BudgetError:
            raise
        except Exception as e:
            # A failed request may mean the routed channel died after probing
            # (proxy down, forward endpoint down, network blip). Tell the
            # channel layer so the next resolve() re-probes and re-routes;
            # harmless no-op for sources outside the channel layer (tavily).
            try:
                await _outbound.get_resolver().invalidate(self.source)
            except Exception:
                print_agent_output(
                    f"Resolver invalidate failed for {self.source}",
                    agent="RETRIEVER",
                )
            return RetrievalResult(
                source=self.source,
                status="failed",
                results=[],
                error=error_text(e),
                latency_ms=round((time.monotonic() - t0) * 1000),
            )

    async def search(self, query: str, sub_questions: list[str], max_results: int = 7,
                     adapted_queries: list[str] | None = None) -> dict:
        request = RetrievalRequest(
            query=query,
            sub_questions=sub_questions,
            max_results=max_results,
            adapted_queries=adapted_queries or [],
        )
        return (await self.retrieve(request)).model_dump(exclude={"schema_version"})

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        raise NotImplementedError
