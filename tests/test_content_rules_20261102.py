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
        assert "其余 2 条检索结果未进入本报告的可引用依据清单" in report, report[-1200:]


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


class TestRoundThreeRepairs:
    """Residual fixes from the round-two validation (2026-11-03): coverage note
    page failures, remainder identity matching, clipped gap summaries, unlisted
    source note, availability/snippet rules and their diagnostics."""

    def test_coverage_note_lists_page_fetch_failures(self):
        from deepchoice.formats.coverage import derive_data_source_note
        state = {
            "task": {"query": "vLLM vs TGI 技术选型"},
            "partial_failures": ['"arxiv"'],
            "search_results": [
                {"source": "official", "results": [
                    {"url": "https://docs.example/a", "has_body": False,
                     "body_error": "ConnectError"},
                    {"url": "https://docs.example/b", "has_body": False,
                     "body_error": "timeout"},
                    {"url": "https://docs.example/c", "has_body": True},
                ]},
            ],
        }
        note = derive_data_source_note(state)
        assert "未返回可用正文" in note
        assert "ConnectError" in note and "timeout" in note
        assert "arxiv" in note

    def test_remainder_does_not_merge_distinct_pages_with_same_title(self):
        chains = [{"sources": [
            {"url": "https://a.example/page", "title": "X — deep documentation"},
            {"url": "https://b.example/page", "title": "X — deep documentation"},
        ]}]
        used = [{"url": "https://a.example/page", "title": "X — deep documentation"}]
        assert unused_retrieved_count(chains, used) == 1

    def test_gap_summary_excerpt_has_no_clipped_citation(self):
        state = _state(retrieved=2, cited=2)
        state["final_recommendation"]["unresolved_questions"] = [
            "缺失数据：迁移工时与回滚成本，且部分来源 [Source: Alpha vs Beta source 1] 仅摘要级。"
        ]
        report = render(state)
        summary = report.split("## 决策摘要", 1)[1].split("\n## ", 1)[0]
        assert "[Source:" not in summary, summary
        assert "迁移工时" in summary

    def test_reference_section_notes_unlisted_mentioned_sources(self):
        state = _state(retrieved=4, cited=1)
        state["final_recommendation"]["evidence_summary"] = (
            "补充提及 Alpha vs Beta source 3 的社区转储，但未取得正文。")
        report = render(state)
        assert "未计入本清单" in report

    def test_availability_and_snippet_rules_in_prompts(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        assert "same deployment mode for every option" in SYNTHESIS_PROMPT
        assert "SNIPPET-LEVEL EVIDENCE IS NOT BODY" in SYNTHESIS_PROMPT
        assert "Self-contradictory availability claim" in REVIEW_SYSTEM
        assert "Same-mode ranking" in REVIEW_SYSTEM
        assert "Snippet-level sources" in REVIEW_SYSTEM

    def test_availability_claim_flag(self):
        from deepchoice.formats.report_quality import report_ledger_flags
        chains = [{"sources": [{"title": "Host and deploy", "url": "https://docs.example/h",
                                "has_body": True, "snippet": "body"}]}]
        rec = {"recommendation": "见 [Source: Host and deploy]",
               "citation_sources": {"recommendation": [
                   {"title": "Host and deploy", "url": "https://docs.example/h",
                    "has_body": True}]}}
        flags = report_ledger_flags(
            rec, chains, "报告称该指南正文未取回，故未纳入比较。")
        assert "availability_claim_with_collected_bodies" in flags

    def test_ranked_options_repeat_reader_facing_caveat(self):
        state = _state(retrieved=2, cited=2)
        state["final_recommendation"]["decision_guard_actions"] = [
            "conditional_top_option_strength_caveat"]
        report = render(state)
        assert "上述排序为条件性/待验证假设" in report


class TestRoundThreeRunRepairs:
    """Defects exposed by the round-three validation run itself (2026-11-03):
    mixed literal+numeric markers nested gaps (F200-151), and coverage notes that
    were absent when only page-level fetches failed."""

    def test_mixed_literal_and_numeric_marker_is_split(self):
        from deepchoice.agents.conclusion_synthesizer import resolve_text_with_sources
        chains = [{"sources": [
            {"title": "vLLM — Official Documentation", "url": "https://docs.vllm.ai",
             "snippet": "body", "has_body": True, "body": "body"}]}]
        resolved, bindings = resolve_text_with_sources(
            "见 [Source: vLLM — Official Documentation [[1]]", chains)
        assert "引用未解析" not in resolved, resolved
        assert "[Source: vLLM — Official Documentation]" in resolved
        assert bindings

    def test_nested_gap_marker_is_collapsed(self):
        from deepchoice.formats.report_quality import finalize_report_text
        raw = ("〔引用未解析：来源标题 “vLLM — Official Documentation "
               "〔引用未解析：编号 4（截断）〕”〕]]")
        cleaned = finalize_report_text(raw)
        assert cleaned.count("〔引用未解析") == 1, cleaned
        assert "]]" not in cleaned
        assert "vLLM — Official Documentation" in cleaned

    def test_coverage_note_renders_without_channel_failures(self):
        from deepchoice.formats.coverage import derive_data_source_note
        state = {
            "task": {"query": "vLLM vs TGI 技术选型"},
            "partial_failures": [],
            "search_results": [{"source": "official", "results": [
                {"url": "https://huggingface.co/docs/x", "has_body": False,
                 "body_error": "ConnectError"},
            ]}],
        }
        note = derive_data_source_note(state)
        assert "未返回可用正文" in note, note
        assert "ConnectError" in note

    def test_gap_excerpt_has_no_dangling_punctuation_space(self):
        from deepchoice.formats.what_why_how import _strip_marker_text
        text = ("现有数字不可拼接 [Source: A] [Source: B] 无 NestJS 对照， 的对手是 [Source: C]。")
        cleaned = _strip_marker_text(text)
        assert "[Source:" not in cleaned
        assert "， 的" not in cleaned, cleaned
        assert " 的" not in cleaned, cleaned


class TestR4RunFixes:
    """Bugs exposed by the F200-151 revalidation (2026-11-03): the unlisted-source
    note was emitted twice (zh + stray en), and not_prose/empty-channel outcomes
    were mislabelled in the coverage note."""

    def test_unlisted_note_is_emitted_once(self):
        state = _state(retrieved=4, cited=1)
        state["final_recommendation"]["evidence_summary"] = (
            "补充提及 Alpha vs Beta source 3 的社区转储，但未取得正文。")
        report = render(state)
        assert report.count("未计入本清单") == 1
        assert "not part of this list" not in report

    def test_not_prose_and_empty_channels_are_labelled(self):
        from deepchoice.formats.coverage import derive_data_source_note
        state = {
            "task": {"query": "vLLM vs TGI 技术选型"},
            "partial_failures": [],
            "empty_sources": ["chroma"],
            "search_results": [
                {"source": "official", "results": [
                    {"url": "https://a", "has_body": False,
                     "body_error": "not_prose:low_prose_ratio"},
                    {"url": "https://b", "has_body": False,
                     "body_error": "ConnectError"},
                ]},
            ],
        }
        note = derive_data_source_note(state)
        assert "非正文" in note, note
        assert "ConnectError" in note
        assert "chroma" in note
        assert "空结果" in note


class TestNavigationVsCitation:
    """Round-four validation (F200-151): one URL appeared both as "no body, not
    usable as a basis" navigation and as the #1 ranking's cited official basis."""

    def _state(self):
        state = _state(retrieved=3, cited=1)
        state["evidence_chains"] = [{"sources": [
            {"url": "https://docs.example/body", "title": "Alpha Docs",
             "snippet": "fact", "has_body": True, "body": "fact"},
            {"url": "https://docs.example/snippet", "title": "Beta Snippet",
             "snippet": "snippet fact", "has_body": False},
            {"url": "https://docs.example/nav", "title": "Beta Nav",
             "snippet": "nav", "has_body": False},
        ]}]
        state["final_recommendation"]["citation_sources"] = {
            "recommendation": [
                {"source_id": "https://docs.example/body", "title": "Alpha Docs",
                 "url": "https://docs.example/body", "has_body": True},
                {"source_id": "https://docs.example/snippet", "title": "Beta Snippet",
                 "url": "https://docs.example/snippet", "has_body": False},
            ],
        }
        state["final_recommendation"]["recommendation"] = (
            "Alpha or Beta [Source: Alpha Docs]，摘要证据 [Source: Beta Snippet]。")
        return state

    def test_cited_snippet_is_not_in_navigation_block(self):
        report = render(self._state())
        nav_block = report.split("导航链接")[1] if "导航链接" in report else ""
        nav_block = nav_block.split("\n## ", 1)[0]
        assert "https://docs.example/nav" in nav_block
        assert "https://docs.example/snippet" not in nav_block
        assert "另有被引用的摘要级来源" in report

    def test_reference_marks_snippet_level_source(self):
        report = render(self._state())
        assert "（摘要级：未取得正文）" in report

    def test_provenance_note_marks_snippet_level(self):
        from deepchoice.formats.basis import source_provenance_note
        assert "摘要级" in source_provenance_note(
            {"url": "https://x/y", "title": "T", "has_body": False}, "zh")
        assert "摘要级" not in source_provenance_note(
            {"url": "https://x/y", "title": "T", "has_body": True}, "zh")

    def test_nav_citation_rules_in_prompts(self):
        from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT
        from deepchoice.agents.self_reviewer import REVIEW_SYSTEM
        assert "NAVIGATION IS NOT CITATION" in SYNTHESIS_PROMPT
        assert "Navigation/citation contradiction" in REVIEW_SYSTEM
        assert "Citation-source match" in REVIEW_SYSTEM
        assert "Snippet-only decisive basis" in REVIEW_SYSTEM


class TestR5RunFixes:
    """Bugs exposed by the fifth F200-151 run (2026-11-03): [DISPUTED] suffix in
    literal citation titles became unresolved gaps, and empty-source dicts were
    printed raw in the coverage note."""

    def test_disputed_title_suffix_resolves(self):
        from deepchoice.agents.conclusion_synthesizer import resolve_text_with_sources
        chains = [{"sources": [{
            "title": "vLLM vs. TGI", "url": "https://x/vs", "snippet": "body",
            "has_body": True, "body": "body", "disputed": True}]}]
        resolved, bindings = resolve_text_with_sources(
            "对比结论 [Source: vLLM vs. TGI [DISPUTED]]。", chains)
        assert "引用未解析" not in resolved, resolved
        assert "[Source: vLLM vs. TGI]" in resolved
        assert bindings

    def test_empty_source_dict_is_rendered_readably(self):
        from deepchoice.formats.coverage import derive_data_source_note
        state = {
            "task": {"query": "vLLM vs TGI 技术选型"},
            "partial_failures": [],
            "empty_sources": [{"source": "chroma", "reason": "no_research_material"}],
            "search_results": [],
        }
        note = derive_data_source_note(state)
        assert "chroma" in note
        assert "{'source'" not in note, note


class TestR5DisplayResidue:
    """Round-five review residues: unmatched brackets around gap markers and
    bracket residue in the decision-summary key-gap excerpt."""

    def test_gap_wrapper_brackets_are_removed(self):
        from deepchoice.formats.report_quality import finalize_report_text
        raw = "对比结论 [〔引用未解析：来源标题 “vLLM vs. TGI [DISPUTED”〕]]。"
        cleaned = finalize_report_text(raw)
        assert "[〔引用未解析" not in cleaned, cleaned
        assert "〕]]" not in cleaned, cleaned
        assert "引用未解析" in cleaned

    def test_summary_gap_excerpt_has_no_bracket_residue(self):
        state = _state(retrieved=2, cited=2)
        state["final_recommendation"]["unresolved_questions"] = [
            "缺失数据 [DISPUTED]] 与回滚成本。"]
        report = render(state)
        summary = report.split("## 决策摘要", 1)[1].split("\n## ", 1)[0]
        assert "]]" not in summary, summary
        assert "[]]" not in summary, summary
