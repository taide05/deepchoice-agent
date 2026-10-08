"""Bounded source-scope proposals use synthetic documents, no external calls."""
import pytest

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


@pytest.mark.parametrize("source, expected", [
    ("Acme 过滤记录。过滤不能建立权限边界。必须单独限制可访问文档。",
     ("Acme 过滤记录。过滤不能建立权限边界。必须单独限制可访问文档。",)),
    ("Acme 过滤记录。 过滤不能建立权限边界。",
     ("Acme 过滤记录。", "过滤不能建立权限边界。")),
    ("Acme 过滤记录。\n\n过滤不能建立权限边界。必须限制可访问文档。",
     ("Acme 过滤记录。", "过滤不能建立权限边界。必须限制可访问文档。")),
    ("Acme filters records. However, it is not an authorization boundary.",
     ("Acme filters records.", "However, it is not an authorization boundary.")),
])
def test_scope_preserves_original_sentence_separators_and_conditions(source, expected):
    units = scope_sentences(source)
    assert units == expected
    assert bounded_scope_sentences(list(units)) == units
    assert passages_from_ranges(units, [[0, len(units)]]) == (" ".join(source.split()),)


def test_consecutive_sentence_unit_keeps_actual_sentence_limits():
    source = "甲" * 290 + "。" + "乙" * 290 + "。" + "丙" * 290 + "。"
    units = scope_sentences(source)
    assert units == (source,)
    assert bounded_scope_sentences(list(units)) == units
    assert passages_from_ranges(units, [[0, 1]]) == (source,)
    # Bounds apply to actual sentences, even inside one indivisible unit.
    assert scope_sentences("甲" * 400 + "。") is None
    assert scope_sentences("甲。" * 41) is None


def test_indivisible_unit_cannot_clip_qualifier_to_fit_fact_budget():
    source = "甲" * 310 + "。" + "乙" * 310 + "。" + "丙" * 310 + "。" + "丁" * 310 + "。"
    units = scope_sentences(source)
    assert units == (source,)
    assert passages_from_ranges(units, [[0, 1]]) is None
    unfinished = scope_sentences("Acme 可以过滤记录。但是权限条件尚未说明")
    assert unfinished is not None
    assert passages_from_ranges(unfinished, [[0, 1]]) is None


def test_duplicate_units_still_need_unique_source_location():
    units = scope_sentences("Acme 可以过滤记录。 Acme 可以过滤记录。")
    assert units is not None and len(units) == 2
    assert passages_from_ranges(units, [[0, 1]]) is None
