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


def test_prompt_requires_source_independence():
    assert "SOURCE INDEPENDENCE" in SYNTHESIS_PROMPT
    assert "cannot be two independent corroborating sources" in SYNTHESIS_PROMPT


def test_prompt_forbids_inventing_specific_tool_stack():
    assert "DO NOT SPECIFY GIVEN TOOLS/STACKS" in SYNTHESIS_PROMPT
    assert "do not write a specific product" in SYNTHESIS_PROMPT.lower()


def test_prompt_requires_useful_hold():
    assert "A HOLD MUST STILL BE USEFUL" in SYNTHESIS_PROMPT
    assert "do not leave candidate sections or what empty" in SYNTHESIS_PROMPT.lower()

def test_prompt_requires_applicability_and_community_p2():
    assert "EVIDENCE APPLICABILITY" in SYNTHESIS_PROMPT
    assert "single vendor comparison page" in SYNTHESIS_PROMPT
    assert "COMMUNITY EVIDENCE IS PRACTITIONER EVIDENCE" in SYNTHESIS_PROMPT
    assert "single community post" in SYNTHESIS_PROMPT

def test_prompt_requires_omitting_irrelevant_community():
    assert "OMIT IRRELEVANT COMMUNITY MATERIAL" in SYNTHESIS_PROMPT
    assert "generic Q&A" in SYNTHESIS_PROMPT
