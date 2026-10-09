"""Original saved context is ephemeral and never extends citable coordinates."""
from copy import deepcopy
import json

import pytest

from deepchoice.utils import fact_selection
from deepchoice.utils.evidence_choices import bind_evidence_choices
from deepchoice.utils.question_packet import basis_reference_packet, bind_question_rows


ACTOR = "Boreal version 2 requires an independently administered durable store."
TAIL = "This section applies only to version 2, not to version 1."
TEXT = ACTOR + " " + " ".join(
    f"Administration section {i} describes retained configuration and recovery responsibilities."
    for i in range(15)
) + " " + TAIL


def fixture():
    chains = [{"evidence_strength": "moderate", "sources": [{
        "title": "Atlas and Boreal comparison", "url": "https://docs.example/compare",
        "snippet": TEXT,
    }]}]
    facts = bind_evidence_choices({"source_facts": [{
        "id": "F1", "evidence_id": 1, "source_ranges": [[8, 10]],
    }]}, chains, ["Atlas", "Boreal"], [])["source_facts"]
    assert len(facts) == 1 and ACTOR not in facts[0]["saved_text"]
    return chains, facts


def contexts(facts, chains):
    from deepchoice.utils.fact_selection import original_fact_contexts
    return original_fact_contexts(facts, chains)


def test_judgment_sees_distant_subject_and_qualifier_without_new_references():
    chains, facts = fixture()
    before = deepcopy((chains, facts))
    old_packet, old_refs = basis_reference_packet(facts, ["Atlas", "Boreal"])
    packet, refs = basis_reference_packet(facts, ["Atlas", "Boreal"], evidence_chains=chains)
    assert ACTOR not in old_packet and TAIL not in old_packet
    assert ACTOR in packet and TAIL in packet
    assert refs == old_refs
    assert all(ACTOR not in b["source_sentences"] and TAIL not in b["source_sentences"]
               for b in refs.values())
    row = {"kind": "answer", "option": "", "question_id": "R0",
           "basis_refs": ["B99999"], "reasoning": "Context alone is not new evidence.",
           "assumptions": [], "change_condition": "Recheck the source."}
    assert not bind_question_rows([row], {"R0"}, refs, diagnostics={})
    assert (chains, facts) == before


@pytest.mark.parametrize("field,value", [
    ("id", "not-a-fact"), ("evidence_id", True), ("evidence_id", 2),
    ("source_title", "Other guide"), ("canonical_url", "https://other.example/docs"),
    ("saved_text", "Forged saved text."), ("text", "Forged attributed text."),
    ("saved_passages", ["Forged saved passage."]), ("source_ranges", [[0, 2]]),
])
def test_forged_fact_never_receives_original_context(field, value):
    chains, facts = fixture()
    facts[0][field] = value
    assert contexts(facts, chains) == {}


def test_source_mutation_and_ambiguous_identity_are_rejected():
    chains, facts = fixture()
    chains[0]["sources"][0]["url"] = "https://other.example/docs"
    assert contexts(facts, chains) == {}
    chains, facts = fixture()
    other = deepcopy(chains[0])
    other["sources"][0]["url"] = "https://other.example/ambiguous"
    chains.append(other)
    assert contexts(facts, chains) == {}
    chains, facts = fixture()
    chains[0]["sources"][0]["snippet"] = "not a complete original source"
    assert contexts(facts, chains) == {}


def test_context_limit_counts_serialized_identity_unicode_and_never_truncates(monkeypatch):
    chains, facts = fixture()
    context = contexts(facts, chains)
    assert context == {"F1": " ".join(TEXT.split())}
    serialized = json.dumps({"original_saved_contexts": context}, ensure_ascii=False)
    size = len(serialized.encode("utf-8"))
    monkeypatch.setattr(fact_selection, "MAX_PACKET_BYTES", size)
    assert contexts(facts, chains) == context
    monkeypatch.setattr(fact_selection, "MAX_PACKET_BYTES", size - 1)
    assert contexts(facts, chains) == {}
    chains[0]["sources"][0]["snippet"] += " 完整限定必须保留。"
    # Source tail mutations outside the crop may add challenges, never change refs.
    monkeypatch.setattr(fact_selection, "MAX_PACKET_BYTES", 24000)
    context = contexts(facts, chains)
    assert context["F1"].endswith("完整限定必须保留。")
    size = len(json.dumps({"original_saved_contexts": context}, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(fact_selection, "MAX_PACKET_BYTES", size - 1)
    assert contexts(facts, chains) == {}


def test_oversized_original_and_whole_facts_do_not_create_redundant_context():
    chains, facts = fixture()
    chains[0]["sources"][0]["snippet"] += " " + "X" * 2001
    assert contexts(facts, chains) == {}
    chains = [{"sources": [{"title": "Atlas guide", "url": "https://docs.example/atlas",
                            "snippet": "Atlas retains records. Configuration affects retention."}]}]
    facts = bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]},
                                 chains, ["Atlas"], [])["source_facts"]
    assert contexts(facts, chains) == {}
    assert contexts(facts * 6, chains) == {}


