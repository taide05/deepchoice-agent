from datetime import datetime
import posixpath
import re
from urllib.parse import unquote, urlsplit

from ..utils.evidence import is_navigation_placeholder, source_title
from ..utils.evidence_choices import bounded_source_passages
from ..utils.official_catalog import (
    AUDITED_PRODUCT_SEED_IDENTITY,
    AUDITED_SNIPPET_WINDOW,
    is_catalog_official_url,
    normalized_hostname,
)


_AUDITED_SEED_TARGET_ALIASES = {
    "p01-sqlite-appropriate-uses": frozenset({"sqlite"}),
    "p01-sqlite-wal": frozenset({"sqlite"}),
    "p01-sqlite-backup": frozenset({"sqlite"}),
    "p01-sqlite-fts5": frozenset({"sqlite"}),
    "p01-postgresql-concurrency-introduction": frozenset({"postgresql", "postgres"}),
    "p01-postgresql-backup": frozenset({"postgresql", "postgres"}),
    "p01-postgresql-text-search-introduction": frozenset({"postgresql", "postgres"}),
    "p04-fastapi-background-tasks": frozenset(
        {"fastapi", "backgroundtasks", "fastapibackgroundtasks"}
    ),
    "p04-celery-introduction": frozenset({"celery"}),
    "p04-celery-task-semantics": frozenset({"celery"}),
    "p08-redis-data-types": frozenset({"redis"}),
    "p08-redis-persistence": frozenset({"redis"}),
    "p08-redis-eviction": frozenset({"redis"}),
    "p08-memcached-overview": frozenset({"memcached", "memcache"}),
    "p08-memcached-faq": frozenset({"memcached", "memcache"}),
}


def _candidate_patterns(task: dict) -> list[re.Pattern]:
    """Use only explicit candidates; do not guess technologies from prose."""
    candidates = task.get("candidate_techs", [])
    if not isinstance(candidates, (list, tuple)):
        return []
    patterns = []
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        words = candidate.casefold().split()
        name = r"\s+".join(re.escape(word) for word in words)
        # ASCII identifier boundaries retain Chinese/Latin mixed prose while
        # rejecting e.g. 'React' inside 'reactor' or 'C++' inside 'C++++'.
        patterns.append(re.compile(r"(?<![a-z0-9_+#])" + name + r"(?![a-z0-9_+#])"))
    return patterns


def _mentions_candidate(result: dict, patterns: list[re.Pattern]) -> bool:
    if not patterns:
        return True  # Legacy/category-only tasks have no explicit lexical gate.
    text = " ".join(
        value for key in ("title", "snippet")
        if isinstance((value := result.get(key)), str)
    ).casefold()
    return any(pattern.search(text) for pattern in patterns)


def _audited_seed_scope_covers_candidate(
    result: dict,
    source: str,
    candidates: object,
) -> bool | None:
    """Use an audited seed target only for the product named by its identity.

    Official pages often mention other products incidentally (for example as
    result backends).  Only the exact frozen identity and target registry may
    reject such a cross-scope page.  A positive scope match never grants
    admission: every result still passes the existing lexical candidate gate.
    Ordinary Chroma documents retain that gate without audited scope claims.
    """

    target_id = result.get("_seed_target_id")
    seed_identity = result.get("_seed_seed_identity_sha256")
    if (
        source != "chroma"
        or result.get("_seed_source_type") != "official"
        or seed_identity != AUDITED_PRODUCT_SEED_IDENTITY
    ):
        return None
    aliases = _AUDITED_SEED_TARGET_ALIASES.get(target_id)
    if aliases is None:
        return False
    if not isinstance(candidates, (list, tuple)) or not candidates:
        return True
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = "".join(re.findall(r"[a-z0-9]+", candidate.casefold()))
        if normalized in aliases:
            return True
    return False


def _audited_seed_lexically_names_target(result: dict) -> bool:
    """Match an audited target name across trusted slug/camel separators.

    This is deliberately narrower than general fuzzy matching: the caller has
    already verified the exact frozen seed identity and registered target ID,
    and a target alias must still occur in the visible title or snippet.  The
    provenance claim therefore cannot admit an opaque or unrelated document.
    """

    aliases = _AUDITED_SEED_TARGET_ALIASES.get(result.get("_seed_target_id"))
    if aliases is None:
        return False
    text = " ".join(
        value
        for key in ("title", "snippet")
        if isinstance((value := result.get(key)), str)
    )
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    # Match only complete tokens against explicit reviewed aliases.  Separator
    # slugs expose ``fastapi`` as its own token, while an explicitly reviewed
    # CamelCase spelling case-folds to the registered compact alias.  Never
    # concatenate arbitrary natural-language words (``red is`` != ``redis``).
    return any(token in aliases for token in tokens)


