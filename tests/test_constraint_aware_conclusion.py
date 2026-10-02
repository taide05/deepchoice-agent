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


def _p08_state(*, supplemental_input: str | None = None) -> dict:
    state = {
        "task": {
            "query": "帮我在 Redis 和 Memcached 之间选择缓存。",
            "scene_context": (
                "请求没有说明数据结构、持久化、淘汰策略、部署环境或团队能力。"
            ),
            "constraints": [
                (
                    "缺少会改变选择的约束时应明确列出未知并给条件性结论；"
                    "仅在满足项目证据不足 gate 时进行交互"
                ),
                "不得自行编造流量和一致性要求",
            ],
            "sub_questions": [
                "哪些未知约束会改变选择？",
                "补充信息后如何形成条件性结论？",
            ],
        },
        "constraints": [],
        "sub_questions": [],
        "evidence_chains": [{
            "evidence_strength": "strong",
            "conclusion": "缓存选型取决于所需能力",
            "disputed": False,
            "sources": [{
                "title": "缓存能力说明",
                "url": "https://example.test/cache",
                "snippet": "Redis 与 Memcached 提供不同的数据结构和持久化能力。",
            }],
        }],
        "conflicts": [],
        "source_scores": [],
        "token_usage": [],
    }
    if supplemental_input is not None:
        state["_supplemental_input"] = supplemental_input
    return state


def _p08_overconfident_model_result() -> dict:
    return {
        "winner": "Redis",
        "winner_rationale": "Redis 的能力更丰富，因此应直接选择 Redis [[1]].",
        "recommendation": "立即采用 Redis [[1]].",
        "ranked_options": [
            {
                "name": "Redis",
                "rank": 1,
                "constraint_fit": "high",
                "constraint_fit_reason": "能力范围更广 [[1]].",
                "rationale": "覆盖更多缓存场景 [[1]].",
                "key_strength": "支持更多数据结构 [[1]].",
                "key_weakness": "运维面更大 [[1]].",
            },
            {
                "name": "Memcached",
                "rank": 2,
                "constraint_fit": "medium",
                "constraint_fit_reason": "适合简单键值缓存 [[1]].",
                "rationale": "能力范围较窄 [[1]].",
                "key_strength": "模型简单 [[1]].",
                "key_weakness": "缺少部分能力 [[1]].",
            },
        ],
        "trade_offs": [],
        "evidence_summary": "来源描述了两者的能力差异 [[1]].",
        "confidence": "medium",
        "confidence_rationale": "来源可用于比较能力边界 [[1]].",
        "requirement_assessments": [
            {
                "id": identifier,
                "requirement": "模型不得改写冻结要求",
                "status": "satisfied",
                "decision_critical": True,
                "explanation": "该要求已由来源覆盖 [[1]].",
                "evidence_ids": [1],
            }
            for identifier in ("C1", "C2", "Q1", "Q2")
        ],
        "decision_branches": [
            {
                "option": "Redis",
                "condition": "若需要复杂数据结构或持久化，则选择 Redis [[1]].",
            },
            {
                "option": "Memcached",
                "condition": "若只需简单可再生键值缓存，则选择 Memcached [[1]].",
            },
        ],
        "action_plan": [{
            "step": "在隔离环境中验证候选缓存 [[1]].",
            "verification": "检查命中率和故障恢复 [[1]].",
            "change_trigger": "关键约束明确后再推进 [[1]].",
            "rollback": "停止试验并保留现有缓存路径 [[1]].",
        }],
        "unresolved_questions": [],
        "scene_fit_note": "Redis 更适合当前请求 [[1]].",
    }


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
        "C1", "A1", "A2", "A3", "A4", "Q1", "Q2",
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
    assert "Rollback procedure and restored-state verification" not in prompt_text


def test_explicit_missing_context_prevents_overconfident_p08_winner(monkeypatch):
    monkeypatch.setattr(
        cs_mod,
        "call_model",
        _fake_call(_p08_overconfident_model_result()),
    )

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_p08_state()))
    recommendation = result["final_recommendation"]

    assert recommendation["winner"] == "context_dependent"
    assert recommendation["ranked_options"] == []
    assert recommendation["decision_branches"]
    assert recommendation["action_plan_mode"] == "validation_only"
    assert "立即采用 Redis" not in recommendation["recommendation"]
    assert any(
        "明确缺少会改变选择的关键上下文" in question
        for question in recommendation["unresolved_questions"]
    )


def test_p08_supplement_allows_supported_concrete_winner(monkeypatch):
    captured = []
    monkeypatch.setattr(
        cs_mod,
        "call_model",
        _fake_call(_p08_overconfident_model_result(), captured),
    )

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(_p08_state(
        supplemental_input=(
            "缓存内容是可再生 JSON，不要求持久化；峰值约 3000 次读取和 "
            "200 次写入；团队已有 Redis 经验。"
        ),
    )))

    assert result["final_recommendation"]["winner"] == "Redis"
    assert "缓存内容是可再生 JSON" in captured[0][0]["content"]
    assert "untrusted user context rather than source evidence" in captured[0][0]["content"]


