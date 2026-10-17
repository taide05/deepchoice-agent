"""Regressions for the v4 acceptance repairs.

Each test uses the preserved fourth real run as fixed input
(`outputs/9dd25b70-.../research_snapshot.json`) so the defect it pins is the one
observed in that run, not a synthetic stand-in.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from deepchoice.agents import conclusion_synthesizer as cs
from deepchoice.formats.what_why_how import render

V4_RUN = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
          / "9dd25b70-f9f7-4c43-bfc4-ef6cc29c0c14" / "research_snapshot.json")


def v4_state() -> dict:
    """The fourth run's saved state.

    Not a skip: these regressions are pinned to that material and a silent skip
    would report green without running them.
    """
    if not V4_RUN.exists():
        pytest.fail(f"required fixture missing: {V4_RUN}")
    return json.loads(V4_RUN.read_text(encoding="utf-8"))


def synthesis_prompt(state: dict) -> str:
    """The exact text the synthesis node sends, captured from the real node."""
    captured: dict[str, str] = {}

    async def fake_call_model(prompt, **kwargs):
        captured["payload"] = "\n".join(
            str(m.get("content", "")) for m in prompt if isinstance(m, dict))
        return {"recommendation": "x", "winner": "x"}

    real = cs.call_model
    cs.call_model = fake_call_model
    try:
        asyncio.run(cs.ConclusionSynthesizerAgent().run(dict(state)))
    finally:
        cs.call_model = real
    assert captured.get("payload"), "the synthesizer built no payload"
    return captured["payload"]


class TestOriginalQuestionsReachSynthesis:
    """Synthesis received only the original query; the four sub-questions the
    pipeline had already decomposed never entered the call."""

    def test_every_sub_question_is_in_the_sent_prompt(self):
        state = v4_state()
        subs = [str(q).strip() for q in state["sub_questions"] if str(q).strip()]
        assert len(subs) == 4, f"fixture: expected 4 sub-questions, got {len(subs)}"
        payload = synthesis_prompt(state)
        missing = [q for q in subs if q not in payload]
        assert not missing, f"sub-questions missing from the synthesis call: {missing}"

    def test_the_prompt_asks_for_them_to_be_answered_or_recorded(self):
        payload = synthesis_prompt(v4_state())
        assert "Original Sub-Questions" in payload
        assert "unresolved_questions" in payload

    def test_self_review_and_synthesis_use_the_same_questions(self):
        """Both nodes must read the same state field, so one cannot drop a
        question the other still reviews."""
        syn = cs.SYNTHESIS_PROMPT
        assert "{sub_questions}" in syn
        from deepchoice.agents import self_reviewer as sr
        assert 'research_state.get("sub_questions"' in __import__(
            "inspect").getsource(sr.SelfReviewerAgent.run)


class TestFlaggedSourcesAreNotCalledConfirmedContradictions:
    """The synthesis prompt labelled a count of sources that appeared in a
    compared pair as 'Confirmed contradictions among sources'. A flag covers a
    position difference, a factual contradiction, or a comparison whose ruling
    was not finished, so that label overstated what the pipeline established."""

    def _state_with_conflicts(self, resolutions):
        state = dict(v4_state())
        state["conflicts"] = [
            {"claim_a": f"claim A{i}", "claim_b": f"claim B{i}",
             "resolution": res, "confidence": "low", "reasoning": "r",
             "source_a": {"url": f"https://a{i}.example/x", "title": f"A{i}"},
             "source_b": {"url": f"https://b{i}.example/x", "title": f"B{i}"}}
            for i, res in enumerate(resolutions)
        ]
        state["conflict_check"] = {"pairs_scanned": len(resolutions),
                                   "pairs_arbitrated": len(resolutions),
                                   "pairs_evidence": 0,
                                   "pairs_arbitration_failed": 0,
                                   "scan_outcomes": {"difference": len(resolutions),
                                                     "no_difference": 0, "unscanned": 0}}
        return state

    def test_the_prompt_does_not_claim_confirmed_contradictions(self):
        payload = synthesis_prompt(
            self._state_with_conflicts(["A_correct", "insufficient_data"]))
        assert "Confirmed contradictions" not in payload
        assert "Sources flagged in a conflict pair" in payload

    def test_the_prompt_keeps_the_three_kinds_distinct(self):
        payload = synthesis_prompt(
            self._state_with_conflicts(["A_correct", "insufficient_data"]))
        # Compare on one line: the prompt is wrapped, so phrases may span a
        # newline.
        flattened = " ".join(payload.lower().split())
        # The label must say a flag can be any of the three, not that it is one.
        assert "difference of position" in flattened
        assert "factual contradiction" in flattened
        assert "not finished" in flattened or "not completed" in flattened
        # And each conflict's recorded resolution is still presented verbatim, so
        # an unfinished comparison is not silently upgraded.
        assert "resolution: A_correct" in payload
        assert "resolution: insufficient_data" in payload

    def test_an_unresolved_flag_is_not_presented_as_a_contradiction(self):
        payload = synthesis_prompt(self._state_with_conflicts(["insufficient_data"]))
        assert "Confirmed contradictions" not in payload
        assert "resolution: insufficient_data" in payload


class TestBenchmarkAnswersAreNotResearchBasis:
    """The knowledge base was populated from benchmark cases' own ground-truth
    answers. A document that IS the expected answer cannot be cited as evidence
    for the question that set is meant to evaluate."""

    def test_the_generated_documents_declare_their_provenance(self):
        kb = pathlib.Path(r"D:\deepchoice-precodex\chroma_kb")
        marked = sorted((kb / "data" / "benchmark_answers").glob("*.md"))
        assert marked, "fixture: the generated answer documents exist"
        for path in marked:
            text = path.read_text(encoding="utf-8")
            assert "**Provenance**: benchmark ground-truth answer" in text, path.name

    def test_the_generator_writes_into_the_benchmark_directory(self):
        import importlib.util

        path = pathlib.Path(r"D:\deepchoice-precodex\chroma_kb\populate_benchmark_kb.py")
        spec = importlib.util.spec_from_file_location("populate_benchmark_kb", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.OUT_DIR.name == "benchmark_answers"
        assert "benchmark ground-truth answer" in mod.PROVENANCE_LINE

    def test_the_ingest_records_provenance_and_channel(self):
        import importlib.util

        path = pathlib.Path(r"D:\deepchoice-precodex\chroma_kb\setup.py")
        source = path.read_text(encoding="utf-8")
        assert "benchmark_ground_truth" in source
        assert '"provenance"' in source and '"channel"' in source

    def test_the_retriever_excludes_benchmark_answers(self):
        """Exercised through the real retriever with a fake collection, so no
        embedding model or network is needed."""
        from deepchoice.retrievers import chroma_kb as mod

        class FakeCollection:
            METADATAS = [
                {"title": "redis-vs-memcached",
                 "url": "file:///kb/data/benchmark_answers/redis-vs-memcached.md",
                 "provenance": "benchmark_ground_truth",
                 "source_type": "benchmark_answers",
                 "channel": "local_kb", "date": ""},
                {"title": "Real Doc",
                 "url": "file:///kb/data/blogs/real-doc.md",
                 "provenance": "unknown",
                 "source_type": "blogs",
                 "channel": "local_kb", "date": ""},
            ]

            def get(self, **kwargs):
                # The pre-check reads metadata only; it must see one research
                # document so retrieval is allowed to proceed.
                return {"ids": ["a", "b"], "metadatas": self.METADATAS}

            def query(self, **kwargs):
                return {
                    "ids": [["benchmark_answers/redis-vs-memcached.md",
                             "blogs/real-doc.md"]],
                    "metadatas": [self.METADATAS],
                    "documents": [["answer body", "documented body"]],
                }

        class FakeModel:
            class _Arr(list):
                def tolist(self):
                    return list(self)

            def encode(self, texts):
                return self._Arr([[0.0] * 1024 for _ in texts])

        kb = mod.ChromaKB.__new__(mod.ChromaKB)
        kb.collection = FakeCollection()
        monkeypatch_model = FakeModel()
        original = mod.get_embedding_model
        mod.get_embedding_model = lambda: monkeypatch_model
        try:
            results = asyncio.run(kb._do_search("q", [], 8, adapted_queries=["q"]))
        finally:
            mod.get_embedding_model = original
        titles = [r["title"] for r in results]
        assert "redis-vs-memcached" not in titles
        assert "Real Doc" in titles

    def test_unknown_provenance_is_not_treated_as_published(self):
        from deepchoice.agents.source_evaluator import classify_source_type, score_authority

        assert classify_source_type("file:///kb/data/blogs/x.md", "chroma") == "local_document"
        assert score_authority("local_document") < score_authority("tech_blog")

    def test_provenance_travels_through_source_evaluation(self):
        from deepchoice.agents.source_evaluator import SourceEvaluatorAgent

        state = {"search_results": [{
            "source": "chroma",
            "results": [{"url": "file:///kb/x.md", "title": "x", "snippet": "body text",
                         "provenance": "benchmark_ground_truth", "channel": "local_kb",
                         "date": ""}],
        }]}
        out = asyncio.run(SourceEvaluatorAgent().run(state))
        entry = out["source_scores"][0]
        assert entry["provenance"] == "benchmark_ground_truth"
        assert entry["channel"] == "local_kb"


class TestRetrievalHitsAreNotJudgments:
    """Every scored retrieval hit used to become a chain whose "conclusion" was
    its title and whose "evidence strength" came from the metadata score, so a
    search result was presented as an established judgment."""

    def test_the_chain_builder_manufactures_no_conclusion_or_strength(self):
        from deepchoice.agents.evidence_chain import build_evidence_chain

        chains = build_evidence_chain([{
            "url": "https://example.com/unrelated",
            "title": "A totally unrelated repository",
            "snippet": "Stars: 894, Description: a scheduling framework",
            "total_score": 7.4,
            "supporting_sources": [],
            "provenance": "unknown", "channel": "web",
        }], [])
        assert len(chains) == 1
        assert chains[0]["conclusion"] == ""
        assert chains[0]["evidence_strength"] == "unknown"
        assert chains[0]["retrieval_score"] == 7.4
        assert chains[0]["sources"][0]["provenance"] == "unknown"

    def test_the_synthesis_prompt_does_not_endorse_metadata_as_evidence(self):
        payload = synthesis_prompt(v4_state())
        lowered = payload.lower()
        assert "strong evidence" not in lowered
        assert "strength ratings" not in lowered
        assert "weight strong" not in lowered
        assert "retrieval" in lowered

    def test_the_reviewer_payload_has_no_strength_band(self):
        from deepchoice.agents import self_reviewer as sr

        captured = {}

        async def fake(prompt, **kwargs):
            captured["user"] = prompt[1]["content"]
            return {"confidence": "low", "knowledge_gaps": [], "corrections": []}

        real = sr.call_model
        sr.call_model = fake
        try:
            asyncio.run(sr.SelfReviewerAgent().run(dict(v4_state())))
        finally:
            sr.call_model = real
        payload = captured["user"]
        assert "[moderate]" not in payload
        assert "[strong]" not in payload

    def test_the_report_basis_is_the_sources_synthesis_actually_used(self):
        import re

        from deepchoice.formats.basis import used_sources

        state = v4_state()
        report = render(state)
        why = report.split("## Why")[1].split("## 争议")[0]
        assert why, "the Why section is present"
        used = used_sources(state["final_recommendation"], state["evidence_chains"])
        assert used, "fixture: the synthesis cites sources"
        # The Why section must name exactly the sources production derives as
        # used — not every retrieved hit. It is compared against the production
        # helper rather than re-deriving the set here.
        listed = set(re.findall(r"^- \[(.+?)\]\(.+?\) ×\d+", why, re.MULTILINE))
        assert listed, "the Why section lists no sources at all"
        assert listed == {u["title"] for u in used}, (
            f"presented but not used: {sorted(listed - {u['title'] for u in used})}; "
            f"used but not presented: {sorted({u['title'] for u in used} - listed)}")
        # An unused retrieval hit must not appear as a basis anywhere.
        unused = {s.get("title") for c in state["evidence_chains"]
                  for s in (c.get("sources") or [])} - {u["title"] for u in used}
        references = report.split("### References")[-1].split("### 参考来源")[-1]
        for title in unused:
            if not title:
                continue
            assert f"[{title}]" not in references, \
                f"unused retrieval hit listed as a reference: {title}"


class TestFinalArtefactsAgree:
    """The saved report omitted the review's own findings while the endpoint
    showed them, and the data-coverage note vanished when the reviewer
    re-rendered."""

    REVIEW = {
        "confidence": "low", "passed_count": 4,
        "knowledge_gaps": ["缺口甲：容量估算未验证", "缺口乙：持久化方案未比较"],
        "corrections": [{
            "option": "Amazon ElastiCache for Memcached", "field": "key_strength",
            "action": "withdraw", "reason": "所引来源不支持该断言。"}],
    }

    def _run(self, state=None):
        from deepchoice.agents import self_reviewer as sr

        state = dict(state or v4_state())
        state["report"] = render(state)

        async def fake(prompt, **kwargs):
            return self.REVIEW

        real = sr.call_model
        sr.call_model = fake
        try:
            return asyncio.run(sr.SelfReviewerAgent().run(dict(state))), state
        finally:
            sr.call_model = real

    def test_the_saved_body_carries_the_review_gaps(self):
        out, _state = self._run()
        for gap in self.REVIEW["knowledge_gaps"]:
            assert gap in out["report"], f"review gap missing from saved body: {gap}"

    def test_the_saved_body_equals_a_render_of_the_final_state(self):
        out, state = self._run()
        merged = dict(state)
        merged["final_recommendation"] = out["final_recommendation"]
        merged["confidence"] = out["confidence"]
        merged["knowledge_gaps"] = out["knowledge_gaps"]
        assert render(merged) == out["report"]

    def test_the_coverage_note_survives_the_review_render(self):
        state = v4_state()
        assert state.get("partial_failures"), "fixture: the run had a failed source"
        out, _state = self._run(state)
        assert "数据覆盖" in out["report"], "the partial-failure note was lost"

    def test_the_coverage_note_is_derived_at_the_render_entry(self):
        from deepchoice.formats.coverage import derive_data_source_note

        state = v4_state()
        note = derive_data_source_note(state)
        assert "arxiv" in note
        assert derive_data_source_note({**state, "partial_failures": []}) == ""
        assert note in render(state)

    def test_trade_off_labels_carry_no_dangling_numbers(self):
        import re
        state = v4_state()
        report = render(state)
        assert not re.search(r"\[\[\s*-?\d+\s*\]\]", report), \
            "a dangling citation number is visible in the report"

    def test_trade_off_label_identity_is_clean_and_locatable(self):
        """The label is normalised once, so what is displayed is also what the
        self-review matches on."""
        from deepchoice.agents.conclusion_synthesizer import clean_label
        from deepchoice.agents.self_reviewer import _apply_corrections

        state = v4_state()
        rec = json.loads(json.dumps(state["final_recommendation"]))
        rec["trade_offs"][0]["dimension"] = "内存效率与成本 [[16]]"
        rec["trade_offs"][0]["finding"] = "原始论断"
        applied, rejected = _apply_corrections(
            rec, [{"option": "内存效率与成本 [[16]]", "field": "finding",
                   "action": "withdraw", "reason": "来源不支持"}],
            evidence_chains=state["evidence_chains"],
            cite_map={})
        assert applied and not rejected, rejected
        assert "撤回" in rec["trade_offs"][0]["finding"] or \
            "withdrawn" in rec["trade_offs"][0]["finding"].lower()
        assert clean_label("内存效率与成本 [[16]]") == "内存效率与成本"

    def test_legitimate_citations_survive_all_of_this(self):
        import re
        state = v4_state()
        report = render(state)
        rec = state["final_recommendation"]
        title = None
        for opt in rec.get("ranked_options") or []:
            found = re.findall(r"\[Source:\s*([^\]]+)\]", str(opt.get("rationale") or ""))
            if found:
                title = found[0]
                break
        assert title, "fixture: the recommendation cites a source"
        # The inline citation survives, and the source is also listed in the
        # References section derived from the used-source set.
        assert f"[Source: {title}]" in report
        references = report.split("### References")[-1]
        assert title in references


class TestUnresolvedQuestionsAreRendered:
    """The synthesis writes `unresolved_questions` into the recommendation, but
    no renderer printed them, so questions it could not answer vanished."""

    def test_rendered_alongside_knowledge_gaps(self):
        state = v4_state()
        rec = json.loads(json.dumps(state["final_recommendation"]))
        rec["unresolved_questions"] = ["问题甲：容量估算", "问题乙：持久化取舍"]
        report = render({**state, "final_recommendation": rec})
        assert "问题甲：容量估算" in report
        assert "问题乙：持久化取舍" in report

    def test_forwarded_without_losing_the_review_gaps(self):
        from deepchoice.agents.conclusion_synthesizer import clean_label

        state = v4_state()
        rec = json.loads(json.dumps(state["final_recommendation"]))
        rec["unresolved_questions"] = ["问题甲：容量估算"]
        report = render({**state, "final_recommendation": rec})
        gaps = state.get("knowledge_gaps") or []
        assert gaps, "fixture: the v4 run recorded knowledge gaps"
        for gap in gaps:
            # Display is cleaned of dangling citation numbers, so compare the
            # cleaned text: the gap itself must still be present.
            assert clean_label(gap) in report, f"review gap lost: {gap[:40]}"

    def test_a_duplicate_is_shown_once(self):
        from deepchoice.agents.conclusion_synthesizer import clean_label

        state = v4_state()
        gap = (state.get("knowledge_gaps") or [""])[0]
        rec = json.loads(json.dumps(state["final_recommendation"]))
        rec["unresolved_questions"] = [gap]
        report = render({**state, "final_recommendation": rec})
        # The question must actually be rendered (not skipped), exactly once.
        shown = clean_label(gap)
        assert shown in report
        assert report.count(f"- {shown}") == 1


class TestTheOtherReportFormatsShareTheBasis:
    """The comparison and evidence-first formats still read the chain
    `conclusion`/`evidence_strength`/`score` fields after the chain builder
    stopped supplying them, so they rendered empty conclusions and "(unknown)".
    Both are selectable through /report?format=, /export and /regenerate."""

    def _renders(self):
        from deepchoice.formats.comparison_matrix import render as render_matrix
        from deepchoice.formats.evidence_first import render as render_evidence
        state = v4_state()
        # Take the shape the current chain builder produces. The preserved
        # snapshot still holds the OLD chain shape (a title as `conclusion`, a
        # score-derived `evidence_strength`, a `score`), so rendering it would not
        # exercise the defect this class pins: the other formats reading fields
        # that the builder no longer emits.
        state["evidence_chains"] = [
            {"conclusion": "", "evidence_strength": "unknown",
             "retrieval_score": (c.get("sources") or [{}])[0].get("score", 6.0),
             "disputed": c.get("disputed", False),
             "sources": [{k: v for k, v in (s or {}).items() if k != "score"}
                         for s in (c.get("sources") or [])]}
            for c in state["evidence_chains"]
        ]
        return state, render_evidence(state), render_matrix(state)

    def test_no_format_renders_a_removed_field_as_content(self):
        _state, evidence, matrix = self._renders()
        for name, text in (("evidence_first", evidence), ("comparison_matrix", matrix)):
            for marker in ("(unknown)", "score: N/A", "strength: unknown",
                           "Insufficient evidence", "数据不足"):
                assert marker not in text, f"{name} rendered {marker!r}"

    def test_no_format_prints_a_dangling_citation_number(self):
        import re
        for name, text in zip(("evidence_first", "comparison_matrix"),
                              self._renders()[1:]):
            assert not re.search(r"\[\[\s*-?\d+\s*\]\]", text), \
                f"{name} printed a dangling citation number"

    def test_the_matrix_compares_the_synthesis_candidates(self):
        state, _evidence, matrix = self._renders()
        # The matrix is built from the synthesis result's per-candidate fields.
        # The old format printed a five-row keyword-derived dimension table; these
        # headers only exist in the candidate comparison.
        assert "约束适配" in matrix or "Constraint fit" in matrix
        for opt in state["final_recommendation"]["ranked_options"]:
            assert opt["name"] in matrix, f"candidate missing from the matrix: {opt['name']}"
            assert str(opt.get("rationale") or "")[:40] in matrix, \
                f"the matrix lost {opt['name']}'s own rationale"

    def test_every_format_lists_the_same_used_sources(self):
        from deepchoice.formats.basis import used_sources

        state, evidence, matrix = self._renders()
        names = [s["title"] for s in used_sources(state["final_recommendation"],
                                                  state["evidence_chains"])]
        assert names, "fixture: the synthesis cites sources"
        for title in names:
            assert title in evidence, f"evidence_first lost {title}"
            assert title in matrix, f"comparison_matrix lost {title}"

