"""Regressions for the converged package.

Each of these pins a fix whose absence produced a specific defect in the third
real run. The run's saved material is the fixed input where a fixture would be
less faithful.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import re

import pytest

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import orchestrator as orch
from deepchoice.agents import self_reviewer as sr
from deepchoice.formats.what_why_how import render
from deepchoice.utils.candidate_identity import names_candidate

FAILED_RUN = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
              / "8049500c-bd39-44e4-81bb-a1fbbebac780" / "research_snapshot.json")


def _failed_run_state() -> dict:
    """The preserved failed run, used as fixed input.

    Deliberately not a skip: these regressions are only meaningful against this
    material. A silent skip would report green on a checkout that never ran
    them, which is worse than a red test that says the fixture is missing.
    """
    if not FAILED_RUN.exists():
        pytest.fail(
            f"required fixture missing: {FAILED_RUN}. These regressions are "
            f"pinned to the preserved run's saved material and cannot be "
            f"evaluated without it."
        )
    return json.loads(FAILED_RUN.read_text(encoding="utf-8"))


def _reviewer_payload(state: dict) -> str:
    """The complete text the self-review node sends to the model.

    Runs the real node with `call_model` intercepted, so the assertion is on the
    payload that is actually built rather than on a copy of its logic.
    """
    captured: dict[str, str] = {}

    async def fake_call_model(prompt, **kwargs):
        captured["payload"] = "\n".join(
            str(m.get("content", "")) for m in prompt if isinstance(m, dict))
        return {"confidence": "low", "knowledge_gaps": [], "passed_count": 0}

    real = sr.call_model
    sr.call_model = fake_call_model
    try:
        asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
    finally:
        sr.call_model = real
    assert captured.get("payload"), "the reviewer built no payload"
    return captured["payload"]


class TestCitationBinding:
    """confidence_rationale was asked to cite but was not bound, so the served
    report kept raw [[16]] [[17]] [[22]] markers."""

    def test_every_citing_field_is_bound(self):
        assert "confidence_rationale" in cs._CITATION_TEXT_FIELDS

    def test_prompt_fields_all_appear_in_the_binding_lists(self):
        """A field the prompt tells the model to cite must be bound somewhere, or
        its markers survive into the report."""
        prompt = cs.SYNTHESIS_PROMPT
        bound = set(cs._CITATION_TEXT_FIELDS) | set(cs._CITATION_OPT_FIELDS) | \
            set(cs._CITATION_TRADEOFF_FIELDS)
        for field in ("recommendation", "winner_rationale", "evidence_summary",
                      "scene_fit_note", "confidence_rationale", "rationale",
                      "key_strength", "key_weakness", "finding", "impact"):
            assert field in prompt, f"{field} is not requested by the prompt"
            assert field in bound, f"{field} is requested but never bound"

    def test_bound_markers_are_converted_and_unknown_ones_located(self):
        mapping = {1: "Real Source"}
        bound = cs.apply_citation_rules(
            {"confidence_rationale": "Zero strong chains [[1]] plus [[999]]."}, [], mapping)
        text = bound["confidence_rationale"]
        assert "[Source: Real Source]" in text
        assert "[[999]]" not in text, "the raw number must not be displayed"
        assert "999" in text, "the unresolved citation must stay locatable"
        assert "引用未解析" in text or "citation-unresolved" in text

    def test_the_saved_run_no_longer_keeps_raw_markers(self):
        """Replay: the field that held [[16]] [[17]] [[22]] binds cleanly."""
        state = _failed_run_state()
        chains = state.get("evidence_chains") or []
        candidates = state["task"]["candidate_techs"]
        _prompt, mapping = cs._summarize_chains(chains, candidates)
        raw = "强证据链为 0，6 条发现存在争议 [[16]] [[17]] [[22]]。"
        bound = cs.apply_citation_rules({"confidence_rationale": raw}, chains,
                                        mapping)
        assert "[[" not in bound["confidence_rationale"], bound


class TestReviewIsNotDiscarded:
    """A low-confidence review restarted the graph from query_analyzer, which
    overwrote the reviewer's output: the run served a pre-review report after
    paying for the review, and the restart reset the pass counter so the loop
    could repeat."""

    def test_review_terminates_the_graph(self):
        src = inspect.getsource(orch.ChiefEditorAgent._create_workflow)
        assert 'add_edge("self_reviewer", END)' in src
        assert "add_conditional_edges" not in src
        assert "retry_small" not in src and "retry_full" not in src

    def test_router_is_gone(self):
        assert not hasattr(orch.ChiefEditorAgent, "_route_after_review")

    @pytest.mark.asyncio
    async def test_low_confidence_run_ends_after_one_review(self, monkeypatch):
        from tests.test_pipeline import (  # type: ignore
            MOCK_EVIDENCE_CHAINS, MOCK_QUERY_RESULT, MOCK_REPORT,
            MOCK_REVIEW_LOW, MOCK_SEARCH_RESULTS, MOCK_SOURCE_SCORES,
            _make_mock_run,
        )

        calls = {"review": 0}

        async def mock_review(*args, **kwargs):
            calls["review"] += 1
            return MOCK_REVIEW_LOW

        task = {"query": "t", "scene_context": "team", "constraints": [],
                "report_format": "what_why_how"}
        agent = orch.ChiefEditorAgent(task)
        monkeypatch.setattr(orch.QueryAnalyzerAgent, "run",
                            _make_mock_run(MOCK_QUERY_RESULT))
        monkeypatch.setattr(orch.MultiRetrieverAgent, "run",
                            _make_mock_run({"search_results": MOCK_SEARCH_RESULTS,
                                            "partial_failures": []}))
        monkeypatch.setattr(orch.SourceEvaluatorAgent, "run",
                            _make_mock_run({"source_scores": MOCK_SOURCE_SCORES}))
        monkeypatch.setattr(orch.ConflictDetectorAgent, "run",
                            _make_mock_run({"conflicts": []}))
        monkeypatch.setattr(orch.EvidenceChainAgent, "run",
                            _make_mock_run({"evidence_chains": MOCK_EVIDENCE_CHAINS}))
        monkeypatch.setattr(orch.ReportGeneratorAgent, "run",
                            _make_mock_run({"report": MOCK_REPORT}))
        monkeypatch.setattr(orch.SelfReviewerAgent, "run", mock_review)

        result = await agent.run_research_task()
        assert calls["review"] == 1, "the reviewer redid its own work"
        assert result["current_phase"] == "self_reviewer"


class TestReviewSeesTheDecisionClaims:
    """The per-candidate justifications decide the ranking, but nothing reviewed
    them: the reviewer received only the headline. A wrong scale, an unsupported
    justification and an unsupported dismissal all lived there."""

    def test_the_payload_has_one_content_block_and_a_locating_index(self):
        """The located fields carry the claims once; the source register is
        included for checking and the report body is not repeated."""
        source = inspect.getsource(sr.SelfReviewerAgent.run)
        assert "## Fields To Review" in source
        assert "{review_fields}" in source
        assert "source_register_text" in source and "{source_register_text}" in source
        assert "## Report To Review" not in source
        assert "revision_targets" not in source
        assert "{claims_text}" not in source, "the duplicated claims block is gone"

    def test_the_reviewer_payload_carries_the_source_text(self):
        """The reviewer is told to check claims against the cited source text, so
        the source text must be in what it receives.

        Titles alone made the decisive comparison impossible: the run's wrong
        scale (5 万亿) was visible while the source saying 500 亿 was not, so the
        error could not be caught.
        """
        state = _failed_run_state()
        payload = _reviewer_payload(state)
        assert "500 亿" in payload, \
            "the source stating the real scale is not in the reviewer payload"
        # And it is the source text, not just a title, that carries it.
        assert "在高达 500 亿行" in payload, payload[:200]

    def test_the_reviewer_payload_carries_the_three_named_claims(self):
        """Replay the payload the node builds; each error's claim text must be in
        it, alongside the source material needed to judge it."""
        state = _failed_run_state()
        payload = _reviewer_payload(state)
        assert "5 万亿" in payload, "the wrong scale is not visible to the reviewer"
        assert "Serverless" in payload, "the #1 justification is not visible"
        assert "Athena" in payload, "the dismissed candidate is not visible"
        # The Athena source's own text is present, so its dismissal is checkable.
        assert "per terabyte scanned" in payload.lower() or "¥41.20" in payload

    def test_the_wrong_scale_is_absent_from_the_cited_source(self):
        """The source says 500 亿 rows and never says 5 万亿, so the two are
        distinguishable inside the payload the reviewer receives."""
        state = _failed_run_state()
        source_body = ""
        for chain in state.get("evidence_chains") or []:
            for src in chain.get("sources", []):
                if "InfoQ" in (src.get("title") or ""):
                    source_body = src.get("snippet") or ""
        assert "500 亿行" in source_body, "fixture: the source states the real scale"
        assert "5 万亿" not in source_body, "the source never states the reported scale"


class TestWhatReusesOneExplanation:
    """The renderer used to build its own source-to-candidate mapping, so What and
    the recommendation could disagree, and the mapping had to guess a page's
    subject — which a page covering several products cannot answer."""

    def test_no_second_attribution_in_the_renderer(self):
        src = inspect.getsource(render)
        assert "index_sources_by_candidate" not in src
        assert "candidate_for_source" not in src

    def test_the_renderer_does_not_import_an_attribution_index(self):
        import deepchoice.formats.what_why_how as ww

        src = inspect.getsource(ww)
        assert "index_sources_by_candidate" not in src
        assert "UNASSIGNED" not in src

    def test_candidate_bullets_are_the_ranking_explanation(self):
        state = _failed_run_state()
        report = render(state)
        what = report.split("\n## Why")[0]
        for opt in (state["final_recommendation"].get("ranked_options") or []):
            assert f"### {opt['name']}" in what
            if opt.get("reason") or opt.get("rationale"):
                first_sentence = str(opt["rationale"]).split("；")[0][:30]
                assert first_sentence in what, f"{opt['name']} lost its own explanation"

    def test_the_dismissed_candidate_keeps_its_stated_basis(self):
        """Athena was ranked last; its own rationale and cited source must still
        reach the report rather than being dropped by a renderer-side filter."""
        state = _failed_run_state()
        what = render(state).split("\n## Why")[0]
        assert "### Amazon Athena over S3" in what
        assert "¥41.20/TB" in what or "Athena" in what
        assert "https://" in what, "the cited source should be reachable"


class TestReviewCorrectionsReachTheReport:
    """A decisive error must be revised or withdrawn in the served result.

    Lowering confidence and adding a gap left the error on display. With the
    preserved run as fixed input, the reviewer's corrections are applied to the
    recommendation the endpoints render from.
    """

    REVIEW = {
        "checks": [{"item": 1, "passed": True, "note": "ok"}],
        "passed_count": 5,
        "confidence": "low",
        "knowledge_gaps": ["independent benchmark"],
        "corrections": [
            {"option": "ClickHouse", "field": "rationale", "action": "revise",
             "corrected": ("公开基准称其在 500 亿行级 OTel 日志上磁盘占用约降 5 倍"
                           " [Source: ClickHouse 填平 Elasticsearch 护城河？日志分析新选择！ - InfoQ]。"),
             "reason": "来源写 500 亿；报告写成 5 万亿，把同段的能力上限当成了基准规模。"},
            {"option": "Amazon OpenSearch Serverless", "field": "key_strength",
             "action": "withdraw", "reason": "所引来源正文不支持该断言。"},
            {"option": "No Such Option", "field": "rationale", "action": "withdraw",
             "reason": "unknown option"},
            {"option": "ClickHouse", "field": "name", "action": "withdraw",
             "reason": "not a correctable field"},
            {"option": "ClickHouse", "field": "key_weakness", "action": "withdraw",
             "reason": ""},
        ],
    }

    def _run_with(self, review, state=None):
        state = state or _failed_run_state()

        async def fake_call_model(prompt, **kwargs):
            return review

        real = sr.call_model
        sr.call_model = fake_call_model
        try:
            return asyncio.run(sr.SelfReviewerAgent().run(dict(state)))
        finally:
            sr.call_model = real

    def _run(self, state=None):
        return self._run_with(self.REVIEW, state)

    @staticmethod
    def _opt(rec, name):
        return next(o for o in rec["ranked_options"] if o["name"] == name)

    def test_the_wrong_scale_is_revised_not_merely_noted(self):
        state = _failed_run_state()
        out = self._run(state)
        after = self._opt(out["final_recommendation"], "ClickHouse")["rationale"]
        assert "5 万亿" not in after, after
        assert "500 亿" in after, after
        assert len(after) > 60, "the field must stay a substantive answer"

    def test_an_unsupported_justification_is_withdrawn(self):
        state = _failed_run_state()
        name = "Amazon OpenSearch Serverless"
        out = self._run(state)
        after = self._opt(out["final_recommendation"], name)["key_strength"]
        before = self._opt(state["final_recommendation"], name)["key_strength"]
        assert after != before
        assert "撤回" in after, after
        # The sibling field is untouched: a correction is not a blanket clearing.
        assert (self._opt(out["final_recommendation"], name)["rationale"]
                == self._opt(state["final_recommendation"], name)["rationale"])

    def test_the_input_recommendation_is_not_mutated(self):
        """Editing the caller's nested dicts in place would also rewrite the
        checkpointed pre-review state, hiding the change."""
        state = _failed_run_state()
        before = json.dumps(state["final_recommendation"], ensure_ascii=False)
        self._run(state)
        assert json.dumps(state["final_recommendation"], ensure_ascii=False) == before

    def test_only_valid_corrections_are_applied(self):
        out = self._run()
        signal = out["quality_signals"][0]
        assert signal["corrections_applied"] == 2, signal
        assert signal["corrections_rejected"] == 3, signal

    def test_confidence_does_not_contradict_itself(self):
        state = _failed_run_state()
        out = self._run(state)
        assert out["confidence"] == out["final_recommendation"]["confidence"]
        levels = {"low": 0, "medium": 1, "high": 2}
        assert levels[out["confidence"]] <= levels[state["final_recommendation"]["confidence"]]

    def test_the_served_report_reflects_the_correction(self):
        state = _failed_run_state()
        out = self._run(state)
        report = render({**state, "final_recommendation": out["final_recommendation"]})
        assert "500 亿" in report
        assert "5 万亿" not in report
        assert "撤回" in report

    def test_a_top_level_field_the_report_prints_is_correctable(self):
        """The recommendation, winner rationale and confidence rationale are
        printed verbatim, so an error there must be correctable too — the review
        found them omitted, which left a reported error on display."""
        review = {"confidence": "low", "knowledge_gaps": [], "corrections": [
            {"option": "ClickHouse", "field": "recommendation",
             "action": "revise", "corrected": "在 500 亿行级日志上选 ClickHouse。",
             "reason": "来源写 500 亿。"},
            {"option": "ClickHouse", "field": "winner_rationale",
             "action": "withdraw", "reason": "无来源支持。"},
        ]}
        out = self._run_with(review)
        rec = out["final_recommendation"]
        assert rec["recommendation"] == "在 500 亿行级日志上选 ClickHouse。"
        assert "撤回" in rec["winner_rationale"] or "withdrawn" in rec["winner_rationale"]
        assert out["quality_signals"][0]["corrections_rejected"] == 0

    def test_a_trade_off_finding_is_correctable(self):
        review = {"confidence": "low", "knowledge_gaps": [], "corrections": [
            {"option": "成本可预测性", "field": "finding", "action": "withdraw",
             "reason": "无来源支持。"},
        ]}
        out = self._run_with(review)
        rec = out["final_recommendation"]
        target = next(t for t in rec["trade_offs"]
                      if t.get("dimension") == "成本可预测性")
        assert "撤回" in target["finding"] or "withdrawn" in target["finding"]
        assert out["quality_signals"][0]["corrections_applied"] == 1

    def test_an_unusable_confidence_cannot_raise_the_result(self):
        """The cap required the exact lowercase triple, so any other spelling
        skipped it and an invalid value reached the report."""
        prior_level = {"low": 0, "medium": 1, "high": 2}[
            _failed_run_state()["final_recommendation"]["confidence"]]
        for value in ("HIGH", "High", " high", "medium ", "unknown", "", None, 2, True):
            out = self._run_with({"confidence": value, "knowledge_gaps": [],
                                  "corrections": []})
            confidence = out["confidence"]
            assert confidence in ("low", "medium", "high"), (value, confidence)
            assert {"low": 0, "medium": 1, "high": 2}[confidence] <= prior_level, \
                f"reviewer value {value!r} raised confidence to {confidence!r}"
            assert out["final_recommendation"]["confidence"] == confidence


class TestRevisedCitationsFollowTheSynthesisRules:
    """A revision is the reviewer's own prose, so it must go through the same
    citation rules as synthesis. Without that, a revision could reintroduce an
    unknown title, a navigation-only page or an out-of-range number."""

    REVISION = "修订内容 [Source: Unknown invented title] [Source: Navigation only] [[999]]"

    def _ctx(self):
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        return state, mapping

    def _apply(self, text, field="rationale", chains=None, mapping=None):
        state, real_mapping = self._ctx()
        rec = json.loads(json.dumps(state["final_recommendation"]))
        applied, rejected = sr._apply_corrections(
            rec, [{"option": "ClickHouse", "field": field, "action": "revise",
                   "corrected": text, "reason": "test"}],
            evidence_chains=chains if chains is not None else state["evidence_chains"],
            cite_map=mapping if mapping is not None else real_mapping,
        )
        got = next(o for o in rec["ranked_options"] if o["name"] == "ClickHouse")[field]
        return applied, got

    def test_the_reported_leak_is_closed(self):
        """The exact reported payload must not survive as citations."""
        _applied, got = self._apply(self.REVISION)
        assert "[Source: Unknown invented title]" not in got, got
        assert "[Source: Navigation only]" not in got, got
        assert "[[999]]" not in got, got
        assert "引用未解析" in got or "citation-unresolved" in got, got

    def test_a_navigation_only_source_cannot_be_cited(self):
        """A page with no collected body is not a basis, even when it is in the
        evidence: naming it must not make it citable."""
        state, mapping = self._ctx()
        nav = {"title": "Navigation only", "url": "https://nav.example/x",
               "snippet": "", "has_body": False}
        chains = json.loads(json.dumps(state["evidence_chains"]))
        chains[0]["sources"].append(nav)
        _applied, got = self._apply("理由 [Source: Navigation only]",
                                   chains=chains, mapping=mapping)
        assert "[Source: Navigation only]" not in got, got
        assert "引用未解析" in got or "citation-unresolved" in got, got

    def test_an_out_of_range_number_is_located_not_dropped(self):
        _applied, got = self._apply("理由 [[999999]]")
        assert "[[999999]]" not in got, got
        assert "999999" in got, got
        assert "引用未解析" in got or "citation-unresolved" in got, got

    def test_a_legitimate_citation_survives(self):
        """The reviewer's own valid citation must not be stripped."""
        _state, mapping = self._ctx()
        number = sorted(mapping)[0]
        title = mapping[number]
        for text in (f"理由 [Source: {title}]", f"理由 [[{number}]]"):
            _applied, got = self._apply(text)
            assert "撤回" not in got, got
            assert title in got, (text, got)

    def test_a_revision_with_no_citation_is_kept(self):
        _applied, got = self._apply("理由无需引用")
        assert got == "理由无需引用"

    def test_resolution_uses_the_synthesis_rule_not_a_copy(self):
        """Both paths must call the same helper. Asserted by behaviour: the
        synthesis path and the reviewer path must remove exactly the same
        fabricated marker from the same evidence."""
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        text = "理由 [Source: Unknown invented title] [[999]]"
        via_synthesis = cs.resolve_citations(text, state["evidence_chains"], mapping)
        rec = json.loads(json.dumps(state["final_recommendation"]))
        sr._apply_corrections(rec, [{
            "option": "ClickHouse", "field": "rationale", "action": "revise",
            "corrected": text, "reason": "t"}],
            evidence_chains=state["evidence_chains"], cite_map=mapping)
        via_reviewer = next(o for o in rec["ranked_options"]
                            if o["name"] == "ClickHouse")["rationale"]
        assert "[Source: Unknown invented title]" not in via_synthesis
        assert "[Source: Unknown invented title]" not in via_reviewer
        assert "引用未解析" in via_synthesis or "citation-unresolved" in via_synthesis
        # And the reviewer's revision is the resolved text, not the raw input.
        assert via_reviewer == via_synthesis

    def test_a_marker_that_never_closes_is_not_treated_as_a_source(self):
        """`[Source: X` with no closing bracket is still a claimed citation; it
        is not accepted as a source, and its title stays locatable as a gap."""
        _applied, got = self._apply("probe [Source: Unknown invented title")
        assert "[Source: Unknown invented title" not in got, got
        assert "引用未解析" in got or "citation-unresolved" in got, got

    def test_number_spacing_and_sign_variants_do_not_survive(self):
        # An unknown positive number becomes a locatable gap; a known number
        # binds even with spaces around it; a negative number is not a citation
        # at all and is left as written rather than fabricating a source for it.
        _applied, got = self._apply("理由 [[ 999 ]]")
        assert "[[" not in got, got
        assert "引用未解析" in got or "citation-unresolved" in got, got

        _state, mapping = self._ctx()
        number = sorted(mapping)[0]
        _applied, got = self._apply(f"理由 [[ {number} ]]")
        assert mapping[number] in got, got

        _applied, got = self._apply("理由 [[-1]]")
        assert got == "理由 [[-1]]", got

    def test_a_markers_only_revision_is_withdrawn_not_blanked(self):
        """Stripping the markers left the field whitespace, which blanked the
        answer and hid why. A revision that is nothing but markers must become
        the withdrawal note, whose language follows the field it replaces."""
        for text in ("[Source: Unknown invented title] [[999]]", "[[999]]",
                     "[Source: Navigation only]",
                     "  [Source: Unknown invented title]  ",
                     "[Source: Unknown invented title"):
            _applied, got = self._apply(text)
            assert got.strip(), f"blanked by {text!r}"
            assert "撤回" in got or "withdrawn" in got.lower(), (text, got)

    def test_a_revision_with_prose_keeps_its_prose(self):
        """A marker stripped from a revision that also says something keeps the
        statement: dropping the claim as well would lose an answer the reviewer
        did support."""
        _applied, got = self._apply("理由 [Source: Unknown invented title] [[999]] 说明")
        assert "理由" in got and "说明" in got, got
        assert "[Source: Unknown invented title]" not in got, got
        assert "[[999]]" not in got, got
        assert "引用未解析" in got or "citation-unresolved" in got, got

    def test_a_title_containing_a_commas_survives_resolution(self):
        """The reviewer path scrubbed a second time, after binding, and the
        sanitizer splits a marker's titles on commas — so a real title such as
        'Deploy, Calibrate, Monitor, Heal …' was truncated and dropped. The
        reviewer path must therefore follow the node's order exactly."""
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        comma_titles = {n: t for n, t in mapping.items() if "," in t}
        assert comma_titles, "fixture: expected a title containing a comma"
        for number, title in comma_titles.items():
            via_synthesis = cs.resolve_citations(
                f"理由 [[{number}]]", state["evidence_chains"], mapping)
            assert title in via_synthesis, (number, via_synthesis)
            _applied, via_reviewer = self._apply(f"理由 [[{number}]]")
            assert title in via_reviewer, (number, via_reviewer)
            assert via_reviewer == via_synthesis, (number, via_reviewer)

    def test_a_bound_citation_is_not_reported_as_unresolved(self):
        """A comma-bearing title made the unresolved check split the marker and
        call a correct citation unresolved, which withdrew it."""
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        for number, title in mapping.items():
            if "," not in title:
                continue
            resolved = cs.resolve_citations(
                f"理由 [[{number}]]", state["evidence_chains"], mapping)
            assert not cs.unresolved_citations(resolved, state["evidence_chains"])

    def test_a_non_positive_number_rejects_the_whole_marker(self):
        """A marker containing a non-positive number is not a source list — an
        interval `[[0,1]]` or `[[-1,2]]`. Binding its remaining in-range numbers
        gave a real source to text that cites nothing, so the whole marker is
        rejected rather than only the bad number being filtered out.

        Both the unspaced and the spaced form reach the binding pass, so both are
        covered here. The assertion is on the rendered text, so it fails whether
        the title leaks or the marker is silently left unresolved as a title.
        """
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        all_titles = set(mapping.values())
        cases = ("[[0,1]]", "[[0,2]]", "[[-1,2]]", "[[ 0,1 ]]", "[[ 0, 1 ]]",
                 "[[+0,1]]", "[[0,0]]", "[[1,0]]",
                 "the interval [[0,1]] is normalized", "x=[[0,1]]")
        for text in cases:
            for label, got in (
                ("synthesis", cs.resolve_citations(text, state["evidence_chains"], mapping)),
                ("reviewer", self._apply(text)[1]),
            ):
                leaked = {t for t in all_titles if t in got}
                assert not leaked, (label, text, sorted(leaked)[:1], got)

    def test_a_wider_grammar_cannot_turn_prose_into_a_citation(self):
        """A looser number grammar matched ordinary text and resolved it to real
        sources, fabricating an attribution the model never made. Every source
        title must stay absent from such text, not just the first one."""
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        all_titles = set(mapping.values())
        for text in ("the interval [[0, 1]] is normalized",
                     "code: arr[[1, 2]] = x",
                     "code: arr[[1,2]] = x",
                     "x[[1]]y[[2]]z",
                     "matrix m[[2,3]] element",
                     "list[[1,2]] = values",
                     "row[[2,3]][0]",
                     "a[[1]]b"):
            via_synthesis = cs.resolve_citations(text, state["evidence_chains"], mapping)
            _applied, via_reviewer = self._apply(text)
            for got in (via_synthesis, via_reviewer):
                leaked = all_titles & {t for t in all_titles if t in got}
                assert not leaked, (text, sorted(leaked)[:2], got)

    def test_a_citation_shaped_marker_still_resolves(self):
        """The guard must not stop the model's own convention from working: the
        prompt asks for `[[N]]`, which a model often writes unspaced."""
        _state, mapping = self._ctx()
        numbers = sorted(mapping)
        number = numbers[0]
        title = mapping[number]
        # A multi-source marker is checked against two distinct numbers: one
        # number twice de-duplicates to a single title, which the whole-content
        # check in unresolved_citations cannot tell from a leftover plain title.
        multi = f"{number},{numbers[1]}" if len(numbers) > 1 else str(number)
        for text in (f"理由[[{number}]]", f"理由 [[{number}]]", f"理由：[[{number}]]",
                     f"理由 [[{multi}]]", f"text [[{number}]] more"):
            _applied, got = self._apply(text)
            assert title in got, (text, got)

    def test_a_word_marker_is_left_as_written(self):
        """Only numeric markers are treated as citations."""
        for text in ("见 [[附录]] 说明", 'quoted "[[the manual]]" text'):
            _applied, got = self._apply(text)
            assert got == text, (text, got)


