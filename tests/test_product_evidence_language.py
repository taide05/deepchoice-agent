"""Offline counterexamples, not a measurement of live-model quality.

Short source-language excerpts come from the already captured P01/P04 official
documents (serial-check-v1, 2026-09-27). HTTP and model calls are replaced.
"""
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from deepchoice.agents.citation_validator import CitationValidatorAgent, _calibrate_decision
from deepchoice.citations.contracts import CitationCheck, CitationReason, CitationStatus
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
@pytest.mark.parametrize("case,original,translated,requirement,url", CASES)
async def test_supported_source_fact_survives_with_unknown_workload_fit(
    monkeypatch, case, original, translated, requirement, url,
):
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=original, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = _state(original, case, requirement, url)
    row = state["final_recommendation"]["requirement_assessments"][0]
    row["status"] = "unknown"
    state["final_recommendation"]["unresolved_questions"] = [
        "该来源条件是否适用于当前工作负载，仍需实测。",
    ]
    result = await CitationValidatorAgent().run(state)
    rec = result["final_recommendation"]
    report = "\n".join(render_decision_details(rec, "zh"))

    assert result["citation_verification"]["status_counts"]["verified"] == 1
    assert rec["winner"] == "context_dependent"
    assert rec["requirement_assessments"][0]["status"] == "unknown"
    assert original in report
    assert "仍需实测" in rec["unresolved_questions"][0]
    assert translated not in report


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


@pytest.mark.asyncio
@pytest.mark.parametrize("case,original,translated,requirement,url", CASES)
async def test_mixed_translated_fact_and_uncited_inference_keeps_only_saved_source(
    monkeypatch, case, original, translated, requirement, url,
):

    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=original, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = _state(translated, case, requirement, url)
    state["evidence_chains"][0]["sources"][0]["snippet"] = original
    inference = "所以当前工作负载已经证明该方案足够安全。"
    state["final_recommendation"]["requirement_assessments"][0]["explanation"] = (
        f"{translated} [Source: {case}]；{inference}"
    )
    result = await CitationValidatorAgent().run(state)
    checks = result["citation_verification"]["checks"]
    assert {check["reason"] for check in checks} >= {"cross_language", "citation_missing"}
    row = result["final_recommendation"]["requirement_assessments"][0]
    report = "\n".join(render_decision_details(result["final_recommendation"], "zh"))
    assert row["status"] == "unknown"
    assert "provisional_explanation" not in row
    assert row["saved_source_excerpts"] == [{"title": case, "text": original}]
    assert inference not in report
    assert original in report


def test_mixed_critical_rows_receive_bounded_source_slots_before_ordinary_rows():
    sources = [{
        "title": f"Docs {index}", "url": f"https://docs.example.org/{index}",
        "snippet": f"Original source condition {index}."
    } for index in range(6)]
    checks = []
    rows = []
    for row_index in range(4):
        path = f"final_recommendation.requirement_assessments[{row_index}].explanation"
        source_indices = (0, 1) if row_index == 0 else (2, 3) if row_index == 1 else (row_index + 2,)
        for source_index in source_indices:
            source = sources[source_index]
            checks.append(CitationCheck(
                claim_id=f"c{row_index}-{source_index}", claim_path=path,
                claim_text="Translated source claim", source_title=source["title"],
                canonical_url=source["url"], status=CitationStatus.UNKNOWN,
                reason=CitationReason.CROSS_LANGUAGE,
            ))
        if row_index >= 2:
            checks.append(CitationCheck(
                claim_id=f"missing-{row_index}", claim_path=path,
                claim_text="Uncited workload inference", status=CitationStatus.UNSUPPORTED,
                reason=CitationReason.CITATION_MISSING,
            ))
        rows.append({
            "id": f"C{row_index + 1}", "requirement": f"Requirement {row_index}",
            "status": "satisfied", "decision_critical": True,
            "explanation": "Mixed model line", "evidence_ids": [1],
        })
    recommendation = {
        "decision_basis_version": "constraint-aware-v1", "winner": "context_dependent",
        "requirement_assessments": rows, "decision_branches": [], "action_plan": [],
    }
    result = _calibrate_decision(
        recommendation, SimpleNamespace(checks=tuple(checks)), "比较方案",
        [{"sources": sources}],
    )
    visible = result["requirement_assessments"]
    assert [row["id"] for row in visible] == ["C1", "C2", "C3", "C4"]
    assert all(row["status"] == "unknown" for row in visible)
    assert [len(row.get("saved_source_excerpts", [])) for row in visible] == [2, 0, 1, 1]
    assert all("provisional_explanation" not in row for row in visible[2:])


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


