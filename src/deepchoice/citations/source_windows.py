"""Bounded text-block locations for runtime-copied source excerpts.

Locations establish text provenance, not semantic truth. Keep complete blocks
and a neighbouring block on each side; never clip away a trailing condition.
"""
from dataclasses import dataclass
from html.parser import HTMLParser

MAX_DOCUMENT_TEXT = 64 * 1024
MAX_SOURCE_WINDOW = 6000
MAX_PROSE_DEPTH = 64
_BLOCK_TAGS = frozenset({
    'article', 'blockquote', 'br', 'dd', 'div', 'dt', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'li', 'main', 'p', 'pre', 'section', 'td', 'th',
})
_SKIP_TAGS = frozenset({'script', 'style', 'noscript', 'svg', 'template'})
_PROSE_TAGS = frozenset({'p', 'blockquote', 'dd', 'td'})
_NON_PROSE_TAGS = frozenset({'a', 'code', 'pre', 'head', 'header', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})


@dataclass(frozen=True, slots=True)
class SourceDocument:
    blocks: tuple[str, ...]
    incomplete: bool
    # Local extraction provenance only; never grants fact/citation authority.
    prose_indices: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceWindow:
    text: str
    outside: tuple[str, ...]


class _Blocks(HTMLParser):
    def __init__(self, *, skip_navigation: bool = False, preserve_pre: bool = False):
        super().__init__(convert_charrefs=True)
        self.skip_tags = _SKIP_TAGS | ({"nav", "form"} if skip_navigation else set())
        if skip_navigation and not preserve_pre:
            self.skip_tags |= {"pre"}
        self.separate_omitted = skip_navigation
        self.blocks = []
        self.prose_indices = []
        self.prose_context = []
        self.prose_tracking_exhausted = False
        self.pending_prose = False
        self.pending = []
        self.ignored_depth = 0
        self.omitted_tag = None
        self.omitted_depth = 0
        self.used = 0
        self.exhausted = False

    def flush(self):
        text = ' '.join(''.join(self.pending).split())
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
        if self.separate_omitted and not self.ignored_depth and any(
            (key == "role" and "navigation" in (value or "").casefold().split()) or key == "hidden"
            or (key == "aria-hidden" and (value or "").strip().casefold() == "true")
            for key, value in attrs
        ):
            self.flush()
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self.omitted_tag, self.omitted_depth = tag, 1
            return
        if tag in self.skip_tags:
            if self.separate_omitted and not self.ignored_depth:
                self.flush()
            self.ignored_depth += 1
        if not self.ignored_depth:
            if tag in _BLOCK_TAGS:
                self.flush()
            if (self.separate_omitted and not self.prose_tracking_exhausted
                    and tag in _PROSE_TAGS | _NON_PROSE_TAGS):
                if len(self.prose_context) >= MAX_PROSE_DEPTH:
                    # Fail closed only for new short-prose eligibility. Keep
                    # source text and its original completeness boundaries.
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
            if self.prose_context and self.prose_context[-1] == tag:
                self.prose_context.pop()
            elif tag in self.prose_context:
                index = next(index for index in range(len(self.prose_context) - 1, -1, -1)
                             if self.prose_context[index] == tag)
                del self.prose_context[index:]
            if tag in _BLOCK_TAGS or tag == 'body':
                self.flush()

    def handle_data(self, data):
        if not self.ignored_depth and not self.omitted_depth and not self.exhausted:
            self.pending.append(data)
            if (self.separate_omitted and not self.prose_tracking_exhausted
                    and any(tag in _PROSE_TAGS for tag in self.prose_context)
                    and not any(tag in _NON_PROSE_TAGS for tag in self.prose_context)
                    and any(char.isalpha() for char in data)):
                self.pending_prose = True


