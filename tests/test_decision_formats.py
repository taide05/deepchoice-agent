from deepchoice.formats.comparison_matrix import render as render_comparison
from deepchoice.formats.evidence_first import render as render_evidence
from deepchoice.formats.what_why_how import render as render_what


def _state(query: str, recommendation: dict) -> dict:
    return {
        "task": {"query": query, "candidate_techs": ["SQLite", "PostgreSQL"]},
        "evidence_chains": [],
        "conflicts": [],
        "knowledge_gaps": [],
        "final_recommendation": recommendation,
    }


def _recommendation(winner: str = "SQLite") -> dict:
    return {
        "winner": winner,
        "winner_rationale": "Fits the stated constraints.",
        "recommendation": "Choose conditionally.",
        "confidence": "medium",
        "ranked_options": [{"rank": 1, "name": "SQLite", "rationale": "Local deployment"}],
        "requirement_assessments": [
            {
                "id": "C1",
                "requirement": "Local deployment",
                "status": "satisfied",
                "decision_critical": True,
                "explanation": "The option runs in-process.",
                "evidence_ids": ["E1"],
            },
            {
                "id": "C2",
                "requirement": "Concurrent writes",
                "status": "unknown",
                "decision_critical": True,
                "explanation": "Measure the workload first.",
                "evidence_ids": [],
            },
        ],
        "decision_branches": [
            {"option": "SQLite", "condition": "If writes remain local and bounded."},
            {"option": "PostgreSQL", "condition": "If concurrent writes exceed the threshold."},
        ],
        "action_plan": [
            {
                "step": "Measure concurrent writes",
                "verification": "Record p95 latency and lock waits.",
                "change_trigger": "p95 exceeds 100 ms.",
                "rollback": "Keep SQLite and restore the prior backup.",
            }
        ],
    }


def test_all_formats_show_requirements_unknown_branches_and_action_plan_in_english():
    for render in (render_what, render_evidence, render_comparison):
        report = render(_state("Choose a database", _recommendation()))
        assert "Requirement Assessments" in report
        assert "Unknown" in report and "Concurrent writes" in report
        assert "Decision Branches" in report
        assert "Action Plan" in report
        assert "verification:" in report
        assert "change trigger:" in report
        assert "rollback:" in report
        assert "C1" not in report and "E1" not in report


def test_all_formats_show_chinese_details_and_unknown_next_to_requirement():
    recommendation = _recommendation()
    recommendation["requirement_assessments"][0]["status"] = "unknown"
    for render in (render_what, render_evidence, render_comparison):
        report = render(_state("选择数据库", recommendation))
        assert "逐项需求判断" in report
        assert "未知" in report and "Local deployment" in report
        assert "条件分支" in report
        assert "行动计划" in report
        assert "验证：" in report and "变更触发：" in report and "回退：" in report


def test_context_dependent_hides_ranking_and_default_trial_prompt():
    recommendation = _recommendation("context_dependent")
    recommendation["ranked_options"] = []
    for render in (render_what, render_evidence, render_comparison):
        report = render(_state("Choose a database", recommendation))
        assert "No single winner" in report
        assert "#1" not in report
        assert "Ranked Options" not in report and "Ranking" not in report
        assert "recommended option" not in report.lower()


def test_optional_decision_lists_are_tolerant_and_bounded():
    recommendation = _recommendation()
    recommendation["requirement_assessments"] = None
    recommendation["decision_branches"] = "invalid"
    recommendation["action_plan"] = [None, {"step": "Keep it bounded"}]
    for render in (render_what, render_evidence, render_comparison):
        report = render(_state("Choose a database", recommendation))
        assert "Keep it bounded" in report
        assert "Decision Branches" not in report


def test_normal_winner_keeps_existing_ranked_output_and_conditional_next_step():
    for render in (render_what, render_evidence, render_comparison):
        report = render(_state("Choose a database", _recommendation()))
        assert "Winner: SQLite" in report
    for render in (render_what, render_comparison):
        report = render(_state("Choose a database", _recommendation()))
        assert "#1 SQLite" in report
    for render in (render_evidence, render_comparison):
        report = render(_state("Choose a database", _recommendation()))
        assert "recommended option" in report.lower()
