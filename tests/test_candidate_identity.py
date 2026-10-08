"""Candidate action labels keep their choices while routing literal products."""
import pytest

from deepchoice.agents.source_evaluator import (
    SourceEvaluatorAgent, _audited_seed_scope_covers_candidate, _candidate_patterns, _mentions_candidate,
)
from deepchoice.utils.evidence import candidate_name_pattern
from deepchoice.utils.official_catalog import AUDITED_PRODUCT_SEED_IDENTITY
from deepchoice.utils.question_packet import candidate_mentions, has_multi_candidate_coverage


@pytest.mark.parametrize("label,title", [
    ("继续使用 Atlas", "Atlas documentation"),
    ("迁移到 C++", "C++ reference"),
    ("切换到 Qt", "Qt deployment guide"),
    ("continue using Bun", "Bun runtime guide"),
    ("migrate to C#", "C# language reference"),
    ("keep using Node.js", "Node.js manual"),
    ("stay with Apache Kafka", "Apache Kafka documentation"),
    ("  CONTINUE   USING Atlas  ", "Atlas documentation"),
    ("继续使用甲乙", "甲乙文档"),
])
def test_action_label_uses_literal_identity_at_source_and_packet_boundaries(label, title):
    pattern = candidate_name_pattern(label)
    assert pattern is not None and pattern.search(title.casefold())
    assert _mentions_candidate({"title": title}, _candidate_patterns({"candidate_techs": [label]}))
    assert candidate_mentions(title, [label]) == [label]
    assert candidate_mentions("Unrelated product documentation", [label]) == []


@pytest.mark.parametrize("label", ["continue using", "keep using ", "迁移到", "继续使用",
    "continue using switch to Atlas", "继续使用 迁移到 uv"])
def test_action_without_product_cannot_disable_candidate_gate_or_claim_coverage(label):
    patterns = _candidate_patterns({"candidate_techs": [label]})
    assert patterns
    assert not _mentions_candidate({"title": "Continue using deployment patterns and documentation"}, patterns)
    assert not _mentions_candidate({"title": label + " general advice"}, patterns)
    assert candidate_mentions("Continue using deployment patterns and documentation", [label]) == []
    assert candidate_mentions("Switch implementation details for Atlas and uv", [label]) == []


@pytest.mark.parametrize("label,title,bad", [
    ("migrate to C++", "C++", "C++++"),
    ("继续使用 uv", "uv", "uvicorn"),
    ("keep using Node.js 22", "Node.js 22", "Node.js 20"),
    ("switch to Atlas + Vector", "Atlas + Vector", "Atlas"),
    ("Unknown Action Atlas", "Unknown Action Atlas", "Atlas"),
    ("Use Case", "Use Case", "Case"),
])
def test_identity_keeps_identifier_version_compound_and_unknown_label_bounds(label, title, bad):
    pattern = candidate_name_pattern(label)
    assert pattern is not None and pattern.search(title.casefold())
    assert not pattern.search(bad.casefold())


@pytest.mark.asyncio
async def test_evaluator_admits_product_prose_for_action_label_without_changing_task(monkeypatch):
    monkeypatch.setattr("deepchoice.runtime.context.get_run_context", lambda: None)
    task = {"query": "Choose how to use Atlas", "candidate_techs": ["继续使用 Atlas", "迁移到 Beta"]}
    results = [{"title": name + " documentation", "url": "https://example.org/" + name,
                "snippet": name + " stores records in a bounded local journal."} for name in ["Atlas", "Other"]]
    state = await SourceEvaluatorAgent().run({"task": task,
        "search_results": [{"source": "tavily", "results": results}]})
    assert [row["title"] for row in state["source_scores"]] == ["Atlas documentation"]
    assert task["candidate_techs"] == ["继续使用 Atlas", "迁移到 Beta"]