def extract_source_document(
    value: str, *, truncated: bool, plain_text: bool = False, skip_navigation: bool = False,
    raise_on_error: bool = False, preserve_pre: bool = False,
) -> SourceDocument:
    value = value.removeprefix('\ufeff')
    if plain_text:
        lines = value.splitlines()
        if truncated and lines:
            lines = lines[:-1]
        blocks = []
        used = 0
        for line in lines:
            text = ' '.join(line.split())
            if not text:
                continue
            if used + len(text) + 1 > MAX_DOCUMENT_TEXT:
                return SourceDocument(tuple(blocks), True)
            blocks.append(text)
            used += len(text) + 1
        return SourceDocument(tuple(blocks), truncated)
    parser = _Blocks(skip_navigation=skip_navigation, preserve_pre=preserve_pre)
    try:
        parser.feed(value)
        parser.close()
        # Only block boundaries close HTML text. EOF does not establish that
        # an unclosed paragraph retained its trailing qualification.
    except Exception:
        if raise_on_error:
            raise
        return SourceDocument((), True)
    unfinished = bool(''.join(parser.pending).strip()) or bool(parser.ignored_depth) or bool(parser.omitted_depth)
    return SourceDocument(tuple(parser.blocks), truncated or parser.exhausted or unfinished,
                          tuple(parser.prose_indices))


def locate_source_window(excerpt: str, document: SourceDocument) -> SourceWindow | None:
    excerpt = ' '.join(excerpt.split())
    if not excerpt or len(excerpt) > 1200:
        return None
    whole = ' '.join(document.blocks)
    start = whole.find(excerpt)
    if start < 0 or whole.find(excerpt, start + 1) >= 0:
        return None
    end = start + len(excerpt)
    positions = []
    cursor = 0
    for index, block in enumerate(document.blocks):
        if cursor < end and cursor + len(block) > start:
            positions.append(index)
        cursor += len(block) + 1
    if not positions:
        return None
    block_start = sum(len(block) + 1 for block in document.blocks[:positions[0]])
    block_end = sum(len(block) + 1 for block in document.blocks[:positions[-1] + 1]) - 1
    before, after = whole[block_start:start].rstrip(), whole[end:block_end].lstrip()
    # Exact substrings inside a word or in the middle of a sentence cannot
    # masquerade as complete copied sentences. Keep the whole surrounding block
    # in the window even when the excerpt itself starts/ends at a sentence edge.
    if before and before[-1] not in '.!?。！？;；:：':
        return None
    if after and excerpt[-1] not in '.!?。！？;；':
        return None
    if start > block_start and not (whole[start - 1].isspace() or whole[start - 1] in '。！？；'):
        return None
    if end < block_end and not (whole[end].isspace() or excerpt[-1] in '。！？；'):
        return None
    # A following complete block is necessary at an incomplete response edge.
    if document.incomplete and positions[-1] == len(document.blocks) - 1:
        return None
    left, right = max(0, positions[0] - 1), min(len(document.blocks), positions[-1] + 2)
    text = ' '.join(document.blocks[left:right])
    if len(text) > MAX_SOURCE_WINDOW:
        return None
    return SourceWindow(text, document.blocks[:left] + document.blocks[right:])


def locate_source_windows(excerpts: tuple[str, ...], document: SourceDocument) -> tuple[SourceWindow, ...] | None:
    """Locate separate, ordered excerpts in one saved source document.

    Each excerpt retains the existing complete-boundary and ambiguity checks.
    This proves location only; it does not grant semantic support or allow a
    joined excerpt to masquerade as contiguous page text.
    """
    if not isinstance(excerpts, tuple) or not 1 <= len(excerpts) <= 3:
        return None
    whole = " ".join(document.blocks)
    previous_end = 0
    total = 0
    windows: list[SourceWindow] = []
    for excerpt in excerpts:
        if not isinstance(excerpt, str):
            return None
        clean = " ".join(excerpt.split())
        total += len(clean)
        if not clean or total + 2 * (len(windows)) > 1200:
            return None
        start = whole.find(clean)
        if start < previous_end:
            return None
        window = locate_source_window(clean, document)
        if window is None:
            return None
        windows.append(window)
        previous_end = start + len(clean)
    return tuple(windows)
