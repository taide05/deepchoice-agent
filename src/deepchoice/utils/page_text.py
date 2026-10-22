"""Bounded structural text extraction for fetched HTML.

Ported minimally from the maintenance worktree's citations/source_windows.py;
only the page-document extractor and its parser are kept. Navigation, forms,
hidden subtrees, scripts/styles and headings are excluded from prose eligibility;
the extractor returns block structure, not a keyword/truth score.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

MAX_DOCUMENT_TEXT = 64 * 1024
MAX_PROSE_DEPTH = 64
_BLOCK_TAGS = frozenset({
    "article", "blockquote", "br", "dd", "div", "dt", "h1", "h2", "h3",
    "h4", "h5", "h6", "li", "main", "p", "pre", "section", "td", "th",
})
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "svg", "template", "aside", "footer", "header",
})
_PROSE_TAGS = frozenset({"p", "blockquote", "dd", "td"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_CONTROL_TAGS = frozenset({"button", "option"})
_NON_PROSE_TAGS = frozenset({
    "a", "code", "pre", "head", "header", "title", "h1", "h2", "h3",
    "h4", "h5", "h6",
})


@dataclass(frozen=True, slots=True)
class SourceDocument:
    blocks: tuple[str, ...]
    incomplete: bool
    prose_indices: tuple[int, ...] = ()
    text_chars: int = 0
    link_chars: int = 0
    non_heading_chars: int = 0
    control_chars: int = 0
    main_blocks: tuple[str, ...] = ()
    page_role: str = "unknown"
    heading_context_count: int = 0


class _Blocks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_tags = _SKIP_TAGS | {"nav", "form"}
        self.blocks: list[str] = []
        self.prose_indices: list[int] = []
        self.prose_context: list[str] = []
        self.prose_tracking_exhausted = False
        self.pending_prose = False
        self.pending: list[str] = []
        self.ignored_depth = 0
        self.omitted_tag = None
        self.omitted_depth = 0
        self.used = 0
        self.exhausted = False
        self.text_chars = 0
        self.link_chars = 0
        self.link_depth = 0
        self.heading_depth = 0
        self.control_depth = 0
        self.non_heading_chars = 0
        self.control_chars = 0
        self.block_meta: list[dict] = []
        self.pending_link_chars = 0
        self.pending_control_chars = 0
        self.pending_non_heading_chars = 0
        self.heading_block = False

    def flush(self) -> None:
        text = " ".join("".join(self.pending).split())
        self.pending = []
        prose, self.pending_prose = self.pending_prose, False
        heading, self.heading_block = self.heading_block, False
        if not text or self.exhausted:
            return
        if self.used + len(text) + 1 > MAX_DOCUMENT_TEXT:
            self.exhausted = True
            return
        if prose:
            self.prose_indices.append(len(self.blocks))
        self.blocks.append(text)
        self.block_meta.append({
            "heading": heading,
            "link_chars": self.pending_link_chars,
            "control_chars": self.pending_control_chars,
            "non_heading_chars": self.pending_non_heading_chars,
        })
        self.pending_link_chars = 0
        self.pending_control_chars = 0
        self.pending_non_heading_chars = 0
        self.used += len(text) + 1

    def handle_starttag(self, tag, attrs):
        if self.omitted_depth:
            if tag == self.omitted_tag:
                self.omitted_depth += 1
            return
        if not self.ignored_depth and any(
            (key == "role" and "navigation" in (value or "").casefold().split())
            or key == "hidden"
            or (key == "aria-hidden" and (value or "").strip().casefold() == "true")
            for key, value in attrs
        ):
            self.flush()
            if tag not in {
                "area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "param", "source", "track", "wbr",
            }:
                self.omitted_tag, self.omitted_depth = tag, 1
            return
        if tag in self.skip_tags:
            if not self.ignored_depth:
                self.flush()
            self.ignored_depth += 1
        if not self.ignored_depth:
            if tag == "a":
                self.link_depth += 1
            if tag in _HEADING_TAGS:
                self.heading_depth += 1
            if tag in _CONTROL_TAGS:
                self.control_depth += 1
            if tag in _BLOCK_TAGS:
                self.flush()
            if tag in _HEADING_TAGS:
                self.heading_block = True
            if (not self.prose_tracking_exhausted
                    and tag in _PROSE_TAGS | _NON_PROSE_TAGS):
                if len(self.prose_context) >= MAX_PROSE_DEPTH:
                    self.prose_tracking_exhausted = True
                    self.prose_context.clear()
                    self.prose_indices.clear()
                    self.pending_prose = False
                else:
                    self.prose_context.append(tag)

    def handle_endtag(self, tag):
        if self.omitted_depth:
            if tag == self.omitted_tag:
                self.omitted_depth -= 1
            return
        if tag in self.skip_tags and self.ignored_depth:
            self.ignored_depth -= 1
        if not self.ignored_depth:
            if tag == "a" and self.link_depth:
                self.link_depth -= 1
            if tag in _HEADING_TAGS and self.heading_depth:
                self.heading_depth -= 1
            if tag in _CONTROL_TAGS and self.control_depth:
                self.control_depth -= 1
            if self.prose_context and self.prose_context[-1] == tag:
                self.prose_context.pop()
            elif tag in self.prose_context:
                index = next(
                    index for index in range(len(self.prose_context) - 1, -1, -1)
                    if self.prose_context[index] == tag)
                del self.prose_context[index:]
            if tag in _BLOCK_TAGS or tag == "body":
                self.flush()

    def handle_data(self, data):
        if not self.ignored_depth and not self.omitted_depth and not self.exhausted:
            self.pending.append(data)
            visible = " ".join(data.split())
            self.text_chars += len(visible)
            if self.link_depth:
                self.link_chars += len(visible)
                self.pending_link_chars += len(visible)
            if self.control_depth:
                self.control_chars += len(visible)
                self.pending_control_chars += len(visible)
            elif not self.heading_depth:
                self.non_heading_chars += len(visible)
                self.pending_non_heading_chars += len(visible)
            if (not self.prose_tracking_exhausted
                    and any(tag in _PROSE_TAGS for tag in self.prose_context)
                    and not any(tag in _NON_PROSE_TAGS for tag in self.prose_context)
                    and any(char.isalpha() for char in data)):
                self.pending_prose = True


def _select_main_blocks(blocks: list[str], meta: list[dict],
                        prose_indices: tuple[int, ...]) -> tuple[list[str], int]:
    """Main paragraphs plus the nearest heading context, not a nav dump."""
    prose_set = set(prose_indices)
    selected: list[str] = []
    headings: list[str] = []
    heading_count = 0
    for index, text in enumerate(blocks):
        info = meta[index] if index < len(meta) else {}
        if info.get("heading"):
            headings.append(text)
            headings = headings[-3:]
            continue
        if index not in prose_set:
            continue
        if headings:
            selected.extend(headings)
            heading_count += len(headings)
            headings = []
        selected.append(text)
    return selected, heading_count


def extract_page_document(value: str, *, truncated: bool,
                          plain_text: bool = False) -> SourceDocument:
    """Extract visible blocks and prose eligibility from a fetched page.

    The `incomplete` flag means the page body ended before the document closed
    (or the transport cut it); a caller must not treat the stored excerpt as the
    whole page in that case. `main_blocks` keeps prose paragraphs plus the
    nearest heading context, so navigation labels and bare menus are not passed
    downstream as page content even when the fetch succeeded.
    """
    value = value.removeprefix("\ufeff")
    if plain_text:
        blocks: list[str] = []
        used = 0
        for line in value.splitlines():
            text = " ".join(line.split())
            if not text:
                continue
            if used + len(text) + 1 > MAX_DOCUMENT_TEXT:
                selected, headings = _select_main_blocks(
                    blocks, [{"heading": False} for _ in blocks],
                    tuple(range(len(blocks))))
                return SourceDocument(tuple(blocks), True, tuple(range(len(blocks))),
                                      sum(len(block) for block in blocks), 0,
                                      sum(len(block) for block in blocks), 0,
                                      tuple(selected), "prose_document", headings)
            blocks.append(text)
            used += len(text) + 1
        selected, headings = _select_main_blocks(
            blocks, [{"heading": False} for _ in blocks],
            tuple(range(len(blocks))))
        return SourceDocument(tuple(blocks), truncated, tuple(range(len(blocks))),
                              sum(len(block) for block in blocks), 0,
                              sum(len(block) for block in blocks), 0,
                              tuple(selected), "prose_document", headings)
    parser = _Blocks()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return SourceDocument((), True)
    unfinished = (
        bool("".join(parser.pending).strip())
        or bool(parser.ignored_depth)
        or bool(parser.omitted_depth)
    )
    selected, headings = _select_main_blocks(
        parser.blocks, parser.block_meta, tuple(parser.prose_indices))
    total_chars = parser.text_chars or sum(len(block) for block in parser.blocks)
    prose_chars = sum(len(parser.blocks[i]) for i in parser.prose_indices
                      if i < len(parser.blocks))
    prose_ratio = (prose_chars / total_chars) if total_chars else 0.0
    link_ratio = (parser.link_chars / total_chars) if total_chars else 1.0
    control_ratio = (parser.control_chars / total_chars) if total_chars else 1.0
    if not parser.prose_indices:
        if (total_chars >= 400 and link_ratio <= 0.15
                and control_ratio <= 0.20 and parser.non_heading_chars >= 300):
            page_role = "structured_document"
            selected = [block for block in parser.blocks
                        if block.strip()][:80]
            headings = 0
        else:
            page_role = "navigation"
    elif (prose_ratio >= 0.30 and link_ratio <= 0.25
          and control_ratio <= 0.20):
        page_role = "prose_document"
    elif prose_ratio >= 0.20 and link_ratio <= 0.25:
        page_role = "mixed_document"
    else:
        page_role = "navigation"
    return SourceDocument(
        tuple(parser.blocks), truncated or parser.exhausted or unfinished,
        tuple(parser.prose_indices), parser.text_chars, parser.link_chars,
        parser.non_heading_chars, parser.control_chars,
        tuple(selected), page_role, headings,
    )


__all__ = ["SourceDocument", "extract_page_document", "MAX_DOCUMENT_TEXT"]
