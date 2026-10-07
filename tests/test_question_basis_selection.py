"""Runtime references preserve original quotes without granting answer authority."""
from copy import deepcopy

import pytest

from deepchoice.utils.decision_analysis import bind_decision_analysis
from deepchoice.utils.question_packet import basis_reference_packet, bind_question_rows


FACTS = [
    {"id": "F1", "source_title": "Alpha guide", "saved_text":
     "Alpha requires a separate durable store. Without it, recovery is not guaranteed."},
    {"id": "F2", "source_title": "Beta guide", "saved_text":
     "Beta supports resumable reads. Consumers must preserve their position."},
]


def row(question="R0", refs=None):
    return {"question_id": question, "basis_refs": ["B1", "B2"] if refs is None else refs,
            "kind": "answer", "option": "", "reasoning": "Recovery depends on the durable store.",
            "assumptions": [], "change_condition": "Reconsider if the store is unavailable."}


def test_refs_copy_full_original_qualifiers_and_cannot_claim_constraint_coverage():
    packet, offered = basis_reference_packet(FACTS, ["Alpha", "Beta"])
    assert "B1: Alpha requires a separate durable store." in packet
    assert "B2: Without it, recovery is not guaranteed." in packet
    forged = {**row(), "requirement_ids": ["C99"], "basis": [{"fact_id": "FORGED"}],
              "source_sentences": ["Recovery is guaranteed."], "winner": "Alpha"}
    rows = bind_question_rows([forged], {"R0", "Q1"}, offered, diagnostics={})
    assert rows[0]["requirement_ids"] == ["R0"]
    assert rows[0]["basis"] == [{"fact_id": "F1", "sentence_ids": [1, 2], "source_sentences":
                                ["Alpha requires a separate durable store.",
                                 "Without it, recovery is not guaranteed."]}]
    assert not {"question_id", "basis_refs", "winner", "source_sentences"} & rows[0].keys()
    requirements = [{"id": f"C{i}", "kind": "frozen_constraint", "requirement": f"Condition {i}"}
                    for i in range(1, 5)]
    bound = bind_decision_analysis({"source_facts": FACTS, "decision_analysis": rows},
                                  requirements, ["Alpha", "Beta"], "Choose under four conditions",
                                  require_basis=True)
    assert bound["decision_analysis"][0]["requirements"] == ["Choose under four conditions"]
    assert bound["decision_analysis"][0]["basis"] == rows[0]["basis"]


@pytest.mark.parametrize("refs", [[], ["B0"], ["F1S1"], ["B1", "B1"],
                                  ["B1", "B99"], [1], [True], "B1", ["B1"] * 13])
def test_bad_reference_never_donates_a_partial_basis_or_guesses_coordinates(refs):
    _, offered = basis_reference_packet(FACTS, ["Alpha", "Beta"])
    assert bind_question_rows([row(refs=refs)], {"R0"}, offered, diagnostics={}) == []


def test_refs_preserve_separate_locations_and_reject_stale_source_text():
    facts = deepcopy(FACTS)
    facts[0]["saved_passages"] = ["Alpha requires a separate durable store.",
                                  "Without it, recovery is not guaranteed."]
    packet, offered = basis_reference_packet(facts, ["Alpha", "Beta"])
    assert packet.index("Passage 1/2") < packet.index("B1:") < packet.index("Passage 2/2") < packet.index("B2:")
    rows = bind_question_rows([row()], {"R0"}, offered, diagnostics={})
    facts[0]["saved_text"] = "Alpha guarantees recovery. No separate store is required."
    diagnostics = {}
    bound = bind_decision_analysis({"source_facts": facts, "decision_analysis": rows}, [],
                                  ["Alpha", "Beta"], "Compare", diagnostics=diagnostics,
                                  require_basis=True)
    assert bound["decision_analysis"] == []
    assert diagnostics["rejected"] == {"basis_source_sentences_mismatch": 1}


def test_model_cannot_target_a_constraint_or_create_a_subquestion_choice():
    _, offered = basis_reference_packet(FACTS, ["Alpha", "Beta"])
    for question in ("C1", "Q9", {"not": "an ID"}):
        assert bind_question_rows([row(question)], {"R0", "Q1"}, offered, diagnostics={}) == []
    choice = {**row("Q1"), "kind": "choice", "option": "Alpha"}
    assert bind_question_rows([choice], {"R0", "Q1"}, offered, diagnostics={}) == []
    assert bind_question_rows([row(), row()], {"R0", "Q1"}, offered, diagnostics={}) == [
        bind_question_rows([row()], {"R0"}, offered, diagnostics={})[0]]


def test_original_fact_and_sentence_bounds_apply_to_reference_groups():
    facts = [{"id": f"F{i}", "source_title": f"Guide {i}", "saved_text":
              "First qualified statement. Second qualified statement. Third qualified statement. Fourth qualified statement."}
             for i in range(1, 6)]
    _, offered = basis_reference_packet(facts, [])
    assert bind_question_rows([row(refs=["B1", "B2", "B3", "B4"])], {"R0"}, offered, diagnostics={}) == []
    assert bind_question_rows([row(refs=["B1", "B5", "B9", "B13", "B17"])], {"R0"}, offered, diagnostics={}) == []
    legal = [f"B{i}" for i in (1, 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15)]
    rows = bind_question_rows([row(refs=legal)], {"R0"}, offered, diagnostics={})
    assert len(rows[0]["basis"]) == 4
    assert all(len(b["sentence_ids"]) == 3 for b in rows[0]["basis"])


def test_ambiguous_duplicate_fact_ids_are_not_offered():
    assert basis_reference_packet([FACTS[0], {**FACTS[1], "id": "F1"}], ["Alpha", "Beta"])[1] == {}


def test_passage_and_binding_sentence_policy_mismatch_offers_no_reference(monkeypatch):
    from deepchoice.citations import verifier
    fact = {**FACTS[0], "saved_passages": ["Alpha requires a separate durable store.",
                                           "Without it, recovery is not guaranteed."]}
    original = verifier._split_sentences
    monkeypatch.setattr(verifier, "_split_sentences", lambda text:
                        [text] if text == fact["saved_text"] else original(text))
    assert basis_reference_packet([fact], ["Alpha"])[1] == {}


def test_duplicate_question_cannot_replace_an_invalid_first_basis():
    _, offered = basis_reference_packet(FACTS, ["Alpha", "Beta"])
    diagnostic = {}
    assert bind_question_rows([row(refs=["B0"]), row()], {"R0", "Q1"}, offered,
                              diagnostics=diagnostic) == []
    assert diagnostic["rows_rejected_shape"] == 1
    assert diagnostic["rows_rejected_question"] == 1
