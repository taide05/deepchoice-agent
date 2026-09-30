"""Synthetic offline controls: selection evidence is not a completed deployment drill.

These invented fixture sentences test control flow, not real queue capabilities.
No model, DNS or external HTTP request is made.
"""
from copy import deepcopy

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.evidence_decision_gate import should_request_evidence_decision
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.formats.decision import render_decision_details
from deepchoice.utils.decision_contract import (
    abstain_recommendation, is_fixed_validation_only_plan, restrict_recommendation,
)


QUERY = "Choose a background task queue and discuss restart recovery"
FACTS = [
    "Delivery retries can cause duplicate task processing.",
    "The application owns idempotency verification for side effects.",
    "Recovery replays tasks from a durable journal after process restart.",
]
OLD_DRILL = "Recovery behavior is verified across the declared process and dependency failures."


def _requirements():
    requirements, overflow = synth._decision_requirements(QUERY, [], [], [], [])
    assert not overflow and len(requirements) == 3
    return requirements


def _proposal(requirements):
    return {
        "winner": "ExampleQueue", "winner_rationale": FACTS[2] + " [[3]]",
        "ranked_options": [], "recommendation": "", "confidence": "medium",
        "deployment_readiness": {"status": "ready", "proof": "MODEL_FORGERY"},
        "action_plan_mode": "production_approved",
        "requirement_assessments": [{
            "id": row["id"], "requirement": "MODEL_REPLACEMENT",
            "status": "satisfied", "decision_critical": False,
            "assessment_scope": "deployment_only", "kind": "noncritical",
            "explanation": FACTS[index % 3] + f" [[{index % 3 + 1}]]",
            "evidence_ids": [index % 3 + 1],
        } for index, row in enumerate(requirements)],
        "action_plan": [{
            "step": "UNSAFE_PRODUCTION_CUTOVER", "verification": "Assume ready",
            "change_trigger": "Do it now", "rollback": "OVERWRITE_NEW_WRITES",
        }],
    }


def _normalized(requirements=None, proposal=None):
    requirements = _requirements() if requirements is None else requirements
    return synth._normalize_decision_contract(
        _proposal(requirements) if proposal is None else proposal,
        requirements, {1, 2, 3}, QUERY,
    )


@pytest.mark.parametrize("plan", [None, [], "malformed", [{}], "unsafe", "missing"])
def test_supported_selection_does_not_need_completed_drill_or_model_plan(plan):
    requirements = _requirements()
    assert "mechanisms, prerequisites and limits" in requirements[2]["requirement"]
    assert OLD_DRILL not in str(requirements)
    proposal = _proposal(requirements)
    if plan == "missing":
        proposal.pop("action_plan")
    elif plan != "unsafe":
        proposal["action_plan"] = plan
    result, withdraw = _normalized(requirements, proposal)
    assert not withdraw and result["winner"] == "ExampleQueue"
    assert result["deployment_readiness"] == "unverified"
    assert all(row["decision_critical"] for row in result["requirement_assessments"])
    assert all(row["status"] == "satisfied" for row in result["requirement_assessments"])
    assert is_fixed_validation_only_plan(result, QUERY) and len(result["action_plan"]) == 4
    assert "UNSAFE_PRODUCTION" not in str(result) and "MODEL_FORGERY" not in str(result)
    assert any("deployment acceptance" in gap for gap in result["unresolved_questions"])


@pytest.mark.parametrize("field", ["constraints", "questions", "analysis"])
def test_explicit_drill_requirement_stays_critical_even_when_model_forges_scope(field):
    requirements, _ = synth._decision_requirements(
        QUERY, [OLD_DRILL] if field == "constraints" else [],
        [OLD_DRILL] if field == "analysis" else [],
        [OLD_DRILL] if field == "questions" else [], [],
    )
    proposal = _proposal(requirements)
    explicit = next(row for row in requirements if row["requirement"] == OLD_DRILL)
    row = next(row for row in proposal["requirement_assessments"] if row["id"] == explicit["id"])
    row.update(status="unknown", explanation="", evidence_ids=[])
    result, withdraw = _normalized(requirements, proposal)
    row = next(row for row in result["requirement_assessments"] if row["id"] == explicit["id"])
    assert withdraw and row["decision_critical"] and row["requirement"] == OLD_DRILL
    assert row["status"] == "unknown" and "assessment_scope" not in row


