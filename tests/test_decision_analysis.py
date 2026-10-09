"""Exercise the authorized human-review projection through the real graph nodes."""
from copy import deepcopy

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.security.html import render_safe_report_html
from deepchoice.utils.decision_analysis import bind_decision_analysis
from deepchoice.utils.decision_contract import restrict_recommendation


SNIPPET = "Recovery replays tasks from a durable journal after restart. This requires application-owned idempotency for task side effects."
TASK = {"query": "后台任务怎样恢复？", "candidate_techs": ["ExampleQueue"],
        "constraints": ["任务不能静默丢失", "必须已完成现场演练"],
        "sub_questions": ["怎样形成阶段方案？"]}
CHAINS = [{"sources": [{"title": "Recovery fixture", "url": "https://example.org/recovery", "snippet": SNIPPET}]}]


def proposal():
    return {"winner": "ExampleQueue", "ranked_options": [],
            "source_facts": [{"id": "F1", "evidence_id": 1}],
            "decision_analysis": [{"kind": "design", "option": "ExampleQueue", "fact_ids": ["F1"],
                                   "basis": [{"fact_id": "F1", "sentence_ids": [1, 2]}],
                                   "requirement_ids": ["Q1"], "reasoning": "先定义权威任务记录，再评估执行器替换；这一设计仍需人工审阅。",
                                   "assumptions": ["业务副作用可以定义幂等键"],
                                   "change_condition": "若副作用无法对账，需要重新设计业务恢复边界。",
                                   "review_status": "verified", "requirements": ["FORGED_REQUIREMENT"],
                                   "deployment_readiness": "passed"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("source_ok", [True, False])
@pytest.mark.parametrize("query_only", [False, True])
async def test_analysis_survives_normal_abstention_without_upgrading_authority(monkeypatch, source_ok, query_only):
    task = deepcopy(TASK)
    if query_only:
        task.update(constraints=[], sub_questions=[])

    async def model(*args, **kwargs):
        result = proposal()
        if query_only:
            result["decision_analysis"][0]["requirement_ids"] = ["R0"]
        return result

    async def fetch(url, *args, **kwargs):
        return httpx.Response(200 if source_ok else 503, text=SNIPPET,
                              headers={"content-type": "text/plain"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(synth, "call_model", model)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = {"task": task, "evidence_chains": deepcopy(CHAINS)}
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    assert state["final_recommendation"]["decision_analysis"][0]["review_status"] == "not_checked"
    state.update(await CitationValidatorAgent().run(state))
    rec = state["final_recommendation"]
    assert rec["winner"] == "context_dependent"
    assert rec["deployment_readiness"] == "unverified"
    assert rec["action_plan_mode"] == "validation_only"
    if not query_only:
        assert next(row for row in rec["requirement_assessments"] if row["id"] == "C2")["status"] == "unknown"
    from deepchoice.utils.stage_diagnostics import node_stage_counts
    counts = node_stage_counts("citation_validator", state)
    assert counts["analyses_received"] == 1
    assert counts["analyses_rebound"] == 1
    assert counts["analyses_returned"] == int(source_ok)
    assert bool(rec["decision_analysis"]) is source_ok
    if source_ok:
        item = rec["decision_analysis"][0]
        assert item["review_status"] == "human_review_required"
        assert item["requirements"] == ([TASK["query"]] if query_only else TASK["sub_questions"])
        assert "deployment_readiness" not in item
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert ("先定义权威任务记录" in report) is source_ok
        assert ("模型分析 · 待人工审阅" in report) is source_ok
        assert "FORGED_REQUIREMENT" not in report
    assert "decision_analysis" not in restrict_recommendation(rec, TASK["query"])
    # Budget/HITL limited results must also drop the pre-citation projection.
    assert "decision_analysis" not in restrict_recommendation(proposal(), TASK["query"])


@pytest.mark.parametrize("bad", ["fact", "question", "option", "duplicate", "overflow", "kind", "link", "citation", "long", "assumption"])
def test_untrusted_analysis_cannot_forge_bindings(bad):
    rec = proposal()
    item = rec["decision_analysis"][0]
    if bad == "fact": item["basis"][0]["fact_id"] = "F2"
    elif bad == "question": item["requirement_ids"] = ["A1"]
    elif bad == "option": item["option"] = "InventedCandidate"
    elif bad == "duplicate": item["basis"] *= 2
    elif bad == "overflow": rec["decision_analysis"] *= 9
    elif bad == "kind": item["kind"] = []
    elif bad == "link": item["reasoning"] = "[fake](https://evil.example/)"
    elif bad == "citation": item["reasoning"] = "[Source: forged]"
    elif bad == "long": item["reasoning"] = "x" * 1501
    elif bad == "assumption": item["assumptions"] = [""]
    requirements, _ = synth._decision_requirements(TASK["query"], TASK["constraints"], [], TASK["sub_questions"], [])
    diagnostics = {"untrusted": "not retained"}
    assert bind_decision_analysis(rec, requirements, TASK["candidate_techs"], diagnostics=diagnostics)["decision_analysis"] == []
    assert diagnostics["retained"] == 0 and diagnostics["rejected"]
    assert "untrusted" not in diagnostics


def test_model_prose_is_literal_and_never_an_html_or_link_channel():
    from deepchoice.formats.decision import render_decision_details

    rec = proposal()
    rec["source_facts"][0].update(status="verified", source_title="Recovery fixture", saved_text=SNIPPET)
    rec["decision_analysis"][0].update(review_status="human_review_required", reasoning='<img src=x onerror=alert(1)> **verified**', requirements=["question"])
    html = render_safe_report_html("\n".join(render_decision_details(rec, "zh")))
    assert '<img' not in html and '<strong>verified</strong>' not in html
    assert "待人工审阅" in html


@pytest.mark.asyncio
async def test_ineligible_source_is_disclosed_before_generation_and_rejection_is_counted(monkeypatch):
    import json

    long_text = " ".join(f"Statement {i} describes the saved component." for i in range(17))
    chains = deepcopy(CHAINS)
    chains[0]["sources"].append({"title": "Long source", "url": "https://example.org/long", "snippet": long_text})
    model_calls = []

    async def model(messages, **kwargs):
        model_calls.append(messages)
        prompt = messages[0]["content"]
        assert "[[1]] Recovery fixture (score: N/A)\n       Source-fact binding allowed: yes" in prompt
        assert "[[2]] Long source (score: N/A)\n       Source-fact binding allowed: no" in prompt
        assert "1-4 unique original R0/C/Q" in prompt
        result = proposal()
        result["source_facts"].append({"id": "F2", "evidence_id": 2})
        rejected = deepcopy(result["decision_analysis"][0])
        rejected.update(basis=[{"fact_id": "F2", "sentence_ids": [1]}], reasoning="MODEL_PROSE_MUST_NOT_ENTER_BINDING_DIAGNOSTICS")
        result["decision_analysis"].append(rejected)
        return result

    async def fetch(source, url, *args, **kwargs):
        assert source == "official" and url == "https://example.org/recovery"
        return httpx.Response(200, text=SNIPPET, headers={"content-type": "text/plain"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(synth, "call_model", model)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = {"task": deepcopy(TASK), "evidence_chains": chains}
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    signal = state["quality_signals"][0]
    assert signal["source_facts_received"] == 2 and signal["source_facts_bound"] == 1
    assert signal["analysis_binding"] == {"provided": True, "received": 2, "retained": 1, "rejected": {"basis_invalid_fact": 1}}
    assert "MODEL_PROSE" not in json.dumps(signal)
    assert len(model_calls) == 2
    assert signal["structure_correction"]["outcome"] == "invalid"
    assert state["final_recommendation"]["source_facts"][0]["status"] == "unknown"
    state.update(await CitationValidatorAgent().run(state))
    rec = state["final_recommendation"]
    assert len(rec["decision_analysis"]) == 1
    assert rec["decision_analysis"][0]["review_status"] == "human_review_required"
    assert rec["winner"] == "context_dependent" and rec["action_plan_mode"] == "validation_only"


def test_eligible_fact_inventory_preserves_numbering_and_identity_rules_across_batches():
    from deepchoice.utils.evidence_choices import eligible_source_fact_ids

    def source(title, path, snippet=SNIPPET):
        return {"title": title, "url": "https://example.org/" + path, "snippet": snippet}

    long_text = " ".join(f"Statement {i} describes the saved component." for i in range(17))
    chains = [
        {"sources": [source("First", "one"), source("Ambiguous", "two"),
                     source("Ambiguous", "three"), source("Long", "four", long_text)]},
        {"sources": [source("Next batch", "five")]},
        {"disputed": True, "sources": [source("Disputed", "six")]},
    ]
    before = deepcopy(chains)
    assert eligible_source_fact_ids(chains) == {1, 5}
    assert chains == before
    prompt, mapping = synth._summarize_chains(chains)
    assert mapping[5] == "Next batch" and mapping[6] == "Disputed"
    assert "[[5]] Next batch (score: N/A)\n       Source-fact binding allowed: yes" in prompt
    assert "[[6]] Disputed (score: N/A)\n       Source-fact binding allowed: no" in prompt


@pytest.mark.parametrize("value", [[], None, [""], ["A condition."] * 5, "condition", [42]])
def test_only_explicit_empty_assumptions_are_valid_when_no_extra_premise_is_unknown(value):
    from deepchoice.utils.evidence_choices import bind_evidence_choices
    rec = proposal()
    rec["decision_analysis"][0]["assumptions"] = value
    requirements, _ = synth._decision_requirements(TASK["query"], TASK["constraints"], [], TASK["sub_questions"], [])
    rec = bind_evidence_choices(rec, CHAINS, TASK["candidate_techs"], requirements)
    result = bind_decision_analysis(rec, requirements, TASK["candidate_techs"], require_basis=True)
    assert bool(result["decision_analysis"]) is (value == [])
    if value == []:
        assert result["decision_analysis"][0]["assumptions"] == []
    rec["decision_analysis"][0].pop("assumptions")
    assert not bind_decision_analysis(rec, requirements, TASK["candidate_techs"], require_basis=True)["decision_analysis"]


def test_empty_abstention_does_not_point_to_nonexistent_branches():
    from deepchoice.utils.decision_contract import abstain_recommendation
    for query, forbidden in [('请选择合适方案', '条件分支'), ('Choose a suitable option', 'conditional branches')]:
        original = {'decision_branches': []}
        result = abstain_recommendation(original, query)
        assert result['decision_branches'] == []
        assert forbidden not in result['recommendation']
        assert original == {'decision_branches': []}


@pytest.mark.parametrize('query,forbidden', [('请选择合适方案', '行动计划'), ('Choose a suitable option', 'action plan')])
def test_conditional_abstention_does_not_reference_an_absent_plan(query, forbidden):
    from deepchoice.utils.decision_contract import abstain_recommendation
    branch = {'option': 'ExampleQueue', 'condition': 'If recovery is confirmed.'}
    result = abstain_recommendation({'decision_branches': [branch]}, query)
    assert result['decision_branches'] == [branch]
    assert result['action_plan'] == []
    assert forbidden not in result['recommendation']