def _local_comparison_covers_candidates(result: dict, source: str,
                                        patterns: list[re.Pattern]) -> bool | None:
    """A local pair template must cover the whole explicit comparison.

    This is only lexical scope admission, not proof of any template claim.
    Ordinary single-candidate capability documents retain their admission.
    """
    if source != "chroma" or len(patterns) < 2:
        return None
    url = str(result.get("url", ""))
    if not url.casefold().startswith("file:"):
        return None
    title = result.get("title", "")
    if not isinstance(title, str):
        return None
    if title == source_title(None, url):
        # A missing title remains an explicit identifier in scored output.
        # Its local filename may still reveal an out-of-scope pair template;
        # decode only for lexical scope, without accessing the filesystem.
        try:
            path = unquote(urlsplit(url.replace("\\", "/")).path).replace("\\", "/")
        except ValueError:
            return False
        title = posixpath.splitext(posixpath.basename(path))[0]
    title = title.casefold()
    if not re.search(r"(?:[-_\s])vs(?:[-_\s])", title):
        return None
    # Preserve punctuation inside identifiers, and isolate only the pair
    # separator before also accepting whitespace-normalized multiword slugs.
    comparison_text = re.sub(r"[-_\s]+vs[-_\s]+", " vs ", title)
    normalized = re.sub(r"[-_]", " ", comparison_text)
    return all(pattern.search(title) or pattern.search(comparison_text)
               or pattern.search(normalized) for pattern in patterns)

WEIGHTS = {
    "authority": 0.35,
    "timeliness": 0.25,
    "consistency": 0.20,
    "verifiability": 0.20,
}

AUTHORITY_MAP = {
    "official_doc": 10,
    "arxiv_paper": 10,
    "tech_blog": 7,
    "github": 6,
    "stackoverflow": 5,
    "reddit": 4,
    "anonymous": 2,
}

VERIFIABILITY_MAP = {
    "code": 10,
    "benchmark": 8,
    "citation": 6,
    "opinion": 2,
}


def _host_in_family(host: str | None, family: str) -> bool:
    return host == family or (host is not None and host.endswith("." + family))


def classify_source_type(url: str, source: str) -> str:
    """Classify only valid HTTP(S) identities; source labels never prove authority."""
    if not isinstance(url, str) or url.casefold().startswith("file:"):
        return "tech_blog"
    host = normalized_hostname(url)
    if host is None:
        return "tech_blog"
    if _host_in_family(host, "arxiv.org"):
        return "arxiv_paper"
    if _host_in_family(host, "github.com"):
        return "github"
    if _host_in_family(host, "stackoverflow.com") or _host_in_family(host, "stackexchange.com"):
        return "stackoverflow"
    if _host_in_family(host, "reddit.com"):
        return "reddit"
    if is_catalog_official_url(url):
        return "official_doc"
    return "tech_blog"

def classify_evidence_type(snippet: str) -> str:
    snip_lower = snippet.lower()
    if any(kw in snip_lower for kw in ["```", "def ", "import ", "pip install", "npm install"]):
        return "code"
    if any(kw in snip_lower for kw in ["benchmark", "throughput", "latency", "rps", "tokens/s"]):
        return "benchmark"
    if any(kw in snip_lower for kw in ["according to", "cited by", "reference", "[1]", "[2]"]):
        return "citation"
    if any(kw in snip_lower for kw in ["i think", "in my opinion", "i prefer", "i believe"]):
        return "opinion"
    return "citation"


def score_authority(source_type: str) -> int:
    return AUTHORITY_MAP.get(source_type, 4)


def score_timeliness(date_str: str | None) -> int:
    if not date_str:
        return 5
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        age = (datetime.now() - d).days
        if age < 90:
            return 10
        if age < 180:
            return 8
        if age < 365:
            return 6
        if age < 730:
            return 4
        return 2
    except (ValueError, TypeError):
        return 5


def score_consistency(supporting_sources: list[str]) -> int:
    if len(supporting_sources) >= 2:
        return 10
    if len(supporting_sources) == 1:
        return 6
    return 4


