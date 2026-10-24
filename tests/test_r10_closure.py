"""Round-10 offline closure regressions: capacity, display, diagnostics, admission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import AsyncMock

from benchmarks.batch_authorization import (
    AuthorizationDuplicate,
    AuthorizationError,
    AuthorizationExceeded,
    AuthorizationUnsettled,
    BatchAuthorizationLedger,
)
from benchmarks.final_batch import (
    AuthorizationGatedCollector,
    append_reconciliation_record,
    terminal_case_ids,
    uncertain_admitted_case_ids,
    validate_resume_authorization,
    validate_authorization_ledger_path,
)
from benchmarks.product_baseline import CollectionOptions, DurableBaselineCollector
from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.formats.decision import _source_index_lines, render_answer_report
from deepchoice.utils.answer_delivery import ANSWER_CONTRACT
from deepchoice.utils.decision_analysis import (
    MAX_ROW_BASIS_FACTS,
    bind_analysis_basis,
)
from deepchoice.utils.evidence_choices import MAX_SOURCE_FACTS
from deepchoice.utils.question_packet import basis_reference_packet, bind_question_rows
from deepchoice.utils.stage_diagnostics import append_quality_signal


def _quotes(n=9):
    return {
        f"B{i}": {"fact_id": f"F{i}", "sentence_ids": [1],
                  "source_sentences": [f"Saved sentence {i}."]}
        for i in range(1, n + 1)
    }


def _facts(n=9):
    return [
        {"id": f"F{i}", "status": "verified", "source_title": f"Source {i}",
         "saved_text": f"Saved sentence {i}."}
        for i in range(1, n + 1)
    ]


def test_capacity_contract_is_explicit_and_separated():
    assert MAX_SOURCE_FACTS == 5
    assert MAX_ROW_BASIS_FACTS == 4
    prompt = synth.JOINT_SYNTHESIS_PROMPT
    assert "at most FIVE" in prompt
    assert "at most FOUR" in prompt
    assert "at most four selected views" not in prompt
    assert "at most 5" in synth.SYNTHESIS_CORRECTION_TEMPLATE
    assert "at most four distinct" in synth.SYNTHESIS_CORRECTION_TEMPLATE


def test_legacy_packet_rejects_over_capacity_instead_of_truncating():
    text, offered = basis_reference_packet(_facts(5), ["Alpha"])
    assert offered and len({row["fact_id"] for row in offered.values()}) == 5
    text, offered = basis_reference_packet(_facts(6), ["Alpha"])
    assert text == "No bound source facts." and offered == {}


def test_analysis_row_fact_limit_has_fixed_diagnostic():
    quotes = _quotes(5)
    row = {"question_id": "Q1", "kind": "answer",
           "basis_refs": ["B1", "B2", "B3", "B4"],
           "reasoning": "Conditional answer.", "assumptions": [],
           "change_condition": "If conditions change."}
    diag = {}
    accepted = bind_question_rows([row], ["Q1"], quotes, diagnostics=diag)
    assert len(accepted) == 1
    assert diag["rows_rejected_fact_limit"] == 0

    diag = {}
    row5 = {**row, "basis_refs": ["B1", "B2", "B3", "B4", "B5"]}
    rejected = bind_question_rows([row5], ["Q1"], quotes, diagnostics=diag)
    assert rejected == []
    assert diag["rows_rejected_fact_limit"] == 1
    assert diag["rows_rejected_shape"] == 0

    facts = {item["id"]: item for item in _facts(5)}
    basis = [{"fact_id": f"F{i}", "sentence_ids": [1]} for i in range(1, 6)]
    assert bind_analysis_basis(basis, facts)[1] == "basis_fact_limit"


def test_oversized_selected_views_is_explicit_not_a_prefix():
    from deepchoice.utils.fact_selection import bind_selection_answers

    diagnostics = {}
    facts, rows = bind_selection_answers(
        {"source_view_ids": [f"S{i}" for i in range(1, 7)], "decision_analysis": []},
        {}, [], [], ["Q1"], diagnostics,
    )
    assert facts == [] and rows == []
    assert diagnostics["selected_views_received"] == 6
    assert diagnostics["selected_views_rejected_limit"] == 1


def test_source_index_groups_by_url_and_keeps_same_title_sources():
    facts = [
        {"id": "F1", "source_title": "Same title", "status": "verified",
         "canonical_url": "https://a.example/docs#one"},
        {"id": "F2", "source_title": "Same title", "status": "unknown",
         "canonical_url": "https://a.example/docs#two"},
        {"id": "F3", "source_title": "Same title", "status": "verified",
         "canonical_url": "https://b.example/docs"},
        {"id": "F4", "source_title": "No URL source", "status": "unknown",
         "canonical_url": ""},
    ]
    lines = _source_index_lines(facts, False)
    bullets = [line for line in lines if line.startswith("- ")]
    assert len(bullets) == 3
    assert sum(line.startswith("- [Same title]") for line in bullets) == 2
    assert any("2 saved excerpts" in line and "verified: 1" in line
               and "unknown: 1" in line for line in bullets)


def test_source_index_has_no_display_five_cap_and_renderer_uses_it():
    facts = [
        {"id": f"F{i}", "source_title": f"Source {i}", "status": "unknown",
         "canonical_url": f"https://source{i}.example/docs"}
        for i in range(1, 9)
    ]
    lines = _source_index_lines(facts, False)
    assert len([line for line in lines if line.startswith("- ")]) == 8
    rec = {"source_facts": deepcopy(facts), "decision_analysis": [],
           "answer_delivery": {"version": ANSWER_CONTRACT, "requirements": {"R0": "Pick"}}}
    rendered = render_answer_report({"task": {"query": "Pick"}, "final_recommendation": rec}, "en")
    assert rendered.count("https://source") == 8
    assert rec["source_facts"] == facts


def test_diagnostics_append_preserves_earlier_stages_and_missing_stays_missing():
    state = {"quality_signals": [{"agent": "conclusion_synthesizer", "rows_received": 2}]}
    merged = append_quality_signal(state, {"agent": "citation_validator", "unknown": 3})
    assert [row["agent"] for row in merged] == ["conclusion_synthesizer", "citation_validator"]
    assert merged[0] == {"agent": "conclusion_synthesizer", "rows_received": 2}
    assert append_quality_signal({}, {"agent": "self_reviewer"}) == [{"agent": "self_reviewer"}]
    assert append_quality_signal({"quality_signals": None}, {"agent": "x"}) == [{"agent": "x"}]


@pytest.mark.asyncio
async def test_collector_reserves_inside_pre_post_journal_not_before_health(tmp_path, monkeypatch):
    ledger = BatchAuthorizationLedger(tmp_path / "ledger.sqlite",
                                      authorization_id="dev-a", cap=1)
    (tmp_path / "out").mkdir()
    collector = AuthorizationGatedCollector(
        None, tmp_path / "out", experiment_id="e", dataset_hash="a" * 64,
        options=CollectionOptions(profile="candidate", repetition=1, concurrency=1,
                                  poll_interval_seconds=0, case_timeout_seconds=1),
        authorization=ledger,
    )
    collector._healthy = AsyncMock(return_value=False)
    parent = AsyncMock(side_effect=AssertionError("must not dispatch"))
    monkeypatch.setattr(DurableBaselineCollector, "_request_json", parent)
    record = await collector._collect_case(
        {"id": "P01", "split": "final", "request": {}, "hitl": {}}
    )
    assert record["status"] == "not_submitted"
    parent.assert_not_awaited()
    assert ledger.status()["used"] == 0

    # Consume the only slot before the second call to prove a pre-POST refusal
    # happens before the product request.
    ledger.reserve("P00", "prior")
    collector._healthy = AsyncMock(return_value=True)
    monkeypatch.undo()
    post = AsyncMock(side_effect=AssertionError("must not dispatch"))
    monkeypatch.setattr(DurableBaselineCollector, "_request_json", post)
    record = await collector._collect_case(
        {"id": "P01", "split": "final", "request": {}, "hitl": {}}
    )
    assert record["error_code"] == "AUTHORIZATION_LIMIT_REACHED"
    post.assert_not_awaited()
    assert ledger.status()["used"] == 1


@pytest.mark.asyncio
async def test_citation_appends_last_signal_without_mutating_prior_state():
    from deepchoice.agents.citation_validator import CitationValidatorAgent

    state = {"task": {"query": "Q"}, "evidence_chains": [],
             "final_recommendation": {}, "quality_signals": [{"agent": "synthesis", "x": 1}]}
    before = deepcopy(state)
    output = await CitationValidatorAgent().run(state)
    assert state == before
    assert [row["agent"] for row in output["quality_signals"]] == [
        "synthesis", "citation_validator"
    ]
    assert output["quality_signals"][0] == {"agent": "synthesis", "x": 1}


@pytest.mark.asyncio
async def test_gated_collector_reserves_then_marks_and_settles(tmp_path):
    import asyncio as _asyncio
    import time as _time

    (tmp_path / "out").mkdir()
    collector = AuthorizationGatedCollector(
        None, tmp_path / "out", experiment_id="e", dataset_hash="a" * 64,
        options=CollectionOptions(profile="candidate", repetition=1, concurrency=1,
                                  poll_interval_seconds=0, case_timeout_seconds=1),
        authorization=BatchAuthorizationLedger(tmp_path / "ledger.sqlite",
                                               authorization_id="dev-a", cap=1),
    )
    record = {"case_id": "P01", "task_id": None, "status": "running"}
    await collector._journal(record, "submission_started")
    assert collector.authorization.status()["used"] == 1
    record["task_id"] = "task-1"
    await collector._journal(record, "admitted")
    assert collector.authorization.status()["by_status"] == {"submitted": 1}
    assert collector.authorization.unresolved()[0]["task_id"] == "task-1"
    record["status"] = "completed"
    await collector._finish(record, _time.monotonic())
    assert collector.authorization.status()["reserved"] == 0
    assert collector.authorization.status()["by_status"] == {"completed": 1}


def test_duplicate_and_immutable_authorization_are_rejected(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = BatchAuthorizationLedger(path, authorization_id="dev-a", cap=2)
    token = ledger.reserve("P01", "e")
    with pytest.raises(AuthorizationUnsettled):
        ledger.reserve("P01", "e")
    ledger.settle(token, "completed")
    with pytest.raises(AuthorizationDuplicate):
        ledger.reserve("P01", "e")
    with pytest.raises(AuthorizationError):
        BatchAuthorizationLedger(path, authorization_id="dev-a", cap=3)


def test_resume_authorization_identity_is_bound(tmp_path):
    output = tmp_path / "out"; output.mkdir()
    (output / "runs.jsonl").write_text('{"case_id":"P01","status":"completed"}\n', encoding="utf-8")
    (output / "batch-identity.json").write_text(json.dumps({
        "authorization_id": "old", "authorization_cap": 24,
        "authorization_prior_used": 0,
        "authorization_ledger": str((tmp_path / "old.sqlite").resolve()),
    }), encoding="utf-8")
    args = argparse.Namespace(resume=True, authorization_id="new",
                              authorization_cap=24, authorization_prior_used=0,
                              authorization_ledger=str(tmp_path / "new.sqlite"))
    with pytest.raises(ValueError, match="resume authorization identity changed"):
        validate_resume_authorization(output, args)

def test_twenty_fifth_slot_is_rejected_without_any_product_call(tmp_path):
    ledger = BatchAuthorizationLedger(tmp_path / "ledger.sqlite",
                                      authorization_id="dev-a", cap=24)
    for index in range(24):
        ledger.reserve(f"P{index:02d}", "experiment-x")
    with pytest.raises(AuthorizationExceeded):
        ledger.reserve("P24", "experiment-y")
    assert ledger.status()["used"] == 24
    assert ledger.status()["remaining"] == 0



def test_last_slot_is_atomic_under_concurrent_reservations(tmp_path):
    ledger = BatchAuthorizationLedger(tmp_path / "ledger.sqlite",
                                      authorization_id="dev-a", cap=1)

    def reserve(case_id):
        try:
            return ledger.reserve(case_id, "experiment-x")
        except AuthorizationExceeded:
            return "exceeded"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["P01", "P02"]))
    assert results.count("exceeded") == 1
    assert ledger.status()["used"] == 1


def test_reserved_crash_is_not_released_by_new_directory_or_experiment(tmp_path):
    path = tmp_path / "ledger.sqlite"
    first = BatchAuthorizationLedger(path, authorization_id="dev-a", cap=2,
                                     owner_token="process-1")
    token = first.reserve("P01", "old-directory")
    restarted = BatchAuthorizationLedger(path, authorization_id="dev-a", cap=2,
                                         owner_token="process-2")
    with pytest.raises(AuthorizationUnsettled):
        restarted.reserve("P02", "new-directory")
    assert restarted.status()["used"] == 1
    restarted.reconcile(token, outcome="failed", task_id="task-1")
    assert restarted.reserve("P02", "new-directory")
    assert restarted.status()["used"] == 2


def test_reconcile_terminal_record_clears_resume_block(tmp_path):
    output = tmp_path / "out"; output.mkdir()
    ledger = BatchAuthorizationLedger(tmp_path / "ledger.sqlite",
                                      authorization_id="dev-a", cap=1)
    token = ledger.reserve("P01", "e")
    (output / "batch-identity.json").write_text(json.dumps({"experiment_id": "e"}), encoding="utf-8")
    (output / "admissions.jsonl").write_text(
        json.dumps({"case_id": "P01", "event": "submission_started"}) + "\n",
        encoding="utf-8")
    assert uncertain_admitted_case_ids(
        [{"case_id": "P01", "event": "submission_started"}], set()) == {"P01"}
    append_reconciliation_record(output, ledger, token, "failed", "task-1")
    ledger.reconcile(token, outcome="failed", task_id="task-1")
    records = [json.loads(line) for line in (output / "runs.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert terminal_case_ids(records) == {"P01"}
    assert uncertain_admitted_case_ids(
        [{"case_id": "P01", "event": "submission_started"}], {"P01"}) == set()
    assert ledger.status()["by_status"] == {"failed": 1}

def test_ledger_must_be_outside_output_and_prior_used_carries_history(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        validate_authorization_ledger_path(tmp_path / "out", tmp_path / "out" / "ledger.sqlite")
    ledger = BatchAuthorizationLedger(tmp_path / "ledger.sqlite",
                                      authorization_id="dev-a", cap=24, prior_used=28)
    assert ledger.status()["used"] == 28
    assert ledger.status()["remaining"] == 0
    with pytest.raises(AuthorizationExceeded):
        ledger.reserve("P25", "experiment-z")