def test_audited_seed_scope_uses_same_identity_without_granting_other_product_scope():
    source = {"_seed_target_id": "p01-sqlite-wal", "_seed_source_type": "official",
              "_seed_verified_chunk": True,
              "_seed_seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY}
    assert _audited_seed_scope_covers_candidate(source, "chroma", ["continue using SQLite"]) is True
    assert _audited_seed_scope_covers_candidate(source, "chroma", ["迁移到 Redis"]) is False
    assert _audited_seed_scope_covers_candidate({**source, "_seed_seed_identity_sha256": "forged"},
                                              "chroma", ["继续使用 SQLite"]) is None


def test_multi_candidate_packet_preserves_original_choice_labels_and_missing_side():
    labels = ["continue using Atlas", "migrate to Beta"]
    assert not has_multi_candidate_coverage([{"source_title": "Atlas documentation"}], labels)
    assert has_multi_candidate_coverage([{"source_title": "Atlas documentation"},
                                        {"source_title": "Beta documentation"}], labels)


@pytest.mark.asyncio
@pytest.mark.parametrize("labels,source_names,supported", [
    (["continue using Alpha", "switch to Beta"], ["Alpha", "Beta"], True),
    (["继续使用 Alpha", "迁移到 Beta"], ["Alpha", "Beta"], True),
    (["continue using Alpha", "switch to Alpha Pro"], ["Alpha Pro"], False),
    (["继续使用甲乙", "切换到甲乙丙"], ["甲乙丙"], False),
])
@pytest.mark.parametrize("action", ["keep", "revise"])
async def test_action_choice_uses_own_product_through_binding_review_and_render(monkeypatch, labels, source_names, supported, action):
    from copy import deepcopy
    from unittest.mock import AsyncMock
    import httpx
    from deepchoice.agents import conclusion_synthesizer as synth, self_reviewer as review
    from deepchoice.agents.citation_validator import CitationValidatorAgent
    from deepchoice.agents.evidence_chain import EvidenceChainAgent
    from deepchoice.agents.report_generator import FORMAT_RENDERERS
    from deepchoice.contracts.manifest import build_run_manifest
    from tests.test_staged_question_synthesis import CHAINS, TASK, answer

    task = {**TASK, "candidate_techs": labels}
    originals = [deepcopy(chain["sources"][0]) for chain in CHAINS[:len(source_names)]]
    for source, name, original_name in zip(originals, source_names, ("Alpha", "Beta")):
        for key in ("title", "snippet"):
            source[key] = source[key].replace(original_name, name)
    state = {"task": deepcopy(task), "search_results": [{"source": "official", "results": originals}]}
    state.update(await SourceEvaluatorAgent().run(state))
    assert len(state["source_scores"]) == len(source_names)
    state.update(await EvidenceChainAgent().run(state))
    row = answer("R0")["decision_analysis"][0]
    row.update(kind="choice", option=labels[0], basis_refs=["B1", "B2"], assumptions=[],
               reasoning="Given tolerance for queuing, Alpha is an option to evaluate; restart recovery remains unconfirmed.")
    model = AsyncMock(side_effect=[{"source_view_ids": [f"S{i}" for i in range(1, len(source_names) + 1)]},
                                  {"decision_analysis": [row]}])
    monkeypatch.setattr(synth, "call_model", model)
    state.update(await synth.ConclusionSynthesizerAgent(run_manifest=build_run_manifest(task)).run(state))
    assert state["final_recommendation"]["decision_analysis"][0]["option"] == labels[0]

    async def fetch(_provider, url, **kwargs):
        text = next(source["snippet"] for source in originals if source["url"] == url)
        return httpx.Response(200, text=f"<p>{text}</p>", headers={"content-type": "text/html"})
    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state.update(await CitationValidatorAgent().run(state))
    before = deepcopy(state["final_recommendation"])
    review_row = {"analysis_id": "A1", "action": action,
                  "source_checks": [["F1", "supports", [1, 2]]]
                  + ([["F2", "irrelevant", []]] if len(source_names) == 2 else [])}
    if action == "revise":
        review_row.update(reasoning="Alpha can be evaluated when writers can wait; restart recovery still needs verification.",
                          assumptions=[], change_condition=row["change_condition"])
    reviewer = AsyncMock(return_value={"analysis_reviews": [review_row]})
    monkeypatch.setattr(review, "call_model", reviewer)
    state.update(await review.SelfReviewerAgent().run(state))
    final = state["final_recommendation"]
    if not supported:
        assert final["decision_analysis"] == []
        for render in FORMAT_RENDERERS.values():
            assert row["reasoning"] not in render(state)
        return
    assert len(final["decision_analysis"]) == 1
    retained = final["decision_analysis"][0]
    assert retained["option"] == labels[0]
    assert retained["basis"] == before["decision_analysis"][0]["basis"]
    assert final["source_facts"] == before["source_facts"]
    assert all(fact["status"] == "verified" for fact in final["source_facts"])
    assert final["winner"] == "context_dependent" and final["deployment_readiness"] == "unverified"
    assert final["action_plan_mode"] == "validation_only" and state["task"] == task
    for render in FORMAT_RENDERERS.values():
        report = render(state)
        assert retained["reasoning"] in report and labels[0] in report
    assert model.await_count == 2 and reviewer.await_count == 1


@pytest.mark.parametrize("label,product,wrong", [
    ("continue using C++", "C++", "C++++"),
    ("迁移到 C#", "C#", "C"),
    ("keep using Node.js 22", "Node.js 22", "Node.js 20"),
    ("switch to Atlas + Vector", "Atlas + Vector", "Atlas"),
    ("  CONTINUE   USING Alpha  ", "Alpha", "Alphabet"),
    ("继续使用甲乙", "甲乙", "其他"),
    ("Unknown Action Atlas", "Unknown Action Atlas", "Atlas"),
])
def test_review_candidate_identity_preserves_exact_product_boundaries(label, product, wrong):
    from types import SimpleNamespace
    from deepchoice.utils.analysis_review import _candidate_attribution
    context = SimpleNamespace(candidates=[label], facts=[{
        "id": "F1", "source_title": product + " manual", "saved_text": "Documented operating limits apply."}])
    assert _candidate_attribution(label, ["F1"], context)
    assert not _candidate_attribution(product + " has guaranteed recovery.", [], context)
    context.facts[0]["source_title"] = wrong + " manual"
    assert not _candidate_attribution(label, ["F1"], context)


@pytest.mark.parametrize("label", ["continue using", "迁移到", "continue using switch to Alpha"])
def test_review_rejects_named_action_without_unambiguous_product_identity(label):
    from types import SimpleNamespace
    from deepchoice.utils.analysis_review import _candidate_attribution
    context = SimpleNamespace(candidates=[label], facts=[{
        "id": "F1", "source_title": label, "saved_text": "General operating advice."}])
    assert not _candidate_attribution(label, ["F1"], context)


@pytest.mark.parametrize("short,long", [("Atlas", "Atlas + Vector"), ("Atlas", "Atlas Pro"),
                                        ("Node.js", "Node.js 22"), ("甲乙", "甲乙丙")])
def test_review_resolves_explicit_overlapping_products_without_borrowing_coverage(short, long):
    from types import SimpleNamespace
    from deepchoice.utils.analysis_review import _candidate_attribution
    context = SimpleNamespace(candidates=["continue using " + short, "switch to " + long], facts=[{
        "id": "F1", "source_title": long + " manual", "saved_text": "Operating limits apply."}])
    assert not _candidate_attribution("continue using " + short, ["F1"], context)
    assert _candidate_attribution("switch to " + long, ["F1"], context)
    # An actual separate mention may cover the short name; a contained prefix may not.
    context.facts[0]["saved_text"] = short + " has separate documented limits."
    assert _candidate_attribution("continue using " + short, ["F1"], context)
    assert _candidate_attribution(short + " compared with " + long, ["F1"], context)


def test_different_actions_for_same_literal_product_keep_shared_identity():
    from types import SimpleNamespace
    from deepchoice.utils.analysis_review import _candidate_attribution
    context = SimpleNamespace(candidates=["continue using Atlas", "switch to Atlas"], facts=[{
        "id": "F1", "source_title": "Atlas manual", "saved_text": "Operating limits apply."}])
    assert _candidate_attribution("continue using Atlas", ["F1"], context)
    assert _candidate_attribution("switch to Atlas", ["F1"], context)


@pytest.mark.parametrize("verified", [None, False, 1, "true"])
def test_audited_scope_requires_exact_producer_verification_flag(verified):
    source = {"_seed_target_id": "p04-fastapi-background-tasks", "_seed_source_type": "official",
              "_seed_seed_identity_sha256": AUDITED_PRODUCT_SEED_IDENTITY,
              "_seed_verified_chunk": verified}
    assert _audited_seed_scope_covers_candidate(source, "chroma", ["FastAPI BackgroundTasks"]) is None
