"""Candidate identity for the official-source retriever.

The failure this addresses: the official retriever matched the *adapted query's*
words, so an ordinary search term ("vector") pulled in whatever official-docs
mapping shared that token — vector.dev, a log pipeline — and the report then
cited it as pgvector's basis.

The rule here is structural, not a term list: only the declared
`task.candidate_techs` may introduce an official source. A learned-cache hit is
not evidence of candidacy either; being cached says a term was searched once, not
that it is a candidate in this run.

Both the adapted queries and the curated mapping stay as they are. The adapted
queries still drive ordinary search; the mapping is still consulted, just only
for terms that a declared candidate actually names.
"""
from __future__ import annotations

import os
import re

# One bounded evidence window for every downstream consumer. Synthesis and
# self-review previously used 600 and 900 characters independently, so the two
# stages could see different parts of the same saved body with no record of the
# cut. The window is a display/input bound, not a token budget; the actual visible
# range is reported by bounded_evidence_record().
EVIDENCE_WINDOW_CHARS = int(os.environ.get("EVIDENCE_WINDOW_CHARS", "1600"))

# Words that carry no identity in a product name. A token from here never makes
# a mapping entry count as "named by this candidate". This list predates the
# candidate-attribution work; attribution itself no longer consults word lists.
_GENERIC = frozenset("""
on in for with and or the a an of to using use used via at by from
official documentation docs site database server managed service store
amazon aws google cloud azure self hosted hostable
""".split())

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+#-]*")


