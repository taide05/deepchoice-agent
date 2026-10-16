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

import pytest

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.agents import orchestrator as orch
from deepchoice.agents import self_reviewer as sr
from deepchoice.formats.what_why_how import render
from deepchoice.utils.candidate_identity import names_candidate

FAILED_RUN = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
              / "8049500c-bd39-44e4-81bb-a1fbbebac780" / "research_snapshot.json")


def _failed_run_state() -> dict:
    if not FAILED_RUN.exists():
        pytest.skip(f"failed-run snapshot not present at {FAILED_RUN}")
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

    def test_bound_markers_are_converted_and_unknown_ones_dropped(self):
        mapping = {1: "Real Source"}
        bound = cs._bind_citations(
            {"confidence_rationale": "Zero strong chains [[1]] plus [[999]]."}, mapping)
        assert "[[" not in bound["confidence_rationale"]
        assert "[Source: Real Source]" in bound["confidence_rationale"]

    def test_the_saved_run_no_longer_keeps_raw_markers(self):
        """Replay: the field that held [[16]] [[17]] [[22]] binds cleanly."""
        state = _failed_run_state()
        chains = state.get("evidence_chains") or []
        candidates = state["task"]["candidate_techs"]
        _prompt, mapping = cs._summarize_chains(chains, candidates)
        raw = "强证据链为 0，6 条发现存在争议 [[16]] [[17]] [[22]]。"
        bound = cs._bind_citations({"confidence_rationale": raw}, mapping)
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

    def test_claims_text_carries_the_ranked_justifications(self):
        state = _failed_run_state()
        source = inspect.getsource(sr.SelfReviewerAgent.run)
        assert "claims_text" in source
        assert "{claims_text}" in source, "the reviewer prompt never receives it"

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
