"""Content-rule repairs from the G1 residual-defect list (2026-11-02).

Covers the zero-cost prompt/rendering changes made after G1:
- gap claims must match cited bodies (F200-190),
- like-for-like deployment comparison (F200-041),
- no unsupported exclusivity (F200-199),
- the "其余 N 条检索结果" remainder counts folded same-page rows correctly
  (F200-187/190 off-by-one),
- the no-conflict case gets a non-redundant hedge sentence (F200-164),
- parenthetical confidence levels in the rationale are aligned to the label
  (F200-186).
"""
from deepchoice.formats.basis import unused_retrieved_count
from deepchoice.formats.what_why_how import render
from deepchoice.utils.confidence_text import align_confidence_rationale


def _binding(title, url):
    return {"source_id": url, "title": title, "url": url,
            "provenance": "tavily", "channel": "tavily",
            "date": "2026-01-01", "source_type": "web_document"}


def _state(retrieved=5, cited=3, conflicts=None):
    chains = []
    bindings = []
    for index in range(retrieved):
        title = f"Alpha vs Beta source {index}"
        url = f"https://example.com/source-{index}"
        chains.append({"sources": [{
            "url": url, "title": title, "snippet": "Alpha and Beta compare here.",
            "has_body": True, "body": "Alpha and Beta compare here.",
            "provenance": "tavily", "channel": "tavily",
            "date": "2026-01-01", "source_type": "web_document"}]})
        if index < cited:
            bindings.append(_binding(title, url))
    return {
        "task": {"query": "Alpha vs Beta 技术选型", "candidate_techs": ["Alpha", "Beta"],
                 "language": "zh", "constraints": [], "report_format": "what_why_how"},
        "sub_questions": [],
        "search_results": [],
        "source_scores": [],
        "conflicts": conflicts or [],
        "conflict_check": {"pairs_scanned": 4,
                           "sources_without_comparable_claim": 1},
        "evidence_chains": chains,
        "knowledge_gaps": [],
        "confidence": "medium",
        "final_recommendation": {
            "decision_status": "conditional", "winner": "",
            "recommendation": "Alpha or Beta [Source: Alpha vs Beta source 0]",
            "ranked_options": [
                {"name": "Alpha", "rationale": "Alpha [Source: Alpha vs Beta source 1]"},
                {"name": "Beta", "rationale": "Beta [Source: Alpha vs Beta source 2]"},
            ],
            "trade_offs": [], "evidence_summary": "",
            "citation_sources": {"recommendation": bindings},
        },
    }