def test_auxiliary_context_is_runtime_rebuilt_not_fact_authored():
    chains, facts = fixture()
    facts[0]["original_saved_contexts"] = {"F1": "Atlas guarantees recovery."}
    facts[0]["status"] = "verified"
    assert contexts(facts, chains) == {"F1": " ".join(TEXT.split())}
    assert contexts(facts + facts, chains) == {}


def review_state(rec, task, chains):
    from deepchoice.citations.contracts import CITATION_POLICY_VERSION
    from deepchoice.citations.verifier import _split_sentences
    from deepchoice.utils.decision_analysis import calibrate_decision_analysis

    checks = []
    for i, fact in enumerate(rec["source_facts"]):
        fact["status"] = "verified"
        checks.extend({"claim_id": f"source-{i}-{j}",
                       "claim_path": f"final_recommendation.source_facts[{i}].text",
                       "claim_text": sentence, "source_title": fact["source_title"],
                       "canonical_url": fact["canonical_url"],
                       "status": "verified", "reason": "lexical_support"}
                      for j, sentence in enumerate(_split_sentences(fact["saved_text"])))
    return {"task": task, "evidence_chains": chains,
            "final_recommendation": calibrate_decision_analysis(rec),
            "citation_verification": {"schema_version": 1, "policy_version": CITATION_POLICY_VERSION,
                                      "status_counts": {"verified": len(checks)}, "checks": checks}}


