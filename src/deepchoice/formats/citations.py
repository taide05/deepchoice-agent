"""Post-processing for the report reading view: numbered citations and TOC anchors."""
import re

MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.*)$", re.MULTILINE)


def number_sources(chains: list[dict]) -> list[dict]:
    """Assign stable 1-based numbers to unique source URLs across evidence chains.

    Returns registry entries: {"n", "url", "title", "chain_idx"}. The frontend
    renders one evidence card per entry with id="ev-{n}".
    """
    registry: list[dict] = []
    seen: set[str] = set()
    for chain_idx, chain in enumerate(chains):
        for src in chain.get("sources", []):
            url = src.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            registry.append(
                {
                    "n": len(registry) + 1,
                    "url": url,
                    "title": src.get("title", ""),
                    "chain_idx": chain_idx,
                }
            )
    return registry


def inject_citations(md: str, registry: list[dict]) -> str:
    """Replace [title](url) links with title + superscript [N] anchor to #ev-N.

    Links whose URL is not in the registry are left untouched.
    """
    by_url = {r["url"]: r["n"] for r in registry}

    def _sub(match: re.Match) -> str:
        title, url = match.group(1), match.group(2)
        n = by_url.get(url)
        if n is None:
            return match.group(0)
        return f'{title}<sup><a class="cite" href="#ev-{n}">[{n}]</a></sup>'

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
