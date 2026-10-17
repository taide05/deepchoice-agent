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


class TestBenchmarkAnswersAreNotResearchBasis:
    """The knowledge base was populated from benchmark cases' own ground-truth
    answers. A document that IS the expected answer cannot be cited as evidence
    for the question that set is meant to evaluate."""

    def test_the_generated_documents_declare_their_provenance(self):
        from deepchoice.agents.conclusion_synthesizer import _summarize_chains  # noqa: F401
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
            def query(self, **kwargs):
                return {
                    "ids": [["benchmark_answers/redis-vs-memcached.md",
                             "blogs/real-doc.md"]],
                    "metadatas": [[
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
                    ]],
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
        state = v4_state()
        report = render(state)
        why = report.split("## Why")[1].split("## 争议")[0] if "## Why" in report else ""
        assert why, "the Why section is present"
        # Every source named in the Why section must appear as a citation in the
        # synthesis result; an unused retrieval hit must not be presented there.
        rec = state["final_recommendation"]
        import re
        cited = set()
        blobs = [str(rec.get(f) or "") for f in
                 ("recommendation", "winner_rationale", "confidence_rationale",
                  "evidence_summary", "scene_fit_note")]
        for opt in rec.get("ranked_options") or []:
            blobs.extend(str(opt.get(f) or "") for f in
                         ("rationale", "constraint_fit_reason", "key_strength",
                          "key_weakness"))
        for to in rec.get("trade_offs") or []:
            blobs.extend(str(to.get(f) or "") for f in ("finding", "impact"))
        for blob in blobs:
            cited.update(p.strip() for p in
                         re.findall(r"\[Source:\s*([^\]]+)\]", blob))
        for name in re.findall(r"^- \[(.+?)\]\(.+?\) ×\d+", why, re.MULTILINE):
            assert name in cited, f"unused retrieval hit presented as basis: {name}"


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
        state = v4_state()
        report = render(state)
        rec = state["final_recommendation"]
        title = None
        for opt in rec.get("ranked_options") or []:
            import re
            found = re.findall(r"\[Source:\s*([^\]]+)\]", str(opt.get("rationale") or ""))
            if found:
                title = found[0]
                break
        assert title, "fixture: the recommendation cites a source"
        assert f"[Source: {title}]" in report

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
        state = v4_state()
        gap = (state.get("knowledge_gaps") or [""])[0]
        rec = json.loads(json.dumps(state["final_recommendation"]))
        rec["unresolved_questions"] = [gap]
        report = render({**state, "final_recommendation": rec})
        assert report.count(f"- {gap}") == 1
