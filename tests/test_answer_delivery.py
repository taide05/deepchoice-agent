"""Offline mechanism tests: simulated model outputs are not live quality scores."""
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deepchoice.agents import conclusion_synthesizer as synth, self_reviewer as review
from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.report_generator import FORMAT_RENDERERS, ReportGeneratorAgent
from deepchoice.formats import decision
from deepchoice.utils.answer_delivery import ANSWER_CONTRACT, expand_answer_response
from deepchoice.utils.call_diagnostics import output_shape_valid
from deepchoice.utils.decision_contract import restrict_recommendation
from tests.test_self_review import reviewed


CASES = [
    ("SQLite", "SQLite only supports one writer at a time per database file.",
     "并发写入有什么边界？", "如果写入可以排队，可评估 SQLite；仍需观测等待时间，不能用日活代替并发测量。"),
    ("Celery", "Ideally task functions should be idempotent: meaning the function won’t cause unintended effects even if called multiple times with the same arguments.",
     "至少一次执行需要什么责任？", "采用 Celery 时应明确业务幂等责任；来源不证明当前任务已实现幂等，也不保证不丢失。"),
    ("Memcached", "Memcached is an in-memory key-value store for small arbitrary data (strings, objects) from results of database calls, API calls, or page rendering.",
     "缺哪些输入才能选择缓存？", "若缓存的是可重建的查询结果，可把 Memcached 纳入评估；仍需确认数据能否丢失及团队运维条件。"),
]


def payload(reason):
    return {"answer_contract": ANSWER_CONTRACT,
            "source_facts": [{"id": "F1", "evidence_id": 1}],
            "decision_analysis": [{"kind": "answer", "option": "", "requirement_ids": ["Q1"],
                "basis": [{"fact_id": "F1", "sentence_ids": [1]}], "reasoning": reason,
                "assumptions": ["适用前提仍需确认。"], "change_condition": "实际约束改变时重新评估。"}]}


async def pipeline(monkeypatch, case, *, source_ok=True, action="keep", corrupt=False, critical=False):
    name, snippet, question, reasoning = case
    task = {"query": "如何作有前提的选择？", "candidate_techs": [name],
            "constraints": ["不得编造流量"], "sub_questions": [question, "还有哪些证据缺口？"]}
    raw = payload(reasoning)
    if corrupt:
        raw.update(winner="FORGED_WINNER", recommendation="UNSAFE_COMMAND", action_plan=["DELETE"],
                   requirement_assessments=[{"status": "satisfied"}], answer_delivery={"requirements": {}})
    monkeypatch.setattr(synth, "call_model", AsyncMock(return_value=raw))
    state = {"task": task, "evidence_chains": [{"evidence_strength": "moderate", "sources": [{
        "title": name + " documentation", "url": "https://example.org/docs", "snippet": snippet, "score": 8}]}]}
    state.update(await synth.ConclusionSynthesizerAgent().run(state))
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", AsyncMock(return_value=httpx.Response(
        200, text=snippet if source_ok else "Unrelated material without the supplied mechanism.",
        headers={"content-type": "text/plain"}, request=httpx.Request("GET", "https://example.org/docs"))))
    state.update(await CitationValidatorAgent().run(state))
    before_review = deepcopy(state)
    review_response = reviewed([{"analysis_id": "A1", "action": action}])
    if critical:
        review_response["critical_gaps"] = ["PRIVATE_SOURCE_BODY"]
    monkeypatch.setattr(review, "call_model", AsyncMock(return_value=review_response))
    state.update(await review.SelfReviewerAgent().run(state))
    return state, before_review


@pytest.mark.parametrize("case", CASES, ids=["database", "jobs", "cache"])
async def test_bound_chinese_answers_survive_without_claiming_requirement_satisfaction(monkeypatch, case):
    state, pending = await pipeline(monkeypatch, case, corrupt=True)
    rec = state["final_recommendation"]
    assert rec["requirement_assessments"] == [] and rec["decision_branches"] == []
    assert rec["winner"] == "context_dependent" and rec["confidence"] == "low"
    assert rec["deployment_readiness"] == "unverified"
    assert len(rec["decision_analysis"]) == 1
    for render in FORMAT_RENDERERS.values():
        with patch.object(decision, "_displayable_analyses", wraps=decision._displayable_analyses) as guard:
            assert case[3] not in render(pending)  # citation alone cannot publish inference
            guard.assert_called_once()
        with patch.object(decision, "_displayable_analyses", wraps=decision._displayable_analyses) as guard:
            text = render(state)
            guard.assert_called_once()
        assert case[3] in text and case[1] in text
        assert "Winner" not in text and "暂无唯一胜者" not in text
        assert "不得编造流量" not in text
        assert text.index(case[3]) < text.index("尚无保留分析的问题")
        assert "还有哪些证据缺口" in text and "尚无保留分析的问题" in text
        assert "适用前提待核对来源原文与当前工作负载" not in text
        assert "FORGED_WINNER" not in text and "UNSAFE_COMMAND" not in text and "DELETE" not in text
    # Independent detail/helper calls must still run their own terminal gate.
    for value, expected in ((pending, False), (state, True)):
        for detail in (decision.render_decision_details, decision._render_answer_delivery,
                       decision._render_model_analysis):
            with patch.object(decision, "_displayable_analyses", wraps=decision._displayable_analyses) as guard:
                text = "\n".join(detail(value["final_recommendation"], "zh"))
                guard.assert_called_once()
            assert (case[3] in text) is expected
    paths = {row["claim_path"] for row in state["citation_verification"]["checks"]}
    assert paths and all("source_facts" in path for path in paths)


