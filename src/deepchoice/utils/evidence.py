"""Deterministic evidence metadata cleanup; never invent a document title."""

import hashlib
import re
from urllib.parse import urlsplit


_CHOICE_ACTION_PREFIX = re.compile(
    r"^(?:(?:continue|keep)\s+using|(?:migrate|switch|move)\s+to|stay\s+with)(?:\s+|$)|"
    r"^(?:继续使用|继续采用|迁移到|切换到)\s*", re.IGNORECASE,
)


def candidate_search_name(candidate: object) -> str | None:
    """Separate one explicit decision action from its literal product identity.

    Unknown labels remain literal, including compounds and versions. This is
    a lexical routing hint, not an inferred alias or proof of applicability.
    The original task/choice label is never changed. Action-only labels have
    no product identity and must not disable an explicit candidate gate.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    label = candidate.strip()
    prefix = _CHOICE_ACTION_PREFIX.match(label)
    identity = label[prefix.end():].strip() if prefix is not None else label
    # Nested actions are ambiguous, not a literal product identity.
    action = _CHOICE_ACTION_PREFIX.match(identity)
    return identity if identity and action is None else None


def candidate_name_pattern(candidate: object) -> re.Pattern | None:
    """Match an explicit product name in casefolded text, including short names.

    ASCII identifier boundaries allow mixed Chinese/Latin prose while excluding
    embedded identifiers and extensions such as C++++ for C++. A literal name
    is a lexical hint only, never proof of source applicability.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    identity = candidate_search_name(candidate)
    if identity is None:
        return re.compile(r"(?!)")  # Explicit action-only gate must fail closed.
    name = r"\s+".join(re.escape(word) for word in identity.casefold().split())
    return re.compile(r"(?<![a-z0-9_+#])" + name + r"(?![a-z0-9_+#])")


def candidate_product_mentions(text, candidates):
    """Return literal product identities, excluding names contained in longer ones.

    Choice actions do not change a product identity; no aliases are inferred.
    A mention is a routing hint, not evidence of applicability or claim support.
    """
    if not isinstance(text, str) or not isinstance(candidates, (list, tuple)):
        return set()
    patterns = {}
    for candidate in candidates:
        if candidate_search_name(candidate) is not None:
            pattern = candidate_name_pattern(candidate)
            patterns[pattern.pattern] = pattern
    spans = sorted((match.start(), -match.end(), key)
                   for key, pattern in patterns.items() for match in pattern.finditer(text.casefold()))
    mentioned, enclosing = set(), (-1, -1)
    for start, negative_end, key in spans:
        end = -negative_end
        if end > enclosing[1]:
            enclosing = (start, end)
            mentioned.add(key)
        elif enclosing == (start, end):
            mentioned.add(key)
    return mentioned


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
