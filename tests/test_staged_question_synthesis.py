"""Staged synthesis contracts; fixtures show routing, not semantic quality."""
from unittest.mock import AsyncMock

import pytest

from deepchoice.agents import conclusion_synthesizer as synth
from deepchoice.budget_errors import BudgetPersistenceError
from deepchoice.contracts.manifest import build_run_manifest
from deepchoice.utils.question_packet import (
    bounded_fact_packet, candidate_mentions, has_multi_candidate_coverage,
    preferred_official_fact_ids, question_rows,
)

TASK = {"query": "Choose Alpha or Beta under restart constraints?",
        "candidate_techs": ["Alpha", "Beta"],
        "constraints": ["Do not invent durability"],
        "sub_questions": ["What changes after restart?"]}
CHAINS = [
    {"evidence_strength": "moderate", "sources": [{"title": "Alpha guide",
      "url": "https://alpha.example/guide", "snippet": "If writers can wait, Alpha can queue writes. Alpha does not guarantee restart recovery."}]},
    {"evidence_strength": "moderate", "sources": [{"title": "Beta guide",
      "url": "https://beta.example/guide", "snippet": "Beta requires a separate service. If the service fails, results need a durable store."}]},
]


def answer(question_id, fact_id, sentence_id=1):
    return {"decision_analysis": [{"kind": "answer", "option": "", "requirement_ids": [question_id],
        "basis": [{"fact_id": fact_id, "sentence_ids": [sentence_id]}],
        "reasoning": "Conditional judgment based on the stated prerequisite.",
        "assumptions": ["The relevant prerequisite is confirmed."],
        "change_condition": "Reconsider when the prerequisite changes."}]}


def test_packet_keeps_complete_sentence_addresses_and_title_tags():
    facts = [{"id": "F1", "source_title": "Alpha guide", "saved_text": CHAINS[0]["sources"][0]["snippet"]},
             {"id": "F2", "source_title": "Beta guide", "saved_text": CHAINS[1]["sources"][0]["snippet"]}]
    packet = bounded_fact_packet(facts, TASK["candidate_techs"])
    assert "F1 | title: Alpha guide | title mentions: ['Alpha']" in packet
    assert "s1: If writers can wait" in packet
    assert "s2: Alpha does not guarantee restart recovery" in packet
    assert "s2: If the service fails" in packet
    assert has_multi_candidate_coverage(facts, TASK["candidate_techs"])
    assert not has_multi_candidate_coverage(facts[1:], TASK["candidate_techs"])
    assert candidate_mentions("Alpha vs Beta", TASK["candidate_techs"]) == ["Alpha", "Beta"]
    assert has_multi_candidate_coverage([{"source_title": "Unclassified comparison"}], TASK["candidate_techs"])


def test_only_original_question_rows_are_planned():
    rows = question_rows(TASK["query"], [
        {"id": "C1", "kind": "frozen_constraint", "requirement": "Hard"},
        {"id": "Q1", "kind": "frozen_sub_question", "requirement": "Original"},
        {"id": "Q2", "kind": "analysis_sub_question", "requirement": "Derived"},
    ])
    assert rows == [("R0", TASK["query"]), ("Q1", "Original")]


