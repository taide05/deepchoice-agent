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
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

LEARNED_DOCS_PATH = Path(os.environ.get("LEARNED_DOCS_PATH", "./learned_docs.json"))

# learn()/harvest() run short read-modify-write cycles on a small JSON file
# from async callers; the critical section is a memory loop plus one tiny
# file write, acceptable to serialize with a sync lock (B1-D1).
_write_lock = threading.Lock()

# Read-only mode: benchmark/diagnostic runs set LEARNED_DOCS_READONLY=1 so the
# self-updating cache does not mutate across cases/runs. This keeps evaluation
# reproducible — a case must not learn a term that pollutes a later case.
_READONLY = os.environ.get("LEARNED_DOCS_READONLY", "") == "1"


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

_DOCS_SIGNALS = ("docs.", "/docs", "readthedocs", "documentation", "learn.")

# Generic English words that are never tech names in context. Observed
# pollution (100-case run): 'docs', 'code', 'url', 'dom', 'flow', 'metrics',
# 'kernel' etc. were learned as "official docs" entries and polluted the
# official retriever's results.
_GENERIC_TERMS = frozenset({
    "docs", "code", "url", "dom", "dev", "flow", "metrics", "drift", "json",
    "persistent", "pivot", "rich", "encoding", "kernel", "apache",
    "api", "app", "apps", "web", "data", "team", "tool", "tools", "service",
    "services", "platform", "framework", "solution", "library", "package",
    "system", "agent", "agents", "model", "models", "cloud", "server",
    "client", "feature", "features", "flags", "search", "query", "database",
    "storage", "network", "security", "testing", "build", "builds", "building",
    "using", "with",
    "for", "and", "the", "vs", "solo", "developer", "developers", "learning",
    "support", "open", "source", "free", "best", "top", "new", "fast",
    "simple", "modern", "scalable", "production", "analytics", "dashboard",
    "management", "monitoring", "deployment", "language", "languages",
    "documentation", "reference", "guide", "tutorial", "comparison",
})


def is_plausible_term(term: str) -> bool:
    """True if the token looks like a technology name, not a generic word."""
    t = term.lower().strip()
    return len(t) > 2 and t not in _GENERIC_TERMS


def load_learned() -> dict[str, dict]:
    if not LEARNED_DOCS_PATH.exists():
        return {}
    try:
        return json.loads(LEARNED_DOCS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_learned(docs: dict[str, dict]) -> None:
    _atomic_write_text(
        LEARNED_DOCS_PATH,
        json.dumps(docs, ensure_ascii=False, indent=2),
    )


def learn(term: str, url: str, title: str, via: str) -> dict[str, dict]:
    if _READONLY:
        return load_learned()
    with _write_lock:
        docs = load_learned()
        docs[term] = {"url": url, "title": title or term, "via": via}
        _atomic_write_text(
            LEARNED_DOCS_PATH,
            json.dumps(docs, ensure_ascii=False, indent=2),
        )
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
    if _READONLY:
        return []
    with _write_lock:
        docs = load_learned()
        known = set(existing or []) | set(docs.keys())
        learned = []
        for term in terms:
            if term in known or not is_plausible_term(term):
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
            _atomic_write_text(
                LEARNED_DOCS_PATH,
                json.dumps(docs, ensure_ascii=False, indent=2),
            )
        return learned
