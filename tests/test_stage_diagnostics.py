"""Evidence-flow diagnostics never persist prose or alter graph decisions."""
import json
from copy import deepcopy

import pytest

from deepchoice.utils.stage_diagnostics import node_stage_counts, public_stage_counts


def test_stage_allowlist_drops_private_content_and_invalid_counts():
    result = {"quality_signals": [
        {"agent": "self_reviewer", "analysis_review": {"retained": 99}},
        {"agent": "conclusion_synthesizer", "source_facts_received": True,
         "source_facts_bound": 2, "staged_generation": {
             "facts_received": 3, "rows_received": 4, "rows_selected": 2,
             "rows_rejected_question": 1, "rows_rejected_shape": 1,
             "provider_errors": -1, "judgment_calls": "1",
             "questions_planned": 10001, "r0_withheld_one_sided": False,
             "raw": "PRIVATE prompt"},
         "analysis_binding": {"received": 2, "retained": 1,
                              "rejected": {"prose_reference": 1, "PRIVATE error": 1}},
         "structure_correction": {"raw": "PRIVATE response"}}],
        "final_recommendation": {"decision_analysis": [{"reasoning": "PRIVATE analysis"}]}}
    before = deepcopy(result)
    counts = node_stage_counts("conclusion_synthesizer", result)
    assert counts == {
        "source_facts_bound": 2, "facts_received": 3, "rows_received": 4,
        "rows_selected": 2, "rows_rejected_question": 1, "rows_rejected_shape": 1,
        "analyses_received": 2, "analyses_bound": 1,
        "binding_rejected_prose_reference": 1, "analyses_returned": 1,
    }
    assert result == before
    stored = json.dumps({"stage_counts": {**counts, "PRIVATE key": 100}, "raw": "PRIVATE body"})
    assert public_stage_counts("conclusion_synthesizer", stored) == counts
    assert "PRIVATE" not in json.dumps(counts)


@pytest.mark.parametrize("value", [
    "{}", "[]", "invalid", '{"stage_counts":null}',
    '{"stage_counts":{"rows_received":true}}',
    '{"stage_counts":{"rows_received":1,"rows_received":2}}',
    " " * 16385,
])
def test_missing_malformed_historical_counts_remain_unknown(value):
    assert public_stage_counts("conclusion_synthesizer", value) is None


def test_stage_names_do_not_authorize_other_nodes_counters():
    stored = '{"stage_counts":{"rows_received":3,"retained":0}}'
    assert public_stage_counts("self_reviewer", stored) == {"retained": 0}
    assert public_stage_counts("unknown", stored) is None
    assert node_stage_counts("citation_validator", {"quality_signals": None}) is None
