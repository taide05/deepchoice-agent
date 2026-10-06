"""Saved-source range contracts; all pages/models are synthetic and offline."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.citations.source_windows import SourceDocument, locate_source_window
from deepchoice.citations.verifier import verify_citations
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.utils.analysis_review import prepare_analysis_review
from deepchoice.utils.call_diagnostics import output_shape_valid
from deepchoice.utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices
from deepchoice.utils.fact_selection import selection_packet, selection_sentences, selected_passages


MECHANISM = "Alpha stores records in a retained log. Consumers can replay those records while retention permits."
TAIL = "The retention policy can be configured by administrators. " + " ".join(f"Documentation section {i} describes administration procedures and configuration options." for i in range(14))
TEXT = MECHANISM + " " + TAIL
TASK = {"query": "How can Alpha consumers replay records?", "candidate_techs": ["Alpha"]}


def chains(text=TEXT):
    return [{"evidence_strength": "moderate", "sources": [{"title": "Alpha guide",
        "url": "https://alpha.example/guide", "snippet": text, "score": 7}]}]


def refs(ranges=None):
    return {"source_facts": [{"id": "F1", "evidence_id": 1,
            "source_ranges": [[0, 2]] if ranges is None else ranges}]}


def model_answer():
    return {"decision_analysis": [{"kind": "answer", "option": "", "requirement_ids": ["R0"],
        "basis": [{"fact_id": "F1", "sentence_ids": [1, 2]}],
        "reasoning": "Replay depends on retained records.", "assumptions": ["Retention is configured."],
        "change_condition": "Reassess if the records expire."}]}


def test_long_source_is_offered_whole_and_rebound_from_immutable_coordinates():
    original = chains()
    assert len(TEXT) > 1200
    assert not bind_evidence_choices({"source_facts": [{"id": "F1", "evidence_id": 1}]}, original, [], [])["source_facts"]
    packet, offered = selection_packet(original)
    assert offered == {1} and TAIL.split(". ")[-1] in packet
    bound = bind_evidence_choices(refs(), original, [], [])
    fact = bound["source_facts"][0]
    assert fact["saved_text"] == MECHANISM + " " + TAIL.split(". ")[0] + "."
    assert fact["saved_passages"] == [fact["saved_text"]]
    assert fact["source_ranges"] == [[0, 2]]
    assert fact["status"] == "unknown"
    assert bind_evidence_choices(json.loads(json.dumps(bound)), original, [], []) == bound
    assert original == chains()


@pytest.mark.parametrize("ranges", [[], None, "0:2", [[True, 2]], [[0, False]], [[-1, 2]],
    [[0, 99]], [[2, 1]], [[0, 2], [1, 3]], [[0, 1], [0, 1]], [[2, 3], [0, 1]],
    [[0, 1], [1, 2], [2, 3], [3, 4]], [[0]], [[0, 1, 2]]])
def test_malformed_ranges_fail_closed_instead_of_falling_back_to_whole(ranges):
    source = chains(MECHANISM)[0]["sources"][0]
    raw = {"source_facts": [{"id": "F1", "evidence_id": 1, "source_ranges": ranges}]}
    assert selected_passages(source, ranges) is None
    assert not bind_evidence_choices(raw, [{"sources": [source]}], [], [])["source_facts"]


@pytest.mark.parametrize("text,ranges", [
    ("Alpha replays retained records. [...] Only a special deployment can replay.", [[0, 2]]),
    ("Alpha replays ... depending on", [[0, 1]]),
    ("records may be replayed. Alpha has an expiry policy.", [[0, 1]]),
    ("Alpha replays retained records. But replay requires", [[1, 2]]),
    ("Alpha stores records. Alpha stores records.", [[0, 1]]),
    ("Alpha replays retained records. Alpha cannot replay retained records.", [[0, 1]]),
])
def test_omission_fragments_ambiguity_and_adjacent_qualifiers_are_not_copied(text, ranges):
    assert selected_passages(chains(text)[0]["sources"][0], ranges) is None


def test_only_single_continuous_passage_can_be_recropped_and_limits_are_not_raised():
    source = chains(MECHANISM)[0]["sources"][0]
    source["passages"] = [MECHANISM]
    assert selection_sentences(source) is not None
    assert selected_passages(source, [[0, 1]]) == (MECHANISM,)
    disjoint = dict(source, passages=[MECHANISM.split(". ")[0] + ".", MECHANISM.split(". ")[1]])
    assert selection_sentences(disjoint) is None
    assert selected_passages(disjoint, [[0, 1]]) is None
    packet, _ = selection_packet([{"sources": [source]}])
    assert '"separate_locations":true' in packet and '"location":1' in packet
    assert selected_passages(chains()[0]["sources"][0], [[0, 17]]) is None
    many = " ".join(f"Fact {i} describes the data." for i in range(17))
    assert len(many) < 1200 and selected_passages(chains(many)[0]["sources"][0], [[0, 17]]) is None


def test_chinese_ranges_preserve_original_no_space_boundaries_and_context():
    text = "记录会在期限内保留。消费者可以重放记录。配置影响保留期限。"
    assert selected_passages(chains(text)[0]["sources"][0], [[0, 2]]) == (text,)
    window = locate_source_window("消费者可以重放记录。", SourceDocument((text,), False))
    assert window and window.text == text
    assert locate_source_window("pha records.", SourceDocument(("Alpha records. More text.",), False)) is None
    opposite = "消费者可以重放记录。但只有保留期限内的记录可以重放。"
    assert selected_passages(chains(opposite)[0]["sources"][0], [[0, 1]]) == (opposite,)


def test_packet_cap_applies_to_whole_sources_and_rebinding_rejects_unoffered(monkeypatch):
    from deepchoice.utils import fact_selection as selection
    original = chains(MECHANISM) + [{"sources": [{"title": "Beta guide", "url": "https://beta.example/guide", "snippet": MECHANISM}]}]
    first, _ = selection_packet(original[:1])
    monkeypatch.setattr(selection, "MAX_PACKET_BYTES", len(first.encode("utf-8")))
    packet, offered = selection_packet(original)
    assert packet == first and offered == {1}
    raw = {"source_facts": [{"id": "F1", "evidence_id": 2, "source_ranges": [[0, 2]]}]}
    assert not bind_evidence_choices(raw, original, [], [])["source_facts"]
    original[0]["disputed"] = True
    assert 1 not in selection_packet(original)[1]


@pytest.mark.parametrize("ranges,valid", [([[0, 2]], True), ([[True, 2]], False), (None, False), ([], False), ([[0, 1, 2]], False)])
def test_range_diagnostic_observes_shape_without_granting_binding(ranges, valid):
    raw = {"source_facts": [{"id": "F1", "evidence_id": 1, "source_ranges": ranges}]}
    assert output_shape_valid("conclusion_synthesizer", raw, profile="fact-selection-v2") is valid
    assert output_shape_valid("conclusion_synthesizer", {"source_facts": [{"id": "F1", "evidence_id": 1}]}, profile="fact-selection-v2")


async def test_staged_coordinates_survive_citation_and_review_without_mutating_chains(monkeypatch):
    original = chains()
    model = AsyncMock(side_effect=[refs(), model_answer()])
    monkeypatch.setattr(synth, "call_model", model)
    state = {"task": TASK, "evidence_chains": deepcopy(original), "search_results": {"fixture": "unchanged"}}
    update = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(state)
    assert model.await_count == 2
    assert update["final_recommendation"]["source_facts"][0]["source_ranges"] == [[0, 2]]
    assert "evidence_chains" not in update and state["evidence_chains"] == original
    state.update(update)
    calls = []
    async def fetch(*args, **kwargs):
        calls.append(args)
        return httpx.Response(200, text=f"<p>{TEXT}</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await CitationValidatorAgent().run(state))
    assert len(calls) == 1
    assert state["final_recommendation"]["source_facts"][0]["status"] == "verified"
    assert len(prepare_analysis_review(state).slots) == 1
    assert state["evidence_chains"][0]["sources"][0]["snippet"] == TEXT
    assert state["search_results"] == {"fixture": "unchanged"}
    forged = deepcopy(state)
    forged["final_recommendation"]["source_facts"][0]["source_ranges"] = [[0, 1]]
    assert not prepare_analysis_review(forged).slots


async def test_live_location_and_network_uncertainty_remain_independent(monkeypatch):
    original = chains()
    bound = bind_evidence_choices(refs(), original, [], [])
    async def wrong_page(*args, **kwargs):
        return httpx.Response(200, text="<p>Alpha is a programming language.</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", wrong_page)
    verification, _ = await verify_citations(bound, original)
    assert {c.status.value for c in verification.checks} == {"unknown"}
    assert {c.reason.value for c in verification.checks} == {"content_insufficient"}
    assert calibrate_evidence_choices(bound, verification)["source_facts"][0].get("review_availability") is None
    async def timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("private diagnostic")
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", timeout)
    verification, _ = await verify_citations(bound, original)
    assert {c.status.value for c in verification.checks} == {"unknown"}
    assert "private diagnostic" not in verification.model_dump_json()


@pytest.mark.parametrize("assumptions", [[], ["Retention is configured."]])
async def test_sqlite_checkpoint_restart_keeps_range_coordinates_and_original_sources(monkeypatch, tmp_path, assumptions):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START, StateGraph
    from deepchoice.state import ResearchState

    answer = model_answer()
    answer["decision_analysis"][0]["assumptions"] = assumptions
    model = AsyncMock(side_effect=[refs(), answer])
    monkeypatch.setattr(synth, "call_model", model)
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=f"<p>{TEXT}</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    workflow = StateGraph(ResearchState)
    workflow.add_node("synthesis", synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run)
    workflow.add_node("citation", CitationValidatorAgent().run)
    workflow.add_edge(START, "synthesis")
    workflow.add_edge("synthesis", "citation")
    workflow.add_edge("citation", END)
    config = {"configurable": {"thread_id": "range-restart"}}
    path = str(tmp_path / "checkpoints.db")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = workflow.compile(checkpointer=saver, interrupt_after=["synthesis"])
        await graph.ainvoke({"task": TASK, "evidence_chains": chains()}, config)
        saved = await graph.aget_state(config)
        assert saved.next == ("citation",)
        assert saved.values["evidence_chains"] == chains()
        assert saved.values["final_recommendation"]["source_facts"][0]["source_ranges"] == [[0, 2]]
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = workflow.compile(checkpointer=saver)
        restored = await graph.ainvoke(None, config)
    assert model.await_count == 2  # Restart does not run either synthesis call again.
    assert restored["final_recommendation"]["source_facts"][0]["status"] == "verified"
    assert restored["evidence_chains"][0]["sources"][0]["snippet"] == TEXT
    assert len(prepare_analysis_review(restored).slots) == 1


@pytest.mark.parametrize("qualifier", ["But only if retention is configured.",
    "This only applies while retention permits.", "The condition is a configured retention period."])
def test_adjacent_conditions_are_copied_without_relying_on_keyword_detection(qualifier):
    text = "Alpha replays retained records. " + qualifier
    assert selected_passages(chains(text)[0]["sources"][0], [[0, 1]]) == (text,)
    bound = bind_evidence_choices(refs([[0, 1]]), chains(text), [], [])
    assert bind_evidence_choices(bound, chains(text), [], []) == bound


def test_disjoint_focus_windows_merge_context_without_repeated_expansion():
    text = "First topic is introduced. Second topic is described. Third topic has a condition. Fourth topic ends."
    source = chains(text)[0]["sources"][0]
    assert selected_passages(source, [[1, 2], [3, 4]]) == (text,)
    bound = bind_evidence_choices(refs([[1, 2], [3, 4]]), chains(text), [], [])
    assert bound["source_facts"][0]["source_ranges"] == [[1, 2], [3, 4]]
    assert bind_evidence_choices(bound, chains(text), [], []) == bound


@pytest.mark.parametrize("text,ranges", [
    ("[...] Both systems can make a read-process-write loop produce each result downstream once, and neither does it by executing the processing step only once. "
     "Kafka commits the result and the consumer offset in one producer transaction; "
     "RabbitMQ streams make the resume point part of the result, using the source offset as the publishing ID so that deduplication discards a replayed result. "
     "Different designs, same guarantee — which RabbitMQ calls effectively-once, the more honest name.", [[1, 4]]),
    ("Alpha supports replay. [...] Only retained records can be replayed.", [[0, 1]]),
])
def test_omission_bearing_neighbor_may_hold_the_decisive_premise(text, ranges):
    # First fixture preserves the exact exposed P11 saved-source counterexample.
    assert selected_passages(chains(text)[0]["sources"][0], ranges) is None
    assert not bind_evidence_choices(refs(ranges), chains(text), [], [])["source_facts"]


@pytest.mark.parametrize("text,ranges", [
    ("First topic is introduced. Second topic is described. [...] This condition applies to the following topic. Third topic is described. Fourth topic ends.", [[0, 1], [3, 4]]),
    ("First topic is introduced. Second topic is described. Third topic is described. Fourth topic ends. [...] This condition limits the previous topic.", [[0, 1], [3, 4]]),
])
def test_each_disjoint_focus_rejects_omission_on_either_side(text, ranges):
    assert selected_passages(chains(text)[0]["sources"][0], ranges) is None
