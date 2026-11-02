"""Deterministic repairs for the defects exposed by the 2026-11-02 final-200 review.

Each test pins one root cause found while reviewing the frozen 200 reports and
replayed offline; none of them needs a network or model call.
"""
from deepchoice.agents.report_generator import render_report
from deepchoice.formats.basis import _merge_used_entries, source_display_title
from deepchoice.formats.what_why_how import _display_text
from deepchoice.utils.confidence_text import (
    align_confidence_rationale,
    normalize_confidence,
)


class TestCanonicalSourceIdentity:
    def test_percent_encoding_variants_are_one_display_source(self):
        # F200-007/008: the same OpenReplay article collected by two channels,
        # one with percent-encoded Chinese path, one with literal Chinese.
        percent = ("https://blog.openreplay.com/zh/solidjs-vs-react-"
                   "%E6%AF%94%E8%BE%83%E7%BB%84%E4%BB%B6%E6%A8%A1%E5%9E%8B%E6%80%A7%E8%83%BD")
        literal = "https://blog.openreplay.com/zh/solidjs-vs-react-比较组件模型性能"
        merged = _merge_used_entries([
            {"url": percent, "title": "SolidJS vs React", "citations": 2},
            {"url": literal, "title": "SolidJS vs React", "citations": 3},
        ])
        assert len(merged) == 1
        assert merged[0]["citations"] == 5

    def test_query_string_still_distinguishes_pages(self):
        merged = _merge_used_entries([
            {"url": "https://www.youtube.com/watch?v=aaa", "title": "Video A"},
            {"url": "https://www.youtube.com/watch?v=bbb", "title": "Video B"},
        ])
        assert len(merged) == 2


class TestLocatableDeepDocLabel:
    def test_auto_deep_doc_title_gets_path_suffix(self):
        # F200-189/190/191/192: an Amazon Linux 2 release-notes URL displayed as
        # "AWS CDK — deep documentation" hid the page-identity mismatch.
        label = source_display_title({
            "title": "AWS CDK — deep documentation",
            "url": "https://docs.aws.amazon.com/AL2/latest/relnotes/relnotes-al2-2026.md",
        })
        assert label.startswith("AWS CDK — deep documentation — ")
        assert "relnotes/relnotes-al2-2026.md" in label

    def test_already_suffixed_title_is_not_doubled(self):
        label = source_display_title({
            "title": "Vue — deep documentation — vuejs.org/about/releases",
            "url": "https://vuejs.org/about/releases",
        })
        assert label.count("about/releases") == 1

    def test_normal_title_untouched(self):
        assert source_display_title({
            "title": "MLflow Tracking Server | MLflow AI Platform",
            "url": "https://mlflow.org/docs",
        }) == "MLflow Tracking Server | MLflow AI Platform"


class TestUnresolvedQuestionSourceLabels:
    def test_resolved_source_label_is_kept_readable(self):
        # F200-037/067: stripping the marker deleted the only source mention,
        # leaving broken clauses like "但  的 Deno 2 工具链清单未列 bundle".
        item = ("子问题1：Deno 在 Deno 2 下是否仍提供 bundler？"
                "[Source: 宣布 Deno 2] 称有，但 [Source: Deno 2 工具链清单] 未列 bundle。")
        out = _display_text(item)
        assert "[Source:" not in out
        assert "来源：宣布 Deno 2" in out
        assert "称有，但 （来源：Deno 2 工具链清单） 未列" in out

    def test_raw_numeric_marker_is_still_removed(self):
        out = _display_text("缺口 [[7]] 与正文无关。")
        assert "[[" not in out
        assert "缺口" in out

    def test_empty_marker_removed_without_breaking_sentence(self):
        assert _display_text("缺口 [Source: ] 未解。").startswith("缺口 未解")


class TestConfidenceConsistency:
    def test_claim_is_aligned_to_authoritative_level(self):
        text = "五问中只有一问有官方证据。最终置信级别：medium——但缺口仍在。"
        aligned = align_confidence_rationale(text, "low")
        assert "最终置信级别：low" in aligned
        assert "最终置信级别：medium" not in aligned
        assert "缺口仍在" in aligned

    def test_internal_review_note_is_removed(self):
        text = ("理由正文。（自审调整：最终置信度为 medium；上述为综合判断，"
                "检查项计数与知识缺口单列，不替代上述理由。）")
        aligned = align_confidence_rationale(text, "medium")
        assert "自审调整" not in aligned
        assert aligned.startswith("理由正文。")

    def test_ceiling_statement_is_not_a_final_level_claim(self):
        text = "证据不足，故不高于 medium。"
        assert align_confidence_rationale(text, "low") == text

    def test_unknown_level_leaves_text_unchanged(self):
        text = "最终置信级别：medium"
        assert align_confidence_rationale(text, None) == text
        assert normalize_confidence("medium") == "medium"
        assert normalize_confidence("中") == "medium"


class TestRenderedReportConsistency:
    STATE = {
        "task": {"query": "Svelte vs Vue 技术选型", "language": "zh"},
        "evidence_chains": [],
        "conflicts": [],
        "conflict_check": {
            "pairs_scanned": 3,
            "scan_outcomes": {},
            "pairs_arbitration_failed": 0,
            "sources_without_comparable_claim": 7,
        },
        "final_recommendation": {
            "decision_status": "conditional",
            "winner": "",
            "confidence": "low",
            "confidence_rationale": (
                "五个子问题中只有一问有官方正文。最终置信级别：medium——缺口仍在。"
                "（自审调整：最终置信度为 medium；上述为综合判断，"
                "检查项计数与知识缺口单列，不替代上述理由。）"),
            "recommendation": "按条件分支选择。",
        },
        "confidence": "low",
    }

    def test_rendered_report_aligns_confidence_and_drops_process_note(self):
        report, fmt = render_report(self.STATE)
        assert fmt == "what_why_how"
        assert "最终置信级别：low" in report
        assert "最终置信级别：medium" not in report
        assert "自审调整" not in report

    def test_render_does_not_mutate_caller_state(self):
        original = self.STATE["final_recommendation"]["confidence_rationale"]
        render_report(self.STATE)
        assert self.STATE["final_recommendation"]["confidence_rationale"] == original

    def test_conflict_exclusion_sentence_has_no_stale_count(self):
        report, _ = render_report(self.STATE)
        assert "另有高相关来源没有取得正文" in report
        import re
        assert re.search(r"另有\s*\d+\s*个高相关来源", report) is None
