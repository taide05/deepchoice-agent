"""Self-updating official-docs mapping: evidence harvest + persistent learned cache.

The static seed mapping lives in utils.official_catalog (TECH_DOCS), re-exported
by official.py. This module maintains a separate learned lookup:
  - harvest(): learns term -> official URL pairs from search evidence
    (a result whose host contains the term as a full label AND whose URL
    carries a docs signal), persisted to learned_docs.json.
  - The official retriever consults the learned cache before falling back
    to an LLM proposal (validated: term must be a host label + URL reachable).
"""
import hashlib
import json
import logging
import os
import threading
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from deepchoice.security.redaction import redact_text

LEARNED_DOCS_PATH = Path(os.environ.get("LEARNED_DOCS_PATH", "./learned_docs.json"))

# learn()/harvest() run short read-modify-write cycles on a small JSON file
# from async callers; the critical section is a memory loop plus one tiny
# file write, acceptable to serialize with a sync lock (B1-D1).
_write_lock = threading.Lock()

# Read-only mode: benchmark/diagnostic runs set LEARNED_DOCS_READONLY=1 so the
# self-updating cache does not mutate across cases/runs. This keeps evaluation
# reproducible — a case must not learn a term that pollutes a later case.
_READONLY = os.environ.get("LEARNED_DOCS_READONLY", "") == "1"


_MAX_MAPPING_BYTES = 512 * 1024
_OPTIONAL_ERRORS = (OSError, ValueError, UnicodeError, RecursionError)
_logger = logging.getLogger(__name__)


def _warn_unavailable() -> None:
    # Never include paths, candidate content or the underlying exception.
    _logger.warning(redact_text("Optional official-document learning unavailable; retrieval continues."))


def _validate_mapping(docs: object) -> None:
    if not isinstance(docs, dict):
        raise ValueError("Invalid learned mapping")
    for term, entry in docs.items():
        if not isinstance(term, str) or not term.strip() or not isinstance(entry, dict):
            raise ValueError("Invalid learned entry")
        url = entry.get("url")
        if not isinstance(url, str):
            raise ValueError("Invalid learned URL")
        parsed = urlparse(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443}):
            raise ValueError("Invalid learned URL")
        if any(key in entry and not isinstance(entry[key], str) for key in ("title", "via")):
            raise ValueError("Invalid learned metadata")


def _read_mapping() -> tuple[bytes, dict]:
    try:
        with LEARNED_DOCS_PATH.open("rb") as stream:
            raw = stream.read(_MAX_MAPPING_BYTES + 1)
    except FileNotFoundError:
        raw = b"{}"
    if len(raw) > _MAX_MAPPING_BYTES:
        raise ValueError("Learned mapping too large")
    docs = json.loads(raw.decode("utf-8"))
    _validate_mapping(docs)
    return raw, docs


def _atomic_write_text(path: Path, text: str) -> None:
    # A failed replacement must preserve the old mapping and remove only our temp.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=path.parent, prefix=path.name + ".",
                                         suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(text)
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                _warn_unavailable()


def _write_mapping(docs: dict) -> None:
    _validate_mapping(docs)
    text = json.dumps(docs, ensure_ascii=False, indent=2)
    if len(text.encode("utf-8")) > _MAX_MAPPING_BYTES:
        raise ValueError("Learned mapping too large")
    _atomic_write_text(LEARNED_DOCS_PATH, text)


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


def official_mapping_identity() -> str | None:
    """Hash bounded persisted discovery bytes; never expose URLs in cache keys.

    An unreadable/invalid/moving mapping cannot participate in cache reuse.
    Missing files have a stable empty identity until discovery creates one.
    """
    try:
        raw, _ = _read_mapping()
        return hashlib.sha256(b"official-mapping-v1\0" + raw).hexdigest()
    except _OPTIONAL_ERRORS:
        return None


def load_learned() -> dict[str, dict]:
    try:
        return _read_mapping()[1]
    except _OPTIONAL_ERRORS:
        _warn_unavailable()
        return {}


def learn(term: str, url: str, title: str, via: str) -> dict[str, dict]:
    if _READONLY:
        return load_learned()
    with _write_lock:
        try:
            _, docs = _read_mapping()
            if not isinstance(term, str) or not isinstance(title, str):
                raise ValueError("Invalid learned input")
            docs[term] = {"url": url, "title": title or term, "via": via}
            _write_mapping(docs)
            return docs
        except _OPTIONAL_ERRORS:
            _warn_unavailable()
            return {}


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
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and term.lower().strip() in host.split(".")


def _looks_official(url: str) -> bool:
    return any(sig in url.lower() for sig in _DOCS_SIGNALS)


def harvest(terms: list[str], search_results: list[dict],
            existing: set[str] | None = None) -> list[dict]:
    """Learn term -> url pairs from search evidence; returns newly learned entries."""
    if _READONLY:
        return []
    with _write_lock:
        try:
            _, docs = _read_mapping()
            known = set(existing or []) | set(docs)
            learned = []
            invalid = False
            for term in terms:
                if not isinstance(term, str):
                    invalid = True
                    continue
                if term in known or not is_plausible_term(term):
                    continue
                for sr in search_results:
                    if sr.get("status") == "partial":
                        continue
                    for item in sr.get("results", []) or []:
                        source = sr.get("source", "unknown")
                        if not isinstance(source, str):
                            invalid = True
                            continue
                        entry = {"url": item.get("url", ""),
                                 "title": item.get("title", term),
                                 "via": f"harvest:{source}"}
                        try:
                            _validate_mapping({term: entry})
                        except (ValueError, UnicodeError):
                            invalid = True
                            continue
                        url = entry["url"]
                        if domain_label_match(term, url) and _looks_official(url):
                            docs[term] = entry
                            learned.append({"term": term, **entry})
                            known.add(term)
                            break
                    else:
                        continue
                    break
            if invalid:
                _warn_unavailable()
            if learned:
                _write_mapping(docs)
            return learned
        except _OPTIONAL_ERRORS:
            _warn_unavailable()
            return []
