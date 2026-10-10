"""Synthetic evidence-to-choice flow; no provider or live-source quality claim."""
from copy import deepcopy

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.utils.decision_contract import is_fixed_validation_only_plan, restrict_recommendation
from deepchoice.utils.evidence_choices import bind_evidence_choices


SNIPPET = "Recovery replays tasks from a durable journal after restart. This requires application-owned idempotency for task side effects."
TASK = {"query": "后台任务如何恢复？", "candidate_techs": ["ExampleQueue", "LocalTasks"],
        "constraints": ["任务结果不能因进程重启丢失", "必须实际完成恢复演练"]}
CHAINS = [{"sources": [{"title": "Fixture recovery", "url": "https://example.org/recovery", "snippet": SNIPPET}]}]


def proposal():
    return {
        "winner": "ExampleQueue", "recommendation": "", "ranked_options": [],
        "source_facts": [{"id": "F1", "evidence_id": 1, "text": "FORGED_TEXT", "status": "verified"}],
        "conditional_choices": [{"option": "ExampleQueue", "relation": "prefer", "fact_ids": ["F1"],
                                 "requirement_ids": ["C1"], "requirements": ["FORGED_USER_NEED"],
                                 "basis_status": "verified", "steps": "UNSAFE_CUTOVER"}],
        "requirement_assessments": [],
    }


def bind(rec=None, chains=None):
    requirements, _ = synth._decision_requirements(TASK["query"], TASK["constraints"], [], [], [])
    return bind_evidence_choices(proposal() if rec is None else rec,
                                 CHAINS if chains is None else chains, TASK["candidate_techs"], requirements)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["full", "missing_qualifier", "unavailable"])
