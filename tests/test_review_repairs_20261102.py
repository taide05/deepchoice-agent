"""Deterministic repairs for the defects exposed by the 2026-11-02 final-200 review.

Each test pins one root cause found while reviewing the frozen 200 reports and
replayed offline; none of them needs a network or model call.
"""
from deepchoice.agents.conclusion_synthesizer import (
    resolve_text_with_sources,
)
from deepchoice.agents.report_generator import render_report
from deepchoice.formats.basis import _merge_used_entries, source_display_title
from deepchoice.formats.what_why_how import _display_text
from deepchoice.utils.confidence_text import (
    align_confidence_rationale,
    normalize_confidence,
)


def _chains(*sources: dict) -> list[dict]:
    return [{"sources": list(sources)}]


def _source(title: str, body: str = "a real body with a factual claim",
            url: str = "") -> dict:
    entry = {"title": title, "snippet": body}
    if url:
        entry["url"] = url
    return entry


def _n_sources(n: int) -> list[dict]:
    return [_source(f"Source {i}", f"body of source {i}",
                    f"https://s{i}.example/doc")
            for i in range(1, n + 1)]


def _chains_of(n: int, per_chain: int = 4) -> list[dict]:
    """The registry keeps at most 4 fact-bearing sources per evidence chain."""
    sources = _n_sources(n)
    return [{"sources": sources[i:i + per_chain]}
            for i in range(0, len(sources), per_chain)]


class TestRegisteredNumberAttachedToWordIsACitation:
    """F200-042/165/186/188: registered numbers written against the preceding word
    were classified as array indexing and then finalised into unresolved gaps."""

    def test_single_registered_number_after_word_is_resolved(self):
        chains = _chains(*_n_sources(2))
        resolved, bindings = resolve_text_with_sources(
            "见 deployment[[1]] 与 versioning 文档。", chains)
        assert "[Source: Source 1]" in resolved, resolved
        assert "[[1]]" not in resolved, resolved
        assert bindings, bindings

    def test_number_after_numeric_prose_is_resolved(self):
        chains = _chains_of(12)
        resolved, _ = resolve_text_with_sources(
            "关键数字不一致（389.73x[[12]] vs 10-100x）。", chains)
        assert "[Source: Source 12]" in resolved, resolved

    def test_subscript_after_token_stays_indexing(self):
        chains = _chains(*_n_sources(2))
        resolved, bindings = resolve_text_with_sources("row[[2]][0] = x", chains)
        assert resolved == "row[[2]][0] = x", resolved
        assert not bindings

    def test_multi_number_array_is_still_indexing(self):
        chains = _chains(*_n_sources(2))
        resolved, bindings = resolve_text_with_sources("code: arr[[1,2]] = x", chains)
        assert resolved == "code: arr[[1,2]] = x", resolved
        assert not bindings

    def test_unregistered_number_is_still_a_visible_gap(self):
        chains = _chains(*_n_sources(2))
        resolved, _ = resolve_text_with_sources("见 deployment[[19]] 与文档。", chains)
        assert "引用未解析" in resolved, resolved
        assert "19" in resolved, resolved


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


class TestContentRulesAreInThePromptsOffline:
    """The content-level fixes are prompt rules until a paid G1 validates model
    behaviour; these tests pin that the rules are actually shipped."""

    def test_synthesis_prompt_has_the_four_new_rules(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        for needle in ("NUMBER DISCIPLINE", "MODALITY FIDELITY",
                       "LIFECYCLE / ROADMAP FACTS ARE DECISION INPUTS",
                       "EXCLUDED MATERIAL MUST NOT BE COUNTED AS A BASIS"):
            assert needle in SYNTHESIS_PROMPT, needle

    def test_review_prompt_checks_the_content_defect_patterns(self):
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        for needle in ("Modality / scale strengthening",
                       "Lifecycle / roadmap facts",
                       "Excluded material in the basis",
                       "Coverage asymmetry"):
            assert needle in REVIEW_SYSTEM, needle

    def test_review_retry_contract_is_documented(self):
        from deepchoice.agents.self_reviewer import _REVIEW_REPAIR_NOTE
        assert "exactly six objects" in _REVIEW_REPAIR_NOTE
        assert "{error}" in _REVIEW_REPAIR_NOTE


class TestSummaryExcerptCitationTrim:
    """G1 review: the front-summary excerpt cut landed inside a [Source: ...]
    marker (F200-049/053/056/165), leaving a dangling citation fragment."""

    def test_dangling_source_marker_is_trimmed(self):
        from deepchoice.formats.what_why_how import _summary_excerpt
        value = "关键缺口：" + ("背景信息" * 60) + "[Source: Airflow vs. Dagster comparison "
        out = _summary_excerpt(value, limit=120)
        assert "[Source:" not in out, out
        assert out.endswith("…"), out

    def test_complete_citation_is_kept(self):
        from deepchoice.formats.what_why_how import _summary_excerpt
        value = "关键缺口很短。[Source: Short Source]"
        assert _summary_excerpt(value, limit=120) == value

    def test_no_markup_is_unchanged(self):
        from deepchoice.formats.what_why_how import _summary_excerpt
        assert _summary_excerpt("没有引用标记的短句。", limit=120) == "没有引用标记的短句。"


class TestInternalMetadataLeakRules:
    """G1 review: F200-151 leaked the prompt rule number ("rule 25") into the
    report; the prompts now forbid internal metadata in user-facing text."""

    def test_synthesis_prompt_forbids_internal_metadata(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "NO INTERNAL METADATA IN THE REPORT" in SYNTHESIS_PROMPT
        assert "rule 25" in SYNTHESIS_PROMPT

    def test_review_prompt_flags_internal_metadata_leak(self):
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        assert "Internal metadata leakage" in REVIEW_SYSTEM