def normalize_term(value: str) -> str:
    """Lowercase alphanumerics only, as the mapping lookup does."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def candidate_tokens(candidate_techs) -> list[str]:
    """Distinctive tokens named by the declared candidates, longest first."""
    tokens: set[str] = set()
    for candidate in candidate_techs or []:
        for raw in _TOKEN.findall(str(candidate).lower()):
            term = raw.strip(".-+#")
            if len(term) >= 4 and term not in _GENERIC:
                tokens.add(term)
    return sorted(tokens, key=lambda t: (-len(t), t))


def candidate_proper_nouns(candidate_techs) -> list[str]:
    """Whole declared candidate names, for identification in prompts/reports."""
    return [str(c).strip() for c in (candidate_techs or []) if str(c).strip()]


def _name_tokens(value: str) -> list[str]:
    """Lowercase word tokens of a name, split on separators too.

    'aws-lambda' and 'AWS Lambda' both yield ['aws', 'lambda'], so a multi-word
    mapping key matches whichever form the candidate uses.
    """
    words = re.split(r"[^a-z0-9+#]+", str(value or "").lower())
    return [w.strip("+#") for w in words if w.strip("+#")]


def _key_token_sequence(key: str) -> list[str]:
    """Normalized tokens of a mapping key, in order."""
    parts = [normalize_term(p) for p in _name_tokens(key)]
    return [p for p in parts if p]


def candidate_names_key(candidate: str, key: str) -> bool:
    """Whether a declared candidate actually names this mapping key.

    Compares token sequences rather than one normalized string inside another, so
    multi-word keys match their spaced or hyphenated forms ('AWS Lambda' names
    the 'aws-lambda' key) while a key that merely shares a substring does not
    ('pgvector' does not name the 'vector' key).
    """
    key_tokens = _key_token_sequence(key)
    if not key_tokens:
        return False
    cand_tokens = [normalize_term(t) for t in _name_tokens(candidate)]
    cand_tokens = [t for t in cand_tokens if t]
    if not cand_tokens:
        return False
    if len(key_tokens) == 1:
        # A single distinctive key token must match a whole candidate token:
        # substring containment would let 'vector' match 'pgvector'.
        return key_tokens[0] in cand_tokens and len(key_tokens[0]) >= 4
    width = len(key_tokens)
    return any(cand_tokens[i:i + width] == key_tokens
               for i in range(len(cand_tokens) - width + 1))


def mapping_key_for(candidate_techs, lookup) -> list[str]:
    """Mapping keys that a declared candidate actually names.

    A key qualifies only when the candidate's own name contains it. So 'vector'
    does not qualify for the declared candidate 'pgvector on Amazon RDS for
    PostgreSQL', while 'postgresql' does, and 'AWS Lambda' still resolves the
    'aws-lambda' key.
    """
    keys = []
    for key in lookup:
        if any(candidate_names_key(candidate, key) for candidate in candidate_techs or []):
            keys.append(key)
    return keys


def split_navigation_label(text: str) -> tuple[str, bool]:
    """Separate a navigation caption from factual content.

    'Official documentation site for X' says where a link points. It states
    nothing about X, so it is not evidence and must not be presented as such.
    Returns (content, is_navigation_only).
    """
    body = (text or "").strip()
    if not body:
        return "", True
    if re.fullmatch(
        r"[Oo]fficial documentation site for .+\.?", body
    ) or body.lower().startswith("official documentation site for"):
        return "", True
    # The explicit gap sentence produced by bounded_content_summary is also not
    # content. It is a statement about the source, not by it, and must not become
    # citable merely because it is a non-empty string.
    if body.startswith("NO CONTENT RETRIEVED"):
        return "", True
    return body, False


def source_content(source: dict) -> str:
    """The stored body text of a source, from content/body/snippet.

    One extraction used by both the admission predicate and every display of a
    source's text, so a source accepted because it carries `content` cannot be
    shown as having no body (or vice versa).
    """
    for key in ("content", "body", "snippet"):
        value = source.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        content, _navigation_only = split_navigation_label(value)
        if content:
            return content
    return ""


def bounded_evidence_record(source: dict, limit: int | None = None) -> dict:
    """The shared bounded view of a source body for synthesis and self-review.

    Returns the visible excerpt plus the actual source length and cut metadata.
    Both stages must read a source's saved body through this one function; a
    caller that shows a source without this record is hiding how much of it was
    visible. The stored source is never mutated.
    """
    window = EVIDENCE_WINDOW_CHARS if limit is None else int(limit)
    content = source_content(source)
    if not content:
        title = source.get("title", "") or "this source"
        _content, navigation_only = split_navigation_label(source.get("snippet", ""))
        if navigation_only:
            gap = (f"NO CONTENT RETRIEVED — {title} is a documentation link only; "
                   f"its page body was not collected, so it states nothing about "
                   f"this question.")
        else:
            gap = f"NO CONTENT RETRIEVED — {title} was indexed without a body."
        return {
            "text": gap,
            "source_chars": 0,
            "visible_chars": 0,
            "truncated": False,
            "has_body": False,
        }
    content = " ".join(str(content).split())
    total = len(content)
    visible = content if total <= window else content[:window].rstrip()
    return {
        "text": visible,
        "source_chars": total,
        "visible_chars": len(visible),
        "truncated": len(visible) < total,
        "has_body": True,
    }


def bounded_content_summary(source: dict, limit: int | None = None) -> str:
    """The shared bounded factual content of a source, or an explicit gap.

    Uses whatever body was stored with the source. When there is none, says so
    rather than substituting the title or an official-looking label.
    """
    return bounded_evidence_record(source, limit=limit)["text"]


def has_factual_content(source: dict) -> bool:
    """Whether a source carries a body that could support a claim.

    A discovered link with no body is navigation. It may be shown as a link, but
    it cannot be a citable fact source: its title says what the page is called,
    not what is true.

    `has_body` is the authoritative marker, set where the source is created when
    no page body was collected. The body text is the fallback and is read through
    the same `source_content` extraction the sources are displayed with.
    """
    if "has_body" in source:
        return bool(source.get("has_body"))
    return bool(source_content(source))


def _word_present(token: str, haystack: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack) is not None


def names_candidate(text: str, candidate: str) -> bool:
    """Whether a text names the candidate in full, as a phrase.

    Stricter than the mapping lookup: the candidate's whole name must appear as a
    run of words, so 'Amazon Aurora PostgreSQL with pgvector pricing' names the
    candidate while 'PostgreSQL 17 release notes' does not. Sharing part of a
    name establishes nothing about a source's subject.
    """
    want = [normalize_term(t) for t in _name_tokens(candidate)]
    want = [t for t in want if t]
    if not want:
        return False
    if len(want) == 1:
        # A one-word candidate is named only by that exact word.
        got = [normalize_term(t) for t in _name_tokens(text)]
        return want[0] in got
    got = [normalize_term(t) for t in _name_tokens(text)]
    got = [t for t in got if t]
    width = len(want)
    return any(got[i:i + width] == want for i in range(len(got) - width + 1))


# The renderer no longer maps sources onto candidates. Candidate explanations
# come from the synthesis result, which is the one place that decided what each
# candidate is for; a page may cover several products, so it is not forced to own
# one. `names_candidate` above remains in use for the official-source mapping
# lookup, which is a different question (which curated docs entry does this
# declared candidate name).
