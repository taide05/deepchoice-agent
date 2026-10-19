"""Regression tests for the conflict and source-evaluation corrections.

These live in the suite deliberately: the behaviours below were each wrong once,
and an uncommitted probe would not protect them. Every test uses offline fakes;
none of them contacts a service.
"""
from __future__ import annotations

import types

import numpy as np
import pytest

from deepchoice.agents import conflict_detector as cd
from deepchoice.agents import source_evaluator as se


def _sources(count: int) -> list[dict]:
    return [
        {"url": f"https://example.invalid/{i}", "title": f"Source {i} comparison",
         "snippet": f"Source {i} reports a distinct throughput and latency trade-off.",
         "total_score": 7.0, "scores": {"authority": 7}}
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

        # Both sources must clear the >= 5.0 high-score gate, or the node exits
        # before reaching any arbitration and the rule path is never exercised.
        # The 4.5 gap is decisive, so the rule decides without an LLM call.
        strong = [{"url": "https://a", "title": "A comparison",
           "snippet": "A reports lower latency on the benchmark.",
                   "total_score": 9.5, "scores": {"authority": 10}},
                  {"url": "https://b", "title": "A comparison too",
           "snippet": "B reports higher throughput at scale.",
                   "total_score": 5.0, "scores": {"authority": 5}}]
        # Guard the fixture itself: if these stop reaching arbitration, the
        # assertions below would pass without testing anything.
        assert all(s["total_score"] >= 5.0 for s in strong)
        assert cd._deterministic_arbitration(strong[0], strong[1]) is not None

        result = await cd.ConflictDetectorAgent(gather_evidence=True).run({
            "source_scores": strong, "task": {"query": "t"}, "token_usage": [],
        })
        assert result["conflict_check"]["pairs_scanned"] > 0, \
            "the run never reached the scan, so the rule path was not tested"
        assert result["conflicts"], "the decisive gap should still yield a conflict"
        assert all(c["arbiter_model"] == "deepseek-flash(rule)"
                   for c in result["conflicts"]), \
            [c["arbiter_model"] for c in result["conflicts"]]
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
        """Drive the REAL scan function, one reply per run.

        call_model returns {} for output it cannot parse, and the model can return
        an empty, None, string or numeric value for the field. None of those
        carries a judgement, so none may be recorded as a completed 'no
        difference' (or, for a truthy string, as a difference).

        Each reply is exercised in its own run: a single run consumes as many
        replies as it has candidate pairs, so a longer list would leave the later
        cases untested.
        """
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        unusable = [
            {},                         # unparsable output -> {} from call_model
            {"has_difference": ""},     # empty string
            {"has_difference": None},   # explicit null
            {"has_difference": "false"},  # truthy string: previously a difference
            {"has_difference": "true"},
            {"has_difference": 0},      # numeric, not a bool
            {"has_difference": 1},
            {"type": "none"},           # field missing
            None,                       # non-dict reply
            [],
        ]
        for reply in unusable:
            async def fake_call_model(prompt, model="x", tag="", _reply=reply, **kwargs):
                return _reply

            monkeypatch.setattr(cd, "call_model", fake_call_model)
            # The real _scan_pair_contradiction is under test here.
            await cd.find_contradictions(_sources(3), "t", usage=[])

            outcomes = cd.find_contradictions.last_outcomes
            assert outcomes["no_difference"] == 0, \
                f"reply {reply!r} was recorded as no difference: {outcomes}"
            assert outcomes["difference"] == 0, \
                f"reply {reply!r} manufactured a difference: {outcomes}"
            assert outcomes["unscanned"] > 0, f"reply {reply!r}: {outcomes}"
            assert cd.conflict_check_incomplete() is True

    @pytest.mark.asyncio
    async def test_failed_arbitration_reads_as_unresolved_not_as_no_conflict(
            self, monkeypatch):
        """A confirmed difference whose ruling failed is a live disagreement.

        End to end: the scan confirms a difference, its arbitration fails, and the
        report must say a potential disagreement was not resolved rather than that
        the check completed with no conflicts.
        """
        from deepchoice.agents.conclusion_synthesizer import _summarize_conflicts
        from deepchoice.formats.comparison_matrix import render as render_matrix
        from deepchoice.formats.evidence_first import render as render_evidence
        from deepchoice.formats.what_why_how import render

        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "e"}

        async def failing_call_model(prompt, model="x", tag="", **kwargs):
            raise RuntimeError("arbitration provider down")

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        monkeypatch.setattr(cd, "call_model", failing_call_model)

        result = await cd.ConflictDetectorAgent(gather_evidence=True).run({
            "source_scores": _sources(4), "task": {"query": "t"}, "token_usage": [],
        })

        check = result["conflict_check"]
        assert result["conflicts"] == []
        assert check["scan_outcomes"]["difference"] > 0, check
        assert check["pairs_arbitration_failed"] > 0, check
        assert cd.conflict_check_incomplete() is True, check

        # The synthesizer must be told this is unfinished, not conflict-free.
        told = _summarize_conflicts(result["conflicts"], check)
        assert "INCOMPLETE" in told, told
        assert ("unresolved potential disagreements" in told
                or "ruling was not completed" in told), told

        # And so must every renderer.
        state = {
            "task": {"query": "Kafka vs Redis"}, "evidence_chains": [],
            "conflicts": result["conflicts"], "knowledge_gaps": [],
            "final_recommendation": {}, "confidence": "low",
            "conflict_check": check,
        }
        for name, renderer in (("what_why_how", render),
                               ("comparison_matrix", render_matrix),
                               ("evidence_first", render_evidence)):
            out = renderer(state)
            assert ("did not complete" in out or "未完成" in out
                    or "not resolved" in out), f"{name} hid the failed ruling"
            assert "No significant disputes" not in out, name
            assert "No major disputes" not in out, name

    @pytest.mark.asyncio
    async def test_coverage_is_replaced_not_merged_between_runs(self, monkeypatch):
        """A second run must not inherit the first run's coverage or reason.

        The coverage record is module-level, so in a long-lived server a merged
        update would leave a stale reason or count visible to a later run.
        """
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        # Run 1: too few high-score sources, which records a specific reason.
        await cd.find_contradictions(
            [{"url": "https://only", "title": "Only source",
          "snippet": "A single source with a comparable body claim.",
              "total_score": 7.0, "scores": {"authority": 7}}], "t", usage=[])
        first = dict(cd.conflict_detector_coverage)
        assert first.get("reason") == "too_few_comparable_sources", first

        # Run 2: a different outcome that takes the conflict path and sets its own
        # fields, without the "reason" key run 1 recorded.
        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "e"}

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            return {"resolution": "a", "confidence": "high", "reasoning": "r"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        monkeypatch.setattr(cd, "call_model", fake_call_model)
        await cd.ConflictDetectorAgent(gather_evidence=False).run({
            "source_scores": _sources(4), "task": {"query": "t"}, "token_usage": [],
        })
        second = dict(cd.conflict_detector_coverage)

        assert second.get("pairs_scanned", 0) > 0, second
        assert second.get("pairs_arbitrated", 0) > 0, second
        # The first run's reason must not survive into the second record.
        assert "reason" not in second, \
            f"run 1 coverage leaked into run 2: {second}"

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
        # Consistency keeps its empty-support value; zeroing it would lower every
        # total by 0.8 against unchanged thresholds.
        assert all(row["scores"]["consistency"] == se.score_consistency([])
                   for row in rows), [row["scores"] for row in rows]

        chains = build_evidence_chain(rows, [])
        assert all(c["evidence_strength"] != "strong" for c in chains), \
            "matching titles alone produced a strong chain"

class TestClaimsComeFromBodies:
    """The saved seventh snapshot records conflict claim_a/claim_b as article
    titles (observed output). The current contract requires claims to come from
    collected bodies, and a source without a body must not supply one; this is a
    mechanism contract, not proof that every old conflict had that cause."""

    def test_a_bodyless_or_metadata_source_has_no_comparable_claim(self):
        assert cd.comparable_claim({
            "title": "Stop Leaked Secrets in Git [2026]",
            "snippet": "body text long enough to be comparable",
        }).startswith("body text")
        assert cd.comparable_claim({
            "title": "gitleaks/gitleaks",
            "snippet": "Stars: 20000, Forks: 1500, Description: secrets",
            "has_body": False,
        }) == ""
        assert cd.comparable_claim({
            "title": "Gitleaks — Official Documentation",
            "snippet": "",
            "has_body": False,
        }) == ""

    @pytest.mark.asyncio
    async def test_conflict_claims_are_body_excerpts_not_titles(self, monkeypatch):
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())
        sources = [
            {"url": "https://a", "title": "Comparison article A",
             "snippet": "Alpha measured lower latency than Beta on the test set.",
             "total_score": 8.0, "scores": {"authority": 8}},
            {"url": "https://b", "title": "Comparison article B",
             "snippet": "Beta measured higher throughput than Alpha in production.",
             "total_score": 7.0, "scores": {"authority": 7}},
        ]
        arbitration_prompts: list[str] = []

        async def fake_scan(src_a, src_b, query, usage=None):
            return {"has_difference": True, "type": "tradeoff_disagreement",
                    "explanation": "latency vs throughput"}

        async def fake_call_model(prompt, model="x", tag="", **kwargs):
            payload = "\n".join(str(m.get("content", "")) for m in prompt)
            arbitration_prompts.append(payload)
            return {"resolution": "both_partial", "confidence": "high", "reasoning": "r"}

        monkeypatch.setattr(cd, "_scan_pair_contradiction", fake_scan)
        monkeypatch.setattr(cd, "call_model", fake_call_model)
        result = await cd.ConflictDetectorAgent(gather_evidence=False).run({
            "source_scores": sources, "task": {"query": "topic"}, "token_usage": [],
        })
        assert len(result["conflicts"]) == 1
        conflict = result["conflicts"][0]
        assert conflict["claim_a"] == sources[0]["snippet"], conflict
        assert conflict["claim_b"] == sources[1]["snippet"], conflict
        assert conflict["claim_a"] != sources[0]["title"]
        # The source identity still travels separately.
        assert conflict["source_a"]["url"] == "https://a"
        assert "Title: Comparison article A" in arbitration_prompts[0]
        assert "Claim excerpt: Alpha measured lower latency" in arbitration_prompts[0]

    @pytest.mark.asyncio
    async def test_bodyless_source_is_not_arbitrated_against_a_body(self, monkeypatch):
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def forbidden_scan(src_a, src_b, query, usage=None):
            raise AssertionError("a body-less source must not be scanned as a claim")

        monkeypatch.setattr(cd, "_scan_pair_contradiction", forbidden_scan)
        result = await cd.ConflictDetectorAgent(gather_evidence=False).run({
            "source_scores": [
                {"url": "https://body", "title": "Body source",
                 "snippet": "The report states a concrete supported claim.",
                 "total_score": 8.0, "scores": {"authority": 8}},
                {"url": "https://nav", "title": "Docs page",
                 "snippet": "", "has_body": False,
                 "total_score": 6.0, "scores": {"authority": 6}},
            ],
            "task": {"query": "topic"}, "token_usage": [],
        })
        assert result["conflicts"] == []
        assert result["conflict_check"]["sources_without_comparable_claim"] == 1
        assert result["conflict_check"]["reason"] == "too_few_comparable_sources"

