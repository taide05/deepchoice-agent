"""Bounded, verbatim text units for an optional source scope proposal.

A model may name text-unit ranges, but only runtime-owned retrieval text can
become a passage. Live citation checks still decide provenance and lexical
support; this module does not decide applicability or recommendation quality.
"""
from __future__ import annotations

import re

from .evidence_choices import bounded_source_passages

MAX_SCOPE_CHARS = 2000
MAX_SCOPE_SENTENCES = 40
MAX_SENTENCE_CHARS = 400
MAX_PROPOSED_SOURCES = 8
MAX_PROPOSAL_INPUT_CHARS = 16000
# Prompt + original request + source menu, excluding validated HITL context.
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


_STOP = frozenset("a an and are as at be by can compare comparison could docs documentation do does for from guide how in is it of on or official reference should than that the their these this to use using versus vs what when which with would".split())


def source_terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9]{2,}", text.casefold())) - _STOP


def proposal_hints(text: str) -> set[str]:
    """Language-neutral sampling hints, never a support/admission decision."""
    hints = source_terms(text)
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        hints.update(run[index:index + 2] for index in range(len(run) - 1))
    return hints


def proposal_scope(document, hints: set[str]) -> list[str] | None:
    """Offer complete prose for selection when old lexical snippets are absent.

    Prefer the entire bounded page. Longer pages sample whole neighbour blocks;
    these windows can miss topics and must never be treated as selected facts.
    """
    if document.incomplete:
        return None
    prose_indices = set(document.prose_indices)
    indices = [index for index, block in enumerate(document.blocks)
               if (len(block) >= 80 or (index in prose_indices and block[-1] in ".!?。！？"))
               and re.search(r"[.!?。！？]", block)]
    if not indices:
        return None
    whole = " ".join(document.blocks)
    scope = scope_sentences(whole)
    if scope:
        return list(scope)
    choices = []
    for index in indices:
        text = " ".join(document.blocks[max(0, index - 1):index + 2])
        scope = scope_sentences(text)
        if scope and whole.count(text) == 1:
            choices.append((len(proposal_hints(document.blocks[index]) & hints), -index, scope))
    return list(max(choices)[2]) if choices else None
