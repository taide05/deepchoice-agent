"""The synthesis prompt must stay decision-first, not official-source maximization."""
from deepchoice.agents.conclusion_synthesizer import SYNTHESIS_PROMPT


def test_evidence_calibration_and_decision_first_rules_are_present():
    assert "EVIDENCE CALIBRATION" in SYNTHESIS_PROMPT
    assert "not the only valid evidence" in SYNTHESIS_PROMPT
    assert "DECISION-FIRST" in SYNTHESIS_PROMPT
    assert "documentation summary" in SYNTHESIS_PROMPT


def test_prompt_no_longer_uses_official_primary_monopoly_rule():
    assert "PRIMARY-EVIDENCE DISCIPLINE" not in SYNTHESIS_PROMPT
    # A secondary source may be decisive when labelled and specific; the prompt must
    # not tell the model to withhold a decision merely because no official page exists.
    assert "do not reject an otherwise answerable decision" in SYNTHESIS_PROMPT.lower()


def test_prompt_forbids_inventing_scenario_context():
    assert "GIVEN CONTEXT IS CLOSED" in SYNTHESIS_PROMPT
    assert "do not invent scenario facts" in SYNTHESIS_PROMPT.lower()
    assert "do not assume the team already runs one of the candidates" in SYNTHESIS_PROMPT.lower()
