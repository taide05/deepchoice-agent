"""Tests for the structural claim-support guard."""
from deepchoice.utils.decision_guard import apply_claim_support_guard


def _recommended_rec(owner="A", n_options=2):
    options = [{"name": "A", "rank": 1}, {"name": "B", "rank": 2}]
    if n_options == 1:
        options = options[:1]
    return {
        "decision_status": "recommended",
        "winner": "A",
        "recommendation": "推荐 A。",
        "ranked_options": options,
        "citation_sources": {
            "recommendation": [
                {"source_id": f"https://docs.{owner.lower()}.com/{i}",
                 "url": f"https://docs.{owner.lower()}.com/{i}",
                 "title": f"{owner} docs {i}", "source_type": "official_doc",
                 "source_owner": owner}
                for i in range(2)
            ],
            "winner_rationale": [
                {"source_id": f"https://docs.{owner.lower()}.com/0",
                 "url": f"https://docs.{owner.lower()}.com/0",
                 "title": f"{owner} docs", "source_type": "official_doc",
                 "source_owner": owner},
            ],
        },
    }


def test_recommended_owner_dominance_downgrades_to_conditional():
    adjusted, actions = apply_claim_support_guard(_recommended_rec(), lang="zh")
    assert adjusted["decision_status"] == "conditional"
    assert adjusted["winner"] == ""
    assert actions == ["recommended_to_conditional"]
    assert "证据强度校准" in adjusted["recommendation"]
    assert len(adjusted["ranked_options"]) == 2


def test_recommended_with_one_option_downgrades_to_hold():
    adjusted, actions = apply_claim_support_guard(
        _recommended_rec(n_options=1), lang="zh")
    assert adjusted["decision_status"] == "insufficient_evidence"
    assert adjusted["winner"] == ""
    assert actions == ["recommended_to_insufficient_evidence"]


def test_conditional_top_option_flag_adds_strength_caveat():
    rec = {
        "decision_status": "conditional",
        "recommendation": "默认选 A。",
        "ranked_options": [{"name": "A", "rank": 1}, {"name": "B", "rank": 2}],
        "citation_sources": {
            "recommendation": [
                {"source_id": "https://buildkite.com/a", "url": "https://buildkite.com/a",
                 "title": "Buildkite comparison", "source_type": "official_doc",
                 "source_owner": "A", "has_body": True},
                {"source_id": "https://buildkite.com/b", "url": "https://buildkite.com/b",
                 "title": "Buildkite docs", "source_type": "official_doc",
                 "source_owner": "A", "has_body": True},
            ],
        },
    }
    adjusted, actions = apply_claim_support_guard(rec, lang="zh")
    assert adjusted["decision_status"] == "conditional"
    assert actions == ["conditional_top_option_strength_caveat"]
    assert "证据强度校准" in adjusted["recommendation"]


def test_guard_is_idempotent():
    adjusted, _ = apply_claim_support_guard(_recommended_rec(), lang="zh")
    again, actions = apply_claim_support_guard(adjusted, lang="zh")
    assert again["recommendation"].count("证据强度校准") == 1
    assert actions == []
