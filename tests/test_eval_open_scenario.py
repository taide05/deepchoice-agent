"""Open-scenario cases: Top-1 scores against an acceptable-winner set, not one name."""
from benchmarks.metrics import compute_top1_accuracy

OPEN_CASE = {
    "id": "OS-0001",
    "case_type": "open_scenario",
    "acceptable_winners": ["react", "vue", "svelte"],
}

CLOSED_CASE = {
    "id": "TC-0001",
    "tech_a": "LangGraph",
    "tech_b": "CrewAI",
    "expected_winner": "LangGraph",
}


def _runs(case_id: str, winner: str) -> list[dict]:
    return [{
        "case_id": case_id,
        "report": f"# Report\n\n**Winner: {winner}**\n\nRationale here.",
        "state": {},
    }]


class TestOpenScenarioTop1:
    def test_winner_in_acceptable_set_is_correct(self):
        result = compute_top1_accuracy(_runs("OS-0001", "Vue"), [OPEN_CASE])
        assert result["correct"] == 1 and result["total"] == 1

    def test_winner_outside_set_is_incorrect(self):
        result = compute_top1_accuracy(_runs("OS-0001", "Rust"), [OPEN_CASE])
        assert result["correct"] == 0 and result["total"] == 1

    def test_closed_case_unaffected(self):
        result = compute_top1_accuracy(_runs("TC-0001", "LangGraph"), [CLOSED_CASE])
        assert result["correct"] == 1 and result["total"] == 1


class TestWinnerExtractionParens:
    """Regression: '**Winner: Firebase Cloud Messaging (FCM)**' — parenthesized
    suffixes broke the Winner regex (second bug in this pattern family),
    producing predicted=None for OS-0042 and garbage for OS-0048."""

    def test_winner_with_paren_suffix_extracts(self):
        from benchmarks.metrics import extract_top_recommendation
        pred = extract_top_recommendation(
            "# R\n\n**Winner: Firebase Cloud Messaging (FCM)**\n\nrationale")
        assert pred and "firebase" in pred

    def test_winner_with_paren_suffix_counts_correct(self):
        case = {"id": "OS-0042", "case_type": "open_scenario",
                "acceptable_winners": ["firebase", "fcm", "onesignal"]}
        result = compute_top1_accuracy(
            _runs("OS-0042", "Firebase Cloud Messaging (FCM)"), [case])
        assert result["correct"] == 1 and result["total"] == 1
