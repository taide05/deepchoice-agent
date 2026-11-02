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
from urllib.parse import unquote, urlparse

# Shared evidence input budget. The old per-source 1,600-character cut is gone:
# when all saved bodies fit the budget, both synthesis and self-review receive
# the complete saved text. Only a genuinely over-budget package is excerpted,
# and the ranges/omitted spans are recorded for both consumers.
EVIDENCE_INPUT_BUDGET_CHARS = int(
    os.environ.get("EVIDENCE_INPUT_BUDGET_CHARS", "24000"))

# Decision-relevant anchor words used only when a source body must be excerpted
# (2026-11-02 R9 work). The full-200 review found that decisive caveats/lifecycle
# facts could sit in the omitted middle of a long official page while the
# excerpt kept only head/tail and candidate-name windows. These anchors widen the
# excerpt toward the facts a selection decision depends on; they never admit a
# source or change the budget.
_DECISION_KEYWORDS = (
    "however", " but ", " only ", " not ", "cannot", " requires", " required",
    " must ", "limitation", "depends", "unknown", "caveat", "except",
    "restrict", "deprecated", "migration", "breaking change", "end of life",
    "eol", "maintenance", "license", "pricing", "cost", " sla", "support",
    "security", "audit", "rbac", "permission", "performance", "latency",
    "throughput", "benchmark", "rollback", "backup", "upgrade", "compatib",
    "不支持", "仅", "限制", "必须", "未知", "弃用", "迁移", "维护",
    "许可", "价格", "成本", "安全", "审计", "权限", "性能", "延迟",
    "吞吐", "基准", "回滚", "升级", "兼容",
)

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
        # substring containment would let 'vector' match 'pgvector'. A short key
        # ('Vue', 'Koa', 'dbt', 'uv') is accepted only by exact equality, never by
        # containment, so short product names still resolve their own mapping.
        token = key_tokens[0]
        if token in cand_tokens:
            return len(token) >= 4 or cand_tokens == [token]
        return False
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


def _compact_text(text: str) -> str:
    return " ".join(str(text or "").split())


def evidence_focus_terms(task: dict | None = None, *,
                         candidate_techs=None, constraints=None,
                         sub_questions=None) -> list[str]:
    """Terms used only when a package is too large to pass in full.

    Candidate names are always retained. Constraint/sub-question vocabulary is
    included only as generic words from the request; this is not a per-case
    keyword list and it never changes which sources are admitted.
    """
    task = task or {}
    candidates = candidate_techs if candidate_techs is not None else task.get("candidate_techs")
    constraint_text = constraints if constraints is not None else task.get("constraints")
    questions = sub_questions if sub_questions is not None else task.get("sub_questions")
    terms: list[str] = []
    for value in list(candidates or []):
        value = _compact_text(value)
        if value and value not in terms:
            terms.append(value)
    text = " ".join([str(x) for x in (constraint_text or [])]
                    + [str(x) for x in (questions or [])]
                    + [str(task.get("query") or "")])
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{2,}", text):
        low = raw.lower()
        if (len(low) < 4 or low in _GENERIC or low in terms
                or low in {t.lower() for t in terms}):
            continue
        terms.append(raw)
    return terms[:40]