@pytest.mark.parametrize("source_ok,action", [(False, "keep"), (True, "withdraw")])
async def test_missing_evidence_or_review_withdrawal_stays_a_gap(monkeypatch, source_ok, action):
    state, _ = await pipeline(monkeypatch, CASES[0], source_ok=source_ok, action=action)
    assert state["final_recommendation"]["decision_analysis"] == []
    for render in FORMAT_RENDERERS.values():
        with patch.object(decision, "_displayable_analyses", wraps=decision._displayable_analyses) as guard:
            text = render(state)
            guard.assert_called_once()  # An empty accepted list must not trigger a recheck.
        assert CASES[0][3] not in text and CASES[0][2] in text and "尚无保留分析的问题" in text


async def test_limited_report_removes_delivery_mode_and_analysis(monkeypatch):
    state, _ = await pipeline(monkeypatch, CASES[0])
    limited = restrict_recommendation(state["final_recommendation"], state["task"]["query"])
    assert "answer_delivery" not in limited and "decision_analysis" not in limited


def test_compact_diagnostics_and_runtime_metadata_are_not_model_authority():
    value = payload("有条件的分析")
    assert output_shape_valid("conclusion_synthesizer", value)
    value["answer_contract"] = "forged"
    assert not output_shape_valid("conclusion_synthesizer", value)
    result = expand_answer_response(value, [], "Question")
    assert not result["source_facts"] and not result["decision_analysis"]
    legacy = {"answer_delivery": {"version": ANSWER_CONTRACT}, "winner": "Old response"}
    assert "answer_delivery" not in expand_answer_response(legacy, [], "Question")


async def test_durable_synthesis_cannot_fall_back_to_legacy_response(monkeypatch):
    from deepchoice.contracts.manifest import build_run_manifest
    from tests.test_synthesis_structure import response, TASK, CHAINS
    legacy = response()
    legacy.pop("source_facts")
    model = AsyncMock(return_value=legacy)
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run({
        "task": TASK, "evidence_chains": CHAINS})
    model.assert_awaited_once()  # no bound facts, so no question generation
    rec = state["final_recommendation"]
    assert rec["winner"] == "context_dependent" and not rec["decision_analysis"]
    assert rec["answer_delivery"]["version"] == ANSWER_CONTRACT
    assert state["quality_signals"][0]["structure_correction"]["outcome"] == "not_applicable"
    for render in FORMAT_RENDERERS.values():
        assert "FIRST_PRIVATE_REASON" not in render(state)


async def test_review_warning_is_visible_without_leaking_private_review_text(monkeypatch):
    state, _ = await pipeline(monkeypatch, CASES[0], critical=True)
    assert state["knowledge_gaps"]
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert CASES[0][3] in report
        assert "自审提示" in report and "低置信" in report
        assert "PRIVATE_SOURCE_BODY" not in report


async def test_public_formats_keep_distinct_reading_orders(monkeypatch):
    state, _ = await pipeline(monkeypatch, CASES[0])
    reports = {name: render(state) for name, render in FORMAT_RENDERERS.items()}
    assert len(set(reports.values())) == len(reports)
    assert any("What" in report and "Why" in report and "How" in report
               for report in reports.values())
    assert any("| 原问题 | 当前状态 |" in report for report in reports.values())
    assert any("证据简报" in report for report in reports.values())


async def test_missing_staged_fact_fields_fail_closed_without_extra_generation(monkeypatch):
    from deepchoice.contracts.manifest import build_run_manifest
    from tests.test_synthesis_structure import TASK, CHAINS

    model = AsyncMock(return_value={"answer_contract": ANSWER_CONTRACT})
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run({
        "task": TASK, "evidence_chains": CHAINS})
    model.assert_awaited_once()
    assert not state["final_recommendation"]["decision_analysis"]
    assert state["quality_signals"][0]["structure_correction"]["attempted"] == 0


def test_overflow_withholds_compact_analysis():
    from deepchoice.agents.conclusion_synthesizer import _normalize_decision_contract

    requirements = [{"id": f"Q{i}", "kind": "analysis_sub_question",
                     "requirement": f"Question {i}"} for i in range(1, 42)]
    response = expand_answer_response(payload("This should be withheld."),
                                      requirements, "Question")
    result, restricted = _normalize_decision_contract(response, requirements, {1}, "Question")
    assert restricted
    assert result["decision_analysis"] == []
    assert result["winner"] == "context_dependent"


