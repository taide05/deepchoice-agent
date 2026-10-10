"""Joint generation is checkpointed before citation; all sources are synthetic."""
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

TASK = {"query": "Choose Alpha or Beta for retained events?", "candidate_techs": ["Alpha", "Beta"],
        "sub_questions": ["What retention premise matters?"], "constraints": []}
CHAINS = [
    {"sources": [{"title": "Alpha guide", "url": "https://alpha.example/guide",
                   "snippet": "Alpha discards events after delivery."}]},
    {"sources": [{"title": "Beta guide", "url": "https://beta.example/guide",
                   "snippet": "Beta retains events. Clients can replay retained events."}]},
]


def proposal(ref="S2B1"):
    return {"source_view_ids": ["S1", "S2"], "decision_analysis": [{
        "kind": "answer", "option": "", "question_id": "Q1", "basis_refs": [ref],
        "reasoning": "Retained events are a prerequisite for later replay.",
        "assumptions": [], "change_condition": "Reassess if the retention policy changes."}]}


@pytest.mark.parametrize("reference,retained", [("S2B1", 1), ("S1B1", 0), ("S2B3", 0)])
async def test_joint_answer_waits_for_citation_and_never_borrows_other_fact(monkeypatch, reference, retained):
    model = AsyncMock(return_value=proposal(reference))
    monkeypatch.setattr(synth, "call_model", model)
    async def fetch(source, url, **kwargs):
        text = "An unrelated geometry page." if "alpha" in url else CHAINS[1]["sources"][0]["snippet"]
        return httpx.Response(200, text=text, headers={"content-type": "text/plain"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = {"task": deepcopy(TASK), "evidence_chains": deepcopy(CHAINS)}
    agent = synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK))
    state.update(await agent.run(state))
    assert all(fact["status"] == "unknown" for fact in state["final_recommendation"]["source_facts"])
    state.update(await CitationValidatorAgent().run(state))
    rec = state["final_recommendation"]
    assert [fact["status"] for fact in rec["source_facts"]] == ["unknown", "verified"]
    assert len(rec["decision_analysis"]) == retained
    if retained:
        assert rec["decision_analysis"][0]["basis"][0]["fact_id"] == "F2"
        assert rec["decision_analysis"][0]["basis"][0]["source_sentences"] == ["Beta retains events."]
    model.assert_awaited_once()


async def test_new_joint_generation_clears_previous_pass_verification(monkeypatch):
    monkeypatch.setattr(synth, "call_model", AsyncMock(return_value=proposal()))
    result = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run({
        "task": TASK, "evidence_chains": CHAINS,
        "citation_verification": {"checks": [{"status": "verified"}]}})
    assert result["citation_verification"] == {}
    assert len(result["final_recommendation"]["decision_analysis"]) == 1
    assert all(fact["status"] == "unknown" for fact in result["final_recommendation"]["source_facts"])


async def test_sqlite_resume_after_joint_does_not_repeat_generation(monkeypatch, tmp_path):
    events = []
    async def model(prompt, **kwargs):
        events.append(kwargs["diagnostic_profile"])
        return proposal()
    async def fetch(source, url, **kwargs):
        events.append(url)
        text = next(src["snippet"] for chain in CHAINS for src in chain["sources"] if src["url"] == url)
        return httpx.Response(200, text=text, headers={"content-type": "text/plain"})
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
        return editor._create_workflow(agents, start_from="conclusion_synthesizer")
    db = str(tmp_path / "checkpoints.sqlite3")
    config = {"configurable": {"thread_id": "joint-citation"}}
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = workflow().compile(checkpointer=saver, interrupt_after=["conclusion_synthesizer"])
        await graph.ainvoke({"task": TASK, "evidence_chains": CHAINS}, config)
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("citation_validator",)
        assert len(snapshot.values["final_recommendation"]["decision_analysis"]) == 1
    assert events == ["joint-question-v1"]
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = workflow().compile(checkpointer=saver)
        result = await graph.ainvoke(None, config)
        assert (await graph.aget_state(config)).next == ()
    assert events == ["joint-question-v1", "https://alpha.example/guide", "https://beta.example/guide"]
    assert result["report"] == "synthetic reviewed report"
    assert len(result["final_recommendation"]["decision_analysis"]) == 1
