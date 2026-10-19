"""Post-processing for the report reading view: numbered citations and TOC anchors."""
import html
import re

# Inline Markdown link scanner. A real source title may contain `[...]`, and a
# report may contain an unmatched `[` in body text; both must be handled without
# losing the annotations of later links.
HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.*)$", re.MULTILINE)


def _iter_markdown_links(text: str):
    """Yield (start, end, label, url) for inline Markdown links.

    Link labels may contain balanced square brackets — a real source title like
    `Stop Leaked Secrets in Git With Gitleaks [2026]` is a valid Markdown label.
    A flat `[^]]*` regex stopped at the inner bracket and silently skipped the
    link, so its citation badge was never injected even though the rendered
    Markdown itself was valid. The scanner tracks bracket depth and then reads
    the `(url)` destination.
    """
    i = 0
    length = len(text)
    while i < length:
        if text[i] != "[":
            i += 1
            continue
        depth = 0
        label_end = -1
        j = i
        while j < length:
            char = text[j]
            if char == "\\":
                j += 2
                continue
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    label_end = j
                    break
            j += 1
        if label_end == -1:
            # An unmatched `[` in body text is not a reason to abandon the rest
            # of the report; advance past it and keep looking for real links.
            i += 1
            continue
        if label_end + 1 < length and text[label_end + 1] == "(":
            url_end = text.find(")", label_end + 2)
            if url_end != -1:
                url = text[label_end + 2:url_end].strip()
                if url.startswith(("http://", "https://")) and " " not in url:
                    yield i, url_end + 1, text[i + 1:label_end], url
                    i = url_end + 1
                    continue
        i += 1


def number_sources(chains: list[dict]) -> list[dict]:
    """Assign stable 1-based numbers to unique source URLs across evidence chains.

    Returns registry entries: {"n", "url", "title", "chain_idx"}. The frontend
    renders one evidence card per entry with id="ev-{n}".

    Only fact-bearing sources are numbered. A discovered link whose page body was
    never collected is navigation, not evidence: giving it a citation number and
    an evidence card would present it as a source of the report's claims.
    """
    from ..utils.candidate_identity import has_factual_content

    registry: list[dict] = []
    seen: set[str] = set()
    for chain_idx, chain in enumerate(chains):
        for src in chain.get("sources", []):
            if not has_factual_content(src):
                continue
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

    Links whose URL is not in the registry are left untouched. Link labels with
    balanced brackets are handled by the shared scanner, so a legitimate title
    containing `[...]` still gets its annotation.
    """
    by_url = {r["url"]: r["n"] for r in registry}
    pieces: list[str] = []
    last = 0
    for start, end, title, url in _iter_markdown_links(md):
        n = by_url.get(url)
        if n is None:
            continue
        pieces.append(md[last:start])
        pieces.append(f'{html.escape(title)}'
                      f'<sup><a class="cite" href="#ev-{n}">[{n}]</a></sup>')
        last = end
    pieces.append(md[last:])
    return "".join(pieces)


def build_toc(md: str) -> tuple[list[dict], str]:
    """Inject <span id="sec-N"> anchors before h1-h3 headings; return (toc, annotated_md)."""
    toc: list[dict] = []

    def _sub(match: re.Match) -> str:
        text = re.sub(r"[*_`]", "", match.group(2)).strip()
        sec_id = len(toc) + 1
        toc.append({"id": f"sec-{sec_id}", "level": len(match.group(1)), "text": text})
        return f'<span id="sec-{sec_id}"></span>\n{match.group(0)}'

    return toc, HEADING_RE.sub(_sub, md)
