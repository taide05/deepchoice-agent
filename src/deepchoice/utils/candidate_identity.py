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
# a mapping entry count as "named by this candidate". This list predates the
# candidate-attribution work; attribution itself no longer consults word lists.
_GENERIC = frozenset("""
on in for with and or the a an of to using use used via at by from
official documentation docs site database server managed service store
amazon aws google cloud azure self hosted hostable
""".split())

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+#-]*")

# Only articles and prepositions stop an identity phrase from the front. Words
# like 'amazon' are part of a product's name, and treating them as generic
# truncated 'Amazon Athena over S3' to nothing, so real material was reported as
# a gap.
_LEADING_STOP = frozenset("""
a an the of for on in with and or to using use used via at by from
self hosted managed over under
""".split())

# Words that mark the start of a variant or qualifier rather than the identity:
# 'Amazon OpenSearch Serverless' is the Serverless variant of OpenSearch, and
# 'Athena over S3' adds a qualifier. Both stop the identity phrase, so the
# Serverless page still resolves to Serverless via its full-name match.
_QUALIFIER = frozenset("""
serverless service managed provisioned over on via using with
s3 cloud enterprise basic standard premium
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
    # The explicit gap sentence produced by bounded_content_summary is also not
    # content. It is a statement about the source, not by it, and must not become
    # citable merely because it is a non-empty string.
    if body.startswith("NO CONTENT RETRIEVED"):
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

    `has_body` is the authoritative marker, set where the source is created when
    no page body was collected. The string shape is only a fallback, because
    relying on a placeholder's exact wording is how a body-less source stayed
    citable before: the gap sentence is non-empty and reads as text.
    """
    if "has_body" in source:
        return bool(source.get("has_body"))
    content, _ = split_navigation_label(source.get("snippet", ""))
    if content:
        return True
    body = source.get("content") or source.get("body") or ""
    return bool(str(body).strip())


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


def identity_phrase(candidate: str) -> tuple[str, ...]:
    """The candidate's leading identity phrase, as normalized tokens.

    'Amazon Athena over S3' -> ('amazon', 'athena'); 'ClickHouse' -> ('clickhouse').
    A page about the product is normally titled with this much of the name, so
    requiring the rest ('over S3') reported real Athena material as a gap.

    The run stops at the first qualifier — a preposition, a size/number token, or
    a generic product word — because everything after that is a variant or a
    qualifier rather than the identity itself.
    """
    run: list[str] = []
    for token in str(candidate).split():
        clean = re.sub(r"[^a-z0-9]", "", token.strip().lower())
        if not clean or clean in _LEADING_STOP or clean in _QUALIFIER:
            break
        run.append(clean)
    return tuple(run)


def phrase_present(phrase: tuple[str, ...], text: str) -> bool:
    """Whether the text contains the token sequence as a contiguous phrase."""
    if not phrase:
        return False
    wanted = [normalize_term(tok) for tok in phrase]
    got = [normalize_term(t) for t in _name_tokens(text)]
    got = [t for t in got if t]
    width = len(wanted)
    return any(got[i:i + width] == wanted for i in range(len(got) - width + 1))


def subject_tokens(source: dict) -> tuple[str, ...]:
    """The tokens naming a source's own subject, from its title and host.

    A page titles itself after what it is about: 'Amazon OpenSearch 对比
    Elasticsearch | Elastic' is Elastic's page, and it appears in a site's own
    listing. This is used only to decide that a page is about something else — it
    never attributes a page to a candidate.
    """
    title = str(source.get("title", "") or "")
    url = str(source.get("url", "") or "")
    run: list[str] = []
    for token in _name_tokens(title):
        clean = re.sub(r"[^a-z0-9]", "", token)
        if not clean or clean in _LEADING_STOP:
            break
        run.append(clean)
        if len(run) >= 3:
            break
    host = ""
    match = re.match(r"https?://([^/]+)", url)
    if match:
        host = re.sub(r"^www\.", "", match.group(1).split(":")[0])
        host = host.split(".")[0]
    if host:
        run.append(re.sub(r"[^a-z0-9]", "", host.lower()))
    return tuple(t for t in run if t)


def _mentioned_in_body(candidate: str, body: str) -> bool:
    """Whether the body text actually discusses the candidate.

    The title may name a product while the collected text is about a different
    one, which is how a third-party comparison page became another product's
    basis. Either the identity phrase or the candidate's own name must appear.
    """
    if not body.strip():
        return False
    text = f"{body}"
    if phrase_present(identity_phrase(candidate), text):
        return True
    return names_candidate(text, candidate)


def candidate_for_source(source: dict, candidate_techs) -> str | None:
    """The declared candidate a source is demonstrably about, or None.

    Two levels, both name-based and neither consulting a word list:

    1. The source names the candidate in full. A source sharing only part of a
       name is not evidence about it — 'PostgreSQL 17 release notes' is not
       material for 'Amazon Aurora PostgreSQL with pgvector'.
    2. The source names the candidate's identity phrase — the leading proper-noun
       run. A page is normally titled 'Amazon Athena - Serverless Interactive
       Query Service' when it is about the candidate 'Amazon Athena over S3', and
       requiring the full name there reported real material as a gap.

    Longest candidate first, so a source naming the specific product is not
    attributed to a shorter candidate whose name it also contains.
    """
    candidates = [str(c).strip() for c in (candidate_techs or []) if str(c).strip()]
    if not candidates:
        return None
    title = source.get("title", "")
    url = source.get("url", "")
    ordered = sorted(candidates, key=len, reverse=True)

    # A page's own subject decides first. If the page names some other product or
    # vendor as its subject and only mentions this candidate in passing, its body
    # is not this candidate's material: the Elastic pricing page and the SelectDB
    # comparison are about Elastic and SelectDB, not the candidate they mention.
    subject = subject_tokens(source)
    if subject:
        def _names_candidate_identity(candidate: str) -> bool:
            phrase = identity_phrase(candidate)
            if not phrase:
                return True
            width = len(phrase)
            return any(subject[i:i + width] == phrase
                       for i in range(len(subject) - width + 1))

        named = [c for c in ordered if _names_candidate_identity(c)]
        if named:
            # The page's subject is one of the declared candidates, but its body
            # must actually discuss it: a third-party comparison titled after one
            # product whose text is entirely about another is not that product's
            # material. Mention of the candidate is the weakest acceptable link,
            # and stricter than the title alone.
            body = f"{source.get('snippet', '') or ''}"
            discussed = [c for c in named if _mentioned_in_body(c, body)]
            if not discussed:
                return None
            for candidate in discussed:
                if names_candidate(title, candidate) or names_candidate(url, candidate):
                    return candidate
            return discussed[0]
        # The page has an identifiable subject and it is none of the declared
        # candidates, so this is material about something else. It stays
        # unassigned rather than becoming the basis of a candidate it only
        # mentions — third-party and vendor comparison pages are the common case.
        return None

    for candidate in ordered:
        if names_candidate(title, candidate) or names_candidate(url, candidate):
            return candidate
    for candidate in ordered:
        if phrase_present(identity_phrase(candidate), f"{title} {url}"):
            return candidate
    return None


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
