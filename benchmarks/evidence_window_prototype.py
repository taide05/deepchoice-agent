"""Non-production, offline experiment in bounded evidence-window selection.

This module is deliberately a locator, not a verifier. Query hints only help
locate a contiguous part of the supplied snippet; no text is generated,
translated, reordered, or semantically judged here.
Counterexamples prevent promotion: local sentence boundaries do not guarantee
that distant scope conditions, table headers, or provider-truncated text survive.
All outputs are therefore provisional and non-binding, including short inputs.
No default workflow imports this module; it must not authorize citations.
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_right
from itertools import islice
import re
from typing import Iterable

from deepchoice.utils.evidence import is_navigation_placeholder


OMITTED_BEFORE = "[preceding text omitted]"
OMITTED_AFTER = "[following text omitted]"
MAX_SCAN_CHARS = 20_000
MAX_HINTS = 64
MAX_HINT_CHARS = 1_000
MAX_TOKENS = 128

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._+\-][A-Za-z0-9]+)*")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_SENTENCE_END_RE = re.compile(r'[。！？!?][\"\u201d\u2019\)]*|\.(?=\s|$)')

# This is intentionally small and functional rather than a language or domain
# dictionary. It prevents e.g. "the" and "with" becoming anchors while
# retaining candidate/product names and technical terms.
_FUNCTION_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
        "to", "use", "using", "what", "which", "with", "的", "和", "或", "在",
        "是", "了", "与", "及", "请", "选择", "使用",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceWindow:
    """A bounded view; completeness flags describe local selection, not support."""

    text: str
    excerpt: str
    start: int
    end: int
    selection_mode: str
    omitted_before: bool
    omitted_after: bool
    boundary_complete: bool
    context_complete: bool
    can_bind: bool


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(_CONTROL_RE.sub(" ", value).split())


def _hint_values(query_hints: object) -> list[str]:
    if isinstance(query_hints, str):
        values: Iterable[object] = (query_hints,)
    else:
        try:
            values = query_hints if query_hints is not None else ()
            iter(values)
        except TypeError:
            values = ()
    result: list[str] = []
    for value in islice(values, MAX_HINTS):
        clean = _normalize(value[:MAX_HINT_CHARS]) if isinstance(value, str) else ""
        if clean:
            result.append(clean)
    return result


def _lexical_tokens(value: str) -> list[str]:
    """Return stable ASCII words and CJK bigrams from normalized text."""
    tokens: list[str] = []
    for match in _ASCII_TOKEN_RE.finditer(value):
        token = match.group(0).casefold()
        if token not in _FUNCTION_WORDS:
            tokens.append(token)
    for match in _CJK_RE.finditer(value):
        run = match.group(0)
        if len(run) >= 2:
            tokens.append(run)
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        elif run and run not in _FUNCTION_WORDS:
            tokens.append(run)
    return tokens


def _hint_tokens(query_hints: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for hint in _hint_values(query_hints):
        for token in _lexical_tokens(hint):
            if token in seen:
                continue
            seen.add(token)
            result.append(token)
            if len(result) >= MAX_TOKENS:
                return result
    return result


def _sentence_spans(value: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(value):
        end = match.end()
        spans.append((start, end))
        start = end
    if start < len(value):
        spans.append((start, len(value)))
    return spans


def _token_occurrences(value: str) -> list[tuple[str, int, int]]:
    occurrences: list[tuple[str, int, int]] = []
    for match in _ASCII_TOKEN_RE.finditer(value):
        occurrences.append((match.group(0).casefold(), match.start(), match.end()))
    for match in _CJK_RE.finditer(value):
        run = match.group(0)
        if len(run) >= 2:
            occurrences.append((run, match.start(), match.end()))
            occurrences.extend(
                (run[index : index + 2], match.start() + index, match.start() + index + 2)
                for index in range(len(run) - 1)
            )
        elif run:
            occurrences.append((run, match.start(), match.end()))
    return occurrences


def _render(value: str, start: int, end: int, truncated=False) -> tuple[str, bool, bool]:
    omitted_before = start > 0
    omitted_after = end < len(value) or truncated
    prefix = (OMITTED_BEFORE + " ") if omitted_before else ""
    suffix = (" " + OMITTED_AFTER) if omitted_after else ""
    return prefix + value[start:end] + suffix, omitted_before, omitted_after


def _rendered_length(value: str, start: int, end: int, truncated=False) -> int:
    return len(_render(value, start, end, truncated)[0])


def _shrink_to_fit(value: str, start: int, end: int, limit: int, truncated=False) -> tuple[int, int]:
    if limit <= 0:
        return start, start
    while end > start and _rendered_length(value, start, end, truncated) > limit:
        end -= 1
    return start, end


def _empty_window() -> EvidenceWindow:
    return EvidenceWindow("", "", 0, 0, "empty", False, False, False, False, False)


def _fallback(value: str, limit: int, truncated=False) -> EvidenceWindow:
    if not value or limit <= 0:
        return EvidenceWindow("", "", 0, 0, "fallback", False, bool(value), False, False, False)
    end = min(len(value), limit)
    while end > 0 and _rendered_length(value, 0, end, truncated) > limit:
        end -= 1
    text, before, after = _render(value, 0, end, truncated)
    if len(text) > limit:
        text = ""
    return EvidenceWindow(text, value[0:end], 0, end, "fallback", before, after,
                          False, False, False)


def _partial_lexical(value: str, hit_start: int, hit_end: int, limit: int, truncated=False) -> EvidenceWindow:
    if limit <= 0:
        return EvidenceWindow("", "", hit_start, hit_start, "lexical", hit_start > 0,
                              hit_start < len(value), False, False, False)
    start = max(0, hit_start - max(1, limit // 3))
    end = min(len(value), start + limit)
    start, end = _shrink_to_fit(value, start, end, limit, truncated)
    if end <= hit_start:
        start = hit_start
        end = min(len(value), hit_end)
        start, end = _shrink_to_fit(value, start, end, limit, truncated)
    text, before, after = _render(value, start, end, truncated)
    if len(text) > limit:
        text = ""
    return EvidenceWindow(text, value[start:end], start, end, "lexical", before, after,
                          False, False, False)


def select_evidence_window(snippet, query_hints=(), limit=600) -> EvidenceWindow:
    """Select one contiguous normalized source window.

    ``can_bind`` is always false: even an uncut saved snippet can be missing
    provider-side context. Boundary/context flags describe this locator only,
    not sentence grammar, global applicability, or claim-level support.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    truncated = isinstance(snippet, str) and len(snippet) > MAX_SCAN_CHARS
    normalized = _normalize(snippet[:MAX_SCAN_CHARS]) if isinstance(snippet, str) else ""
    if not normalized:
        if truncated:
            return EvidenceWindow("", "", 0, 0, "fallback", False, True, False, False, False)
        return _empty_window()
    if len(normalized) <= limit and limit > 0 and not truncated:
        usable = not is_navigation_placeholder(normalized)
        return EvidenceWindow(normalized, normalized, 0, len(normalized), "full",
                              False, False, True, usable, False)
    if limit <= 0:
        return _fallback(normalized, limit, truncated)

    hints = _hint_tokens(query_hints)
    if not hints:
        return _fallback(normalized, limit, truncated)

    scan = normalized
    if not scan:
        return _fallback(normalized, limit, truncated)
    occurrences = _token_occurrences(scan)
    frequencies: dict[str, int] = {}
    for token, _, _ in occurrences:
        frequencies[token] = frequencies.get(token, 0) + 1
    hint_set = set(hints)
    spans = _sentence_spans(scan)
    span_starts = [left for left, _ in spans]
    hits_by_sentence: dict[int, list[tuple[str, int, int]]] = {}
    for token, start, end in occurrences:
        if token not in hint_set:
            continue
        sentence_index = bisect_right(span_starts, start) - 1
        hits_by_sentence.setdefault(sentence_index, []).append((token, start, end))
    if not hits_by_sentence:
        return _fallback(normalized, limit, truncated)

    candidates: list[tuple[tuple[float, int, int, int], EvidenceWindow]] = []
    for anchor_index, hits in hits_by_sentence.items():
        left_index = max(0, anchor_index - 1)
        right_index = min(len(spans) - 1, anchor_index + 1)
        anchor_start, anchor_end = spans[anchor_index]
        start = spans[left_index][0]
        end = spans[right_index][1]
        score = sum(1.0 / frequencies[token] for token in sorted({hit[0] for hit in hits}))
        if _rendered_length(normalized, start, end, truncated) > limit:
            hit = min(hits, key=lambda item: (item[1], item[0]))
            candidates.append(((score, 0, -anchor_index, 1),
                               _partial_lexical(normalized, hit[1], hit[2], limit, truncated)))
            continue
        text, before, after = _render(normalized, start, end, truncated)
        if len(text) > limit:
            continue
        neighbor_before = anchor_index == 0 or left_index < anchor_index
        neighbor_after = anchor_index == len(spans) - 1 or right_index > anchor_index
        context_complete = neighbor_before and neighbor_after
        boundary_complete = start <= anchor_start and end >= anchor_end
        if truncated and end >= len(scan):
            context_complete = False
            boundary_complete = False
        window = EvidenceWindow(text, normalized[start:end], start, end, "lexical",
                                before, after, boundary_complete, context_complete,
                                False)
        candidates.append(((score, int(context_complete), -anchor_index, 0), window))

    if not candidates:
        return _fallback(normalized, limit, truncated)
    candidates.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[0][3]))
    return candidates[0][1]


__all__ = ["EvidenceWindow", "OMITTED_BEFORE", "OMITTED_AFTER", "select_evidence_window"]