@pytest.mark.parametrize("failure", ["unknown", "contradicted", "missing_citation", "unusable_source"])
def test_recovery_technical_premise_still_fails_closed(failure):
    requirements = _requirements()
    proposal = _proposal(requirements)
    row = proposal["requirement_assessments"][2]
    if failure in {"unknown", "contradicted"}:
        row["status"] = failure
    elif failure == "missing_citation":
        row["explanation"] = FACTS[2]
    else:
        row.update(explanation=FACTS[2] + " [[99]]", evidence_ids=[99])
    result, withdraw = _normalized(requirements, proposal)
    assert withdraw and result["requirement_assessments"][2]["status"] != "satisfied"
    restricted = abstain_recommendation(result, QUERY)
    assert restricted["winner"] == "context_dependent"
    assert is_fixed_validation_only_plan(restricted, QUERY)


@pytest.mark.asyncio
@pytest.mark.parametrize("source_supports", [True, False])
async def test_synthesis_citation_render_and_hitl_keep_the_two_decisions_separate(monkeypatch, source_supports):
    state = {
        "task": {"query": QUERY},
        "evidence_chains": [{"sources": [{
            "title": f"Fixture {index}", "url": f"https://example.org/{index}",
            "snippet": fact,
        }]} for index, fact in enumerate(FACTS, 1)],
    }
    calls = []

    async def model(*args, **kwargs):
        return _proposal(_requirements())

    monkeypatch.setattr(synth, "call_model", model)
    synthesis_output = await synth.ConclusionSynthesizerAgent().run(state)
    state.update(synthesis_output)
    assert state["final_recommendation"]["winner"] == "ExampleQueue"

    async def fetch(url, *args, **kwargs):
        calls.append(url)
        body = " ".join(FACTS) if source_supports else "Unrelated content about database indexes and weather."
        return httpx.Response(200, text=body, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    before = deepcopy(state)
    output = await CitationValidatorAgent().run(state)
    assert state == before and len(calls) == 3
    calibrated = output["final_recommendation"]
    assert calibrated["deployment_readiness"] == "unverified"
    assert is_fixed_validation_only_plan(calibrated, QUERY)
    assert calibrated["winner"] == ("ExampleQueue" if source_supports else "context_dependent")
    checks = output["citation_verification"]["checks"]
    assert not any("action_plan" in row["claim_path"] or "deployment_readiness" in row["claim_path"] for row in checks)
    if source_supports:
        assert all(row["status"] == "verified" for row in checks)
        # A second pass cannot grant deployment readiness, even from a forged marker.
        repeated = deepcopy({**state, **output})
        repeated["final_recommendation"]["deployment_readiness"] = "ready"
        again = await CitationValidatorAgent().run(repeated)
        assert again["final_recommendation"] == calibrated
    final_state = {**state, **output}
    assert should_request_evidence_decision(final_state) is (not source_supports)
    for renderer in FORMAT_RENDERERS.values():
        report = renderer(final_state)
        assert "Deployment acceptance: unverified" in report
        assert "no production changes" in report and "UNSAFE_PRODUCTION" not in report


def test_limited_report_cannot_promote_deployment_or_selection_evidence():
    rec, _ = _normalized()
    rec["deployment_readiness"] = "ready"
    limited = restrict_recommendation(rec, QUERY)
    assert limited["deployment_readiness"] == "unverified"
    assert limited["winner"] == "context_dependent"
    assert all(row["status"] == "unknown" for row in limited["requirement_assessments"])
    assert is_fixed_validation_only_plan(limited, QUERY)
    assert restrict_recommendation(limited, QUERY) == limited


def test_p04_shaped_chinese_five_obligations_keep_selection_separate_from_four_stage_rehearsal():
    query = "后台长任务应继续用进程内任务还是 Celery？讨论故障恢复，制定迁移步骤和回退方案。"
    requirements, overflow = synth._decision_requirements(
        query, ["不得把队列描述为天然 exactly-once"], [], [], [],
    )
    assert not overflow
    assert len([row for row in requirements if row["kind"] == "operational_obligation"]) == 5
    assert any("恢复机制、前提和限制" in row["requirement"] for row in requirements)
    proposal = _proposal(requirements)
    proposal["action_plan"] = []
    rec, withdraw = synth._normalize_decision_contract(proposal, requirements, {1, 2, 3}, query)
    assert not withdraw and rec["winner"] == "ExampleQueue"
    assert all(row["decision_critical"] for row in rec["requirement_assessments"])
    assert rec["deployment_readiness"] == "unverified"
    assert is_fixed_validation_only_plan(rec, query) and len(rec["action_plan"]) == 4
    rendered = "\n".join(render_decision_details(rec, "zh"))
    assert "部署验收：未验证" in rendered and "禁止生产变更" in rendered
    assert "任务" in rendered and "故障矩阵" in rendered and "幂等" in rendered
