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
    if bad == "fact": item["fact_ids"] = ["F2"]
    elif bad == "question": item["requirement_ids"] = ["A1"]
    elif bad == "option": item["option"] = "InventedCandidate"
    elif bad == "duplicate": item["fact_ids"] *= 2
    elif bad == "overflow": rec["decision_analysis"] *= 9
    elif bad == "kind": item["kind"] = []
    elif bad == "link": item["reasoning"] = "[fake](https://evil.example/)"
    elif bad == "citation": item["reasoning"] = "[Source: forged]"
    elif bad == "long": item["reasoning"] = "x" * 1501
    elif bad == "assumption": item["assumptions"] = []
    requirements, _ = synth._decision_requirements(TASK["query"], TASK["constraints"], [], TASK["sub_questions"], [])
    assert bind_decision_analysis(rec, requirements, TASK["candidate_techs"])["decision_analysis"] == []


def test_model_prose_is_literal_and_never_an_html_or_link_channel():
    from deepchoice.formats.decision import render_decision_details

    rec = proposal()
    rec["source_facts"][0].update(status="verified", source_title="Recovery fixture", saved_text=SNIPPET)
    rec["decision_analysis"][0].update(review_status="human_review_required", reasoning='<img src=x onerror=alert(1)> **verified**', requirements=["question"])
    html = render_safe_report_html("\n".join(render_decision_details(rec, "zh")))
    assert '<img' not in html and '<strong>verified</strong>' not in html
    assert "待人工审阅" in html
