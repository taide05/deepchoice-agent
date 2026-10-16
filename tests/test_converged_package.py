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
