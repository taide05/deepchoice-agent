"""Final report presentation quality: raw citations and generic source labels."""
from deepchoice.formats.basis import source_display_title
from deepchoice.formats.report_quality import (
    finalize_report_text,
    report_quality_flags,
    source_concentration_flags,
)


def test_raw_numeric_citations_become_explicit_gaps():
    text = "Claim one [[3]] and claim two [[12]]."
    final = finalize_report_text(text)
    assert "[[3]]" not in final
    assert "[[12]]" not in final
    assert "〔引用未解析：编号 3〕" in final
    assert "〔引用未解析：编号 12〕" in final
    assert report_quality_flags(final) == []


def test_empty_source_parentheses_are_removed_and_flagged_before_finalize():
    text = "只有 Microsoft Learn 的说明（），另一项缺少来源（ ）。"
    assert report_quality_flags(text) == ["empty_source_parentheses"]
    final = finalize_report_text(text)
    assert "（）" not in final
    assert "（ ）" not in final
    assert report_quality_flags(final) == []


def test_generic_source_title_uses_url_path_for_display():
    src = {"title": "Medium", "url": "https://medium.com/@author/poetry-vs-uv-2025"}
    label = source_display_title(src)
    assert label.startswith("Medium — ")
    assert "@author/poetry-vs-uv-2025" in label
    assert report_quality_flags(f"- [Medium](https://medium.com/@author/poetry-vs-uv-2025)") \
        == ["generic_source_label"]


def test_normal_source_title_is_not_rewritten():
    src = {"title": "MLflow Tracking Server | MLflow AI Platform", "url": "https://mlflow.org/docs"}
    assert source_display_title(src) == "MLflow Tracking Server | MLflow AI Platform"


def test_source_concentration_is_a_warning_not_an_invalidity():
    rec = {"citation_sources": {"recommendation": [
        {"url": "https://docs.example.com/a"},
        {"url": "https://docs.example.com/b"},
        {"url": "https://docs.example.com/c"},
        {"url": "https://independent.example.org/x"},
    ]}}
    flags = source_concentration_flags(rec, "claim")
    assert any(flag.startswith("source_concentration:docs.example.com:3") for flag in flags)


def test_independence_claim_with_single_publisher_is_flagged():
    rec = {"citation_sources": {"recommendation": [
        {"url": "https://vendor.example.com/a"},
        {"url": "https://vendor.example.com/b"},
    ]}}
    assert "independence_claim_single_publisher" in source_concentration_flags(
        rec, "这是两份独立来源的结论。")