async def test_existing_synthesis_and_review_calls_receive_context_without_public_container(monkeypatch):
    from unittest.mock import AsyncMock
    from deepchoice.agents import conclusion_synthesizer as synth, self_reviewer
    from deepchoice.contracts.manifest import build_run_manifest
    from deepchoice.utils.fact_selection import selection_view_packet
    from deepchoice.agents.report_generator import FORMAT_RENDERERS

    chains, _ = fixture()
    _, menu = selection_view_packet(chains, ["Atlas", "Boreal"])
    view = next(key for key, value in menu.items()
                if value["reference"].get("source_ranges") == [[8, 10]])
    task = {"query": "Compare the administration responsibilities of Atlas and Boreal.",
            "candidate_techs": ["Atlas", "Boreal"], "constraints": [], "sub_questions": []}
    model = AsyncMock(side_effect=[{"source_view_ids": [view]}, {"decision_analysis": [{
        "kind": "answer", "option": "", "question_id": "R0", "basis_refs": ["B1"],
        "reasoning": "Administration responsibilities need configuration evidence; applicability remains unresolved.",
        "assumptions": [], "change_condition": "Reassess when the applicable version is known."}]}])
    monkeypatch.setattr(synth, "call_model", model)
    update = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(
        {"task": task, "evidence_chains": chains})
    assert model.await_count == 2
    judgment = model.await_args_list[1].args[0][0]["content"]
    assert ACTOR in judgment and TAIL in judgment
    state = review_state(update["final_recommendation"], task, chains)
    assert len(state["final_recommendation"]["decision_analysis"]) == 1
    review_calls = []

    async def reviewer(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        review_calls.append(payload)
        assert payload["original_saved_contexts"] == {"F1": " ".join(TEXT.split())}
        assert ACTOR not in payload["complete_saved_sources"][0]["saved_text"]
        return {"checks": [{"item": n, "passed": True} for n in range(1, 7)],
                "confidence": "low", "analysis_reviews": [{"analysis_id": "A1", "action": "keep",
                    "source_checks": [["F1", "supports", [1]]]}]}

    monkeypatch.setattr(self_reviewer, "call_model", reviewer)
    reviewed = await self_reviewer.SelfReviewerAgent().run(state)
    assert len(review_calls) == 1
    assert len(reviewed["final_recommendation"]["decision_analysis"]) == 1
    assert "original_saved_contexts" not in json.dumps(update)
    assert "original_saved_contexts" not in json.dumps(reviewed)
    state.update(reviewed)
    for renderer in FORMAT_RENDERERS.values():
        assert ACTOR not in renderer(state) and "original_saved_contexts" not in renderer(state)


@pytest.mark.parametrize("repair", [False, True])
async def test_review_repair_inherits_context_but_never_accepts_context_coordinates(monkeypatch, repair):
    from deepchoice.agents import self_reviewer
    from deepchoice.utils.decision_analysis import bind_decision_analysis
    from deepchoice.utils.analysis_review import prepare_analysis_review, apply_analysis_review

    chains, facts = fixture()
    task = {"query": "Compare the administration duties.", "candidate_techs": ["Atlas", "Boreal"]}
    rec = bind_decision_analysis({"source_facts": facts, "decision_analysis": [{
        "kind": "answer", "option": "", "requirement_ids": ["R0"],
        "basis": [{"fact_id": "F1", "sentence_ids": [1]}],
        "reasoning": "The saved administration requirements need applicability checks.",
        "assumptions": [], "change_condition": "Recheck the version."}]}, [], task["candidate_techs"], task["query"], require_basis=True)
    state = review_state(rec, task, chains)
    context = prepare_analysis_review(state)
    rejected, _ = apply_analysis_review(context, {"analysis_reviews": [{
        "analysis_id": "A1", "action": "keep", "source_checks": [["F1", "supports", [17]]]}]})
    assert rejected["decision_analysis"] == []
    calls = []

    async def model(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        calls.append(payload["original_saved_contexts"])
        if repair and len(calls) == 1:
            return {"analysis_reviews": []}
        return {"analysis_reviews": [{"analysis_id": "A1", "action": "keep",
                                      "source_checks": [["F1", "supports", [1]]]}]}

    monkeypatch.setattr(self_reviewer, "call_model", model)
    result = await self_reviewer.SelfReviewerAgent().run(state)
    assert calls == [{"F1": " ".join(TEXT.split())}] * (2 if repair else 1)
    assert result["final_recommendation"]["decision_analysis"]
    assert result["quality_signals"][0]["targeted_review_attempts"] == int(repair)


def test_additional_basis_cannot_address_original_context_outside_fact_sentences():
    from deepchoice.utils.decision_analysis import bind_decision_analysis
    from deepchoice.utils.analysis_review import prepare_analysis_review, apply_analysis_review

    chains, facts = fixture()
    facts.append({**deepcopy(facts[0]), "id": "F2"})
    task = {"query": "Compare administration duties.", "candidate_techs": ["Atlas", "Boreal"]}
    rec = bind_decision_analysis({"source_facts": facts, "decision_analysis": [{
        "kind": "answer", "option": "", "requirement_ids": ["R0"],
        "basis": [{"fact_id": "F1", "sentence_ids": [1]}],
        "reasoning": "Administration requirements need applicability checks.",
        "assumptions": [], "change_condition": "Recheck the version."}]},
        [], task["candidate_techs"], task["query"], require_basis=True)
    context = prepare_analysis_review(review_state(rec, task, chains))
    assert context.source_contexts["F2"] == " ".join(TEXT.split())
    row = {"analysis_id": "A1", "action": "revise",
           "reasoning": "Administration requirements depend on the applicable configuration.",
           "assumptions": [], "change_condition": "Recheck the applicable version.",
           "source_checks": [["F1", "supports", [1]], ["F2", "qualifies", [1]]],
           "additional_basis": [{"fact_id": "F2", "sentence_ids": [1]}]}
    accepted, _ = apply_analysis_review(context, {"analysis_reviews": [row]})
    assert len(accepted["decision_analysis"]) == 1
    assert accepted["decision_analysis"][0]["fact_ids"] == ["F1", "F2"]
    row["additional_basis"][0]["sentence_ids"] = [1, 17]
    rejected, _ = apply_analysis_review(context, {"analysis_reviews": [row]})
    assert rejected["decision_analysis"] == []