async def test_durable_stage_answers_each_original_question_with_bound_facts(monkeypatch):
    model = AsyncMock(side_effect=[
        {"source_facts": [{"id": "F1", "evidence_id": 1}, {"id": "F2", "evidence_id": 2}],
         "winner": "FORGED"},
        {"decision_analysis": [answer("R0", "F1")["decision_analysis"][0],
                               answer("Q1", "F2", 2)["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2
    rec = state["final_recommendation"]
    assert rec["winner"] == "context_dependent"
    assert len(rec["source_facts"]) == 2
    assert [row["requirement_ids"] for row in rec["decision_analysis"]] == [["R0"], ["Q1"]]
    assert rec["decision_analysis"][1]["basis"][0]["source_sentences"] == [
        "If the service fails, results need a durable store."]
    assert state["quality_signals"][0]["structure_correction"]["attempted"] == 0
    assert "FORGED" not in str(state)
    selection, judgment = model.await_args_list
    assert "[[1]]" in selection.args[0][0]["content"]
    assert "s2: If the service fails" in judgment.args[0][0]["content"]
    assert "R0:" in judgment.args[0][0]["content"] and "Q1:" in judgment.args[0][0]["content"]
    assert all(call.kwargs["seed"] == 0 for call in model.await_args_list)


async def test_one_sided_facts_withhold_r0_but_allow_bounded_specific_answer(monkeypatch):
    model = AsyncMock(side_effect=[
        {"source_facts": [{"id": "F1", "evidence_id": 2}]}, answer("Q1", "F1")])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]
    assert "R0:" not in model.await_args_list[1].args[0][0]["content"]


async def test_subquestion_cannot_create_a_second_choice(monkeypatch):
    choice = answer("Q1", "F2")
    choice["decision_analysis"][0].update(kind="choice", option="Beta")
    model = AsyncMock(side_effect=[
        {"source_facts": [{"id": "F1", "evidence_id": 1}, {"id": "F2", "evidence_id": 2}]},
        {"decision_analysis": [answer("R0", "F1")["decision_analysis"][0],
                               choice["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["R0"]]
    stage = state["quality_signals"][0]["staged_generation"]
    assert stage["rows_received"] == 2 and stage["rows_selected"] == 1
    assert stage["judgment_calls"] == 1


async def test_malformed_requirement_ids_cannot_crash_or_enter_output(monkeypatch):
    malformed = answer("R0", "F1")["decision_analysis"][0]
    malformed["requirement_ids"] = [{"not": "an ID"}]
    model = AsyncMock(side_effect=[
        {"source_facts": [{"id": "F1", "evidence_id": 1}, {"id": "F2", "evidence_id": 2}]},
        {"decision_analysis": [malformed, answer("Q1", "F2")["decision_analysis"][0]]},
    ])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]


async def test_invalid_question_output_isolated_and_budget_loss_propagates(monkeypatch):
    model = AsyncMock(side_effect=[
        {"source_facts": [{"id": "F1", "evidence_id": 1}, {"id": "F2", "evidence_id": 2}]},
        {"decision_analysis": [
            answer("Q1", "F1")["decision_analysis"][0],
            {**answer("R0", "F1")["decision_analysis"][0],
             "requirement_ids": ["R0", "Q1"]},

        ]}])
    monkeypatch.setattr(synth, "call_model", model)
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
        {"task": TASK, "evidence_chains": CHAINS})
    assert [row["requirement_ids"] for row in state["final_recommendation"]["decision_analysis"]] == [["Q1"]]
    model = AsyncMock(side_effect=[
        {"source_facts": [{"id": "F1", "evidence_id": 1}, {"id": "F2", "evidence_id": 2}]},
        BudgetPersistenceError("private budget error")])
    monkeypatch.setattr(synth, "call_model", model)
    with pytest.raises(BudgetPersistenceError):
        await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(TASK)).run(
            {"task": TASK, "evidence_chains": CHAINS})
    assert model.await_count == 2


def _official_pool_chains():
    rows = [
        ("SQLite uses", "https://sqlite.org/whentouse.html", "SQLite permits one writer at a time."),
        ("SQLite backup", "https://sqlite.org/backup.html", "SQLite offers an online backup API."),
        ("SQLite search", "https://sqlite.org/fts5.html", "SQLite FTS5 supports full-text search."),
        ("PostgreSQL backup", "https://www.postgresql.org/docs/18/backup.html",
         "PostgreSQL documents several backup approaches."),
        ("PostgreSQL search", "https://www.postgresql.org/docs/18/textsearch-intro.html",
         "PostgreSQL supports full text searching."),
        ("SQLite vs PostgreSQL opinion", "https://example.net/compare",
         "An unverified comparison asserts that SQLite is always faster."),
    ]
    return [
        {"evidence_strength": "moderate", "sources": [
            {"title": title, "url": url, "snippet": snippet, "score": 7.0}
        ]}
        for title, url, snippet in rows
    ]


def test_preferred_official_pool_preserves_original_source_numbers():
    chains = _official_pool_chains()
    candidates = ["SQLite", "PostgreSQL"]
    pool = preferred_official_fact_ids(chains, candidates)
    assert pool == {1, 2, 3, 4, 5}
    selection, mapping = synth._summarize_chains(chains, include_numbers=pool)
    assert "[[5]]" in selection and "[[6]]" not in selection
    assert set(mapping) == pool
    full, full_mapping = synth._summarize_chains(chains)
    assert "[[6]]" in full and 6 in full_mapping


def test_preferred_pool_falls_back_for_mixed_one_sided_or_composite_evidence():
    candidates = ["SQLite", "PostgreSQL"]
    chains = _official_pool_chains()
    chains[4]["sources"][0]["url"] = "https://example.net/postgres"
    assert preferred_official_fact_ids(chains, candidates) is None
    chains = _official_pool_chains()
    chains[4]["sources"][0]["title"] = "SQLite search two"
    assert preferred_official_fact_ids(chains, candidates) is None
    chains = _official_pool_chains()
    chains[4]["sources"][0]["url"] = chains[3]["sources"][0]["url"]
    assert preferred_official_fact_ids(chains, candidates) is None
    assert preferred_official_fact_ids(_official_pool_chains(),
                                       ["PostgreSQL + pgvector", "SQLite"]) is None


def test_memcached_docs_exact_alias_can_enter_two_sided_official_pool():
    from deepchoice.utils.official_catalog import is_catalog_official_url
    chains = _official_pool_chains()
    for row, title, url in zip(chains[:5],
                               ["Redis eviction", "Redis persistence", "Redis data types",
                                "Memcached overview", "Memcached FAQ"],
                               ["https://redis.io/docs/latest/eviction/",
                                "https://redis.io/docs/latest/persistence/",
                                "https://redis.io/docs/latest/data-types/",
                                "https://docs.memcached.org/",
                                "https://docs.memcached.org/userguide/faq/"]):
        row["sources"][0].update(title=title, url=url)
    assert is_catalog_official_url("https://docs.memcached.org/userguide/faq/")
    assert not is_catalog_official_url("https://docs.memcached.org.evil.example/faq/")
    assert preferred_official_fact_ids(chains, ["Redis", "Memcached"]) == {1, 2, 3, 4, 5}


async def test_stage_rejects_facts_outside_preferred_pool(monkeypatch):
    model = AsyncMock(return_value={"source_facts": [{"id": "F1", "evidence_id": 6}]})
    monkeypatch.setattr(synth, "call_model", model)
    task = {**TASK, "candidate_techs": ["SQLite", "PostgreSQL"]}
    state = await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(
        {"task": task, "evidence_chains": _official_pool_chains()})
    assert model.await_count == 1
    assert "[[6]]" not in model.await_args_list[0].args[0][0]["content"]
    assert not state["final_recommendation"].get("source_facts", [])
    assert state["quality_signals"][0]["staged_generation"]["official_pool_preferred"]
