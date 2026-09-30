import asyncio

from .. import outbound as _outbound
from ..outbound import throttle
from ..budget_errors import BudgetError
from ..utils.llm import call_model
from .base import BaseRetriever
from .official_pages import MAX_ROOTS, budgeted_http, read_official_roots
from .learned_docs import (
    _looks_official,
    domain_label_match,
    is_plausible_term,
    learn,
    load_learned,
)

from ..utils.official_catalog import TECH_DOCS

# Mapping of known tech terms to their official documentation sites.
# Curated list — only entries with stable, well-known doc URLs.
# Self-updates at runtime: learned pairs (harvest + LLM fallback) persist
# to learned_docs.json and are consulted before this seed dict.

_LLM_FALLBACK_MAX = 3

_VS_MARKERS = (" vs ", " versus ", " 对比 ", " 比较 ")


def _is_vs_query(query: str) -> bool:
    return any(m in query.lower() for m in _VS_MARKERS)


def _normalize(s: str) -> str:
    """Lowercase, alphanumerics only — 'AWS Lambda' and 'aws-lambda' both normalize to 'awslambda'."""
    return "".join(c for c in s.lower() if c.isalnum())


# Bare-token aliases mapping to a curated TECH_DOCS key. Applied via normalized
# lookup so "postgres" resolves to "postgresql" without an LLM fallback. Only
# unambiguous shorthands are listed — ambiguous tokens are left to the LLM.
_TECH_ALIASES = {
    "next": "next.js",
    "transformers": "huggingface",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
}



class OfficialSearch(BaseRetriever):
    source = "official"

    async def _propose_official_url(self, term: str) -> str | None:
        """LLM fallback: propose an official docs URL for an unmapped term."""
        result = await call_model(
            [
                {
                    "role": "system",
                    "content": (
                        "You map technology terms to their official documentation URLs. "
                        'Reply with JSON {"url": "https://..."} or {"url": null} if unsure. '
                        "Only well-known official sites — never guess or invent."
                    ),
                },
                {"role": "user", "content": f"Official documentation URL for: {term}"},
            ],
            model="deepseek-flash", tag="official_fallback",
            response_format="json",
        )
        if isinstance(result, dict):
            return result.get("url")
        return None

    async def _verify_reachable(self, url: str) -> bool:
        try:
            resp = await budgeted_http(
                lambda: _outbound.safe_fetch(
                    "official", url, method="HEAD",
                    allowed_content_types=("text/html", "application/xhtml+xml"),
                    head_fallback_to_range_get=True,
                ), kind="official_reachability",
            )
            if resp.status_code == 429:
                raise throttle.ProviderRateLimitError("official documentation rate limited")
            return resp.status_code == 200
        except (BudgetError, throttle.ProviderAdmissionError):
            raise
        except Exception:
            return False

    async def _do_search(self, query: str, sub_questions: list[str], max_results: int,
                         adapted_queries: list[str] | None = None) -> list[dict]:
        from ..runtime.context import get_run_context

        all_text = " ".join(adapted_queries) if adapted_queries else query
        keywords = all_text.lower().replace(" vs ", " ").replace(" versus ", " ").split()
        learned = load_learned()
        # Curated seed always wins: a learned entry must never shadow a
        # hand-verified mapping (e.g. a harvested 'python' entry once
        # overrode docs.python.org with python.langchain.com).
        lookup = {**learned, **TECH_DOCS}
        results = []
        roots = []

        # Pass 1: curated seed + learned cache via normalized n-gram matching.
        # Space-separated multi-word terms ('AWS Lambda') match hyphenated or
        # dotted keys ('aws-lambda', 'next.js') through alnum normalization.
        norm_lookup = {_normalize(k): k for k in lookup}
        for alias, target in _TECH_ALIASES.items():
            if target in lookup:
                norm_lookup[_normalize(alias)] = target
        matched_norms: set[str] = set()
        matched_ngram_components: set[str] = set()
        for n in (1, 2, 3):
            for i in range(len(keywords) - n + 1):
                phrase = " ".join(keywords[i:i + n])
                norm = _normalize(phrase)
                key = norm_lookup.get(norm)
                if key is None or norm in matched_norms:
                    continue
                matched_norms.add(norm)
                matched_ngram_components.update(_normalize(kw) for kw in keywords[i:i + n])
                doc = lookup[key]
                if key in TECH_DOCS and doc["url"] not in {item["url"] for item in roots}:
                    roots.append({"url": doc["url"], "title": doc["title"], "tech": key})
                results.append({
                    "url": doc["url"],
                    "title": doc["title"],
                    "snippet": f"Official documentation site for {key}",
                    "date": "",
                })

        # Pass 1.5: LLM fallback for unmapped candidate terms (validated + learned)
        unmapped = []
        for kw in keywords:
            kw_clean = kw.strip().rstrip(".").rstrip(",")
            if (kw_clean not in lookup and kw_clean not in unmapped
                    and is_plausible_term(kw_clean)
                    and _normalize(kw_clean) not in matched_ngram_components):
                unmapped.append(kw_clean)
        async def _resolve_fallback(kw):
            url = await self._propose_official_url(kw)
            if not url or not domain_label_match(kw, url):
                return None
            if not _looks_official(url):
                return None
            if not await self._verify_reachable(url):
                return None
            return kw, url

        pending = unmapped[:_LLM_FALLBACK_MAX]
        resolved = await asyncio.gather(*[_resolve_fallback(kw) for kw in pending],
                                        return_exceptions=True)
        for item in resolved:
            if isinstance(item, BudgetError):
                raise item
        for item in resolved:
            if isinstance(item, BaseException):
                raise item
        for item in resolved:
            if item is None:
                continue
            kw, url = item
            learn(kw, url, f"{kw} — Official Documentation", via="llm")
            lookup[kw] = {"url": url, "title": f"{kw} — Official Documentation"}
            results.append({
                "url": url,
                "title": f"{kw} — Official Documentation",
                "snippet": f"Official documentation site for {kw}",
                "date": "",
            })

        # Pass 2: PyPI search for packages. Restricted to vs-style comparison
        # queries — on open-scenario queries the tokens are ordinary English
        # words ('feature', 'team', 'wants'), and PyPI matches polluted the
        # evidence chains with junk packages (recommended "flag (PyPI)" once).
        if _is_vs_query(query):
            async with await _outbound.make_client("official") as client:
                for kw in keywords[:3]:
                    if len(kw) < 3:
                        continue
                    resp = await budgeted_http(
                        lambda: throttle.get("official", client, f"https://pypi.org/pypi/{kw}/json"),
                        kind="official_package_metadata",
                    )
                    if resp.status_code not in (200, 404):
                        raise RuntimeError(f"PyPI HTTP {resp.status_code}")
                    if resp.status_code != 200:
                        continue
                    info = resp.json().get("info", {})
                    results.append({
                        "url": info.get("package_url", f"https://pypi.org/project/{kw}/"),
                        "title": f"{kw} (PyPI)",
                        "snippet": f"Version: {info.get('version', 'N/A')}, Summary: {info.get('summary', '')}",
                        "date": "",
                    })
        if get_run_context() is not None:
            # New body traversal is durable-only and requires real HTTP budget
            # admission. Learned/fallback URLs retain their old directory role.
            selected = roots[:min(MAX_ROOTS, max_results)]
            bodies = await read_official_roots(selected, " ".join([query, all_text, *sub_questions]))
            replaced = {item["url"] for item in selected}
            results = bodies + [item for item in results if item["url"] not in replaced]
        return results[:max_results]
