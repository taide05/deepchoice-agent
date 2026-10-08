"""Bounded, verbatim text units for an optional source scope proposal.

A model may name text-unit ranges, but only runtime-owned retrieval text can
become a passage. Live citation checks still decide provenance and lexical
support; this module does not decide applicability or recommendation quality.
"""
from __future__ import annotations

from .evidence_choices import bounded_source_passages

MAX_SCOPE_CHARS = 2000
MAX_SCOPE_SENTENCES = 40
MAX_SENTENCE_CHARS = 400
MAX_PROPOSED_SOURCES = 8
MAX_PROPOSAL_INPUT_CHARS = 16000
MAX_PROPOSAL_MESSAGE_BYTES = 12000


def scope_sentences(document: str) -> tuple[str, ...] | None:
    """Number exact text units while retaining the original sentence separators.

    Consecutive sentences without intervening whitespace form one indivisible
    unit. Actual sentence limits still apply, and range selection must copy the
    whole unit; adding spaces or clipping a condition would alter source text.
    """
    from ..citations.verifier import _split_sentences

    if not isinstance(document, str):
        return None
    text = " ".join(document.split())
    if not text or len(text) > MAX_SCOPE_CHARS:
        return None
    sentences = tuple(_split_sentences(text))
    if (not sentences or len(sentences) > MAX_SCOPE_SENTENCES
            or any(not sentence or len(sentence) > MAX_SENTENCE_CHARS for sentence in sentences)):
        return None
    units: list[str] = []
    cursor = 0
    for sentence in sentences:
        start = text.find(sentence, cursor)
        if start == cursor and units:
            units[-1] += sentence
        elif start == cursor or (start == cursor + 1 and text[cursor:start] == " "):
            units.append(sentence)
        else:
            return None
        cursor = start + len(sentence)
    return tuple(units) if cursor == len(text) and " ".join(units) == text else None


def bounded_scope_sentences(value: object) -> tuple[str, ...] | None:
    """Check the private retriever projection before sending it to a model."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SCOPE_SENTENCES:
        return None
    if any(not isinstance(item, str) or not item for item in value):
        return None
    text = " ".join(value)
    sentences = scope_sentences(text)
    return sentences if sentences == tuple(value) else None


def passages_from_ranges(
    sentences: tuple[str, ...], ranges: object,
) -> tuple[str, ...] | None:
    """Resolve ordered end-exclusive indices into exact, bounded passages."""
    from ..citations.source_windows import SourceDocument, locate_source_windows

    if (not isinstance(sentences, tuple) or not isinstance(ranges, list)
            or not 1 <= len(ranges) <= 3):
        return None
    previous_end = 0
    passages: list[str] = []
    for pair in ranges:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(index, int) or isinstance(index, bool) for index in pair)):
            return None
        start, end = pair
        if start < previous_end or not 0 <= start < end <= len(sentences):
            return None
        passages.append(" ".join(sentences[start:end]))
        previous_end = end
    bounded = bounded_source_passages({
        "snippet": " ".join(passages), "passages": passages,
    })
    if bounded is None or not bounded:
        return None
    # The selected strings must also retain unique, complete local locations.
    document = SourceDocument(sentences, incomplete=False)
    return bounded if locate_source_windows(bounded, document) is not None else None