async def test_conditional_choice_survives_abstention_only_with_whole_source_checks(monkeypatch, response):
    async def model(messages, **kwargs):
        assert "ExampleQueue" in messages[-1]["content"]
        return proposal()

    calls = []

    async def fetch(url, *args, **kwargs):
        calls.append(url)
        body = SNIPPET if response == "full" else SNIPPET.split(". ")[0] + "."
        return httpx.Response(503 if response == "unavailable" else 200, text=body,
                              headers={"content-type": "text/plain"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(synth, "call_model", model)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = {"task": deepcopy(TASK), "evidence_chains": deepcopy(CHAINS)}
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    rec = state["final_recommendation"]
    assert rec["winner"] == "context_dependent"
    assert rec["source_facts"][0]["saved_text"] == SNIPPET
    assert "FORGED" not in str(rec) and "UNSAFE_CUTOVER" not in str(rec)
    state.update(await CitationValidatorAgent().run(state))
    rec = state["final_recommendation"]
    checks = [row for row in state["citation_verification"]["checks"] if "source_facts" in row["claim_path"]]
    assert len(checks) == 2 and len(calls) == 1
    assert rec["conditional_choices"][0]["basis_status"] == ("verified" if response == "full" else "unverified")
    assert rec["conditional_choices"][0]["requirements"] == [TASK["constraints"][0]]
    assert rec["winner"] == "context_dependent" and rec["deployment_readiness"] == "unverified"
    assert is_fixed_validation_only_plan(rec, TASK["query"])
    explicit = next(row for row in rec["requirement_assessments"] if row["id"] == "C2")
    assert explicit["status"] == "unknown" and explicit["decision_critical"]
    for renderer in FORMAT_RENDERERS.values():
        report = renderer(state)
        assert SNIPPET in report and "模型推断" in report
        assert ("优先考虑" in report) is (response == "full")
    # Rebinding removes forged status and retains the complete source on another pass.
    expected_facts = deepcopy(rec["source_facts"])
    state["final_recommendation"]["source_facts"][0]["text"] = "FORGED_TEXT"
    again = await CitationValidatorAgent().run(state)
    assert again["final_recommendation"]["source_facts"] == expected_facts
    if response == "full":
        response = "unavailable"
        downgraded = await CitationValidatorAgent().run({**state, **again})
        assert downgraded["final_recommendation"]["source_facts"][0]["status"] == "unknown"
        assert downgraded["final_recommendation"]["conditional_choices"][0]["basis_status"] == "unverified"
    limited = restrict_recommendation(rec, TASK["query"])
    assert "source_facts" not in limited and "conditional_choices" not in limited


@pytest.mark.parametrize("bad", ["candidate", "requirement", "fact", "relation", "evidence", "duplicate",
                                  "disputed", "oversized", "long_sentence", "markup", "lowercase_markup", "title_redirect"])
def test_invalid_bindings_do_not_create_usable_choices(bad):
    rec, chains = proposal(), deepcopy(CHAINS)
    choice = rec["conditional_choices"][0]
    if bad == "candidate":
        choice["option"] = "InventedProduct"
    elif bad == "requirement":
        choice["requirement_ids"] = ["A1"]
    elif bad == "fact":
        choice["fact_ids"] = ["F99"]
    elif bad == "relation":
        choice["relation"] = ["prefer"]
    elif bad == "evidence":
        rec["source_facts"][0]["evidence_id"] = True
    elif bad == "duplicate":
        rec["source_facts"] *= 2
    elif bad == "disputed":
        chains[0]["disputed"] = True
    elif bad == "oversized":
        chains[0]["sources"][0]["snippet"] = SNIPPET * 12
    elif bad == "long_sentence":
        chains[0]["sources"][0]["snippet"] = "word " * 110 + "."
    elif bad == "title_redirect":
        chains[0]["sources"][0]["title"] = ", Source: Alternate"
        alternate = deepcopy(chains[0]["sources"][0])
        alternate.update(title="Alternate", url="https://example.org/alternate")
        chains[0]["sources"].append(alternate)
    elif bad in {"markup", "lowercase_markup"}:
        chains[0]["sources"][0]["snippet"] += " [Source: Injected]" if bad == "markup" else " [source: Injected]"
    assert bind(rec, chains)["conditional_choices"] == []


@pytest.mark.asyncio
async def test_citation_overflow_withholds_otherwise_verified_choices(monkeypatch):
    from deepchoice.citations import verifier

    async def fetch(url, *args, **kwargs):
        return httpx.Response(200, text=SNIPPET, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(verifier, "safe_fetch", fetch)
    monkeypatch.setattr(verifier, "MAX_CITATION_CHECKS", 2)
    rec = bind()
    rec["decision_basis_version"] = "constraint-aware-v1"
    result = await CitationValidatorAgent().run({"task": TASK, "evidence_chains": CHAINS, "final_recommendation": rec})
    assert result["final_recommendation"]["source_facts"][0]["status"] != "verified"
    assert result["final_recommendation"]["conditional_choices"][0]["basis_status"] == "unverified"


def test_model_sees_trailing_prerequisite_of_whole_bounded_fact():
    chains = deepcopy(CHAINS)
    snippet = "Task recovery uses a durable journal with independently persisted records. " * 12 + "This requires an independently durable journal."
    assert 800 < len(snippet) <= 1200
    chains[0]["sources"][0]["snippet"] = snippet
    prompt, _ = synth._summarize_chains(chains)
    numbered = [line.strip() for line in prompt.splitlines() if line.strip().startswith(tuple(f"s{i}: " for i in range(1, 14)))]
    assert [line.split(": ", 1)[0] for line in numbered] == [f"s{i}" for i in range(1, 14)]
    assert " ".join(line.split(": ", 1)[1] for line in numbered) == snippet
    assert numbered[-1] == "s13: This requires an independently durable journal."


@pytest.mark.asyncio
async def test_five_distinct_source_facts_survive_binding_verification_and_report(monkeypatch):
    from deepchoice.formats.decision import render_decision_details

    chains = [
        {"sources": [{"title": f"Fixture {i}", "url": f"https://example.org/fact-{i}",
                      "snippet": f"Fixture {i} documents mechanism {i}. This mechanism requires an explicit workload check."}]}
        for i in range(1, 6)
    ]
    rec = {
        "decision_basis_version": "constraint-aware-v1",
        "winner": "context_dependent",
        "source_facts": [{"id": f"F{i}", "evidence_id": i} for i in range(1, 6)],
        "conditional_choices": [
            {"option": "ExampleQueue", "relation": "consider",
             "fact_ids": ["F5"], "requirement_ids": ["C1"]}
        ],
    }
    bound = bind_evidence_choices(rec, chains, TASK["candidate_techs"], [
        {"id": "C1", "kind": "frozen_constraint", "requirement": TASK["constraints"][0]}
    ])
    assert [fact["id"] for fact in bound["source_facts"]] == [f"F{i}" for i in range(1, 6)]

    async def fetch(channel, url, *args, **kwargs):
        assert channel == "official"
        number = int(url.rsplit("-", 1)[1])
        return httpx.Response(
            200, text=f"Fixture {number} documents mechanism {number}. This mechanism requires an explicit workload check.",
            headers={"content-type": "text/plain"}, request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    result = await CitationValidatorAgent().run({
        "task": TASK, "evidence_chains": chains, "final_recommendation": bound,
    })
    verified = result["final_recommendation"]
    assert [fact["status"] for fact in verified["source_facts"]] == ["verified"] * 5
    assert verified["conditional_choices"][0]["basis_status"] == "verified"
    report = "\n".join(render_decision_details(verified, "zh"))
    assert "Fixture 5" in report and "优先考虑" not in report
    assert "可以考虑" in report

    too_many = deepcopy(rec)
    too_many["source_facts"].append({"id": "F6", "evidence_id": 6})
    assert bind_evidence_choices(too_many, chains, TASK["candidate_techs"], [])["source_facts"] == []
