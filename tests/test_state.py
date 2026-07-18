from deepchoice.state import ResearchState


class TestResearchState:
    def test_empty_state_has_all_fields(self):
        state = ResearchState(
            task={},
            sub_questions=[],
            search_results=[],
            source_scores=[],
            conflicts=[],
            evidence_chains=[],
            report="",
            confidence="",
            knowledge_gaps=[],
            retry_count=0,
            partial_failures=[],
            current_phase="",
        )
        assert len(state) == 12
        assert state["retry_count"] == 0
