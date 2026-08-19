"""Self-updating official-docs mapping: evidence harvest + persistent learned cache.

The seed mapping lives in official.py (TECH_DOCS). This module lets the
system grow it automatically:
  - harvest(): learns term -> official URL pairs from search evidence
    (a result whose host contains the term as a full label AND whose URL
    carries a docs signal), persisted to learned_docs.json.
  - The official retriever consults the learned cache before falling back
    to an LLM proposal (validated: term must be a host label + URL reachable).
"""
import json
from pathlib import Path
from urllib.parse import urlparse

LEARNED_DOCS_PATH = Path("./learned_docs.json")

_DOCS_SIGNALS = ("docs.", "/docs", "readthedocs", "documentation", "learn.")


def load_learned() -> dict[str, dict]:
    if not LEARNED_DOCS_PATH.exists():
        return {}
    try:
        return json.loads(LEARNED_DOCS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_learned(docs: dict[str, dict]) -> None:
    LEARNED_DOCS_PATH.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def learn(term: str, url: str, title: str, via: str) -> dict[str, dict]:
    docs = load_learned()
    docs[term] = {"url": url, "title": title or term, "via": via}
    save_learned(docs)
    return docs


def extract_terms(text: str) -> list[str]:
    """Lowercased candidate tech terms from a query string."""
    words = text.lower().replace(" vs ", " ").replace(" versus ", " ").split()
    terms = []
    for w in words:
        w = w.strip().rstrip(".,;:!?()")
        core = w.replace(".", "").replace("-", "").replace("_", "")
        if len(w) > 2 and core.isalnum():
            terms.append(w)
    return terms


def domain_label_match(term: str, url: str) -> bool:
    """True if `term` is a full label of the URL's host (supabase.com has label 'supabase')."""
    host = urlparse(url).netloc.lower()
    return bool(host) and term.lower().strip() in host.split(".")


def _looks_official(url: str) -> bool:
    return any(sig in url.lower() for sig in _DOCS_SIGNALS)


def harvest(terms: list[str], search_results: list[dict],
            existing: set[str] | None = None) -> list[dict]:
    """Learn term -> url pairs from search evidence; returns newly learned entries."""
    docs = load_learned()
    known = set(existing or []) | set(docs.keys())
    learned = []
    for term in terms:
        if term in known:
            continue
        for sr in search_results:
            for item in sr.get("results", []) or []:
                url = item.get("url", "")
                if domain_label_match(term, url) and _looks_official(url):
                    entry = {
                        "url": url,
                        "title": item.get("title", term),
                        "via": f"harvest:{sr.get('source', 'unknown')}",
                    }
                    docs[term] = entry
                    learned.append({"term": term, **entry})
                    known.add(term)
                    break
            else:
                continue
            break
    if learned:
        save_learned(docs)
    return learned
