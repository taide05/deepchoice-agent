"""Deterministic evidence metadata cleanup; never invent a document title."""

import hashlib
import re
from urllib.parse import urlsplit


def conclusion_source_allowed(source: dict) -> bool:
    """Exclude paste-host evidence from new conclusions, not from retrieval.

    This is a source-quality rule, not a safety/truth classification. Ordinary
    GitHub project documentation remains eligible for ordinary citation checks.
    """
    try:
        host = (urlsplit(str(source.get("url", ""))).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host not in {"gist.github.com", "gist.githubusercontent.com", "pastebin.com"}


def is_navigation_placeholder(snippet) -> bool:
    """Recognize the official retriever's navigation-only, single-token stub.

    This is not a content-quality classifier: short real excerpts and text that
    merely starts with the same words must retain their existing admission.
    Curated keys, harvested terms and fallback terms use a single token.
    """
    if not isinstance(snippet, str):
        return False
    normalized = " ".join(snippet.split())
    return re.fullmatch(r"Official documentation site for \S+", normalized, re.IGNORECASE) is not None


def source_title(title, url) -> str:
    """Replace missing/provider-null titles with an explicit stable identifier."""
    clean = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", title).split()) if isinstance(title, str) else ""
    if clean.casefold() not in {"", "\\n", "null", "none", "n/a"}:
        return clean[:300]
    identity = url if isinstance(url, str) else ""
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"Untitled source ({digest})"
