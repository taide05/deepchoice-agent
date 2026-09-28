"""Offline counterexamples for explicit needs buried in the original scene."""

import pytest

from deepchoice.agents import conclusion_synthesizer as synth


P01_SCENE = (
    "单人开发和运维，预计 12 个月内日活低于 5000，读多写少，"
    "需要备份与基本全文检索。"
)
P04_SCENE = (
    "单实例 FastAPI 服务，每天约 200 个任务；"
    "任务结果不能因服务重启静默丢失，但团队不想过早引入复杂基础设施。"
)


def test_p01_explicit_scene_capabilities_become_separate_critical_rows():
    requirements, overflow = synth._decision_requirements(
        "为个人 Web 应用选择 SQLite 还是 PostgreSQL？",
        ["优先降低运维复杂度", "必须说明未来迁移触发条件", "不能仅按理论性能下结论"],
        [], [], [], P01_SCENE,
    )

    assert not overflow
    scene_rows = [row for row in requirements if row["kind"] == "scene_requirement"]
    assert [(row["id"], row["requirement"]) for row in scene_rows] == [
        ("C4", "需要备份"),
        ("C5", "需要基本全文检索"),
    ]
    assert not any("5000" in row["requirement"] for row in scene_rows)
    assert not any("读多写少" in row["requirement"] for row in scene_rows)


def test_p04_no_silent_loss_and_complexity_preference_are_independent():
    requirements, overflow = synth._decision_requirements(
        "需要执行 5 到 30 分钟任务的 Web 产品，应继续使用进程内后台任务还是引入 Celery？",
        ["必须讨论重启恢复和至少一次执行语义", "允许先做阶段性方案",
         "不得把任务队列描述为天然 exactly-once"],
        [], [], [], P04_SCENE,
    )

    assert not overflow
    scene_rows = [row for row in requirements if row["kind"].startswith("scene_")]
    assert [(row["id"], row["requirement"]) for row in scene_rows] == [
        ("C4", "任务结果不能因服务重启静默丢失"),
        ("C5", "团队不想过早引入复杂基础设施"),
    ]
    assert [row["kind"] for row in scene_rows] == ["scene_requirement", "scene_preference"]
    assert not any("200" in row["requirement"] for row in scene_rows)


@pytest.mark.parametrize(
    "scene, expected",
    [
        ("不需要备份但需要基本全文检索。", ["需要基本全文检索"]),
        ("不需要备份且需要基本全文检索。", ["需要基本全文检索"]),
        ("没有要求启用WAL，但需要备份。", ["需要备份"]),
        ("需要备份而不需要全文检索。", ["需要备份"]),
        ("需要备份且无需检索。", ["需要备份"]),
        ("需要备份同时不需要全文检索。", ["需要备份"]),
        ("不需要备份。", []),
        ("We need backups and basic full-text search.",
         ["We need backups", "We need basic full-text search"]),
        ("We need backups and do not need search.", ["We need backups"]),
        ("We need backups and doesn't need search.", ["We need backups"]),
        ("The system cannot silently lose accepted jobs on restart.",
         ["The system cannot silently lose accepted jobs on restart"]),
        ("单实例，日均200个任务，读多写少。", []),
        ("本次报告需要用中文输出，本次报告需要在两周内给出建议。", []),
        ("For this report we need a response in Chinese.", []),
        ("需要用中文回答。", ["需要用中文回答"]),
        ("客服系统需要用中文回答用户问题。", ["客服系统需要用中文回答用户问题"]),
        ("推荐服务需要在 1 秒内给出建议。", ["推荐服务需要在 1 秒内给出建议"]),
        ("单实例服务，要求在 1 秒内给出建议。", ["要求在 1 秒内给出建议"]),
    ],
)
def test_scene_need_extraction_does_not_infer_from_descriptive_or_negated_context(scene, expected):
    assert synth._scene_decision_requirements(scene) == expected


def test_missing_scene_need_cannot_be_silently_satisfied_by_other_citations():
    requirements, _ = synth._decision_requirements(
        "SQLite or PostgreSQL?", ["Keep operations simple"], [], [], [], P01_SCENE,
    )
    model_output = {
        "winner": "SQLite",
        "requirement_assessments": [{
            "id": "C1", "status": "satisfied", "decision_critical": True,
            "explanation": "The source supports the simple option [[1]].", "evidence_ids": [1],
        }],
    }

    normalized, abstain = synth._normalize_decision_contract(
        model_output, requirements, {1}, "SQLite or PostgreSQL?",
    )
    rows = {row["requirement"]: row for row in normalized["requirement_assessments"]}
    assert abstain
    assert rows["需要备份"]["status"] == "unknown"
    assert rows["需要基本全文检索"]["status"] == "unknown"
    assert "需要基本全文检索" in normalized["unresolved_questions"]


