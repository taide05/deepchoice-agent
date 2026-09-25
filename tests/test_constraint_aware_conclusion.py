import asyncio
from copy import deepcopy

import pytest

from deepchoice.agents import conclusion_synthesizer as cs_mod
from deepchoice.utils.decision_contract import (
    MAX_REQUIREMENT_ASSESSMENTS,
    abstain_recommendation,
    restrict_recommendation,
)


def _source_state() -> dict:
    return {
        "task": {
            "query": "Choose a queue for reliable order processing",
            "scene_context": "team",
            "constraints": ["Consumers must be idempotent"],
            "sub_questions": ["Which delivery guarantee is required?"],
        },
        "constraints": [
            "Consumers must be idempotent",
            "Migration must be staged and reversible",
        ],
        "sub_questions": ["How will rollback be verified?"],
        "evidence_chains": [{
            "evidence_strength": "strong",
            "conclusion": "Queue operating model",
            "disputed": False,
            "sources": [{
                "title": "Queue Operations Guide",
                "url": "https://example.test/queue",
                "snippet": "Consumers use idempotency keys; staged migration verifies lag before rollback.",
            }],
        }],
        "conflicts": [],
        "source_scores": [],
        "token_usage": [],
    }


def _complete_model_result() -> dict:
    return {
        "winner": "RabbitMQ",
        "winner_rationale": "RabbitMQ fits the verified requirements [[1]].",
        "recommendation": "Adopt RabbitMQ after the staged validation [[1]].",
        "ranked_options": [{
            "name": "RabbitMQ",
            "rank": 1,
            "constraint_fit": "high",
            "constraint_fit_reason": "Matches the verified operating model [[1]].",
            "rationale": "The staged plan is documented [[1]].",
            "key_strength": "Idempotent consumer guidance [[1]].",
            "key_weakness": "Rollback still requires rehearsal [[1]].",
        }],
        "trade_offs": [],
        "evidence_summary": "The operating guide covers the critical path [[1]].",
        "confidence": "medium",
        "confidence_rationale": "One directly usable source supports the bounded choice [[1]].",
        "requirement_assessments": [
            {
                "id": identifier,
                "requirement": "model may not rewrite canonical text",
                "status": "satisfied",
                "decision_critical": False,
                "explanation": "The guide covers this bounded requirement [[1]].",
                "evidence_ids": [1],
            }
            for identifier in (
                "C1", "A1", "A2", "A3", "A4", "A5", "A6", "Q1", "Q2",
            )
        ],
        "decision_branches": [{
            "option": "RabbitMQ",
            "condition": "Choose it only if the lag rehearsal passes [[1]].",
        }],
        "action_plan": [{
            "step": "Add idempotency keys before dual delivery [[1]].",
            "verification": "Verify duplicate deliveries are harmless [[1]].",
            "change_trigger": "Advance when lag stays within the agreed bound [[1]].",
            "rollback": "Stop dual delivery and restore the prior consumer [[1]].",
        }],
        "unresolved_questions": [],
        "scene_fit_note": "The staged plan fits the team context [[1]].",
    }


def _fake_call(result: dict, captured: list | None = None):
    async def call(prompt, **kwargs):
        if captured is not None:
            captured.append(prompt)
        return deepcopy(result)

    return call


def test_complete_bound_requirements_keep_conditional_winner(monkeypatch):
    captured = []
    monkeypatch.setattr(
        cs_mod,
        "call_model",
        _fake_call(_complete_model_result(), captured),
    )

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_source_state()))
    recommendation = result["final_recommendation"]

    assert recommendation["winner"] == "RabbitMQ"
    assert [item["id"] for item in recommendation["requirement_assessments"]] == [
        "C1", "A1", "A2", "A3", "A4", "A5", "A6", "Q1", "Q2",
    ]
    assert recommendation["requirement_assessments"][0]["decision_critical"] is True
    assert recommendation["requirement_assessments"][1]["decision_critical"] is True
    assert recommendation["requirement_assessments"][0]["requirement"] == (
        "Consumers must be idempotent"
    )
    assert "[Source: Queue Operations Guide]" in (
        recommendation["requirement_assessments"][-1]["explanation"]
    )
    prompt_text = captured[0][0]["content"]
    assert "C1 [frozen-constraint]: Consumers must be idempotent" in prompt_text
    assert "A1 [analysis-constraint]: Migration must be staged and reversible" in prompt_text
    assert "Q1 [frozen-sub-question]: Which delivery guarantee is required?" in prompt_text
    assert "Q2 [analysis-sub-question]: How will rollback be verified?" in prompt_text
    assert "Idempotency ownership and verification" in prompt_text
    assert "Rollback procedure and restored-state verification" in prompt_text


