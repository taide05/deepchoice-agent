"""Offline scope controls with invented evidence; no live quality measurement."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.utils.decision_contract import is_fixed_validation_only_plan


def _requirements(query="", constraints=(), questions=(), analysis=()):
    rows, overflow = synth._decision_requirements(
        query, list(constraints), list(analysis), list(questions), [],
    )
    assert not overflow
    return rows


def _operational(rows):
    return [row for row in rows if row["kind"] == "operational_obligation"]


def test_frozen_development_scope_preserves_every_original_constraint_and_question():
    data = json.loads((Path(__file__).parents[1] / "benchmarks/quality-selection-development-v1.json").read_text(encoding="utf-8"))
    expected = {"P01": 0, "P04": 3, "P08": 0, "P02": 0}
    for case in data["cases"]:
        task = case["request"]
        rows, overflow = synth._decision_requirements(
            task["query"], task["constraints"], [], task["sub_questions"], [],
            task["scene_context"],
        )
        assert not overflow
        assert len(_operational(rows)) == expected[case["case_id"]]
        assert [r["requirement"] for r in rows if r["kind"] == "frozen_constraint"] == task["constraints"]
        assert [r["requirement"] for r in rows if r["kind"] == "frozen_sub_question"] == task["sub_questions"]


@pytest.mark.parametrize("text", [
    "Explain when to migrate.", "必须说明未来迁移触发条件", "是否存在过渡方案？",
    "When do we need a migration plan?", "说明何时制定迁移方案",
    "No need for a migration plan.", "Do not provide rollback steps.",
    "Migration plan not required.", "不需要迁移方案，只需选型条件",
    "无需说明如何迁移", "Choose the default switchboard library",
    "比较 A/B 的迁移方案成本", "迁移方案有哪些风险？", "Compare migration plan costs.",
])
def test_trigger_selection_and_negated_requests_do_not_require_a_runbook(text):
    rows = _requirements(text)
    assert _operational(rows) == []


@pytest.mark.parametrize("field", ["query", "constraints", "questions"])
@pytest.mark.parametrize("text", [
    "Provide a migration plan and rollback procedure.",
    "How should we migrate?", "Give cutover steps.",
    "必须给出迁移步骤和回退方案", "如何迁移？", "需要无停机迁移方案",
    "无需生产切换，但请给出迁移步骤", "何时迁移以及如何迁移？",
    "Do not cut over but provide a migration plan.", "When and how should we migrate?",
])
def test_explicit_original_procedure_requests_keep_critical_explanation_duties(field, text):
    kwargs = {field: text if field == "query" else [text]}
    rows = _requirements(**kwargs)
    assert len(_operational(rows)) == 2
    result, withdraw = synth._normalize_decision_contract(
        {"winner": "ExampleStore", "requirement_assessments": []}, rows, set(), text,
    )
    assert withdraw
    assert all(row["status"] == "unknown" and row["decision_critical"] for row in result["requirement_assessments"])
    assert is_fixed_validation_only_plan(result, text)


def test_analyzer_procedure_text_does_not_generate_extra_operational_rows():
    text = "Provide a migration plan and rollback procedure."
    rows = _requirements("Compare the stores.", analysis=[text])
    assert _operational(rows) == []
    # Existing analysis constraints remain critical; only extra synthetic duties are suppressed.
    assert rows == [{"id": "A1", "requirement": text, "kind": "analysis_constraint"}]
    result, withdraw = synth._normalize_decision_contract({}, rows, set(), "Compare the stores.")
    assert withdraw and is_fixed_validation_only_plan(result, "Compare the stores.")


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, False])
async def test_selection_trigger_does_not_veto_supported_choice_or_authorize_operations(monkeypatch, supported):
    query = "Choose ExampleStore or OtherStore and explain when to migrate."
    question = "When should migration be considered?"
    fact = "A service is appropriate when concurrent writers cannot wait in a queue."
    task = {"query": query, "sub_questions": [question], "candidate_techs": ["ExampleStore", "OtherStore"]}
    rows = _requirements(query, questions=[question])
    assert len(rows) == 1 and rows[0]["id"] == "Q1"
    proposal = {
        "winner": "ExampleStore", "winner_rationale": fact + " [[1]]",
        "ranked_options": [], "recommendation": "", "confidence": "medium",
        "source_facts": [], "decision_analysis": [],
        "requirement_assessments": [{
            "id": "Q1", "requirement": question, "status": "satisfied",
            "explanation": fact + " [[1]]", "evidence_ids": [1],
        }],
        "action_plan_mode": "production_approved", "deployment_readiness": "ready",
        "action_plan": [{
            "step": "UNSAFE_PRODUCTION_CUTOVER", "verification": "Assume ready",
            "change_trigger": "Immediately", "rollback": "OVERWRITE_NEW_WRITES",
        }],
    }
    state = {
        "task": task,
        "evidence_chains": [{"sources": [{
            "title": "Invented scope fixture", "url": "https://example.org/scope",
            "snippet": fact,
        }]}],
    }

    async def model(*args, **kwargs):
        return deepcopy(proposal)

    async def fetch(url, *args, **kwargs):
        body = fact if supported else "This fixture instead describes unrelated colors and shapes."
        return httpx.Response(200, text=body, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(synth, "call_model", model)
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    assert state["final_recommendation"]["winner"] == "ExampleStore"
    assert is_fixed_validation_only_plan(state["final_recommendation"], query)
    state.update(await CitationValidatorAgent().run(state))
    rec = state["final_recommendation"]
    assert rec["winner"] == ("ExampleStore" if supported else "context_dependent")
    assert rec["deployment_readiness"] == "unverified"
    assert is_fixed_validation_only_plan(rec, query)
    for renderer in FORMAT_RENDERERS.values():
        report = renderer(state)
        assert question in report and "UNSAFE_PRODUCTION_CUTOVER" not in report
        assert "OVERWRITE_NEW_WRITES" not in report
