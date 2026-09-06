import asyncio
import xml.etree.ElementTree as ET

from .. import outbound as _outbound
from .base import BaseRetriever

# Tranche 2 B5: bound arxiv concurrency + retry on 429/5xx with Retry-After
# backoff (the original run's arxiv 429 source; github/community/tavily already
# throttle, arxiv was the gap).
_ARXIV_SEM = asyncio.Semaphore(2)
_ARXIV_TIMEOUT_S = 20.0
_ARXIV_MAX_RETRIES = 2
_ARXIV_BACKOFF_S = 3.0


def _retry_delay(headers) -> float:
    try:
        raw = headers.get("Retry-After")
        if raw is not None:
            secs = float(raw)
            if secs > 0.0:
                return min(secs, 60.0)
    except (AttributeError, TypeError, ValueError):
        pass
    return _ARXIV_BACKOFF_S


class ArxivSearch(BaseRetriever):
    source = "arxiv"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else
                    query.replace(" vs ", " ").replace(" versus ", " ")[:200])
        async with _ARXIV_SEM:
            async with await _outbound.make_client("arxiv") as client:
                resp = None
                for attempt in range(_ARXIV_MAX_RETRIES + 1):
                    resp = await asyncio.wait_for(
                        client.get(
                            "https://export.arxiv.org/api/query",
                            params={
                                "search_query": f"all:{keywords}",
                                "max_results": max_results,
                                "sortBy": "relevance",
                            },
                        ),
                        timeout=_ARXIV_TIMEOUT_S,
                    )
                    if resp.status_code not in (429, 500, 502, 503, 504) or attempt == _ARXIV_MAX_RETRIES:
                        break
                    await asyncio.sleep(_retry_delay(resp.headers))
                resp.raise_for_status()

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            raise ValueError(f"Arxiv returned non-XML response: {e}") from e

        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # Extract content-bearing words from query for relevance filtering
        stop_words = {"a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
                      "for", "of", "with", "by", "from", "is", "are", "was", "were",
                      "be", "been", "being", "have", "has", "had", "do", "does", "did",
                      "will", "would", "can", "could", "may", "might", "shall", "should",
                      "vs", "versus", "compare", "comparison", "between", "which", "what",
                      "how", "than", "not", "no"}
        query_words = [w.lower() for w in keywords.replace(",", " ").split()
                       if len(w) >= 3 and w.lower() not in stop_words]

        def _has_overlap(title, snippet):
            text = (title + " " + snippet).lower()
            return any(qw in text for qw in query_words) if query_words else True

        results = []
        for entry in root.findall("atom:entry", ns)[:max_results]:
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            link_el = entry.find("atom:id", ns)
            published_el = entry.find("atom:published", ns)
            title = title_el.text.strip() if title_el is not None else ""
            snippet = (summary_el.text or "")[:500].strip() if summary_el is not None else ""
            if not _has_overlap(title, snippet):
                continue
            results.append({
                "url": link_el.text.strip() if link_el is not None else "",
                "title": title,
                "snippet": snippet,
                "date": (published_el.text or "")[:10] if published_el is not None else "",
            })
        return results
