"""Unresolved premises cannot publish model-authored production procedures."""

from copy import deepcopy

import pytest

from deepchoice.agents.citation_validator import _calibrate_decision
from deepchoice.agents.conclusion_synthesizer import _normalize_decision_contract
from deepchoice.citations import (
    CitationCheck, CitationReason, CitationStatus, CitationStatusCounts, CitationVerification,
)
from deepchoice.formats.decision import render_decision_details
from deepchoice.formats.evidence_first import render as render_evidence_first
from deepchoice.utils.decision_contract import abstain_recommendation, restrict_recommendation


def _recommendation():
    return {
        "decision_basis_version": "constraint-aware-v1",
        "winner": "context_dependent",
        "requirement_assessments": [{
            "id": "A1", "requirement": "Preserve acknowledged writes during rollback",
            "status": "unknown", "decision_critical": True,
            "explanation": "Rollback evidence is missing", "evidence_ids": [],
        }],
        "decision_branches": [{"option": "SQLite", "condition": "If measured lock waits fit the agreed target"}],
        "action_plan_mode": "production_approved",  # An untrusted model cannot grant authority.
        "action_plan": [{
            "step": "DUAL_WRITE_LIVE then switch reads and writes",
            "verification": "Compare the two databases",
            "change_trigger": "Switch when it appears ready",
            "rollback": "RESTORE_OLD_SNAPSHOT without replaying acknowledged writes",
        }],
    }


@pytest.mark.parametrize("query,phrase", [("Choose a database", "isolated"), ("选择数据库", "隔离")])
@pytest.mark.parametrize("restrict", [abstain_recommendation, restrict_recommendation])
def test_abstention_replaces_operations_with_non_production_validation(restrict, query, phrase):
    original = _recommendation()
    before = deepcopy(original)
    result = restrict(original, query)
    assert original == before
    assert result["action_plan_mode"] == "validation_only"
    assert result["action_plan"] and phrase in str(result["action_plan"])
    assert "DUAL_WRITE_LIVE" not in str(result)
    assert "RESTORE_OLD_SNAPSHOT" not in str(result)
    assert result["decision_branches"] == before["decision_branches"]
    assert restrict(result, query) == result


def test_citation_calibration_also_blocks_already_unknown_operational_premises():
    verification = CitationVerification(status_counts=CitationStatusCounts(), checks=())
    result = _calibrate_decision(_recommendation(), verification, "Choose a database")
    assert result["action_plan_mode"] == "validation_only"
    assert "DUAL_WRITE_LIVE" not in str(result)
    assert "acknowledged writes" in str(result["action_plan"])
    assert "prohibit rollback" in str(result["action_plan"])


def test_model_cannot_forge_validation_only_mode():
    original = _recommendation()
    original["action_plan_mode"] = "validation_only"
    result, _ = _normalize_decision_contract(original, [], set())
    assert result["action_plan_mode"] == "proposed"


def test_non_abstaining_proposal_is_not_replaced_or_mislabeled_as_validation_only():
    original = _recommendation()
    original["winner"] = "SQLite"
    original["winner_rationale"] = "A bounded claim [Source: Docs]"
    original["action_plan_mode"] = "proposed"
    original["requirement_assessments"][0].update(
        status="satisfied", explanation="A bounded claim [Source: Docs]", evidence_ids=[1],
    )
    original["action_plan"] = [{"step": "Rehearse recovery on an isolated copy",
                                "verification": "Compare the restored data",
                                "change_trigger": "Request a review after rehearsal",
                                "rollback": "Discard the isolated copy"}]
    check = CitationCheck(
        claim_id="one", claim_path="final_recommendation.requirement_assessments[0].explanation",
        claim_text="A bounded claim", source_title="Docs", status=CitationStatus.VERIFIED,
        reason=CitationReason.LEXICAL_SUPPORT,
    )
    winner_check = check.model_copy(update={
        "claim_id": "winner", "claim_path": "final_recommendation.winner_rationale",
    })
    action_checks = tuple(
        check.model_copy(update={
            "claim_id": f"action-{field}",
            "claim_path": f"final_recommendation.action_plan[0].{field}",
        })
        for field in ("step", "verification", "change_trigger", "rollback")
    )
    verification = CitationVerification(
        status_counts=CitationStatusCounts(verified=6),
        checks=(check, winner_check, *action_checks),
    )
    result = _calibrate_decision(original, verification, "Choose a database")
    assert result == {**original, "deployment_readiness": "unverified"}
    # Lexical support preserves the proposal, not deployment authorization.


