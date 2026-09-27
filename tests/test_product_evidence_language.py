"""Offline counterexamples, not a measurement of live-model quality.

Short source-language excerpts come from the already captured P01/P04 official
documents (serial-check-v1, 2026-09-27). HTTP and model calls are replaced.
"""
from copy import deepcopy

import httpx
import pytest

from deepchoice.agents.citation_validator import CitationValidatorAgent
from deepchoice.agents.conclusion_synthesizer import (
    SYNTHESIS_PROMPT, _bind_citations, _normalize_decision_contract,
    _sanitize_citations, _summarize_chains, _usable_evidence_ids,
)
from deepchoice.citations.verifier import _extract_claims
from deepchoice.formats.decision import render_decision_details
from deepchoice.utils.decision_contract import (
    abstain_recommendation, is_fixed_validation_only_plan, restrict_action_plan,
)


CASES = [
    ("P01", "SQLite only supports one writer at a time per database file.",
     "SQLite 每个数据库文件同一时刻只支持一个写入者。", "Write concurrency",
     "https://www.sqlite.org/whentouse.html"),
    ("P04", "Ideally task functions should be idempotent: meaning the function won’t cause unintended effects even if called multiple times with the same arguments.",
     "任务函数应具有幂等性：相同参数调用多次也不会产生非预期副作用。", "Idempotency semantics",
     "https://docs.celeryq.dev/en/stable/userguide/tasks.html"),
]


