"""Compact question-led synthesis; provenance never grants decision authority."""
from copy import deepcopy

ANSWER_CONTRACT = "question-analysis-v1"


def compact_response(value):
    return isinstance(value, dict) and "answer_contract" in value


def expand_answer_response(value, requirements, query, *, require_compact=False):
    """Discard model authority fields and attach the original request inventory.

    Legacy responses retain their existing validation path. New responses only
    supply facts and bounded analyses; citation and review still gate each item.
    """
    if require_compact and not compact_response(value):
        value = {"answer_contract": "invalid"}
    if not compact_response(value):
        result = deepcopy(value)
        if isinstance(result, dict):
            result.pop("answer_delivery", None)  # The model cannot grant this mode.
        return result
    from .decision_analysis import original_analysis_requirements
    from .question_packet import question_rows
    valid = value.get("answer_contract") == ANSWER_CONTRACT
    inventory = original_analysis_requirements(requirements, query)
    # The answer-slot identity is published once, from the same view the model
    # was offered and the binder validated. Constraint and analysis rows stay in
    # the inventory as context; they are not questions of record.
    questions = [key for key, _ in question_rows(query, requirements or [])]
    return {
        "answer_delivery": {
            "version": ANSWER_CONTRACT,
            "requirements": inventory,
            "questions": [key for key in questions if key in inventory],
        },
        "winner": "context_dependent", "ranked_options": [],
        "source_facts": deepcopy(value.get("source_facts", [])) if valid else [],
        "decision_analysis": deepcopy(value.get("decision_analysis", [])) if valid else [],
    }


def is_answer_delivery(value):
    return (isinstance(value, dict) and isinstance(value.get("answer_delivery"), dict)
            and value["answer_delivery"].get("version") == ANSWER_CONTRACT
            and isinstance(value["answer_delivery"].get("requirements"), dict))


def bound_answer_delivery(value):
    """Runtime-only compatibility projection: no unconditional choice or plan.

    Empty legacy fields prevent parallel, unreviewed explanations from becoming
    a second answer channel. Question labels are not factual satisfaction claims.
    """
    result = deepcopy(value)
    result.update(winner="context_dependent", confidence="low",
                  requirement_assessments=[], decision_branches=[], ranked_options=[],
                  trade_offs=[], unresolved_questions=[], action_plan_mode="validation_only",
                  deployment_readiness="unverified")
    for field in ("winner_rationale", "recommendation", "evidence_summary",
                  "scene_fit_note", "confidence_rationale"):
        result[field] = ""
    return result


def finalize_answer_delivery(value, query, *, requirements_overflow=False):
    """Apply the terminal compatibility projection once after fact/analysis binding.

    The canonical answer and original inventory survive; legacy authority fields
    remain empty. This projection does not verify citations or reasoning.
    """
    from .decision_contract import DECISION_BASIS_VERSION, restrict_action_plan

    result = bound_answer_delivery(value)
    result["decision_basis_version"] = DECISION_BASIS_VERSION
    if requirements_overflow:
        # The legacy assessment limit restricts the plan, not independently
        # bounded question analyses. Citations and review still gate each one.
        result["action_plan"] = []
    else:
        result = restrict_action_plan(result, query, deployment_unverified=True)
        # Original question gaps are rendered from the runtime inventory, not
        # from parallel legacy uncertainty prose produced by this plan adapter.
        result["unresolved_questions"] = []
    return result
