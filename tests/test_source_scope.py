"""Bounded source-scope proposals use synthetic documents, no external calls."""
from deepchoice.utils.source_scope import (
    MAX_SCOPE_CHARS, bounded_scope_sentences, passages_from_ranges, scope_sentences,
)


def test_sentence_ranges_keep_disjoint_conditions_and_dotted_identifiers():
    source = (
        "If writes cannot queue, use a server database. "
        "An unrelated section describes storage size. "
        "SQLite needs no configuration or maintenance. "
        "A terminated worker using sys.exit() can still acknowledge a task."
    )
    sentences = scope_sentences(source)
    assert sentences is not None and len(sentences) == 4
    assert bounded_scope_sentences(list(sentences)) == sentences
    passages = passages_from_ranges(sentences, [[0, 1], [2, 4]])
    assert passages == (
        "If writes cannot queue, use a server database.",
        "SQLite needs no configuration or maintenance. "
        "A terminated worker using sys.exit() can still acknowledge a task.",
    )


def test_scope_rejects_oversized_or_forged_sentence_projection():
    assert scope_sentences("A" * (MAX_SCOPE_CHARS + 1) + ".") is None
    sentences = scope_sentences("A complete fact. A second fact.")
    assert sentences is not None
    forged = [sentences[0], "A fabricated consequence."]
    assert bounded_scope_sentences(forged) == tuple(forged)
    # A retriever may supply new text, but a model cannot introduce words:
    assert passages_from_ranges(sentences, [[0, 99]]) is None
    assert passages_from_ranges(sentences, [[0, 1], [0, 1]]) is None


def test_range_must_end_at_complete_sentence_and_fit_fact_budget():
    incomplete = scope_sentences("A complete fact. But the condition may")
    assert incomplete is not None
    assert passages_from_ranges(incomplete, [[1, 2]]) is None
    long = scope_sentences("A" * 390 + ". " + "B" * 390 + ". " + "C" * 390 + ". " + "D" * 390 + ".")
    assert long is not None
    assert passages_from_ranges(long, [[0, 4]]) is None
