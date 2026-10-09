"""The second model call consumes checked facts; no live services are used."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.orchestrator import ChiefEditorAgent
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.utils.question_packet import basis_reference_packet

TASK = {"query": "Choose Alpha or Beta for retained events?", "candidate_techs": ["Alpha", "Beta"],
        "sub_questions": ["What retention premise matters?"], "constraints": []}
CHAINS = [
    {"sources": [{"title": "Alpha guide", "url": "https://alpha.example/guide",
                   "snippet": "Alpha discards events after delivery."}]},
    {"sources": [{"title": "Beta guide", "url": "https://beta.example/guide",
                   "snippet": "Beta retains events. Clients can replay retained events."}]},
]


def proposal(ref):
    return {"decision_analysis": [{"kind": "answer", "option": "", "question_id": "Q1",
        "basis_refs": [ref], "reasoning": "Retained events are a prerequisite for later replay.",
        "assumptions": [], "change_condition": "Reassess if the retention policy changes."}]}


async def prepare(monkeypatch, *, all_missing=False):
    calls = []
    async def fetch(source, url, **kwargs):
        calls.append(url)
        text = ("An unrelated page about geometry." if all_missing or "alpha" in url
                else CHAINS[1]["sources"][0]["snippet"])
        return httpx.Response(200, text="<p>" + text + "</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = {"task": deepcopy(TASK), "evidence_chains": deepcopy(CHAINS)}
    agent = synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK))
    state.update(await agent.select_sources(state))
    state.update(await CitationValidatorAgent().run(state))
    return agent, state, calls


@pytest.mark.parametrize("reference,retained", [("B1", 1), ("B3", 0)])
async def test_rejected_fact_never_reaches_judgment_basis_or_rebinds_old_reference(monkeypatch, reference, retained):
    model = AsyncMock(side_effect=[{"source_view_ids": ["S1", "S2"]}, proposal(reference)])
    monkeypatch.setattr(synth, "call_model", model)
    agent, state, calls = await prepare(monkeypatch)
    state.update(await agent.run(state))
    assert model.await_count == 2
    prompt = model.await_args_list[1].args[0][0]["content"]
    assert "Alpha discards events" not in prompt
    assert "B1: Beta retains events." in prompt and "B2: Clients can replay" in prompt
    assert "B3:" not in prompt
    rec = state["final_recommendation"]
    assert [fact["status"] for fact in rec["source_facts"]] == ["unknown", "verified"]
    assert len(rec["decision_analysis"]) == retained
    if retained:
        assert rec["decision_analysis"][0]["basis"][0]["fact_id"] == "F2"
        assert rec["decision_analysis"][0]["basis"][0]["source_sentences"] == ["Beta retains events."]
    assert calls == ["https://alpha.example/guide", "https://beta.example/guide"]


async def test_no_eligible_facts_skips_judgment_instead_of_generating_doomed_analyses(monkeypatch):
    model = AsyncMock(return_value={"source_view_ids": ["S1", "S2"]})
    monkeypatch.setattr(synth, "call_model", model)
    agent, state, calls = await prepare(monkeypatch, all_missing=True)
    state.update(await agent.run(state))
    assert model.await_count == 1 and len(calls) == 2
    assert state["final_recommendation"]["decision_analysis"] == []
    assert len(state["final_recommendation"]["source_facts"]) == 2
    assert state["quality_signals"][0]["staged_generation"]["facts_reviewable"] == 0


@pytest.mark.parametrize("status,availability,allowed", [
    ("verified", None, [1, 2]), ("unknown", "network_unconfirmed", [1, 2]),
    ("unknown", "sentence_scoped", [2]), ("unknown", None, []),
    ("unsupported", None, []), ("unreachable", None, []),
])
def test_judgment_packet_opens_only_existing_reviewable_sentence_addresses(status, availability, allowed):
    fact = {"id": "F1", "source_title": "Beta guide", "saved_text": CHAINS[1]["sources"][0]["snippet"],
            "status": status, "review_availability": availability, "reviewable_sentence_ids": [2]}
    packet, offered = basis_reference_packet([fact], ["Beta"], require_reviewable=True)
    assert [item["sentence_ids"][0] for item in offered.values()] == allowed
    if allowed == [2]:
        assert "B1: Clients can replay" in packet and "B2:" not in packet
        assert "B1: Beta retains" not in packet
    if not allowed:
        assert "B1:" not in packet


@pytest.mark.parametrize("field,value", [
    ("evidence_id", 1), ("source_title", "Forged guide"),
    ("canonical_url", "https://other.example/"), ("saved_text", "Forged saved text."),
    ("saved_passages", ["Forged saved text."]), ("source_ranges", [[0, 1]]),
    ("text", "Forged published text."),
])
async def test_fact_identity_drift_cannot_borrow_an_earlier_verification(monkeypatch, field, value):
    model = AsyncMock(return_value={"source_view_ids": ["S1", "S2"]})
    monkeypatch.setattr(synth, "call_model", model)
    agent, state, _ = await prepare(monkeypatch)
    state["final_recommendation"]["source_facts"][1][field] = value
    with pytest.raises(ValueError, match="Citation-calibrated source selection"):
        await agent.run(state)
    assert model.await_count == 1


async def test_new_selection_clears_previous_pass_verification(monkeypatch):
    model = AsyncMock(return_value={"source_view_ids": ["S1", "S2"]})
    monkeypatch.setattr(synth, "call_model", model)
    agent, state, _ = await prepare(monkeypatch)
    assert state["citation_verification"]["checks"]
    selected = await agent.select_sources(state)
    assert selected["citation_verification"] == {}
    assert all(fact["status"] == "unknown" for fact in selected["final_recommendation"]["source_facts"])


async def test_sqlite_resume_after_citation_does_not_repeat_selection_or_fetch(monkeypatch, tmp_path):
    events = []
    async def model(prompt, **kwargs):
        profile = kwargs["diagnostic_profile"]
        events.append(profile)
        return {"source_view_ids": ["S1", "S2"]} if profile == "fact-view-selection-v1" else proposal("B1")
    async def fetch(source, url, **kwargs):
        events.append(url)
        text = next(source["snippet"] for chain in CHAINS for source in chain["sources"] if source["url"] == url)
        return httpx.Response(200, text="<p>" + text + "</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr(synth, "call_model", model)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    async def noop(state): return {}
    async def gate(state): return {"_evidence_decision_route": "continue_report"}
    async def report(state): return {"report": "synthetic reviewed report"}
    def workflow():
        editor = ChiefEditorAgent(TASK)
        agents = editor._initialize_agents()
        agents.update(self_reviewer=SimpleNamespace(run=noop), evidence_decision_gate=SimpleNamespace(run=gate),
                      report_generator=SimpleNamespace(run=report))
        return editor._create_workflow(agents, start_from="source_selection")
    db = str(tmp_path / "checkpoints.sqlite3")
    config = {"configurable": {"thread_id": "verified-judgment"}}
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = workflow().compile(checkpointer=saver, interrupt_after=["citation_validator"])
        await graph.ainvoke({"task": TASK, "evidence_chains": CHAINS}, config)
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("conclusion_synthesizer",)
        assert len(snapshot.values["citation_verification"]["checks"]) == 3
    assert len(events) == 3 and events[0] == "fact-view-selection-v1"
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = workflow().compile(checkpointer=saver)
        result = await graph.ainvoke(None, config)
        assert (await graph.aget_state(config)).next == ()
    assert events[-1] == "question-judgment-v2" and len(events) == 4
    assert result["report"] == "synthetic reviewed report"
    assert len(result["final_recommendation"]["decision_analysis"]) == 1
    from deepchoice.server.app import NODE_TO_PHASE
    assert NODE_TO_PHASE["source_selection"] == "evidence_chain"
    assert NODE_TO_PHASE["conclusion_synthesizer"] == "self_review"


async def test_manifest_node_rejects_missing_preverification_before_model_call(monkeypatch):
    model = AsyncMock()
    monkeypatch.setattr(synth, "call_model", model)
    agent = synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK))
    with pytest.raises(ValueError, match="Citation-calibrated source selection"):
        await agent.run({"task": TASK, "evidence_chains": CHAINS})
    model.assert_not_awaited()