@pytest.mark.asyncio
@pytest.mark.parametrize("source_text,model_claim,url", [
    (
        "Beat for recurring tasks. Celery workers execute queued tasks.",
        "Beat is required for Celery tasks.",
        "https://docs.example.org/p04-beat",
    ),
    (
        "If many threads and/or processes need to write the database at the same instant "
        "(and they cannot queue up and take turns) then it is best to select a "
        "client/server database engine.",
        "Many concurrent writers require a client/server database engine.",
        "https://docs.example.org/p01-writers",
    ),
])
async def test_same_language_qualifier_gap_withdraws_decisive_row_and_branch_but_keeps_source(
    monkeypatch, source_text, model_claim, url,
):
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=source_text, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = _state(model_claim, "Source Docs", "Scene fit", url)
    state["task"]["query"] = "Compare these options for this workload"
    state["evidence_chains"][0]["sources"][0]["snippet"] = source_text
    state["final_recommendation"]["decision_branches"] = [
        {"option": "Option A", "condition": f"{model_claim} [Source: Source Docs]"},
    ]
    result = await CitationValidatorAgent().run(state)
    checks = result["citation_verification"]["checks"]
    assert [(check["status"], check["reason"]) for check in checks] == [
        ("unknown", "qualifier_unverified"), ("unknown", "qualifier_unverified"),
    ]
    rec = result["final_recommendation"]
    assert rec["requirement_assessments"][0]["status"] == "unknown"
    assert "provisional_explanation" not in rec["requirement_assessments"][0]
    assert rec["decision_branches"][0]["condition"] == (
        "Applicability requires checking the original source and this workload."
    )
    report = "\n".join(render_decision_details(rec, "en"))
    assert model_claim not in report
    assert source_text in report


@pytest.mark.asyncio
@pytest.mark.parametrize("case,source_text,model_claim,qualifier,url", [
    (
        "P04",
        "Celery production uses a broker and workers. Beat is for recurring tasks; monitoring is optional.",
        "Celery 需要 broker、worker、Beat 和监控。[Source: Source Docs]",
        "Beat is for recurring tasks",
        "https://docs.example.org/p04",
    ),
    (
        "P01",
        "WAL lets readers and a writer proceed concurrently. It can be slower for mostly-read workloads and adds sidecar files.",
        "SQLite 必须启用 WAL 以提升读写并发。[Source: Source Docs]",
        "can be slower for mostly-read workloads",
        "https://docs.example.org/p01",
    ),
])
async def test_unverified_applicability_keeps_complete_saved_source_separate_from_model_hypothesis(
    monkeypatch, case, source_text, model_claim, qualifier, url,
):
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=source_text, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = _state(model_claim, "Source Docs", "Actual workload applicability", url)
    state["evidence_chains"][0]["sources"][0]["snippet"] = source_text
    state["final_recommendation"]["decision_branches"] = [
        {"option": "Celery" if case == "P04" else "SQLite", "condition": model_claim},
    ]
    result = await CitationValidatorAgent().run(state)
    rec = result["final_recommendation"]
    report = "\n".join(render_decision_details(rec, "zh"))
    assert rec["winner"] == "context_dependent"
    assert rec["deployment_readiness"] == "unverified"
    assert rec["requirement_assessments"][0]["status"] == "unknown"
    assert "provisional_explanation" not in rec["requirement_assessments"][0]
    assert model_claim not in report
    assert "适用条件（待核查，不能仅据此选型）" in report
    assert "仅当（待验证条件）" not in report
    assert qualifier in report
    assert "保存的来源片段" in report
    assert "不证明原页完整或适用于本场景" in report
    assert rec["decision_branches"][0]["saved_source_excerpts"][0]["text"] == source_text


