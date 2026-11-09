"""D1: narrow recovery of conditional answers whose options were malformed.

The model may emit a substantive conditional recommendation with a bad
`ranked_options` structure or version/tier labels ("MySQL 8.0"). The contract keeps
`invalid` for genuinely malformed answers, but recovers only a model-declared
conditional whose own branch text names at least two declared candidates.
"""
from deepchoice.agents.conclusion_synthesizer import normalize_decision
from deepchoice.utils.decision import CONDITIONAL, INSUFFICIENT, INVALID


BASE = {
    "decision_status": "conditional",
    "winner": "",
    "winner_rationale": "branches",
    "recommendation": "分支 A（默认）：选 Alpha；分支 B：平台受限时选 Beta。",
    "unresolved_questions": ["容量数据"],
}


def test_malformed_options_are_recovered_from_branch_text():
    rec = normalize_decision({**BASE, "ranked_options": None},
                             declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == CONDITIONAL
    assert rec["winner"] == ""
    assert [option["name"] for option in rec["ranked_options"]] == ["Alpha", "Beta"]
    assert "recovered" in rec["decision_validation_recovered"]


def test_version_suffix_options_are_recovered_with_declared_names():
    rec = normalize_decision({
        **BASE,
        "recommendation": "分支 A：选 MySQL 8.0 作为默认；分支 B：旧代码兼容优先时选 MariaDB 11。",
        "ranked_options": [{"name": "MySQL 8.0"}, {"name": "MariaDB 11"}],
    }, declared_candidates=["MariaDB", "MySQL"])
    assert rec["decision_status"] == CONDITIONAL
    assert {option["name"] for option in rec["ranked_options"]} == {"MariaDB", "MySQL"}


def test_zero_options_are_recovered_from_branch_text():
    rec = normalize_decision({**BASE, "ranked_options": []},
                             declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == CONDITIONAL
    assert len(rec["ranked_options"]) == 2


def test_branch_text_without_candidates_stays_invalid():
    rec = normalize_decision({
        **BASE,
        "recommendation": "分支 A（默认）与分支 B 见下。",
        "ranked_options": None,
    }, declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == INVALID
    assert rec["ranked_options"] == []


def test_branch_text_naming_one_candidate_stays_invalid():
    rec = normalize_decision({
        **BASE,
        "recommendation": "分支 A（默认）：选 Alpha；分支 B：继续评估。",
        "ranked_options": None,
    }, declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == INVALID


def test_branchless_malformed_answer_stays_invalid():
    rec = normalize_decision({
        "decision_status": "conditional", "winner": "",
        "winner_rationale": "basis", "recommendation": "Adopt it.",
        "ranked_options": None, "unresolved_questions": ["gap"],
    }, declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == INVALID


def test_insufficient_holding_plan_is_not_promoted():
    rec = normalize_decision({
        "decision_status": "insufficient_evidence", "winner": "",
        "winner_rationale": "关键审计字段缺失",
        "recommendation": "暂缓定选；分支 A：若补齐审计证据则选 Alpha，分支 B 则选 Beta。",
        "ranked_options": [], "unresolved_questions": ["审计证据"],
    }, declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == INSUFFICIENT


def test_recommended_winner_variant_stays_invalid():
    rec = normalize_decision({
        "decision_status": "recommended", "winner": "Alpha Cloud",
        "winner_rationale": "basis", "recommendation": "Adopt Alpha Cloud.",
        "ranked_options": [{"name": "Alpha"}, {"name": "Beta"}],
        "unresolved_questions": [],
    }, declared_candidates=["Alpha", "Beta"])
    assert rec["decision_status"] == INVALID
