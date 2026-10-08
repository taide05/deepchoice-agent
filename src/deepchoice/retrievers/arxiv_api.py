import asyncio
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from .. import outbound as _outbound
from ..outbound import throttle
from ..utils.evidence_choices import whole_source_text
from ..utils.source_scope import proposal_hints, proposal_scope
from .base import BaseRetriever
from .http import budgeted_http, check_response_size
from .query_results import merge_query_results

_ARXIV_TIMEOUT_S = 30.0
_ARXIV_MAX_RETRIES = 3
_SEARCH_TIMEOUT_S = 180.0


def _parse_response(resp, keywords: str, max_results: int) -> list[dict]:
    from ..citations.source_windows import MAX_DOCUMENT_TEXT, SourceDocument

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        raise ValueError("Invalid arXiv XML response") from e

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    if root.tag != "{" + ns["atom"] + "}feed":
        raise ValueError("Invalid arXiv Atom feed")
    entries = root.findall("atom:entry", ns)
    # The API can report an error inside an otherwise successful HTTP/Atom reply.
    for entry in entries:
        identifier = (entry.findtext("atom:id", "", ns) or "").strip()
        parsed = urlsplit(identifier)
        if (parsed.hostname in {"arxiv.org", "export.arxiv.org"}
                and parsed.path.rstrip("/") == "/api/errors"):
            raise ValueError("arXiv API error")

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
    hints = proposal_hints(keywords)
    for entry in entries[:max_results]:
        summary_el = entry.find("atom:summary", ns)
        title = (entry.findtext("atom:title", "", ns) or "").strip()
        url = (entry.findtext("atom:id", "", ns) or "").strip()
        if (not title or not url or summary_el is None or len(summary_el)
                or not isinstance(summary_el.text, str) or not summary_el.text.strip()
                or len(summary_el.text) > MAX_DOCUMENT_TEXT):
            raise ValueError("Invalid arXiv abstract entry")
        # Atom abstracts contain XML-decoded text, including math. Single
        # newlines are provider wrapping, not boundaries that permit clipping.
        raw = summary_el.text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = tuple(" ".join(part.split()) for part in re.split(r"\n\s*\n", raw)
                           if part.strip())
        summary = " ".join(paragraphs)
        if not _has_overlap(title, summary):
            continue
        snippet = whole_source_text(summary)
        scope = None if snippet else proposal_scope(
            SourceDocument(paragraphs, incomplete=False,
                           prose_indices=tuple(range(len(paragraphs)))), hints)
        if not snippet and not scope:
            raise ValueError("No admitted arXiv abstract range")
        result = {
            "url": url, "title": title, "snippet": snippet,
            "date": (entry.findtext("atom:published", "", ns) or "")[:10],
        }
        if scope:
            result["_source_scope_sentences"] = scope
        results.append(result)
    return results


class ArxivSearch(BaseRetriever):
    source = "arxiv"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        from ..runtime.context import get_run_context

        queries = list(dict.fromkeys(adapted_queries)) if adapted_queries else [query]
        batches = []
        # Includes route resolution, provider pacing and all bounded retries.
        async with asyncio.timeout(_SEARCH_TIMEOUT_S):
            for keywords in queries:
                async def dispatch():
                    async with await _outbound.make_client("arxiv") as client:
                        return await throttle.get(
                            "arxiv", client, "https://export.arxiv.org/api/query",
                            params={"search_query": f"all:{keywords}", "max_results": max_results,
                                    "sortBy": "relevance"},
                            request_timeout=_ARXIV_TIMEOUT_S, max_retries=_ARXIV_MAX_RETRIES,
                        )
                # Reserve before route probing, not only before the provider GET.
                resp = await budgeted_http(dispatch, kind="arxiv_query",
                                           require_budget=get_run_context() is not None)
                check_response_size(resp)
                resp.raise_for_status()
                batches.append(_parse_response(resp, keywords, max_results))
        return merge_query_results(batches, max_results)