class TestBodylessCoverageIsVisible:
    @pytest.mark.asyncio
    async def test_early_bodyless_check_is_reported_incomplete(self, monkeypatch):
        monkeypatch.setattr(cd, "get_embedding_model", lambda: _embedding_all_similar())

        async def forbidden_scan(src_a, src_b, query, usage=None):
            raise AssertionError("body-less sources must not be scanned")

        monkeypatch.setattr(cd, "_scan_pair_contradiction", forbidden_scan)
        result = await cd.ConflictDetectorAgent(gather_evidence=False).run({
            "source_scores": [
                {"url": "https://body", "title": "Body source",
                 "snippet": "A concrete supported claim.", "total_score": 8.0,
                 "scores": {"authority": 8}},
                {"url": "https://nav", "title": "Docs page", "snippet": "",
                 "has_body": False, "total_score": 6.0, "scores": {"authority": 6}},
            ],
            "task": {"query": "topic"}, "token_usage": [],
        })
        assert result["conflicts"] == []
        assert result["conflict_check"]["sources_without_comparable_claim"] == 1
        assert result["quality_signals"][0]["conflict_check_incomplete"] is True

    def test_excluded_sources_are_told_to_the_synthesizer(self):
        from deepchoice.agents.conclusion_synthesizer import _summarize_conflicts

        text = _summarize_conflicts(
            [], {"pairs_scanned": 2,
                 "scan_outcomes": {"difference": 0, "no_difference": 2,
                                   "unscanned": 0},
                 "sources_without_comparable_claim": 2})
        assert "2 high-scoring source(s) carried no collected body" in text, text
        assert "not establish" in text, text