def test_non_abstaining_choice_replaces_unverified_production_actions():
    original = _recommendation()
    original["winner"] = "SQLite"
    original["winner_rationale"] = "A bounded claim [Source: Docs]"
    original["action_plan_mode"] = "proposed"
    original["requirement_assessments"][0].update(
        status="satisfied", explanation="A bounded claim [Source: Docs]", evidence_ids=[1],
    )
    verified = CitationCheck(
        claim_id="requirement",
        claim_path="final_recommendation.requirement_assessments[0].explanation",
        claim_text="A bounded claim",
        source_title="Docs",
        status=CitationStatus.VERIFIED,
        reason=CitationReason.LEXICAL_SUPPORT,
    )
    action_checks = tuple(
        CitationCheck(
            claim_id=f"action-{field}",
            claim_path=f"final_recommendation.action_plan[0].{field}",
            claim_text=original["action_plan"][0][field],
            status=CitationStatus.UNSUPPORTED,
            reason=CitationReason.CITATION_MISSING,
        )
        for field in ("step", "verification", "change_trigger", "rollback")
    )
    verification = CitationVerification(
        status_counts=CitationStatusCounts(verified=2, unsupported=4),
        checks=(
            verified,
            verified.model_copy(update={
                "claim_id": "winner",
                "claim_path": "final_recommendation.winner_rationale",
            }),
            *action_checks,
        ),
    )

    result = _calibrate_decision(original, verification, "Choose a database")

    assert result["winner"] == "SQLite"
    assert result["action_plan_mode"] == "validation_only"
    assert "DUAL_WRITE_LIVE" not in str(result)
    assert "RESTORE_OLD_SNAPSHOT" not in str(result)
    assert "production changes" in str(result["action_plan"])


@pytest.mark.parametrize("field", ("step", "verification", "change_trigger", "rollback"))
@pytest.mark.parametrize("outcome", (
    "field_missing", "check_missing", "unsupported", "unknown", "unreachable",
))
def test_each_incomplete_or_unverified_action_field_restricts_the_entire_plan(field, outcome):
    original = _recommendation()
    original["winner"] = "SQLite"
    original["winner_rationale"] = "A bounded claim [Source: Docs]"
    original["action_plan_mode"] = "proposed"
    original["requirement_assessments"][0].update(
        status="satisfied", explanation="A bounded claim [Source: Docs]", evidence_ids=[1],
    )
    verified = CitationCheck(
        claim_id="requirement",
        claim_path="final_recommendation.requirement_assessments[0].explanation",
        claim_text="A bounded claim",
        source_title="Docs",
        status=CitationStatus.VERIFIED,
        reason=CitationReason.LEXICAL_SUPPORT,
    )
    checks = [
        verified,
        verified.model_copy(update={
            "claim_id": "winner",
            "claim_path": "final_recommendation.winner_rationale",
        }),
    ]
    status_reason = {
        "unsupported": (CitationStatus.UNSUPPORTED, CitationReason.CITATION_MISSING),
        "unknown": (CitationStatus.UNKNOWN, CitationReason.CONTENT_INSUFFICIENT),
        "unreachable": (CitationStatus.UNREACHABLE, CitationReason.NOT_PUBLICLY_ACCESSIBLE),
    }
    if outcome == "field_missing":
        original["action_plan"][0].pop(field)
    for action_field in ("step", "verification", "change_trigger", "rollback"):
        if action_field == field and outcome in {"field_missing", "check_missing"}:
            continue
        status, reason = status_reason.get(
            outcome if action_field == field else "",
            (CitationStatus.VERIFIED, CitationReason.LEXICAL_SUPPORT),
        )
        checks.append(CitationCheck(
            claim_id=f"action-{action_field}",
            claim_path=f"final_recommendation.action_plan[0].{action_field}",
            claim_text=original["action_plan"][0][action_field],
            source_title="Docs" if status == CitationStatus.VERIFIED else None,
            status=status,
            reason=reason,
        ))
    verification = CitationVerification(
        status_counts=CitationStatusCounts(), checks=tuple(checks),
    )

    result = _calibrate_decision(original, verification, "Choose a database")

    assert result["winner"] == "SQLite"
    assert result["action_plan_mode"] == "validation_only"
    assert "DUAL_WRITE_LIVE" not in str(result)
    assert "RESTORE_OLD_SNAPSHOT" not in str(result)
    assert "Observe the current system read-only" in str(result["action_plan"])
    assert "Action-plan evidence is unverified" in str(result["unresolved_questions"])


@pytest.mark.parametrize("lang,query,label", [
    ("zh", "选择数据库", "仅隔离验证；禁止生产变更"),
    ("en", "Choose a database", "Isolated validation only; no production changes"),
])
def test_validation_plan_renders_an_explicit_non_authorization_boundary(lang, query, label):
    result = abstain_recommendation(_recommendation(), query)
    report = "\n".join(render_decision_details(result, lang))
    assert label in report
    assert "DUAL_WRITE_LIVE" not in report and "RESTORE_OLD_SNAPSHOT" not in report
    assert "SQLite" in report and "measured lock waits" in report


@pytest.mark.parametrize("plan", [None, [], [{"step": "Incomplete"}], [{"step": "overflow"}] * 21])
def test_invalid_plan_does_not_create_a_fake_validated_procedure(plan):
    original = _recommendation()
    original["action_plan"] = plan
    result = abstain_recommendation(original, "Choose a database")
    assert result["action_plan_mode"] == "validation_only"
    assert result["action_plan"] == []


def test_evidence_first_does_not_invite_generic_prototype_when_plan_is_restricted():
    recommendation = abstain_recommendation(_recommendation(), "选择 Celery")
    report = render_evidence_first({
        "task": {"query": "选择 Celery"},
        "final_recommendation": recommendation,
        "evidence_chains": [],
        "conflicts": [],
    })

    assert "仅执行上方隔离验证计划；不要进行生产变更" in report
    assert "用推荐方案做快速原型验证" not in report
