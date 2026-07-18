import json
import tempfile
import pytest
from pathlib import Path
from deepchoice.state import ResearchState
from deepchoice.task import TaskConfig, load_task


class TestTaskConfig:
    def test_defaults(self):
        tc = TaskConfig(query="test query")
        assert tc.scene_context == "team"
        assert tc.constraints == []
        assert tc.report_format == "what_why_how"

    def test_invalid_scene_raises(self):
        with pytest.raises(ValueError, match="scene_context"):
            TaskConfig(query="test", scene_context="invalid")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="report_format"):
            TaskConfig(query="test", report_format="invalid")

    def test_load_task_from_file(self):
        data = {
            "query": "FastAPI vs Flask",
            "scene_context": "solo",
            "constraints": ["python", "async"],
            "report_format": "evidence_first",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            tc = load_task(path)
            assert tc.query == "FastAPI vs Flask"
            assert tc.scene_context == "solo"
            assert tc.report_format == "evidence_first"
        finally:
            Path(path).unlink()


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