def evidence_focus_terms_for_state(research_state: dict) -> list[str]:
    """One state-derived selection input for synthesis and self-review.

    Both stages must make the same excerpt decision from the same research state;
    in particular sub_questions cannot enter only one stage's focus set.
    """
    state = research_state or {}
    task = state.get("task") or {}
    return evidence_focus_terms(task, sub_questions=state.get("sub_questions"))


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _excerpt_spans(content: str, raw_budget: int,
                    focus_terms: list[str],
                    decision_windows: bool = True) -> list[tuple[int, int]]:
    """Select original-character spans within a raw-text allowance.

    Priority order: candidate/sub-question focus windows (and nearby qualifiers)
    first, then decision-relevant anchor windows, then head/tail context with the
    remaining room. The 2026-11-02 R9 work added the decision anchors because a
    long official page's decisive caveat/lifecycle/licensing sentence could sit in
    the omitted middle while head/tail consumed the budget.
    """
    raw_budget = max(40, int(raw_budget))
    spans: list[tuple[int, int]] = []
    qualifiers = ("however", "but ", "only", "not ", "cannot", "requires",
                  "must ", "limitation", "depends", "unknown", "caveat",
                  "except", "restrict", "不支持", "仅", "限制", "必须", "未知")
    haystack = content.lower()
    for term in focus_terms:
        needle = _compact_text(term).lower()
        start = 0
        hits = 0
        while hits < 3:
            pos = haystack.find(needle, start)
            if pos < 0:
                break
            spans.append((max(0, pos - 220), min(len(content), pos + len(needle) + 260)))
            for qualifier in qualifiers:
                qpos = haystack.find(qualifier, max(0, pos - 420),
                                     min(len(content), pos + len(needle) + 420))
                if qpos >= 0:
                    spans.append((max(0, qpos - 160), min(len(content), qpos + 240)))
            start = pos + len(needle)
            hits += 1
    if decision_windows:
        hits = 0
        for term in _DECISION_KEYWORDS:
            if hits >= 12:
                break
            start = 0
            while hits < 12:
                pos = haystack.find(term, start)
                if pos < 0:
                    break
                spans.append((max(0, pos - 180), min(len(content),
                                                     pos + len(term) + 240)))
                hits += 1
                start = pos + max(1, len(term))

    def _union_len(ranges: list[tuple[int, int]]) -> int:
        return sum(end - start for start, end in _merge_spans(ranges))

    selected: list[tuple[int, int]] = []
    for span in spans:
        trial = _merge_spans(selected + [span])
        if _union_len(trial) <= raw_budget:
            selected = trial
    if not selected:
        # No focus/decision anchor in this body: keep the historical prefix cut
        # (a head/tail-only slice would waste budget on such bodies and leave
        # substantial headroom unused across the package).
        selected = [(0, min(len(content), raw_budget))]
    else:
        # Head/tail context only gets the room the priority spans did not need.
        head = max(160, min(len(content), raw_budget // 4))
        tail = max(120, min(len(content), raw_budget // 5))
        for span in ((0, head), (max(0, len(content) - tail), len(content))):
            trial = _merge_spans(selected + [span])
            if _union_len(trial) <= raw_budget:
                selected = trial
    return selected


def _render_excerpt(content: str,
                    selected: list[tuple[int, int]]) -> tuple[str, int]:
    pieces: list[str] = []
    cursor = 0
    for start, end in selected:
        if start > cursor:
            pieces.append(
                f"…[{start - cursor} chars omitted; source offsets {cursor}-{start}]…")
        pieces.append(content[start:end])
        cursor = end
    if cursor < len(content):
        pieces.append(
            f"…[{len(content) - cursor} chars omitted; source offsets {cursor}-{len(content)}]…")
    omitted = max(0, len(content) - sum(end - start for start, end in selected))
    return " ".join(pieces), omitted


def _select_excerpt(content: str, limit: int,
                    focus_terms: list[str] | None = None,
                    decision_windows: bool = True
                    ) -> tuple[str, list[tuple[int, int]], int, bool]:
    """Bounded excerpt whose *complete serialized text* fits `limit`.

    Focus-anchored windows (with nearby qualifiers) plus head/tail context are
    selected from original source offsets. Omission markers are part of the
    limit; if they would overflow, the raw span allowance is reduced and the
    excerpt is rebuilt. The final fallback is an explicit bounded prefix with its
    range and omitted count, never a blind chop of a fully built string.
    """
    content = _compact_text(content)
    if limit <= 0:
        return "", [], len(content), False
    if len(content) <= limit:
        return content, [(0, len(content))], 0, True
    if limit < 200:
        kept = min(limit, len(content))
        return content[:kept], [(0, kept)], len(content) - kept, False
    focus_terms = [t for t in (focus_terms or []) if len(_compact_text(t)) >= 3]
    raw_budget = limit
    selected: list[tuple[int, int]] = []
    text = ""
    omitted = len(content)
    for _ in range(16):
        selected = _excerpt_spans(content, raw_budget, focus_terms, decision_windows)
        text, omitted = _render_excerpt(content, selected)
        if len(text) <= limit:
            return text, selected, omitted, False
        overflow = len(text) - limit
        raw_budget = max(40, raw_budget - overflow)
        if raw_budget <= 40:
            break
    # Very small limits cannot carry meaningful multi-span omission markers.
    # Retain a contiguous, explicitly recorded prefix rather than truncating a
    # selected string or emitting a marker that exceeds the budget.
    kept = min(limit, len(content))
    return content[:kept], [(0, kept)], len(content) - kept, False


def _source_budget_weight(entry: dict) -> float:
    """Relative share of a constrained evidence budget for one source.

    Decisive-source signals (a source in a recorded conflict pair, first-party
    official documentation, identity-verified body) get a larger share; community
    material gets a slightly smaller one. This changes only how a fixed budget is
    divided when the package is already over budget; it never admits, drops or
    increases the total, so the token cost is unchanged.
    """
    weight = 1.0
    if entry.get("disputed"):
        weight += 0.35
    source_type = str(entry.get("source_type") or "").lower()
    if source_type == "official_doc":
        weight += 0.20
    if entry.get("body_identity_verified") is True:
        weight += 0.15
    is_community = (
        source_type in {"stackoverflow", "reddit"}
        or str(entry.get("provenance") or "").lower() == "community"
        or str(entry.get("channel") or "").lower() == "community")
    if is_community:
        weight -= 0.10
    return max(0.6, min(weight, 1.75))


def _evidence_limits(contents: list[str], budget: int,
                     weights: list[float] | None = None) -> list[int]:
    """Water-fill limits, weighted by source importance.

    Small bodies stay complete; the remaining budget is divided by weight instead
    of equally, so a decisive/large source keeps more of its middle content.
    """
    count = len(contents)
    if not weights or len(weights) != count:
        weights = [1.0] * count
    limits = [0] * count
    active = list(range(count))
    remaining = budget
    while active:
        total_weight = sum(weights[index] for index in active) or 1.0
        caps: dict[int, int] = {}
        small: list[int] = []
        for index in active:
            share = remaining * weights[index] / total_weight
            cap = max(80, int(share) - min(160, max(0, int(share)) // 5))
            caps[index] = cap
            if len(contents[index]) <= cap:
                small.append(index)
        if not small:
            for index in active:
                limits[index] = caps[index]
            break
        for index in small:
            limits[index] = len(contents[index])
            remaining -= len(contents[index])
            active.remove(index)
    # Hard ceiling: tiny configured budgets or very many sources can otherwise
    # make the minimum per-source floors exceed the declared total. Trim the
    # largest limits first; zero-limit sources become explicit empty excerpts.
    excess = sum(limits) - budget
    if excess > 0:
        for index in sorted(range(len(limits)), key=lambda i: limits[i], reverse=True):
            take = min(excess, limits[index])
            limits[index] -= take
            excess -= take
            if excess <= 0:
                break
    return limits


def shared_evidence_package(entries: list[dict], *,
                            focus_terms: list[str] | None = None,
                            budget_chars: int | None = None,
                            prioritize: bool = True,
                            decision_windows: bool = True) -> dict:
    """Build the one evidence package used by synthesis and self-review.

    The package includes complete saved bodies whenever their total fits the
    configured input budget. Only when the total is larger does it select bounded
    excerpts, and every view records its original ranges and omitted characters.
    The total budget is unchanged; ``prioritize`` (weighted per-source shares) and
    ``decision_windows`` (decision-relevant anchor windows) only change which part
    of an over-budget body stays visible.
    """
    entries = list(entries or [])
    budget = max(500, int(EVIDENCE_INPUT_BUDGET_CHARS if budget_chars is None
                          else budget_chars))
    contents = [_compact_text(source_content(entry)) for entry in entries]
    total_stored = sum(len(c) for c in contents)
    full_included = total_stored <= budget
    if full_included:
        limits = None
    else:
        weights = ([_source_budget_weight(entry) for entry in entries]
                   if prioritize else None)
        limits = _evidence_limits(contents, budget, weights)
    views: dict[int, dict] = {}
    visible_total = 0
    omitted_total = 0
    for index, (entry, content) in enumerate(zip(entries, contents)):
        key = entry.get("number", index)
        if full_included:
            visible, ranges, omitted, included = content, [(0, len(content))], 0, True
        else:
            visible, ranges, omitted, included = _select_excerpt(
                content, max(1, limits[index] if limits else budget), focus_terms,
                decision_windows)
        view = _evidence_view(entry, content, visible, ranges, omitted,
                              included)
        views[key] = view
        visible_total += view["visible_chars"]
        omitted_total += view["omitted_chars"]
    return {
        "budget_chars": budget,
        "total_stored_chars": total_stored,
        "visible_chars": visible_total,
        "omitted_chars": omitted_total,
        "full_included": full_included,
        "sources": len(entries),
        "views": views,
        "focus_terms": list(focus_terms or []),
    }


def _evidence_view(source: dict, content: str, visible: str,
                   ranges: list[tuple[int, int]], omitted: int,
                   full_included: bool) -> dict:
    stored_chars = len(content)
    page_known = "body_page_chars" in source or "body_chars" in source
    if page_known:
        page_chars = int(source.get("body_page_chars") or source.get("body_chars")
                         or stored_chars)
        page_chars = max(page_chars, stored_chars)
        page_truncated = bool(source.get("body_page_truncated", False))
    else:
        page_chars = None
        page_truncated = None
    stored_truncated = bool(source.get("body_stored_truncated")) or (
        page_known and page_chars is not None and page_chars > stored_chars)
    return {
        "text": visible,
        "body_url": str(source.get("body_url") or source.get("url") or ""),
        "source_owner": source.get("source_owner"),
        "source_kind": source.get("source_kind"),
        "source_type": source.get("source_type"),
        "body_identity_verified": source.get("body_identity_verified"),
        "fetch_status": source.get("fetch_status"),
        "page_chars": page_chars,
        "page_chars_known": page_known,
        "stored_chars": stored_chars,
        "source_chars": page_chars if page_known else stored_chars,
        "visible_chars": len(visible),
        "omitted_chars": omitted,
        "selection_ranges": list(ranges),
        "full_included": full_included,
        "page_truncated": page_truncated,
        "stored_truncated": stored_truncated,
        "visible_truncated": len(visible) < stored_chars,
        "truncated": bool(stored_truncated or len(visible) < stored_chars
                          or page_truncated is True),
        "has_body": True,
    }


def bounded_evidence_record(source: dict, limit: int | None = None) -> dict:
    """Legacy single-source view; no hidden per-source cut.

    With no limit the complete stored body is returned. A caller that passes a
    limit asks for an explicit excerpt and receives its source ranges. The
    synthesis and self-review consumers use `shared_evidence_package` instead,
    so they share one total input budget.
    """
    content = _compact_text(source_content(source))
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
            "text": gap, "page_chars": 0, "page_chars_known": False,
            "stored_chars": 0, "source_chars": 0, "visible_chars": 0,
            "omitted_chars": 0, "selection_ranges": [], "full_included": False,
            "page_truncated": False, "stored_truncated": False,
            "truncated": False, "has_body": False,
        }
    if limit is None:
        return _evidence_view(source, content, content, [(0, len(content))], 0, True)
    visible, ranges, omitted, included = _select_excerpt(content, int(limit), [])
    return _evidence_view(source, content, visible, ranges, omitted, included)


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


def source_text_discusses_candidate(term: str, title: str = "",
                                     content: str = "") -> bool:
    """Whether a page visibly discusses the declared candidate/constraint.

    This is the *page-subject* check, separate from domain ownership and from
    source authority. It accepts a display title such as "Cosign Overview" for
    "Sigstore (Cosign)" because the distinctive alias token is present; it does
    not by itself make the page official.
    """
    variants = _candidate_name_variants(term)
    text = f"{title or ''} {content or ''}".lower()
    if not variants or not text.strip():
        return False
    for tokens in variants:
        for token in tokens:
            if len(token) >= 3 and _word_present(token, text):
                return True
    return False


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


def _identity_tokens(term: str) -> list[str]:
    return [normalize_term(t) for t in _name_tokens(term)
            if len(normalize_term(t)) >= 2]


_PUBLIC_HOSTING_SUFFIXES = (
    # Shared hosting where the product-like label belongs to a user, not to the
    # product owner. This is a source-identity safety list, not a product alias
    # table; curated mappings still cover legitimate official pages elsewhere.
    "github.io", "gitlab.io", "pages.dev", "netlify.app", "vercel.app",
    "herokuapp.com", "web.app", "firebaseapp.com", "azurewebsites.net",
    "cloudfront.net", "blogspot.com", "wordpress.com", "medium.com",
    "substack.com", "notion.site", "readthedocs.io", "s3.amazonaws.com",
    "storage.googleapis.com",
)


def _is_public_hosting(host: str) -> bool:
    host = host.lower().strip(".")
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in _PUBLIC_HOSTING_SUFFIXES)


def _candidate_name_variants(term: str) -> list[list[str]]:
    """Token variants for one declared name; parenthesized text is an alias.

    "Sigstore (Cosign)" can be owned by sigstore.dev and "Notary Project
    (Notation)" by notaryproject.dev; neither requires the alias in the host.
    The full token sequence remains a variant as well.
    """
    raw = str(term or "").strip()
    base_text = re.sub(r"\([^)]*\)", " ", raw).strip() or raw
    variants: list[list[str]] = []
    for tokens in (_identity_tokens(base_text), _identity_tokens(raw)):
        if tokens and tokens not in variants:
            variants.append(tokens)
    return variants


def source_url_identity_match(term: str, url: str) -> bool:
    """Whether a URL's *identity-bearing host/path* names this declared term.

    This replaces the old 'the complete product name must equal a host label'
    test. A multi-word name may be concatenated into one host label
    (`Kata Containers` -> katacontainers.io) or split across an owned vendor host
    and path (`Amazon EKS` -> docs.aws.amazon.com/eks). It is still a bounded
    identity test, not a similarity score: an unrelated host such as
    `katacontainers-blog.example` or `example.com/katacontainers` does not pass.
    """
    term = str(term or "").strip()
    url = str(url or "").strip()
    if not term or not url:
        return False
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().strip(".")
    if not host:
        return False
    labels = [normalize_term(part) for part in host.split(".") if part]
    path = normalize_term(unquote(parsed.path or ""))
    variants = _candidate_name_variants(term)
    if not variants or len(labels) < 2:
        return False
    # Public hosts such as someuser.github.io share a registrable-looking label
    # with the product but are user subdomains, not official ownership.
    if _is_public_hosting(host):
        return False
    for tokens in variants:
        joined = "".join(tokens)
        # A canonical product label immediately before the TLD. Subdomains are
        # fine; a label inside someone else's domain is not identity proof.
        if len(labels) >= 2 and labels[-2] == joined and len(joined) >= 3:
            return True
        if len(tokens) == 1:
            if tokens[0] == labels[-2] and len(tokens[0]) >= 3:
                return True
            continue
        # Multi-word names may split across an owned host and path
        # (aws.amazon.com/eks, docs.github.com/actions).
        if tokens[0] == labels[-2] and all(
                token in path or token in labels for token in tokens[1:]):
            return True
    return False


def source_text_identity_match(term: str, title: str = "",
                               content: str = "") -> bool:
    """Whether a page's title/body actually names the declared term.

    URL similarity alone is not enough to treat a page as the product's official
    source; the fetched page must name the product. The same function is used for
    candidate products and declared platform constraints.
    """
    term = str(term or "").strip()
    if not term:
        return False
    title = str(title or "")
    content = str(content or "")
    if names_candidate(title, term) or names_candidate(content, term):
        return True
    joined = normalize_term(term)
    if len(joined) < 3:
        return False
    for value in (title, content):
        normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
        if re.search(rf"(?<![a-z0-9]){re.escape(joined)}(?![a-z0-9])",
                     normalized):
            return True
    return False


def source_identity_verified(term: str, url: str, title: str = "",
                             content: str = "") -> bool:
    """A safe-fetched source is attributable only if URL and page agree."""
    return (source_url_identity_match(term, url)
            and source_text_discusses_candidate(term, title, content))


_CONSTRAINT_STOP_STARTS = {
    "our", "the", "current", "first", "second", "third", "this", "that",
    "we", "if", "when", "only", "must", "should", "can", "cannot", "future",
    "platform", "production", "customer", "customers", "team", "they", "it",
    "all", "any", "other", "this", "these", "those",
}


def _platform_like_phrase(raw: str, lookup) -> bool:
    words = [w for w in re.split(r"\s+", raw.strip()) if w]
    if not words:
        return False
    if lookup and mapping_key_for([raw], lookup):
        return True
    if len(words) == 1:
        word = words[0]
        # All-caps acronyms or internal-caps product names (RuntimeClass) are
        # platform-like; an ordinary sentence-start capitalization (Deploy,
        # Support, Existing) is not.
        return ((word.isupper() and len(word) >= 2)
                or any(ch.isupper() for ch in word[1:]))
    # Multi-word name: require a distinctive later acronym/digit or a known
    # mapping match, so "Deploy the service" cannot become a discovery target.
    return (any(w.isupper() and len(w) >= 2 for w in words[1:])
            or any(any(ch.isdigit() for ch in w) for w in words[1:]))


def constraint_discovery_terms(constraints, candidate_techs=None,
                               lookup=None, limit: int = 3) -> list[str]:
    """Generic platform/constraint names worth official-source discovery.

    This is deliberately not a product alias table. It extracts explicit
    capitalized/acronym phrases from the frozen constraints, filters ordinary
    words, and prioritises names already present in the curated mapping. The
    declared candidates are excluded because they are handled separately.
    """
    candidates = [str(c).strip() for c in (candidate_techs or []) if str(c).strip()]
    candidate_keys = {normalize_term(c) for c in candidates}
    terms: list[str] = []
    seen: set[str] = set()
    for constraint in constraints or []:
        text = str(constraint or "")
        for match in re.finditer(
                r"(?<![A-Za-z0-9])"
                r"([A-Z][A-Za-z0-9.+#-]*(?:\s+[A-Z0-9][A-Za-z0-9.+#-]*){0,2})",
                text):
            raw = match.group(1).strip()
            raw = raw.strip(".,;:()[]")
            if not raw:
                continue
            words = [w for w in re.split(r"\s+", raw) if w]
            if not words or words[0].lower() in _CONSTRAINT_STOP_STARTS:
                continue
            low = normalize_term(raw)
            if len(low) < 3 or low in candidate_keys or low in seen:
                continue
            if low in _GENERIC:
                continue
            if any(normalize_term(c) == low for c in candidates):
                continue
            if not _platform_like_phrase(raw, lookup):
                continue
            seen.add(low)
            terms.append(raw)
        for acronym in re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,7}(?![A-Za-z0-9])",
                                  text):
            low = normalize_term(acronym)
            if len(low) < 3 or low in seen or low in _GENERIC:
                continue
            if any(normalize_term(c).startswith(low) for c in candidates):
                continue
            seen.add(low)
            terms.append(acronym)
    preferred = []
    if lookup:
        for term in terms:
            if mapping_key_for([term], lookup):
                preferred.append(term)
    ordered = preferred + [t for t in terms if t not in preferred]
    return ordered[:max(0, limit)]