def _state(text, title, requirement, url):
    claim = f"{text} [Source: {title}]"
    return {
        "task": {"query": "比较方案并说明限制"},
        "evidence_chains": [{"sources": [{"title": title, "url": url, "snippet": text}]}],
        "final_recommendation": {
            "decision_basis_version": "constraint-aware-v1", "winner": "context_dependent",
            "requirement_assessments": [{
                "id": "C1", "requirement": requirement, "status": "satisfied",
                "decision_critical": True, "explanation": claim, "evidence_ids": [1],
            }],
            "ranked_options": [], "recommendation": "", "action_plan": [],
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("case,original,translated,requirement,url", CASES)
async def test_original_language_preserves_supported_premise_without_promoting_translation(
    monkeypatch, case, original, translated, requirement, url,
):
    calls = []

    async def fetch(*args, **kwargs):
        calls.append(args)
        return httpx.Response(200, text=original, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    translated_result = await CitationValidatorAgent().run(_state(translated, case, requirement, url))
    state = _state(original, case, requirement, url)
    before = deepcopy(state)
    original_result = await CitationValidatorAgent().run(state)
    assert state == before
    assert len(calls) == 2  # One logical fetch each, no extra translation/judge call.
    assert translated_result["citation_verification"]["checks"][0]["reason"] == "cross_language"
    assert translated_result["final_recommendation"]["requirement_assessments"][0]["status"] == "unknown"
    rec = original_result["final_recommendation"]
    assert original_result["citation_verification"]["status_counts"]["verified"] == 1
    assert rec["requirement_assessments"][0]["status"] == "satisfied"
    assert rec["winner"] == "context_dependent"  # No inference of workload suitability.
    assert "词法支持不等于语义证明" in "\n".join(render_decision_details(rec, "zh"))


@pytest.mark.asyncio
@pytest.mark.parametrize("text,reason", [
    ("SQLite supports 5000 simultaneous writers.", "numeric_mismatch"),
    ("SQLite does not support one writer at a time per database file.", "negation_conflict"),
    ("SQLite guarantees online backup and seamless migration.", "lexical_mismatch"),
])
async def test_source_language_is_not_a_fact_or_applicability_bypass(monkeypatch, text, reason):
    _, original, _, requirement, url = CASES[0]
    original += " SQLite supports an unlimited number of simultaneous readers."

    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=original, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    result = await CitationValidatorAgent().run(_state(text, "P01", requirement, url))
    row = result["final_recommendation"]["requirement_assessments"][0]
    assert result["citation_verification"]["checks"][0]["reason"] == reason
    assert row["status"] == "unknown" and "provisional_explanation" not in row


@pytest.mark.parametrize("url", [
    "https://gist.github.com/user/id", "https://GIST.GITHUB.COM./id",
    "https://gist.githubusercontent.com/user/id/raw/file", "https://pastebin.com/id",
])
def test_paste_evidence_cannot_enter_prompt_number_binding_or_title_binding(url):
    chains = [{"conclusion": "CONTAMINATED SUMMARY", "sources": [
        {"title": "Paste", "url": url, "snippet": "UNTRUSTED PASTE ASSERTION"},
        {"title": "Official Docs", "url": "https://docs.example.org/page", "snippet": "A real excerpt"},
    ]}]
    before = deepcopy(chains)
    prompt, mapping = _summarize_chains(chains)
    assert chains == before
    assert "UNTRUSTED PASTE" not in prompt and "CONTAMINATED" not in prompt
    assert mapping == {2: "Official Docs"} and _usable_evidence_ids(chains) == {2}
    result = {"recommendation": "Bad [[1]] [Source: Paste]; allowed [[2]]"}
    result = _bind_citations(_sanitize_citations(result, chains), mapping)
    assert "Source: Paste" not in result["recommendation"]
    assert "Source: Official Docs" in result["recommendation"]
    rec, unresolved = _normalize_decision_contract({"requirement_assessments": [{
        "id": "C1", "requirement": "Durability", "status": "satisfied",
        "explanation": "Reliable [[1]]", "evidence_ids": [1],
    }]}, [{"id": "C1", "requirement": "Durability", "kind": "frozen_constraint"}], {2})
    assert unresolved and rec["requirement_assessments"][0]["status"] == "unknown"


def test_paste_filter_does_not_ban_github_projects_or_use_url_substrings():
    chains = [{"sources": [
        {"title": "Celery project", "url": "https://github.com/celery/celery", "snippet": "real code"},
        {"title": "Reference", "url": "https://example.org/gist.github.com", "snippet": "real prose"},
    ]}]
    assert set(_summarize_chains(chains)[1]) == _usable_evidence_ids(chains) == {1, 2}


@pytest.mark.asyncio
async def test_abbreviated_official_title_cannot_rebind_to_exact_paste_title(monkeypatch):
    from deepchoice.citations.verifier import verify_citations
    urls = []

    async def fetch(_source, url, **kwargs):
        urls.append(url)
        return httpx.Response(200, text="Tasks should be idempotent.",
                              headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    chains = [{"sources": [
        {"title": "Celery documentation", "url": "https://gist.github.com/u/id"},
        {"title": "Celery documentation: acknowledgements", "url": "https://docs.celeryq.dev/tasks"},
    ]}]
    rec = _sanitize_citations({
        "recommendation": "Tasks should be idempotent. [Source: Celery documentation]",
    }, chains)
    verification, _ = await verify_citations(rec, chains)
    assert urls == ["https://docs.celeryq.dev/tasks"]
    assert verification.status_counts.verified == 1
    urls.clear()
    verification, _ = await verify_citations(rec, [{"sources": [chains[0]["sources"][0]]}])
    assert not urls and verification.status_counts.unsupported == 1


@pytest.mark.parametrize("query", ["FastAPI 后台长任务要用 Celery 吗？", "Celery or in-process background tasks?"])
def test_queue_restriction_has_four_measurable_stages_and_exact_template_guard(query):
    unsafe = {"action_plan": [{"step": "LIVE_CUTOVER", "verification": "trust me",
                                "change_trigger": "now", "rollback": "OVERWRITE_PRODUCTION"}]}
    rec = restrict_action_plan(unsafe, query)
    assert len(rec["action_plan"]) == 4
    plan = str(rec["action_plan"])
    for term in ("task_id", "broker", "result", "worker", "acks_late", "exactly-once"):
        assert term in plan
    assert "LIVE_CUTOVER" not in plan and "OVERWRITE_PRODUCTION" not in plan
    assert is_fixed_validation_only_plan(rec, query)
    assert restrict_action_plan(rec, query) == rec
    assert abstain_recommendation(rec, query)["action_plan"] == rec["action_plan"]
    forged = deepcopy(rec)
    forged["action_plan"][2]["rollback"] = "OVERWRITE_PRODUCTION"
    assert not is_fixed_validation_only_plan(forged, query)
    assert not is_fixed_validation_only_plan(rec, "Choose a database")


def test_unknown_label_does_not_hide_uncited_technical_assertions():
    claims, overflow = _extract_claims({"requirement_assessments": [{
        "status": "unknown", "evidence_ids": [],
        "explanation": "Celery guarantees exactly-once delivery and cannot lose tasks.",
    }]})
    assert not overflow and len(claims) == 1 and claims[0].source_title is None


@pytest.mark.asyncio
async def test_unknown_technical_assertion_is_removed_from_report(monkeypatch):
    async def no_fetch(*args, **kwargs):
        raise AssertionError("uncited claim must not fetch")

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", no_fetch)
    state = _state("ignored", "P04", "Durability", CASES[1][4])
    row = state["final_recommendation"]["requirement_assessments"][0]
    row.update(status="unknown", evidence_ids=[], explanation="Celery guarantees exactly-once delivery.")
    result = await CitationValidatorAgent().run(state)
    report = "\n".join(render_decision_details(result["final_recommendation"], "zh"))
    assert "guarantees exactly-once" not in report
    assert result["citation_verification"]["status_counts"]["unsupported"] == 1


def test_prompt_preserves_language_qualifications_and_primary_source_preference():
    for rule in ("SOURCE-LANGUAGE EXCEPTION", "translation equivalence", "negation",
                 "prefer applicable original documentation", "never imply a deployment test has already passed"):
        assert rule in SYNTHESIS_PROMPT