@pytest.mark.asyncio
async def test_default_synthesis_withdraws_winner_when_model_skips_scene_needs(monkeypatch):
    task = {
        "query": "为个人 Web 应用选择 SQLite 还是 PostgreSQL？",
        "scene_context": P01_SCENE,
        "constraints": ["优先降低运维复杂度"],
        "sub_questions": [],
    }
    requirements, _ = synth._decision_requirements(
        task["query"], task["constraints"], [], [], [], task["scene_context"],
    )
    captured = []

    async def fake_model(prompt, **_kwargs):
        captured.append(prompt[0]["content"])
        return {
            "winner": "SQLite",
            "winner_rationale": "SQLite is simple [[1]].",
            "recommendation": "Use SQLite [[1]].",
            "requirement_assessments": [
                {
                    "id": row["id"], "status": "satisfied", "decision_critical": False,
                    "explanation": "The source describes this capability [[1]].",
                    "evidence_ids": [1],
                }
                for row in requirements if row["kind"] != "scene_requirement"
            ],
        }

    monkeypatch.setattr(synth, "call_model", fake_model)
    output = await synth.ConclusionSynthesizerAgent().run({
        "task": task,
        "evidence_chains": [{
            "conclusion": "SQLite overview", "disputed": False,
            "sources": [{"title": "SQLite Documentation", "url": "https://sqlite.org/fts5.html",
                         "snippet": "FTS5 provides basic full-text search functionality."}],
        }],
    })

    rec = output["final_recommendation"]
    rows = {row["id"]: row for row in rec["requirement_assessments"]}
    assert "C2 [scene-requirement]: 需要备份" in captured[0]
    assert "C3 [scene-requirement]: 需要基本全文检索" in captured[0]
    assert rec["winner"] == "context_dependent"
    assert rec["ranked_options"] == []
    assert rows["C1"]["status"] == "satisfied"
    assert rows["C2"]["decision_critical"] is True
    assert rows["C2"]["status"] == "unknown"
    assert rows["C3"]["status"] == "unknown"


def test_oversized_explicit_scene_need_fails_closed():
    requirements, _ = synth._decision_requirements(
        "Compare options", [], [], [], [], "需要" + "甲" * 550,
    )
    assert any("超过500字" in row["requirement"] for row in requirements)
    normalized, abstain = synth._normalize_decision_contract(
        {"winner": "OptionA", "requirement_assessments": []}, requirements, set(),
    )
    assert abstain
    assert normalized["requirement_assessments"][0]["status"] == "unknown"


def test_soft_scene_preference_is_visible_without_vetoing_supported_hard_need():
    requirements, _ = synth._decision_requirements(
        "Choose a task runner", [], [], [], [],
        "任务结果不能因服务重启静默丢失，但团队不想过早引入复杂基础设施。",
    )
    hard, soft = [row for row in requirements if row["kind"].startswith("scene_")]
    assert hard["kind"] == "scene_requirement"
    assert soft["kind"] == "scene_preference"
    normalized, abstain = synth._normalize_decision_contract({
        "winner": "Celery",
        "requirement_assessments": [
            {
                "id": row["id"], "status": "satisfied", "decision_critical": False,
                "explanation": "The cited source describes recovery [[1]].", "evidence_ids": [1],
            }
            for row in requirements if row["id"] != soft["id"]
        ] + [{
            "id": soft["id"], "status": "unknown", "decision_critical": True,
            "explanation": "The operational cost remains unmeasured.", "evidence_ids": [],
        }],
    }, requirements, {1})
    rows = {row["id"]: row for row in normalized["requirement_assessments"]}
    assert not abstain  # Structural gate only; semantic applicability remains unproven.
    assert rows[hard["id"]]["decision_critical"] is True
    assert rows[soft["id"]]["decision_critical"] is False
    assert rows[soft["id"]]["status"] == "unknown"


def test_no_silent_loss_remains_hard_even_when_phrased_as_a_wish():
    requirements, _ = synth._decision_requirements(
        "Choose a task runner", [], [], [], [],
        "我不想让已接收任务因重启静默丢失。",
    )
    scene_row = next(row for row in requirements if row["kind"].startswith("scene_"))
    assert scene_row["kind"] == "scene_requirement"
    _, abstain = synth._normalize_decision_contract(
        {"winner": "Celery", "requirement_assessments": []}, requirements, set(),
    )
    assert abstain

    requirements, _ = synth._decision_requirements(
        "Choose a task runner", [], [], [], [],
        "我不想因复杂的恢复配置导致任务结果丢失。",
    )
    scene_row = next(row for row in requirements if row["kind"].startswith("scene_"))
    assert scene_row["kind"] == "scene_requirement"


def test_english_complexity_preference_is_visible_but_not_a_veto():
    requirements, _ = synth._decision_requirements(
        "Choose a task runner", [], [], [], [],
        "We prefer simpler infrastructure.",
    )
    assert requirements[0]["kind"] == "scene_preference"
    assert requirements[0]["requirement"] == "We prefer simpler infrastructure"