@pytest.mark.asyncio
async def test_many_earlier_unknown_rows_cannot_hide_beat_qualifier_or_bloat_report(monkeypatch):
    beat = "A broker and workers run tasks. Beat is for recurring tasks, not every queue."
    sources = [
        {"title": f"Earlier Docs {index}", "url": f"https://docs.example.org/earlier-{index}",
         "snippet": f"Earlier source {index} discusses a separate workload limit."}
        for index in range(9)
    ] + [{"title": "Celery Docs", "url": "https://docs.example.org/celery", "snippet": beat}]

    async def fetch(_source, url, **kwargs):
        source = next(item for item in sources if item["url"] == url)
        return httpx.Response(200, text=source["snippet"], headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    rows = [{
        "id": f"C{index}", "requirement": f"Requirement {index}",
        "status": "satisfied", "decision_critical": True,
        "explanation": f"前置条件 {index} 已满足。[Source: Earlier Docs {index}]",
        "evidence_ids": [index + 1],
    } for index in range(9)]
    rows.append({
        "id": "C9", "requirement": "Queue scheduling boundary", "status": "satisfied",
        "decision_critical": True,
        "explanation": "Celery 总是需要 Beat。[Source: Celery Docs]", "evidence_ids": [10],
    })
    state = {
        "task": {"query": "比较后台任务方案"},
        "evidence_chains": [{"sources": sources}],
        "final_recommendation": {
            "decision_basis_version": "constraint-aware-v1", "winner": "context_dependent",
            "requirement_assessments": rows,
            "decision_branches": [
                {"option": "Alternative", "condition": "先核查另一方案。[Source: Earlier Docs 0]"},
                {"option": "Celery", "condition": "Celery 必须部署 Beat。[Source: Celery Docs]"},
            ],
            "ranked_options": [], "recommendation": "", "action_plan": [],
        },
    }
    rec = (await CitationValidatorAgent().run(state))["final_recommendation"]
    report = "\n".join(render_decision_details(rec, "zh"))
    assert "Celery 必须部署 Beat" not in report
    assert "Celery 总是需要 Beat" not in report
    assert beat in report
    assert rec["decision_branches"][1]["saved_source_excerpts"][0]["text"] == beat
    assert sum(len(item.get("saved_source_excerpts", [])) for item in
               rec["requirement_assessments"] + rec["decision_branches"]) <= 4
    assert rec["requirement_assessments"][9]["status"] == "unknown"


@pytest.mark.asyncio
async def test_removed_branch_before_cross_language_claim_does_not_shift_check_binding(monkeypatch):
    source_text = "Beat is for recurring tasks."
    url = "https://docs.example.org/beat"

    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=source_text, headers={"content-type": "text/plain"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", fetch)
    state = _state("Beat  总是必需。[Source: Celery Docs]", "Celery Docs", "Scheduler", url)
    state["evidence_chains"][0]["sources"][0]["snippet"] = source_text
    state["final_recommendation"]["decision_branches"] = [
        {"option": "", "condition": "invalid branch"},
        {"option": "Celery", "condition": "Beat  总是必需。[Source: Celery Docs]"},
    ]
    rec = (await CitationValidatorAgent().run(state))["final_recommendation"]
    assert len(rec["decision_branches"]) == 1
    assert "总是必需" not in rec["decision_branches"][0]["condition"]
    assert rec["decision_branches"][0]["saved_source_excerpts"][0]["text"] == source_text


@pytest.mark.asyncio
@pytest.mark.parametrize("url,snippet", [
    ("https://gist.github.com/user/id", "FORGED SOURCE FACT"),
    ("https://docs.example.org/too-long", "x" * 1201),
])
async def test_model_forged_or_ineligible_saved_source_cannot_become_report_evidence(
    monkeypatch, url, snippet,
):
    async def no_fetch(*args, **kwargs):
        raise TimeoutError("safe fetch unavailable")

    monkeypatch.setattr("deepchoice.citations.verifier.safe_fetch", no_fetch)
    state = _state("Questionable claim. [Source: Source Docs]", "Source Docs", "Boundary", url)
    row = state["final_recommendation"]["requirement_assessments"][0]
    row["saved_source_excerpts"] = [{"title": "fake", "text": "FORGED EXCERPT"}]
    state["final_recommendation"]["decision_branches"] = [{
        "option": "Option A", "condition": "Questionable claim. [Source: Source Docs]",
        "saved_source_excerpts": [{"title": "fake", "text": "FORGED EXCERPT"}],
    }]
    state["evidence_chains"][0]["sources"][0]["snippet"] = snippet
    result = await CitationValidatorAgent().run(state)
    report = "\n".join(render_decision_details(result["final_recommendation"], "zh"))
    assert "FORGED EXCERPT" not in report
    assert "FORGED SOURCE FACT" not in report
    assert "saved_source_excerpts" not in result["final_recommendation"]["decision_branches"][0]


def test_saved_excerpt_markdown_delimiter_cannot_escape_literal_display():
    rec = {"decision_branches": [{
        "option": "Celery", "condition": "Check workload",
        "saved_source_excerpts": [{"title": "Source", "text": "Beat ```for recurring tasks``` only"}],
    }]}
    report = "\n".join(render_decision_details(rec, "en"))
    assert "````Beat ```for recurring tasks``` only````" in report