@pytest.mark.parametrize(
    "scene_context, constraints, supplemental_input, expected",
    [
        (
            "The request does not specify persistence or team capability.",
            ["Give only a conditional conclusion until those constraints are known."],
            None,
            True,
        ),
        (
            "The request does not specify persistence or team capability.",
            ["Compare both products."],
            None,
            False,
        ),
        (
            "The workload is fully described.",
            ["Give only a conditional conclusion if critical context is missing."],
            None,
            False,
        ),
        (
            "The request does not specify persistence or team capability.",
            ["Give only a conditional conclusion until those constraints are known."],
            "The workload is regenerable and persistence is not required.",
            False,
        ),
    ],
)
def test_explicit_missing_context_guard_is_narrow(
    scene_context,
    constraints,
    supplemental_input,
    expected,
):
    assert cs_mod._explicit_missing_context_requires_abstention(
        {"scene_context": scene_context, "constraints": constraints},
        supplemental_input,
    ) is expected


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
        ("Our team wants feature flags with gradual rollout", 0),
        ("Compare reliable storage", 1),
        ("Choose a queue with retry support", 3),
        ("比较任务队列的重试与迁移", 3),
    ],
)
def test_operational_obligations_match_words_not_accidental_substrings(query, expected):
    requirements, overflow = cs_mod._decision_requirements(query, [], [], [], [])
    assert not overflow
    assert sum(item["kind"] == "operational_obligation" for item in requirements) == expected


def test_p04_phased_choice_keeps_delivery_recovery_without_full_migration_duties():
    requirements, overflow = cs_mod._decision_requirements(
        "需要执行 5 到 30 分钟任务的 Web 产品，应继续使用进程内后台任务还是引入 Celery？",
        [
            "必须讨论重启恢复和至少一次执行语义",
            "允许先做阶段性方案",
            "不得把任务队列描述为天然 exactly-once",
        ],
        [],
        [
            "进程内任务在哪些故障下会丢失？",
            "Celery 引入哪些组件和运维责任？",
            "是否存在过渡方案？",
        ],
        [],
    )

    obligations = [
        item["requirement"]
        for item in requirements
        if item["kind"] == "operational_obligation"
    ]
    assert not overflow
    assert len(obligations) == 3
    assert not any("推进条件和中止条件" in item or "回退步骤" in item for item in obligations)
    assert "result backend or late acknowledgement alone" in cs_mod.SYNTHESIS_PROMPT
    assert "broker message durability and result backend result storage are distinct" in cs_mod.SYNTHESIS_PROMPT


def test_p04_missing_original_recovery_requirement_withdraws_winner_and_unsafe_plan(monkeypatch):
    state = _p08_state()
    state["task"] = {
        "query": "需要执行 5 到 30 分钟任务的 Web 产品，应继续使用进程内后台任务还是引入 Celery？",
        "scene_context": (
            "单实例 FastAPI 服务，每天约 200 个任务；任务结果不能因服务重启静默丢失，"
            "但团队不想过早引入复杂基础设施。"
        ),
        "constraints": [
            "必须讨论重启恢复和至少一次执行语义",
            "允许先做阶段性方案",
            "不得把任务队列描述为天然 exactly-once",
        ],
        "sub_questions": [
            "进程内任务在哪些故障下会丢失？",
            "Celery 引入哪些组件和运维责任？",
            "是否存在过渡方案？",
        ],
    }
    model_result = _p08_overconfident_model_result()
    model_result.update(
        winner="Celery",
        winner_rationale="Celery 可以可靠执行长任务 [[1]].",
        recommendation="启用 acks_late 后直接切换生产长任务 [[1]].",
        ranked_options=[
            {
                "name": "Celery",
                "rank": 1,
                "constraint_fit": "high",
                "constraint_fit_reason": "支持后台任务 [[1]].",
                "rationale": "支持后台任务 [[1]].",
                "key_strength": "独立 worker [[1]].",
                "key_weakness": "增加组件 [[1]].",
            },
            {
                "name": "FastAPI BackgroundTasks",
                "rank": 2,
                "constraint_fit": "low",
                "constraint_fit_reason": "进程内执行 [[1]].",
                "rationale": "部署简单 [[1]].",
                "key_strength": "无需额外组件 [[1]].",
                "key_weakness": "恢复语义待确认 [[1]].",
            },
        ],
        requirement_assessments=[
            {
                "id": identifier,
                "requirement": "模型不得改写冻结要求",
                "status": "satisfied",
                "decision_critical": True,
                "explanation": "该要求已由来源覆盖 [[1]].",
                "evidence_ids": [1],
            }
            for identifier in (
                "C1", "C2", "C3", "A1", "A2", "A3", "Q1", "Q2", "Q3",
            )
        ],
        decision_branches=[{
            "option": "Celery",
            "condition": "仅在恢复和重复执行演练通过后采用 [[1]].",
        }],
        action_plan=[{
            "step": "直接开启 acks_late 并切换生产任务 [[1]].",
            "verification": "观察任务是否完成 [[1]].",
            "change_trigger": "worker 可以运行时切换 [[1]].",
            "rollback": "关闭 Celery 后重跑任务 [[1]].",
        }],
    )
    monkeypatch.setattr(cs_mod, "call_model", _fake_call(model_result))

    result = asyncio.run(cs_mod.ConclusionSynthesizerAgent().run(state))
    recommendation = result["final_recommendation"]
    assessments = {
        item["id"]: item for item in recommendation["requirement_assessments"]
    }

    assert recommendation["winner"] == "context_dependent"
    assert assessments["C4"]["status"] == "unknown"
    assert assessments["C4"]["decision_critical"]
    assert "A4" not in assessments and "A5" not in assessments
    assert recommendation["action_plan_mode"] == "validation_only"
    assert "直接开启 acks_late" not in str(recommendation["action_plan"])
    assert recommendation["decision_branches"]
