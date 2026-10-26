"""arXiv source: only for academically/ML-related selection questions.

The old implementation issued one `all:` query for every selection question and
kept any result that shared one query word with the search string. On ordinary
product/ops questions (Elasticsearch vs OpenSearch, Svelte vs Vue, ...) that
pulled in unrelated papers, which then appeared as cited "evidence" in reports.
This source now:

1. skips entirely (empty, not failed, no HTTP call) unless the question is
   academic/ML-related — detected from the declared candidates or explicit ML
   topic terms;
2. keeps only results that actually name a declared candidate (or, for open
   questions, share at least two significant query words).
"""
import re
import xml.etree.ElementTree as ET

from .. import outbound as _outbound
from .base import BaseRetriever, NoRetrievableMaterial

# Candidate technologies for which papers are a plausible evidence source.
_ACADEMIC_CANDIDATE_HINTS = (
    "langgraph", "langchain", "autogen", "crewai", "llamaindex", "haystack",
    "mlflow", "weightsbiases", "wandb", "vllm", "textgenerationinference",
    "pgvector", "qdrant", "milvus", "weaviate", "chroma", "faiss", "pytorch",
    "tensorflow", "huggingface", "transformers", "sentence-transformers",
    "ray", "dask", "ollama", "openai", "anthropic", "semantickernel",
    "dspy", "embedding", "rag",
)
_ACADEMIC_TOPIC = re.compile(
    r"(机器学习|深度学习|大模型|大语言模型|模型训练|模型推理|推理性能|算法|论文|学术|"
    r"基准测试|向量检索|嵌入模型|检索增强|"
    r"\b(llm|rag|embedding|transformer|machine learning|deep learning|"
    r"neural network|inference|fine-?tun\w*|benchmark(?:ing)?|"
    r"state-of-the-art|paper|arxiv|model training|model inference|"
    r"vector search|retrieval-augmented)\b)",
    re.IGNORECASE,
)
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "can", "could",
    "may", "might", "shall", "should", "vs", "versus", "compare", "comparison",
    "between", "which", "what", "how", "than", "not", "no",
}


def _compact(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _words(value: str) -> list[str]:
    return [word for word in re.split(r"[^a-z0-9+#.]+", str(value or "").lower())
            if len(word) >= 3 and word not in _STOP_WORDS]


def is_academic_question(query: str, sub_questions: list[str],
                         candidate_techs: list[str] | None) -> bool:
    """Whether academic papers are a plausible evidence source for the question."""
    for candidate in candidate_techs or []:
        compact = _compact(candidate)
        if any(hint in compact for hint in _ACADEMIC_CANDIDATE_HINTS):
            return True
    text = " ".join([str(query or "")] + [str(item or "") for item in sub_questions or []])
    return bool(_ACADEMIC_TOPIC.search(text))


def _result_is_relevant(title: str, snippet: str, keywords: str,
                        candidate_techs: list[str] | None) -> bool:
    text = f"{title} {snippet}".lower()
    compact_text = _compact(text)
    candidates = [str(c) for c in (candidate_techs or []) if str(c).strip()]
    if candidates:
        for candidate in candidates:
            compact = _compact(candidate)
            if compact and compact in compact_text:
                return True
            tokens = _words(candidate)
            if tokens and any(token in compact_text for token in tokens):
                return True
        return False
    # Open question (no declared candidates): require two significant words.
    query_words = _words(keywords)
    if not query_words:
        return False
    hits = sum(1 for word in set(query_words) if word in compact_text)
    return hits >= 2


class ArxivSearch(BaseRetriever):
    source = "arxiv"

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None,
                         candidate_techs: list[str] | None = None) -> list[dict]:
        if not is_academic_question(query, sub_questions, candidate_techs):
            raise NoRetrievableMaterial(
                "domain_not_academic",
                "question is not academic/ML-related; arXiv is not a relevant source",
            )
        keywords = (adapted_queries[0] if adapted_queries else
                    query.replace(" vs ", " ").replace(" versus ", " ")[:200])
        async with await _outbound.make_client("arxiv") as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{keywords}",
                    "max_results": max_results,
                    "sortBy": "relevance",
                },
            )
            resp.raise_for_status()

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            raise ValueError(f"Arxiv returned non-XML response: {e}") from e

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        results = []
        for entry in root.findall("atom:entry", ns)[:max_results]:
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            link_el = entry.find("atom:id", ns)
            published_el = entry.find("atom:published", ns)
            title = title_el.text.strip() if title_el is not None else ""
            snippet = (summary_el.text or "")[:500].strip() if summary_el is not None else ""
            if not _result_is_relevant(title, snippet, keywords, candidate_techs):
                continue
            results.append({
                "url": link_el.text.strip() if link_el is not None else "",
                "title": title,
                "snippet": snippet,
                "date": (published_el.text or "")[:10] if published_el is not None else "",
            })
        return results