def test_missing_critical_assessment_removes_winner_rank_and_old_prose(monkeypatch):
    model_result = _complete_model_result()
    model_result["requirement_assessments"] = model_result["requirement_assessments"][:-1]
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(model_result))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_source_state()))
    recommendation = result["final_recommendation"]

    assert recommendation["winner"] == "context_dependent"
    assert recommendation["ranked_options"] == []
    assert recommendation["winner_rationale"] == ""
    assert recommendation["scene_fit_note"] == ""
    assert recommendation["trade_offs"] == []
    assert recommendation["evidence_summary"] == ""
    assert recommendation["confidence"] == "low"
    question = recommendation["requirement_assessments"][-1]
    assert question["status"] == "unknown"
    assert question["requirement"] in recommendation["unresolved_questions"]
    assert "Adopt RabbitMQ" not in recommendation["recommendation"]


def test_disputed_or_snippetless_source_cannot_bind_decisive_answer(monkeypatch):
    state = _source_state()
    state["evidence_chains"][0]["disputed"] = True
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(_complete_model_result()))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(state))
    recommendation = result["final_recommendation"]

    assert recommendation["winner"] == "context_dependent"
    assert {
        item["status"] for item in recommendation["requirement_assessments"]
    } == {"unknown"}
    assert all(
        item["evidence_ids"] == []
        for item in recommendation["requirement_assessments"]
    )


def test_noncritical_question_requires_literal_false(monkeypatch):
    state = _source_state()
    state["task"]["query"] = "Choose a library"
    state["task"]["constraints"] = []
    state["task"]["sub_questions"] = []
    state["constraints"] = []
    model_result = _complete_model_result()
    model_result["requirement_assessments"] = [{
        "id": "Q1",
        "requirement": "How will rollback be verified?",
        "status": "unknown",
        "decision_critical": False,
        "explanation": "Unknown.",
        "evidence_ids": [],
    }]
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(model_result))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(state))

    assert result["final_recommendation"]["winner"] == "RabbitMQ"
    assert result["final_recommendation"]["requirement_assessments"][0][
        "decision_critical"
    ] is False


def test_requirement_overflow_abstains_without_emitting_over_cap_rows(monkeypatch):
    state = _source_state()
    state["task"]["query"] = "Choose a database"
    state["task"]["constraints"] = [
        f"constraint {index}" for index in range(MAX_REQUIREMENT_ASSESSMENTS + 1)
    ]
    state["constraints"] = []
    state["sub_questions"] = []
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(_complete_model_result()))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(state))
    recommendation = result["final_recommendation"]

    assert recommendation["winner"] == "context_dependent"
    assert recommendation["requirement_assessments"] == []
    assert "exceed" in recommendation["unresolved_questions"][0]


def test_restriction_helpers_are_pure_and_clear_unconditional_assertions():
    original = _complete_model_result()
    original["trade_offs"] = [{"finding": "100% reliable", "impact": "none"}]
    original_copy = deepcopy(original)

    restricted = restrict_recommendation(original, "请选择队列")
    abstained = abstain_recommendation(original, "Choose a queue", "missing evidence")

    assert original == original_copy
    for result in (restricted, abstained):
        assert result["winner"] == "context_dependent"
        assert result["ranked_options"] == []
        assert result["winner_rationale"] == ""
        assert result["trade_offs"] == []
        assert result["evidence_summary"] == ""
        assert result["confidence"] == "low"
        assert result["decision_branches"]
        assert result["action_plan"]


def test_incomplete_action_step_becomes_fixed_validation_without_withdrawing_winner(monkeypatch):
    model_result = _complete_model_result()
    del model_result["action_plan"][0]["rollback"]
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(model_result))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_source_state()))
    recommendation = result["final_recommendation"]

    assert recommendation["winner"] == "RabbitMQ"
    assert recommendation["action_plan_mode"] == "validation_only"
    assert "dual delivery" not in str(recommendation["action_plan"])
    assert "Observe the current system read-only" in str(recommendation["action_plan"])
    assert any(
        "Action-plan evidence is unverified" in item
        for item in recommendation["unresolved_questions"]
    )


def test_malformed_top_level_model_output_becomes_safe_abstention(monkeypatch):
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(["not", "an", "object"]))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_source_state()))

    assert result["final_recommendation"]["winner"] == "context_dependent"
    assert result["final_recommendation"]["ranked_options"] == []


def test_malformed_nested_model_fields_do_not_raise(monkeypatch):
    model_result = _complete_model_result()
    model_result["winner"] = 42
    model_result["ranked_options"] = [{
        "name": ["RabbitMQ"],
        "constraint_fit": {"bad": "shape"},
        "rationale": {"bad": "shape"},
    }, "not-an-option"]
    model_result["trade_offs"] = [{"finding": ["bad"], "impact": {"bad": 1}}]
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(model_result))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_source_state()))

    assert result["final_recommendation"]["winner"] == "context_dependent"
    assert result["final_recommendation"]["ranked_options"] == []


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Choose the default formatter for a small project", 0),
        ("Compare switchboard visualization libraries", 0),
        ("Compare reliable storage", 1),
        ("Choose a queue with retry support", 3),
        ("比较任务队列的重试与迁移", 5),
    ],
)
def test_operational_obligations_match_words_not_accidental_substrings(query, expected):
    requirements, overflow = cs_mod._decision_requirements(query, [], [], [], [])
    assert not overflow
    assert sum(item["kind"] == "operational_obligation" for item in requirements) == expected