class TestTheSynthesisPipelineLeavesNoBlankField:
    """Binding ran after the sanitizer and could empty a field on its own, so the
    scrub never saw it: a withdrawn claim was printed as a blank line, and the
    report lost the recommendation rather than saying the claim was withdrawn."""

    def _pipeline(self, field: str, text: str):
        state = _failed_run_state()
        result = {field: text}
        cs.apply_citation_rules(result, state["evidence_chains"])
        return result[field]

    def test_a_top_level_field_is_not_left_blank(self):
        for text in ("[[999]]", "[[999,888]]", "[[1 2]]", "[[1.0]]"):
            got = self._pipeline("recommendation", text)
            assert got.strip(), f"{text!r} left the field blank"
            assert "withdraw" in got.lower(), (text, got)

    def test_an_option_field_is_not_left_blank(self):
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        result = {"ranked_options": [{"name": "C", "rationale": "[[999]]"}]}
        cs.apply_citation_rules(result, state["evidence_chains"], mapping)
        got = result["ranked_options"][0]["rationale"]
        assert got.strip() and "withdraw" in got.lower(), got

    def test_a_trade_off_field_is_not_left_blank(self):
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        result = {"trade_offs": [{"dimension": "d", "finding": "[[999]]"}]}
        cs.apply_citation_rules(result, state["evidence_chains"], mapping)
        got = result["trade_offs"][0]["finding"]
        assert got.strip() and "withdraw" in got.lower(), got

    def test_the_report_keeps_the_line_instead_of_dropping_it(self):
        """The served body lost its advice line entirely; it must carry the note."""
        state = _failed_run_state()
        _prompt, mapping = cs._summarize_chains(
            state["evidence_chains"], state["task"]["candidate_techs"])
        rec = json.loads(json.dumps(state["final_recommendation"]))
        rec["recommendation"] = "[[999,888]]"
        cs.apply_citation_rules(rec, state["evidence_chains"], mapping)
        body = render({**state, "final_recommendation": rec})
        assert "**建议:**" in body or "**Recommendation:**" in body
        assert "withdraw" in body.lower() or "撤回" in body

    def test_ordinary_fields_are_untouched(self):
        assert self._pipeline("recommendation", "理由无需引用") == "理由无需引用"


