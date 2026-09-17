"""Deterministic evidence metadata cleanup; never invent a document title."""

import hashlib
import re


def source_title(title, url) -> str:
    """Replace missing/provider-null titles with an explicit stable identifier."""
    clean = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", title).split()) if isinstance(title, str) else ""
    if clean.casefold() not in {"", "\\n", "null", "none", "n/a"}:
        return clean[:300]
    identity = url if isinstance(url, str) else ""
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"Untitled source ({digest})"
