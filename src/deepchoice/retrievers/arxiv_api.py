import httpx
import xml.etree.ElementTree as ET
from .base import BaseRetriever


class ArxivSearch(BaseRetriever):
    source = "arxiv"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        keywords = (adapted_queries[0] if adapted_queries else
                    query.replace(" vs ", " ").replace(" versus ", " ")[:200])
        url = (
            f"https://export.arxiv.org/api/query"
            f"?search_query=all:{keywords}&max_results={max_results}&sortBy=relevance"
        )

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
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
                      "how", "does", "than", "not", "no"}
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
