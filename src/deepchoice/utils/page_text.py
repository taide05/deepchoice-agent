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

    def flush(self) -> None:
        text = " ".join("".join(self.pending).split())
        self.pending = []
        prose, self.pending_prose = self.pending_prose, False
        if not text or self.exhausted:
            return
        if self.used + len(text) + 1 > MAX_DOCUMENT_TEXT:
            self.exhausted = True
            return
        if prose:
            self.prose_indices.append(len(self.blocks))
        self.blocks.append(text)
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
            if self.control_depth:
                self.control_chars += len(visible)
            elif not self.heading_depth:
                self.non_heading_chars += len(visible)
            if (not self.prose_tracking_exhausted
                    and any(tag in _PROSE_TAGS for tag in self.prose_context)
                    and not any(tag in _NON_PROSE_TAGS for tag in self.prose_context)
                    and any(char.isalpha() for char in data)):
                self.pending_prose = True


def extract_page_document(value: str, *, truncated: bool,
                          plain_text: bool = False) -> SourceDocument:
    """Extract visible blocks and prose eligibility from a fetched page.

    The `incomplete` flag means the page body ended before the document closed
    (or the transport cut it); a caller must not treat the stored excerpt as the
    whole page in that case.
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
                return SourceDocument(tuple(blocks), True, tuple(range(len(blocks))),
                                      sum(len(block) for block in blocks), 0,
                                      sum(len(block) for block in blocks), 0)
            blocks.append(text)
            used += len(text) + 1
        return SourceDocument(tuple(blocks), truncated, tuple(range(len(blocks))),
                              sum(len(block) for block in blocks), 0,
                              sum(len(block) for block in blocks), 0)
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
    return SourceDocument(
        tuple(parser.blocks), truncated or parser.exhausted or unfinished,
        tuple(parser.prose_indices), parser.text_chars, parser.link_chars,
        parser.non_heading_chars, parser.control_chars,
    )


__all__ = ["SourceDocument", "extract_page_document", "MAX_DOCUMENT_TEXT"]
