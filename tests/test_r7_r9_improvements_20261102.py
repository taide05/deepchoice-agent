"""R7/R9 zero-cost improvements (2026-11-02).

R9: when a bounded evidence package must excerpt long bodies, decision-relevant
anchor windows and weighted per-source shares keep the decisive content visible
at the same total budget. Offline evidence: .scratch/cases/runs/final-200-20261031b/r9_offline_measurement_20261102.json
R7a: Elasticsearch official mapping points at its docs path instead of the bare
site root that timed out in the final-200 run.
R7b: a conditional conclusion with no primary support gets a deterministic
evidence-gap caveat (previously only the owner/secondary dominance flags did).
"""
from deepchoice.utils.decision_guard import apply_claim_support_guard
from deepchoice.utils.candidate_identity import (
    _evidence_limits,
    _source_budget_weight,
    shared_evidence_package,
)


class TestWeightedEvidenceBudget:
    def test_decisive_source_keeps_more_of_a_fixed_budget(self):
        contents = ["a" * 5000, "b" * 5000]
        equal = _evidence_limits(contents, 4000)
        weighted = _evidence_limits(contents, 4000, [1.5, 0.8])
        assert sum(weighted) <= 4000
        assert weighted[0] > equal[0] > weighted[1]

    def test_budget_is_not_increased(self):
        contents = ["x" * 3000] * 6
        limits = _evidence_limits(contents, 5000, [1.0, 1.5, 1.0, 0.8, 1.0, 1.2])
        assert sum(limits) <= 5000

    def test_small_bodies_stay_complete(self):
        contents = ["a" * 200, "b" * 9000]
        limits = _evidence_limits(contents, 2000, [1.0, 1.4])
        assert limits[0] == 200
        assert limits[1] > 0

    def test_decisive_signals_raise_the_weight(self):
        decisive = _source_budget_weight({
            "disputed": True, "source_type": "official_doc",
            "body_identity_verified": True})
        community = _source_budget_weight({
            "source_type": "stackoverflow", "provenance": "community"})
        neutral = _source_budget_weight({})
        assert decisive > neutral > community


class TestDecisionAnchorWindows:
    def test_middle_decision_caveat_survives_truncation(self):
        body = ("p" * 4000
                + " IMPORTANT: the license requires a commercial upgrade and cannot roll back"
                + "q" * 4000)
        pkg = shared_evidence_package(
            [{"number": 1, "title": "Official docs", "url": "https://x/docs",
              "snippet": body}],
            focus_terms=["unrelated-topic"], budget_chars=1400)
        view = pkg["views"][1]
        visible = view["text"]
        assert len(visible) <= 1400
        assert "cannot roll back" in visible or "commercial upgrade" in visible, visible

    def test_legacy_selection_switch_still_works(self):
        body = "a" * 5000 + " middle caveat " + "b" * 5000
        pkg = shared_evidence_package(
            [{"number": 1, "title": "docs", "url": "https://x/docs",
              "snippet": body}],
            focus_terms=["topic"], budget_chars=1200,
            prioritize=False, decision_windows=False)
        assert len(pkg["views"][1]["text"]) <= 1200
        assert pkg["budget_chars"] == 1200

    def test_full_package_is_unchanged(self):
        body = "short body with a decisive fact"
        pkg = shared_evidence_package(
            [{"number": 1, "title": "docs", "url": "https://x/docs",
              "snippet": body}])
        assert pkg["full_included"] is True
        assert pkg["views"][1]["text"] == body


class TestElasticOfficialMapping:
    def test_mapping_points_at_docs_path(self):
        from deepchoice.retrievers.official import TECH_DOCS
        assert TECH_DOCS["elasticsearch"]["url"] == "https://www.elastic.co/docs"


class TestConditionalNoPrimaryCaveat:
    def _rec(self):
        return {
            "decision_status": "conditional",
            "winner": "",
            "recommendation": "默认选 A，按条件分支决定。",
            "ranked_options": [{"name": "A", "rank": 1}, {"name": "B", "rank": 2}],
            "citation_sources": {
                "recommendation": [{
                    "source_id": "https://blog.example/a", "url": "https://blog.example/a",
                    "title": "A practitioner blog", "source_type": "web_document"}],
            },
        }

    def test_no_primary_conditional_gets_gap_caveat(self):
        adjusted, actions = apply_claim_support_guard(self._rec(), lang="zh")
        assert actions == ["conditional_no_primary_caveat"]
        assert "证据强度校准" in adjusted["recommendation"]
        assert "证据缺口型判断" in adjusted["recommendation"]
        assert adjusted["decision_guard_actions"] == ["conditional_no_primary_caveat"]

    def test_caveat_is_idempotent(self):
        adjusted, _ = apply_claim_support_guard(self._rec(), lang="zh")
        again, actions = apply_claim_support_guard(adjusted, lang="zh")
        assert again["recommendation"].count("证据强度校准") == 1
        assert actions == []