def score_verifiability(evidence_type: str) -> int:
    return VERIFIABILITY_MAP.get(evidence_type, 4)


def compute_total_score(scores: dict[str, int]) -> float:
    return round(
        scores["authority"] * WEIGHTS["authority"]
        + scores["timeliness"] * WEIGHTS["timeliness"]
        + scores["consistency"] * WEIGHTS["consistency"]
        + scores["verifiability"] * WEIGHTS["verifiability"],
        1,
    )


class SourceEvaluatorAgent:
    def __init__(self, websocket=None, stream_output=None, headers=None):
        self.websocket = websocket
        self.stream_output = stream_output
        self.headers = headers

    async def run(self, research_state: dict) -> dict:
        all_results = []
        task = research_state.get("task", {})
        patterns = _candidate_patterns(task)
        candidates = task.get("candidate_techs", []) if isinstance(task, dict) else []
        excluded = 0
        seed_scope_excluded = 0
        navigation_excluded = 0
        for channel in research_state.get("search_results", []):
            source = channel.get("source", "unknown")
            for r in channel.get("results", []):
                if is_navigation_placeholder(r.get("snippet")):
                    navigation_excluded += 1
                    continue
                normalized_result = {**r, "title": source_title(r.get("title"), r.get("url"))}
                seed_scope_covers = _audited_seed_scope_covers_candidate(
                    normalized_result, source, candidates
                )
                if seed_scope_covers is False:
                    excluded += 1
                    seed_scope_excluded += 1
                    continue
                comparison_covers = _local_comparison_covers_candidates(normalized_result, source, patterns)
                if seed_scope_covers is True:
                    lexical_match = _audited_seed_lexically_names_target(normalized_result)
                else:
                    lexical_match = _mentions_candidate(normalized_result, patterns)
                if (comparison_covers is False
                        or (comparison_covers is None
                            and not lexical_match)):
                    excluded += 1
                    continue
                all_results.append({
                    **normalized_result, "_source": source,
                })

        source_scores = []
        for result in all_results:
            if "passages" in result:
                # Public retriever fields cannot assert already-checked passages.
                excluded += 1
                continue
            if "_source_passages" in result:
                passages = bounded_source_passages({
                    "snippet": result.get("snippet"),
                    "passages": result["_source_passages"],
                })
            else:
                passages = ()
            if passages is None:
                excluded += 1
                continue
            url = result.get("url", "")
            source = result.get("_source", "unknown")
            source_type = classify_source_type(url, source)
            evidence_type = classify_evidence_type(result.get("snippet", ""))

            scores = {
                "authority": score_authority(source_type),
                "timeliness": score_timeliness(result.get("date")),
                "consistency": score_consistency([]),
                "verifiability": score_verifiability(evidence_type),
            }
            total = compute_total_score(scores)

            scored = {
                "url": url,
                "title": result.get("title", ""),
                "snippet": result.get("snippet", ""),
                "source_type": source_type,
                "evidence_type": evidence_type,
                "scores": scores,
                "total_score": total,
                "supporting_sources": [],
            }
            if passages:
                scored["passages"] = list(passages)
            if (source == "chroma"
                    and result.get("_seed_excerpt_window") == AUDITED_SNIPPET_WINDOW
                    and _audited_seed_scope_covers_candidate(result, source, candidates) is True):
                scored["_seed_excerpt_window"] = AUDITED_SNIPPET_WINDOW
            source_scores.append(scored)

        # Authority/recency or a shared candidate name does not establish
        # claim agreement. No corroboration is inferred from another URL.

        source_scores.sort(key=lambda x: x["total_score"], reverse=True)
        for i, s in enumerate(source_scores):
            s["rank"] = i + 1

        avg_score = round(sum(s["total_score"] for s in source_scores) / len(source_scores), 1) if source_scores else 0

        return {
            "source_scores": source_scores,
            "quality_signals": [{
                "agent": "source_evaluator",
                "sources_scored": len(source_scores),
                "candidate_gate": "lexical" if patterns else "not_applied",
                "candidate_excluded_count": excluded,
                "audited_seed_scope_excluded_count": seed_scope_excluded,
                "navigation_excluded_count": navigation_excluded,
                "avg_score": avg_score,
                "high_score_count": sum(1 for s in source_scores if s["total_score"] >= 7.0),
                "low_score_count": sum(1 for s in source_scores if s["total_score"] < 5.0),
            }],
        }