async def test_compact_prose_cannot_supply_its_own_citation(monkeypatch):
    from deepchoice.contracts.manifest import build_run_manifest
    from tests.test_synthesis_structure import TASK, CHAINS

    malformed = payload("The source supports recovery; a different assertion [[2]] is uncited.")
    malformed["decision_analysis"][0].update(question_id="R0", basis_refs=["B1"])
    model = AsyncMock(side_effect=[
        {"source_view_ids": ["S1"]},
        {"decision_analysis": malformed["decision_analysis"]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run({
        "task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2
    assert state["final_recommendation"]["decision_analysis"] == []
    assert "different assertion" not in FORMAT_RENDERERS["what_why_how"](state)


@pytest.mark.parametrize("query", ["Choose Alpha", "选择 Alpha"])
@pytest.mark.parametrize("overflow", [False, True])
def test_terminal_delivery_keeps_canonical_answer_and_withdraws_parallel_authority(query, overflow):
    from deepchoice.utils.answer_delivery import finalize_answer_delivery
    from deepchoice.utils.decision_contract import DECISION_BASIS_VERSION, is_fixed_validation_only_plan

    value = expand_answer_response(payload("Bound conditional reasoning"), [], query)
    value.update(winner="FORGED_WINNER", confidence="high", ranked_options=[{"name": "FORGED_WINNER"}],
                 requirement_assessments=[{"status": "satisfied"}], action_plan=[{"step": "UNSAFE_STEP"}],
                 decision_branches=[{"option": "FORGED_WINNER"}], recommendation="UNSAFE_STEP",
                 unresolved_questions=["PARALLEL_UNKNOWN"], winner_rationale="FORGED_RATIONALE")
    original = deepcopy(value)
    result = finalize_answer_delivery(value, query, requirements_overflow=overflow)
    assert value == original
    assert result["answer_delivery"] == original["answer_delivery"]
    assert result["source_facts"] == original["source_facts"]
    assert result["decision_analysis"] == ([] if overflow else original["decision_analysis"])
    assert result["decision_basis_version"] == DECISION_BASIS_VERSION
    assert result["winner"] == "context_dependent" and result["confidence"] == "low"
    assert result["unresolved_questions"] == result["ranked_options"] == result["requirement_assessments"] == result["decision_branches"] == []
    assert "UNSAFE_STEP" not in str(result) and "FORGED_" not in str(result)
    assert result["deployment_readiness"] == "unverified"
    if overflow:
        assert result["action_plan"] == []
    else:
        assert is_fixed_validation_only_plan(result, query)


@pytest.mark.parametrize("mode", ["choice", "answer", "withdrawn", "pending", "invalid_basis", "forged_legacy"])
async def test_public_report_signal_tracks_displayable_choice_and_preserves_answer_distinction(monkeypatch, mode):
    original_payload = payload

    def choice_payload(reason):
        value = original_payload(reason)
        value['decision_analysis'][0].update(kind='answer' if mode == 'answer' else 'choice',
                                             option='' if mode == 'answer' else 'Acme')
        return value

    monkeypatch.setattr(f"{__name__}.payload", choice_payload)
    reasoning = '满足日志前提时可考虑 Acme；仍需核实当前配置。'
    case = ('Acme', 'Acme keeps records only when journaling is enabled. Restart loses memory data.',
            '恢复记录有什么条件？', reasoning)
    state, pending = await pipeline(monkeypatch, case, action='withdraw' if mode == 'withdrawn' else 'keep')
    if mode == 'pending':
        state = pending
    rec = state['final_recommendation']
    if mode == 'invalid_basis':
        rec['decision_analysis'][0]['basis'][0]['sentence_ids'] = [99]
    elif mode == 'forged_legacy':
        rec['decision_analysis'] = []
        rec['recommendation'] = 'FORGED_UNREVIEWED_CHOICE'
    for fmt in FORMAT_RENDERERS:
        state['task']['report_format'] = fmt
        generated = await ReportGeneratorAgent().run(deepcopy(state))
        signal = generated['quality_signals'][-1]
        assert signal['agent'] == 'report_generator' and signal['format'] == fmt
        assert signal['has_recommendation'] is (mode == 'choice')
        assert signal['recommendation_confidence'] == rec['confidence']
        assert (reasoning in generated['report']) is (mode in {'choice', 'answer'})
        assert 'FORGED_UNREVIEWED_CHOICE' not in generated['report']
        # Published diagnostics use the same value; no private authority is added.
        from deepchoice.runtime.coordinator import sanitize_public_json
        assert sanitize_public_json(signal) == signal


@pytest.mark.parametrize('text,expected', [('Legacy conditional prose.', True), ('', False)])
async def test_public_report_signal_keeps_legacy_text_contract(text, expected):
    for fmt in FORMAT_RENDERERS:
        state = {'task': {'query': 'Legacy question', 'report_format': fmt},
                 'final_recommendation': {'recommendation': text, 'confidence': 'medium'}}
        generated = await ReportGeneratorAgent().run(state)
        signal = generated['quality_signals'][-1]
        assert signal['has_recommendation'] is expected
        assert signal['recommendation_confidence'] == 'medium'