class TestPromptContentRules:
    def test_gap_claim_rule(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "GAP CLAIMS MUST MATCH THE CITED BODIES" in SYNTHESIS_PROMPT

    def test_like_for_like_rule(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "LIKE-FOR-LIKE COMPARISON" in SYNTHESIS_PROMPT

    def test_exclusivity_rule(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "NO UNSUPPORTED EXCLUSIVITY" in SYNTHESIS_PROMPT

    def test_review_checks_expose_the_new_patterns(self):
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        for marker in ("Gap accuracy", "Comparison-mode asymmetry",
                       "Unsupported exclusivity", "Confidence prose level"):
            assert marker in REVIEW_SYSTEM, marker


class TestRemainderCount:
    def test_folded_same_page_rows_are_not_counted_as_unused(self):
        chains = [{"sources": [
            {"url": "https://example.com/a", "title": "Guide"},
            {"url": "https://example.com/a/#section", "title": "Guide (mirror)"},
            {"url": "https://example.com/b", "title": "Blog"},
        ]}]
        used = [{"url": "https://example.com/a", "title": "Guide"},
                {"url": "https://example.com/b", "title": "Blog"}]
        assert unused_retrieved_count(chains, used) == 0

    def test_genuinely_uncited_row_is_counted(self):
        chains = [{"sources": [
            {"url": "https://example.com/a", "title": "Guide"},
            {"url": "https://example.com/b", "title": "Blog"},
        ]}]
        used = [{"url": "https://example.com/a", "title": "Guide"}]
        assert unused_retrieved_count(chains, used) == 1

    def test_rendered_remainder_uses_uncited_rows(self):
        report = render(_state(retrieved=5, cited=3))
        assert "其余 2 条检索结果未进入本报告的依据" in report, report[-1200:]


class TestConflictHedgePhrasing:
    def test_no_conflict_case_says_no_arbitrable_conflict(self):
        report = render(_state())
        assert "本次没有记录可裁决的争议" in report
        assert "未参与冲突比较" not in report

    def test_hedge_still_states_statistics_do_not_establish_agreement(self):
        report = render(_state())
        assert "不代表这些来源之间没有分歧" in report


class TestConfidenceParenthetical:
    def test_parenthetical_level_is_aligned_to_label(self):
        text = "结论本身证据充分（high），但检索受限于本次材料。"
        aligned = align_confidence_rationale(text, "medium")
        assert "（medium）" in aligned, aligned
        assert "（high）" not in aligned

    def test_unrelated_parenthetical_level_is_left_alone(self):
        text = "来源把 priority（high）标注为高优先级。"
        aligned = align_confidence_rationale(text, "medium")
        assert "（high）" in aligned


class TestArbitrationRuleLeak:
    """Validation run F200-082 rendered the arbitrator reasoning verbatim and it
    echoed the internal rules ("so rule 1 does not apply ... (rule 2)")."""

    def test_english_rule_reference_is_neutralized(self):
        from deepchoice.formats.report_quality import sanitize_arbitration_text
        text = "Score difference is 1.0 (<2.5), so rule 1 does not apply. Both cite benchmark evidence (rule 2)."
        cleaned = sanitize_arbitration_text(text)
        assert "rule 1" not in cleaned and "rule 2" not in cleaned
        assert "scoring rule" in cleaned

    def test_chinese_rule_reference_is_neutralized(self):
        from deepchoice.formats.report_quality import sanitize_arbitration_text
        cleaned = sanitize_arbitration_text("按 rule 12 判定，证据类型相同。")
        assert "rule 12" not in cleaned
        assert "该规则" in cleaned

    def test_arbitration_prompt_forbids_rule_numbers(self):
        from deepchoice.agents.conflict_detector import ARBITRATION_SYSTEM
        assert "NEVER mention rule numbers" in ARBITRATION_SYSTEM


class TestBareSourceOrdinals:
    """Validation run F200-176: the evidence summary wrote "[1] 与 [13] 是同一页"."""

    def test_evidence_summary_number_becomes_source_label(self):
        state = _state(retrieved=2, cited=2)
        state["final_recommendation"]["evidence_summary"] = "[1] 与 [2] 是同页转载，不能当作独立佐证。"
        report = render(state)
        assert "[1] 与 [2]" not in report, report
        assert "[Source: Alpha vs Beta source 1]" in report

    def test_prompt_forbids_bare_source_numbers(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "NO BARE SOURCE NUMBERS" in SYNTHESIS_PROMPT

    def test_review_prompt_flags_bare_source_ordinals(self):
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        assert "Bare source ordinals" in REVIEW_SYSTEM


class TestLiteralEscapeCleanup:
    """Validation run F200-165: 15 literal backslash-n escapes in the recommendation."""

    def test_literal_newline_escapes_become_real_newlines(self):
        from deepchoice.formats.report_quality import finalize_report_text
        text = "**建议:** 分支选择。\\n\\n分支 A：选 Dagster。"
        cleaned = finalize_report_text(text)
        assert "\\n" not in cleaned
        assert "分支 A" in cleaned

    def test_blank_line_runs_collapse(self):
        from deepchoice.formats.report_quality import finalize_report_text
        cleaned = finalize_report_text("a\n\n\n\nb")
        assert "\n\n\n" not in cleaned


class TestRoundTwoContentRules:
    """Second content round (2026-11-02): managed-option search, global absence
    claims, guidance-vs-requirement, reader-facing strength caveat, and reordered
    R9 decision anchors."""

    def test_prompt_requires_managed_option_search(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "azure app service" in SYNTHESIS_PROMPT.lower()
        assert "no comparable managed/hosted option" in SYNTHESIS_PROMPT
        assert "search B's cited bodies" in SYNTHESIS_PROMPT

    def test_prompt_covers_gap_checklist(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "price, licence, import/adoption path" in SYNTHESIS_PROMPT
        assert "GLOBAL ABSENCE CLAIMS" in SYNTHESIS_PROMPT
        assert "本报告可见材料未给出" in SYNTHESIS_PROMPT

    def test_prompt_distinguishes_guidance_from_requirement(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "Operational advice" in SYNTHESIS_PROMPT
        assert "not a requirement" in SYNTHESIS_PROMPT

    def test_review_prompt_has_the_three_checks(self):
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        for marker in ("Global absence claims", "Managed-option search",
                       "Guidance vs requirement"):
            assert marker in REVIEW_SYSTEM, marker

    def test_strength_caveat_is_reader_facing(self):
        state = _state(retrieved=2, cited=2)
        state["final_recommendation"]["decision_guard_actions"] = [
            "conditional_top_option_strength_caveat"]
        report = render(state)
        assert "不构成已证实的产品优劣结论" in report
        assert "排序已降级" not in report

    def test_managed_hosting_fact_survives_a_small_budget(self):
        from deepchoice.utils.candidate_identity import shared_evidence_package
        body = ("p" * 3000
                + " ASP.NET Core can be published to Azure App Service (a fully managed "
                  "hosting option) as well as IIS."
                + "q" * 3000)
        pkg = shared_evidence_package(
            [{"number": 1, "title": "Host and deploy", "url": "https://x/docs",
              "snippet": body}],
            focus_terms=["unrelated"], budget_chars=1400)
        visible = pkg["views"][1]["text"]
        assert len(visible) <= 1400
        assert "Azure App Service" in visible or "hosting option" in visible, visible

    def test_licence_anchor_is_scanned_before_generic_qualifiers(self):
        from deepchoice.utils.candidate_identity import _DECISION_KEYWORDS
        words = list(_DECISION_KEYWORDS)
        assert words.index("license") < words.index("however")
        assert words.index("managed") < words.index("caveat")


class TestUnnumberedSourceTitleMarker:
    """Round-two validation F200-151/190: the model cited a collected but
    bodyless/navigation source by title. Established contract: a navigation-only
    source cannot be cited, so such a marker stays a visible gap; the prompt now
    forbids writing the marker in the first place."""

    def _chains(self):
        return [{"sources": [
            {"title": "Official Deployment Guide", "url": "https://docs.example/deploy",
             "snippet": "A real body text.", "has_body": True,
             "body": "A real body text."},
            {"title": "Serving models on Huggingface Spaces",
             "url": "https://example/community-post",
             "snippet": "Stars: 12", "has_body": False},
        ]}]

    def test_registered_source_still_resolves(self):
        from deepchoice.agents.conclusion_synthesizer import resolve_text_with_sources
        resolved, bindings = resolve_text_with_sources(
            "部署见 [Source: Official Deployment Guide]。", self._chains())
        assert "引用未解析" not in resolved
        assert "[Source: Official Deployment Guide]" in resolved
        assert bindings

    def test_bodyless_source_citation_stays_a_visible_gap(self):
        from deepchoice.agents.conclusion_synthesizer import resolve_text_with_sources
        resolved, bindings = resolve_text_with_sources(
            "社区转储提到 api_key 参数 [Source: Serving models on Huggingface Spaces]（非官方）。",
            self._chains())
        assert "引用未解析" in resolved, resolved
        assert not bindings

    def test_unknown_title_still_gap(self):
        from deepchoice.agents.conclusion_synthesizer import resolve_text_with_sources
        resolved, _ = resolve_text_with_sources(
            "某处 [Source: Never Collected Page] 声称。", self._chains())
        assert "引用未解析" in resolved, resolved

    def test_prompt_forbids_marks_for_unnumbered_sources(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        assert "listed without a number" in SYNTHESIS_PROMPT
