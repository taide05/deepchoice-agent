"""Regression tests for the conflict and source-evaluation corrections.

These live in the suite deliberately: the behaviours below were each wrong once,
and an uncommitted probe would not protect them. Every test uses offline fakes;
none of them contacts a service.
"""
from __future__ import annotations

import asyncio
import types

import numpy as np
import pytest

from deepchoice.agents import conflict_detector as cd
from deepchoice.agents import source_evaluator as se


def _sources(count: int) -> list[dict]:
    return [
        {"url": f"https://example.invalid/{i}", "title": f"Source {i} comparison",
         "snippet": "s", "total_score": 7.0, "scores": {"authority": 7}}
        for i in range(count)
    ]


def _embedding_all_similar(dim: int = 8):
    """Distinct vectors that all stay above threshold, so every pair is a candidate.

    Distinct rather than identical on purpose: identical titles once let a
    withdrawn duplicate-exclusion rule empty the candidate list, which made a
    "cap" assertion pass without any pair actually being scanned.
    """
    def encode(titles):
        rows = []
        for index in range(len(titles)):
            row = np.ones(dim)
            row[0] = 1.0 - 0.01 * (index % 3)
            row[1] = 1.0 - 0.01 * ((index // 3) % 3)
            rows.append(row)
        return np.array(rows) if rows else np.ones((0, dim))
    return types.SimpleNamespace(encode=encode)


class TestScanWorkBound:
    @pytest.mark.asyncio
    async def test_pair_cap_holds_with_many_sources(self, monkeypatch):
        """29 sources must still scan at most 15 pairs."""
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())
        scanned = []

        async def fake_scan(src_a, src_b, query, usage=None):
            scanned.append((src_a["url"], src_b["url"]))
            return {"has_difference": False, "type": "none"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        pairs = await cd.find_contradictions(_sources(29), "topic", usage=[])

        assert pairs == []
        # A cap assertion is only meaningful if pairs were actually scanned.
        assert scanned, "no pair reached the scan, so the cap was never exercised"
        assert len(scanned) == 15, f"scanned {len(scanned)} pairs, cap is 15"

    @pytest.mark.asyncio
    async def test_evidence_gathering_stays_at_the_single_pair_bound(self, monkeypatch):
        """Evidence stays capped to one pair, not expanded to every pair."""
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "e"}

        gathered = []
        arbitrated = []

        async def fake_gather(topic, claim_a, claim_b, usage=None):
            gathered.append((claim_a, claim_b))
            return "gathered"

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            arbitrated.append(tag)
            if tag == "conflict_rearbitration":
                raise AssertionError("the duplicate re-arbitration call is back")
            return {"resolution": "a", "confidence": "low", "reasoning": "r"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        monkeypatch.setattr(cd, "_gather_evidence", fake_gather)
        monkeypatch.setattr(cd, "call_model", fake_call_model)

        result = await cd.ConflictDetectorAgent(gather_evidence=True).run({
            "source_scores": _sources(29),
            "task": {"query": "topic"},
            "token_usage": [],
        })

        assert gathered, "the ambiguous pair must still get evidence"
        assert len(gathered) == 1, f"evidence gathered for {len(gathered)} pairs"
        assert "conflict_rearbitration" not in arbitrated
        check = result["conflict_check"]
        assert check["pairs_evidence"] == 1
        assert check["pairs_scanned"] <= 15

    @pytest.mark.asyncio
    async def test_deterministic_rule_path_pays_no_evidence_cost(self, monkeypatch):
        """A pair the score rule can decide must not trigger the search cost."""
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "e"}

        gathered = []
        message_calls = []

        async def fake_gather(topic, claim_a, claim_b, usage=None):
            gathered.append(claim_a)
            return "gathered"

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            message_calls.append(tag)
            return {"resolution": "a", "confidence": "low", "reasoning": "r"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        monkeypatch.setattr(cd, "_gather_evidence", fake_gather)
        monkeypatch.setattr(cd, "call_model", fake_call_model)

        # A clear score gap is decided by the deterministic rule.
        strong = [{"url": "https://a", "title": "A comparison", "snippet": "s",
                   "total_score": 9.5, "scores": {"authority": 10}},
                  {"url": "https://b", "title": "A comparison too", "snippet": "s",
                   "total_score": 2.0, "scores": {"authority": 2}}]
        await cd.ConflictDetectorAgent(gather_evidence=True).run({
            "source_scores": strong, "task": {"query": "t"}, "token_usage": [],
        })
        assert message_calls == [], "the rule path made an LLM call"
        assert gathered == [], "the rule path paid the evidence search cost"


class TestIncompleteIsNotNoDifference:
    @pytest.mark.asyncio
    async def test_all_scans_failing_is_reported_incomplete(self, monkeypatch):
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def failing_scan(src_a, src_b, query, usage=None):
            raise RuntimeError("provider down")

        monkeypatch.setattr(cd, "_scan_pair_contradiction", failing_scan)
        result = await cd.ConflictDetectorAgent(gather_evidence=True).run({
            "source_scores": _sources(6), "task": {"query": "t"}, "token_usage": [],
        })

        assert result["conflicts"] == []
        assert result["conflict_check"]["scan_outcomes"]["unscanned"] > 0
        assert result["quality_signals"][0]["conflict_check_incomplete"] is True

    @pytest.mark.asyncio
    async def test_evidence_slot_targets_the_ambiguous_pair_not_a_failed_one(self, monkeypatch):
        """A failed arbitration must not shift the evidence slot onto another pair.

        The slot index is a position among the pairs that produced a conflict; it
        must not be a position in the filtered list, or a failure earlier in the
        scan silently spends the one evidence search on the wrong pair and drops
        the pair that was actually ambiguous.
        """
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "e"}

        gathered = []
        arbitrations = {"n": 0}

        async def fake_gather(topic, claim_a, claim_b, usage=None):
            gathered.append((claim_a, claim_b))
            return "gathered evidence"

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            if tag != "conflict_arbitration":
                return {"resolution": "a", "confidence": "low", "reasoning": "r"}
            arbitrations["n"] += 1
            if arbitrations["n"] == 1:
                raise RuntimeError("first arbitration fails")
            return {"resolution": "a", "confidence": "low", "reasoning": "r"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        monkeypatch.setattr(cd, "_gather_evidence", fake_gather)
        monkeypatch.setattr(cd, "call_model", fake_call_model)

        result = await cd.ConflictDetectorAgent(gather_evidence=True).run({
            "source_scores": _sources(4), "task": {"query": "t"}, "token_usage": [],
        })

        assert len(gathered) == 1, f"evidence gathered for {len(gathered)} pairs"
        # The pair that failed arbitration must not be the one that gets evidence.
        failed_pair = ("Source 0 comparison", "Source 1 comparison")
        assert gathered[0] != failed_pair, (
            "the single evidence search was spent on a pair whose arbitration failed"
        )
        # And the failure has to be visible rather than silently dropped.
        check = result["conflict_check"]
        assert check["pairs_arbitration_failed"] == 1, check
        assert check["pairs_arbitrated"] == check["scan_outcomes"]["difference"] - 1, check

    @pytest.mark.asyncio
    async def test_unusable_model_replies_are_unscanned_not_no_difference(self, monkeypatch):
        """Drive the REAL scan function with the replies that carry no judgement.

        call_model returns {} for output it cannot parse and the model can return
        an empty or string value for the field, so these replies must not be
        recorded as a completed 'no difference'.
        """
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        unusable = [{}, {"has_difference": ""}, {"has_difference": None},
                    {"has_difference": "false"}, None, []]
        replies = iter(unusable)

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            return next(replies, {})

        monkeypatch.setattr(cd, "call_model", fake_call_model)
        # The real _scan_pair_contradiction is under test here.
        await cd.find_contradictions(_sources(3), "t", usage=[])

        outcomes = cd.find_contradictions.last_outcomes
        assert outcomes["no_difference"] == 0, \
            f"an unusable reply was recorded as no difference: {outcomes}"
        assert outcomes["difference"] == 0, \
            f"a wrong-typed reply manufactured a difference: {outcomes}"
        assert outcomes["unscanned"] > 0
        assert cd.conflict_check_incomplete() is True

    @pytest.mark.asyncio
    async def test_a_real_negative_verdict_still_counts_as_completed(self, monkeypatch):
        """A usable boolean false is a completed scan, not an unscanned pair."""
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            return {"has_difference": False, "type": "none", "explanation": ""}

        monkeypatch.setattr(cd, "call_model", fake_call_model)
        await cd.find_contradictions(_sources(3), "t", usage=[])

        outcomes = cd.find_contradictions.last_outcomes
        assert outcomes["no_difference"] > 0
        assert outcomes["unscanned"] == 0
        assert cd.conflict_check_incomplete() is False

    @pytest.mark.asyncio
    async def test_synthesizer_is_not_told_no_conflicts_when_incomplete(self):
        from deepchoice.agents.conclusion_synthesizer import _summarize_conflicts

        incomplete = _summarize_conflicts(
            [], {"pairs_scanned": 5, "scan_outcomes": {"unscanned": 3, "difference": 0,
                                                       "no_difference": 2}})
        assert "INCOMPLETE" in incomplete
        # It must not assert the absence of conflicts as an established fact.
        assert not incomplete.startswith("No conflicts")
        assert "found no confirmed contradiction" not in incomplete

        completed = _summarize_conflicts(
            [], {"pairs_scanned": 5, "scan_outcomes": {"unscanned": 0, "difference": 0,
                                                       "no_difference": 5}})
        assert "INCOMPLETE" not in completed
        assert "found no confirmed contradiction" in completed

    @pytest.mark.asyncio
    async def test_report_states_an_unfinished_check(self):
        from deepchoice.formats.comparison_matrix import render as render_matrix
        from deepchoice.formats.evidence_first import render as render_evidence
        from deepchoice.formats.what_why_how import render

        base = {
            "task": {"query": "Kafka vs Redis"}, "evidence_chains": [],
            "conflicts": [], "knowledge_gaps": [], "final_recommendation": {},
            "confidence": "low",
        }
        unfinished = {**base, "conflict_check": {
            "pairs_scanned": 4,
            "scan_outcomes": {"unscanned": 4, "difference": 0, "no_difference": 0}}}
        completed = {**base, "conflict_check": {
            "pairs_scanned": 4,
            "scan_outcomes": {"unscanned": 0, "difference": 0, "no_difference": 4}}}

        markers = ("did not complete", "未完成")
        for name, renderer in (("what_why_how", render),
                               ("comparison_matrix", render_matrix),
                               ("evidence_first", render_evidence)):
            assert any(m in renderer(unfinished) for m in markers), \
                f"{name} did not state the unfinished check"
            assert not any(m in renderer(completed) for m in markers), \
                f"{name} treated a completed check as unfinished"


class TestSourceEvaluation:
    def test_chroma_does_not_imply_official(self):
        assert se.classify_source_type(
            "https://example.com/blog/redis-vs-kafka", "chroma") == "tech_blog"

    def test_docs_host_is_still_official_by_url(self):
        assert se.classify_source_type(
            "https://docs.confluent.io/kafka", "chroma") == "official_doc"

    @pytest.mark.asyncio
    async def test_same_title_opposite_bodies_cannot_manufacture_strong(self):
        """Identical titles with opposite bodies must not create support.

        Runs the real source evaluator, so the test fails if any rule starts
        populating support from title evidence alone.
        """
        from deepchoice.agents.evidence_chain import build_evidence_chain
        from deepchoice.agents.source_evaluator import SourceEvaluatorAgent

        channels = [{
            "source": "tavily",
            "results": [
                {"url": "https://a", "title": "Kafka vs Redis", "date": "2026-01-01",
                 "snippet": "Kafka is the faster option here."},
                {"url": "https://b", "title": "Kafka vs Redis", "date": "2026-01-01",
                 "snippet": "Redis is the slower option here."},
            ],
        }]
        state = await SourceEvaluatorAgent().run({
            "task": {"query": "Kafka vs Redis", "candidate_techs": ["Kafka", "Redis"]},
            "search_results": channels,
            "token_usage": [],
        })
        rows = state["source_scores"]
        assert len(rows) == 2
        # Same titles, conflicting bodies: no support may be inferred.
        assert all(not row["supporting_sources"] for row in rows), \
            [row["supporting_sources"] for row in rows]

        chains = build_evidence_chain(rows, [])
        assert all(c["evidence_strength"] != "strong" for c in chains), \
            "matching titles alone produced a strong chain"
