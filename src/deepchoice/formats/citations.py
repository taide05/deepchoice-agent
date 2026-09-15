"""Post-processing for the report reading view: numbered citations and TOC anchors."""
import html
import re

from deepchoice.citations import canonicalize_source_url

MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.*)$", re.MULTILINE)


def number_sources(chains: list[dict]) -> list[dict]:
    """Assign stable 1-based numbers to unique source URLs across evidence chains.

    Returns one registry entry per canonical URL. The frontend renders one
    evidence card per entry with id="ev-{n}".
    """
    registry: list[dict] = []
    by_canonical_url: dict[str, dict] = {}
    status_priority = {"verified": 0, "unknown": 1, "unreachable": 2, "unsupported": 3}
    allowed_reasons = {
        "lexical_support", "citation_missing", "source_not_found", "source_ambiguous",
        "url_invalid", "source_limit", "not_publicly_accessible", "network_uncertain",
        "http_uncertain", "content_insufficient", "cross_language", "numeric_mismatch",
        "negation_conflict", "lexical_mismatch", "not_cited",
    }
    for chain_idx, chain in enumerate(chains):
        for source_idx, src in enumerate(chain.get("sources", [])):
            url = src.get("url", "")
            if not isinstance(url, str) or not url:
                continue
            # Recompute at the presentation boundary; legacy/imported state is
            # not trusted merely because it contains a canonical_url field.
            canonical_url = canonicalize_source_url(url)
            # Invalid or legacy URLs still get a stable registry key based on
            # their exact original value; the frontend independently gates links.
            key = canonical_url or url
            status = src.get("verification_status", "unknown")
            if not isinstance(status, str) or status not in status_priority:
                status = "unknown"
            reason = src.get("verification_reason")
            if not isinstance(reason, str) or reason not in allowed_reasons:
                reason = "not_checked"

            entry = by_canonical_url.get(key)
            if entry is None:
                entry = {
                    "n": len(registry) + 1,
                    "url": canonical_url or url,
                    "canonical_url": canonical_url,
                    "title": src.get("title", ""),
                    "chain_idx": chain_idx,
                    "source_idx": source_idx,
                    "verification_status": status,
                    "verification_reason": reason,
                }
                by_canonical_url[key] = entry
                registry.append(entry)
            elif status_priority[status] > status_priority[entry["verification_status"]]:
                entry["verification_status"] = status
                entry["verification_reason"] = reason
    return registry


def inject_citations(md: str, registry: list[dict]) -> str:
    """Replace [title](url) links with title + superscript [N] anchor to #ev-N.

    Links whose URL is not in the registry are left untouched.
    """
    by_url: dict[str, int] = {}
    for entry in registry:
        url = entry.get("url", "")
        if not isinstance(url, str) or not url:
            continue
        canonical = canonicalize_source_url(url)
        by_url[canonical or url] = entry["n"]

    def _sub(match: re.Match) -> str:
        title, url = match.group(1), match.group(2)
        canonical = canonicalize_source_url(url)
        n = by_url.get(canonical or url)
        if n is None:
            return match.group(0)
        return f'{html.escape(title)}<sup><a class="cite" href="#ev-{n}">[{n}]</a></sup>'

    return MD_LINK_RE.sub(_sub, md)


def build_toc(md: str) -> tuple[list[dict], str]:
    """Inject <span id="sec-N"> anchors before h1-h3 headings; return (toc, annotated_md)."""
    toc: list[dict] = []

    def _sub(match: re.Match) -> str:
        text = re.sub(r"[*_`]", "", match.group(2)).strip()
        sec_id = len(toc) + 1
        toc.append({"id": f"sec-{sec_id}", "level": len(match.group(1)), "text": text})
        return f'<span id="sec-{sec_id}"></span>\n{match.group(0)}'

    return toc, HEADING_RE.sub(_sub, md)


def citation_verification_section(state: dict, lang: str) -> list[str]:
    """Return a concise bilingual citation-verification summary, if present."""
    verification = state.get("citation_verification")
    counts = verification.get("status_counts") if isinstance(verification, dict) else None
    if not isinstance(counts, dict):
        return []

    statuses = ("verified", "unsupported", "unreachable", "unknown")
    normalized: dict[str, int] = {}
    for status in statuses:
        value = counts.get(status, 0)
        normalized[status] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    if lang == "zh":
        heading = "## 引用验证 / Citation Verification"
        summary = "已核验 {verified} · 不支持 {unsupported} · 无法访问 {unreachable} · 未能判定 {unknown}"
        warning = "请人工复核不支持、无法访问或未能判定的引用；“未能判定”表示证据不足以判断，不等于引用错误。"
        success = "所有已检查的引用均通过确定性核验。"
    else:
        heading = "## Citation Verification / 引用验证"
        summary = "Verified {verified} · Unsupported {unsupported} · Unreachable {unreachable} · Unknown {unknown}"
        warning = "Please review unsupported, unreachable, or unknown citations. Unknown means inconclusive, not necessarily incorrect."
        success = "All checked citations passed deterministic verification."

    lines = [heading, "", summary.format(**normalized)]
    if any(normalized[s] for s in ("unsupported", "unreachable", "unknown")):
        lines.append(warning)
    elif normalized["verified"]:
        lines.append(success)
    return [*lines, ""]