class TestTheContractSentToTheModel:
    """The executor accepted top-level and trade-off fields while the prompt only
    described four per-candidate ones, so the model was never told it could use
    them. A simulated response proves the executor accepts; it does not prove the
    model knows what to send."""

    def _system_prompt(self):
        captured = {}

        async def fake_call_model(prompt, **kwargs):
            captured["system"] = prompt[0]["content"]
            captured["user"] = prompt[1]["content"]
            return {"confidence": "low", "knowledge_gaps": [], "corrections": []}

        real = sr.call_model
        sr.call_model = fake_call_model
        try:
            asyncio.run(sr.SelfReviewerAgent().run(dict(_failed_run_state())))
        finally:
            sr.call_model = real
        return captured["system"], captured["user"]

    def test_every_executor_field_is_described(self):
        system, _user = self._system_prompt()
        for field in sr._CORRECTABLE_FIELDS:
            assert field in system, f"{field} is accepted but never described"

    def test_the_executor_field_set_has_one_definition(self):
        """The set is defined in one place, so the contract cannot describe a
        field the applier does not know, or omit one it does."""
        assert sr._CORRECTABLE_FIELDS == (
            sr._CORRECTABLE_OPTION_FIELDS + sr._CORRECTABLE_TOP_FIELDS
            + sr._CORRECTABLE_TRADEOFF_FIELDS)
        assert len(sr._CORRECTABLE_FIELDS) == len(set(sr._CORRECTABLE_FIELDS))

    def test_the_contract_and_the_applier_cannot_drift(self):
        """Every field the contract lists must be one the applier accepts, and
        the contract must list them all. Guarded against a field being added to
        one side only, which a copied list of names cannot catch."""
        system, _user = self._system_prompt()
        listed = set(self._contract_fields(system))
        assert listed == set(sr._CORRECTABLE_FIELDS), (
            f"contract only: {sorted(listed - set(sr._CORRECTABLE_FIELDS))}; "
            f"applier only: {sorted(set(sr._CORRECTABLE_FIELDS) - listed)}")

    @staticmethod
    def _contract_fields(system: str) -> list[str]:
        """Field names the contract lists, read from its own generated map.

        The map is written as `* <family> (option = <selector>): a, b, c`, so the
        names come from the text the model actually received rather than from a
        copy of the list kept in this test.
        """
        fields: list[str] = []
        for line in system.splitlines():
            stripped = line.strip()
            if not stripped.startswith("*") or "):" not in stripped:
                continue
            names = stripped.split("):", 1)[1]
            found = [n.strip() for n in names.split(",") if n.strip()]
            if found and all(re.fullmatch(r"[a-z_]+", n) for n in found):
                fields.extend(found)
        return fields

    def test_the_contract_says_how_to_select_each_family(self):
        system, _user = self._system_prompt()
        lowered = system.lower()
        assert "candidate" in lowered and "name" in lowered
        assert "dimension" in lowered
        assert '""' in system and "empty" in lowered

    def test_the_contract_requires_corrections_not_only_gaps(self):
        system, _user = self._system_prompt()
        assert "knowledge_gaps" in system
        assert "not acceptable" in system

    def test_the_contract_does_not_force_invention(self):
        system, _user = self._system_prompt()
        lowered = system.lower()
        assert "invent" in lowered
        assert "withdraw" in lowered

    def test_the_json_example_is_valid(self):
        """A placeholder like `"passed_count": N` is not valid JSON and a model
        can copy it into a numeric field."""
        system, _user = self._system_prompt()
        line = next(ln for ln in system.splitlines() if ln.strip().startswith('{"checks"'))
        example = json.loads(line.strip())
        assert example["corrections"], "the example must show a corrections entry"
        assert {"option", "field", "action", "reason"} <= set(example["corrections"][0])

    def test_the_payload_still_carries_what_the_review_must_compare(self):
        _system, user = self._system_prompt()
        for name in ("ClickHouse", "Amazon OpenSearch Serverless"):
            assert name in user
        assert "在高达 500 亿行" in user, "the cited source text must be supplied"


