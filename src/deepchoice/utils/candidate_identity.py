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

import re

# Words that carry no identity in a product name. A token from here never makes
# a mapping entry count as "named by this candidate".
_GENERIC = frozenset("""
on in for with and or the a an of to using use used via at by from as
official documentation docs site database server managed service store
amazon aws google cloud azure self hosted hostable
over under between versus vs than
""".split())

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+#-]*")

# Tokens that distinguish between products sharing a name, so a source must
# contain them to be attributed to that candidate. Ordinary words such as 'over'
# and 'with' are not here: they disambiguate nothing.
_DISAMBIGUATING = frozenset("""
serverless managed self hosted cloud enterprise pro plus lite
streams cluster vector search analytics warehouse
""".split())


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
    return body, False


def bounded_content_summary(source: dict, limit: int = 600) -> str:
    """The factual content of a source, or an explicit gap.

    Uses whatever body was stored with the source. When there is none, says so
    rather than substituting the title or an official-looking label.
    """
    content, navigation_only = split_navigation_label(source.get("snippet", ""))
    if not content:
        title = source.get("title", "") or "this source"
        if navigation_only:
            return (f"NO CONTENT RETRIEVED — {title} is a documentation link only; "
                    f"its page body was not collected, so it states nothing about "
                    f"this question.")
        return f"NO CONTENT RETRIEVED — {title} was indexed without a body."
    content = " ".join(content.split())
    if len(content) > limit:
        content = content[:limit].rstrip() + "…"
    return content


def has_factual_content(source: dict) -> bool:
    """Whether a source carries a body that could support a claim.

    A discovered link with no body is navigation. It may be shown as a link, but
    it cannot be a citable fact source: its title says what the page is called,
    not what is true.
    """
    content, _ = split_navigation_label(source.get("snippet", ""))
    if content:
        return True
    body = source.get("content") or source.get("body") or ""
    return bool(str(body).strip())


def _word_present(token: str, haystack: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack) is not None


def candidate_for_source(source: dict, candidate_techs) -> str | None:
    """The declared candidate a source is demonstrably about, or None.

    Association is name-based: the source's own title or URL must name the
    candidate. Sharing a generic word is not an association, so a page that
    merely contains 'serverless' is not thereby about a serverless candidate, and
    a page naming no candidate is unattributed rather than dealt to one.

    The most specific match wins, so 'Amazon OpenSearch Serverless' is not
    reported as 'Amazon OpenSearch Service'.
    """
    candidates = [str(c).strip() for c in (candidate_techs or []) if str(c).strip()]
    if not candidates:
        return None
    title = source.get("title", "")
    url = source.get("url", "")
    haystack = f"{title} {url}".lower()

    matches: list[str] = []
    for candidate in candidates:
        if candidate_names_key(title, candidate) or candidate_names_key(url, candidate):
            matches.append(candidate)
            continue
        tokens = [t for t in candidate_tokens([candidate]) if len(t) >= 4]
        if not tokens:
            continue
        # The candidate's most distinctive token must appear as a whole word, so
        # 'Athena' matches 'Query S3 with Athena'. Where the candidate has further
        # words that actually disambiguate it ('Serverless'), those must appear
        # too: a page that only mentions the shared word 'opensearch' does not
        # establish which OpenSearch product it is about.
        primary = max(tokens, key=len)
        if not _word_present(primary, haystack):
            continue
        extras = [t for t in tokens if t != primary and t in _DISAMBIGUATING]
        if all(_word_present(t, haystack) for t in extras):
            matches.append(candidate)
    if not matches:
        return None
    # Prefer the most specific match, so a serverless page is not attributed to
    # the generic service.
    return max(matches, key=lambda c: (len(str(c)), len(candidate_tokens([c]))))


UNASSIGNED = "__unassigned__"


def index_sources_by_candidate(source_scores, candidate_techs) -> dict:
    """Group sources under the declared candidate each one is demonstrably about.

    Returns {candidate: [sources]} plus the UNASSIGNED key for material that
    cannot be attributed. Unattributable material is reported as unassigned
    rather than pushed onto whichever candidate shares a word.
    """
    index: dict[str, list[dict]] = {str(c).strip(): [] for c in (candidate_techs or [])
                                    if str(c).strip()}
    index[UNASSIGNED] = []
    for source in source_scores or []:
        owner = candidate_for_source(source, candidate_techs)
        index[owner if owner in index else UNASSIGNED].append(source)
    return index