class TestTheReviewedResultReachesEveryArtefact:
    """The graph rendered the draft, the reviewer corrected the recommendation,
    and the server then saved the pre-review draft. The endpoints re-render, so
    they looked updated while report.md and the snapshot did not."""

    REVIEW = {
        "confidence": "low", "knowledge_gaps": [], "passed_count": 5,
        "corrections": [{
            "option": "ClickHouse", "field": "rationale", "action": "revise",
            "corrected": ("公开基准称其在 500 亿行级 OTel 日志上磁盘占用约降 5 倍"
                          " [Source: ClickHouse 填平 Elasticsearch 护城河？日志分析新选择！ - InfoQ]。"),
            "reason": "来源写 500 亿，报告的 5 万亿无来源支持。"}],
    }

    def _state_with_draft(self):
        state = _failed_run_state()
        state = dict(state)
        state["report"] = render(state)
        return state

    def _run(self, review, state=None):
        state = state if state is not None else self._state_with_draft()
        captured = {}

        async def fake_call_model(prompt, **kwargs):
            captured["user"] = prompt[1]["content"]
            return review

        real = sr.call_model
        sr.call_model = fake_call_model
        try:
            return asyncio.run(sr.SelfReviewerAgent().run(dict(state))), state, captured
        finally:
            sr.call_model = real

    def test_the_reviewer_still_receives_the_draft(self):
        _out, state, captured = self._run(self.REVIEW)
        assert "## Fields To Review" in captured["user"]
        # The reviewer receives every served field with its locator, not the
        # rendered report (which would duplicate the same prose).
        assert state["final_recommendation"]["recommendation"][:80] in \
            captured["user"], "the reviewer must receive the text it reviews"
        assert "## Report" not in captured["user"]

    def test_the_returned_report_is_the_reviewed_body(self):
        out, _state, _cap = self._run(self.REVIEW)
        assert out["report"], "a report must be returned for saving"
        assert "5 万亿" not in out["report"]
        assert "500 亿" in out["report"]

    def test_the_saved_report_matches_a_fresh_render_of_the_final_state(self):
        """report.md, the snapshot and the endpoints must show one result."""
        out, state, _cap = self._run(self.REVIEW)
        merged = {**state, "final_recommendation": out["final_recommendation"],
                  "confidence": out["confidence"],
                  "knowledge_gaps": out["knowledge_gaps"]}
        assert render(merged) == out["report"]

    def test_the_pre_review_draft_is_not_what_gets_saved(self):
        _out, state, _cap = self._run(self.REVIEW)
        assert "5 万亿" in state["report"], "fixture: the draft had the error"
        assert "5 万亿" not in _out["report"]

    def test_a_withdrawal_path_is_consistent_too(self):
        review = {"confidence": "low", "knowledge_gaps": [], "corrections": [
            {"option": "ClickHouse", "field": "key_strength",
             "action": "withdraw", "reason": "无来源支持。"}]}
        out, state, _cap = self._run(review)
        assert "撤回" in out["report"]
        merged = {**state, "final_recommendation": out["final_recommendation"],
                  "confidence": out["confidence"],
                  "knowledge_gaps": out["knowledge_gaps"]}
        assert render(merged) == out["report"]

    def test_a_run_with_no_corrections_is_consistent_too(self):
        out, state, _cap = self._run(
            {"confidence": "high", "knowledge_gaps": [], "corrections": []})
        merged = {**state, "final_recommendation": out["final_recommendation"],
                  "confidence": out["confidence"],
                  "knowledge_gaps": out["knowledge_gaps"]}
        assert render(merged) == out["report"]

    def test_the_draft_is_not_mutated(self):
        _out, state, _cap = self._run(self.REVIEW)
        assert "5 万亿" in state["report"]


class TestSubjectGuessingStaysRemoved:
    """An earlier attempt added word lists and title-prefix rules to decide a
    page's subject. A page may cover several products, so it is not forced to own
    one; those rules are withdrawn and must not return."""

    def test_no_subject_guessing_helpers(self):
        import deepchoice.utils.candidate_identity as cid

        for removed in ("_DISAMBIGUATING", "_QUALIFIER", "subject_tokens",
                        "identity_phrase", "_mentioned_in_body", "_LEADING_STOP",
                        "candidate_for_source", "index_sources_by_candidate",
                        "UNASSIGNED"):
            assert not hasattr(cid, removed), f"{removed} was reintroduced"

    def test_name_matching_is_the_only_rule_left(self):
        # A page naming the candidate matches its name.
        assert names_candidate("ClickHouse for logs", "ClickHouse")
        # A page naming a different product is not matched onto a candidate.
        assert not names_candidate("SelectDB vs Elasticsearch", "ClickHouse")
