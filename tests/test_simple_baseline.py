"""Paired baseline runner: shared evidence, one synthesis, isolated candidate tail."""
import asyncio
import hashlib
import json
import pathlib

import pytest

from deepchoice.evaluation import simple_baseline as sb
from deepchoice.evaluation.simple_baseline import (
    EvidenceMismatchError,
    OfflineGateError,
    build_shared_evidence,
    run_baseline,
    run_candidate,
    run_pair,
)

SNAPSHOT = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
            / "600af92f-f65e-41c0-aa6f-2811f943c124"
            / "research_snapshot.json")
HISTORICAL_SNAPSHOTS = [
    pathlib.Path(r"D:\deepchoice-precodex\outputs")
    / "e339d065-7a61-4993-9819-1405b23bb7cd" / "research_snapshot.json",
    pathlib.Path(r"D:\deepchoice-precodex\outputs")
    / "f4e9b7d5-10a8-4dcf-a69d-5b2a20a58a3b" / "research_snapshot.json",
    SNAPSHOT,
]


def _state():
    return {
        "task": {"query": "A vs B", "candidate_techs": ["A", "B"],
                 "constraints": [], "report_format": "what_why_how"},
        "sub_questions": ["which is safer?"],
        "source_scores": [{
            "url": "https://example.com/a", "title": "A docs",
            "snippet": "A supports the deployment.", "source_type": "tech_blog",
            "total_score": 7.0, "scores": {}, "date": "2026-01-01",
        }],
        "search_results": [{"source": "tavily", "status": "success",
                            "results": [{"url": "https://example.com/a"}]}],
        "conflicts": [], "conflict_check": {}, "evidence_chains": [],
        "quality_signals": [], "token_usage": [], "partial_failures": [],
        "empty_sources": [], "retry_count": 0,
    }


def _fake_model(review_usable=True):
    async def fake(prompt, **kwargs):
        tag = kwargs.get("tag", "")
        if tag == "self_reviewer":
            return {
                "checks": [{"item": i, "passed": True} for i in range(1, 7)],
                "passed_count": 6, "confidence": "medium", "knowledge_gaps": [],
                "corrections": [],
            }
        return {
            "winner": "A", "recommendation": "Use A [Source: A docs].",
            "ranked_options": [{"name": "A", "rank": 1,
                                "rationale": "Fits [Source: A docs]."}],
            "trade_offs": [], "evidence_summary": "limited",
            "confidence": "medium", "confidence_rationale": "limited",
            "unresolved_questions": [], "scene_fit_note": "",
        }
    return fake


def test_pair_uses_one_shared_evidence_package_and_separate_tails():
    out = asyncio.run(run_pair(_state(), call_model_fn=_fake_model()))
    assert out["evidence_equal"] is True
    assert out["baseline"]["evidence_package"] == out["shared_evidence"].package
    assert out["actual_evidence_package_count"] >= 2
    assert out["actual_evidence_entries_mismatch"] is False
    assert all(package == out["shared_evidence"].package
               for package in out["baseline"]["actual_evidence_packages"]
               + out["candidate"]["actual_evidence_packages"])
    assert all(record["entries_match"] is True
               for record in out["baseline"]["actual_evidence_records"]
               + out["candidate"]["actual_evidence_records"])
    assert out["baseline"]["report"]
    baseline_agents = {s.get("agent") for s in out["baseline"]["quality_signals"]}
    candidate_agents = {s.get("agent") for s in out["candidate"]["quality_signals"]}
    assert "simple_baseline_shared_evidence" in baseline_agents
    assert "self_reviewer" not in baseline_agents
    assert "self_reviewer" in candidate_agents
    assert out["baseline_incremental_calls"] == 0
    assert out["candidate_incremental_calls"] == 0


def test_baseline_refuses_external_calls_by_default():
    with pytest.raises(OfflineGateError):
        asyncio.run(run_baseline(_state()))


def test_incremental_calls_exclude_prefilled_shared_tokens():
    state = _state()
    state["token_usage"] = [
        {"agent": "shared", "model": "deepseek-flash", "calls": 2,
         "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        {"agent": "shared", "model": "deepseek-flash", "calls": 1,
         "prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    ]
    captured = {}

    async def fake(prompt, **kwargs):
        usage = kwargs.get("usage")
        if usage is not None:
            usage.append({"model": "deepseek-flash", "prompt_tokens": 1,
                          "completion_tokens": 1, "total_tokens": 2})
        tag = kwargs.get("tag", "")
        if tag == "self_reviewer":
            return {"checks": [{"item": i, "passed": True} for i in range(1, 7)],
                    "passed_count": 6, "confidence": "medium",
                    "knowledge_gaps": [], "corrections": []}
        captured["prompt"] = "\n".join(str(m.get("content", "")) for m in prompt)
        return {"winner": "A", "recommendation": "Use A.",
                "ranked_options": [], "trade_offs": [], "evidence_summary": "",
                "confidence": "medium", "confidence_rationale": "",
                "unresolved_questions": [], "scene_fit_note": ""}

    out = asyncio.run(run_candidate(state, call_model_fn=fake))
    assert sum(row["calls"] for row in out["token_usage"]) == 2
    assert all(row["agent"] != "shared" for row in out["token_usage"])


def test_incremental_baseline_calls_are_one_synthesis():
    state = _state()
    state["token_usage"] = [{"agent": "shared", "model": "deepseek-flash",
                             "calls": 5, "prompt_tokens": 1,
                             "completion_tokens": 1, "total_tokens": 2}]

    async def fake(prompt, **kwargs):
        usage = kwargs.get("usage")
        if usage is not None:
            usage.append({"model": "deepseek-flash", "prompt_tokens": 1,
                          "completion_tokens": 1, "total_tokens": 2})
        return {"winner": "A", "recommendation": "Use A.",
                "ranked_options": [], "trade_offs": [], "evidence_summary": "",
                "confidence": "medium", "confidence_rationale": "",
                "unresolved_questions": [], "scene_fit_note": ""}

    out = asyncio.run(run_baseline(state, call_model_fn=fake))
    assert sum(row["calls"] for row in out["token_usage"]) == 1
    assert all(row["agent"] != "shared" for row in out["token_usage"])


def test_budget_argument_controls_actual_synthesis_prompt():
    state = _state()
    long_body = "START " + ("X" * 5000) + " END"
    state["source_scores"][0]["snippet"] = long_body
    captured = {}

    def _fake(label):
        async def fake(prompt, **kwargs):
            captured[label] = "\n".join(
                str(m.get("content", "")) for m in prompt)
            return {"winner": "A", "recommendation": "Use A.",
                    "ranked_options": [], "trade_offs": [], "evidence_summary": "",
                    "confidence": "medium", "confidence_rationale": "",
                    "unresolved_questions": [], "scene_fit_note": ""}
        return fake

    out = asyncio.run(run_baseline(
        state, call_model_fn=_fake("tight"), budget_chars=500))
    asyncio.run(run_baseline(
        state, call_model_fn=_fake("default")))
    assert out["evidence_package"]["budget_chars"] == 500
    assert len(out["evidence_package"]["views"][1]["text"]) <= 500
    assert out["actual_evidence_packages"]
    assert all(pkg == out["evidence_package"]
               for pkg in out["actual_evidence_packages"])
    assert long_body not in captured["tight"]
    assert long_body in captured["default"]
    assert len(captured["tight"]) < len(captured["default"])


def test_missing_baseline_consumer_is_not_evidence_equal(monkeypatch):
    from deepchoice.agents import conclusion_synthesizer as cs
    monkeypatch.setattr(
        cs, "_summarize_chains",
        lambda *args, **kwargs: ("evidence not sent through the frozen package", {}, [])
    )
    out = asyncio.run(run_pair(_state(), call_model_fn=_fake_model()))
    assert out["baseline_actual_package_count"] == 0
    assert out["evidence_equal"] is False


def test_divergent_candidate_entries_are_rejected_before_synthesis(monkeypatch):
    from deepchoice.agents import evidence_chain as ec
    monkeypatch.setattr(
        ec.EvidenceChainAgent, "run",
        lambda self, state: _async_value({"evidence_chains": [],
                                           "quality_signals": []}),
    )
    with pytest.raises(EvidenceMismatchError):
        asyncio.run(run_pair(_state(), call_model_fn=_fake_model()))


async def _async_value(value):
    return value


def test_offline_candidate_disables_conflict_evidence_gathering(monkeypatch):
    captured = {}

    class FakeConflict:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, state):
            return {"conflicts": [], "conflict_check": {}}

    monkeypatch.setattr(sb.cd, "ConflictDetectorAgent", FakeConflict)
    asyncio.run(run_candidate(_state(), call_model_fn=_fake_model()))
    assert captured.get("gather_evidence") is False
    asyncio.run(run_candidate(_state(), call_model_fn=_fake_model(),
                              allow_model=True))
    assert captured.get("gather_evidence") is False


def test_source_envelope_count_is_not_called_request_count():
    out = asyncio.run(run_pair(
        _state(), call_model_fn=_fake_model(),
        shared_retrieval_counts=None))
    assert out["shared_retrieval_source_envelopes"] == 1
    assert out["shared_retrieval_http_requests"] is None
    assert out["shared_retrieval_http_requests_known"] is False


def test_saved_tenth_material_keeps_candidate_coverage_gaps_visible():
    if not SNAPSHOT.exists():
        pytest.skip(f"tenth snapshot not present at {SNAPSHOT}")
    before = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    state = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    shared = build_shared_evidence(state)
    assert shared.package["sources"] >= 1
    candidates = shared.coverage["candidates"]
    assert set(candidates) == {"Sigstore (Cosign)", "Notary Project (Notation)"}
    assert all(item["official_body_missing"] for item in candidates.values())
    assert shared.coverage["official_body_total"] == 0
    assert hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest() == before


def test_saved_v11_coverage_uses_row_owner_not_retriever_label():
    path = (pathlib.Path(r"D:\deepchoice-precodex\outputs")
            / "v11pair-a42b7594fa47" / "shared_snapshot.json")
    if not path.exists():
        pytest.skip(f"v11 snapshot not present at {path}")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    state = json.loads(path.read_text(encoding="utf-8"))["state"]
    shared = build_shared_evidence(state)
    candidates = shared.coverage["candidates"]
    assert candidates["OpenTelemetry Collector"]["official_body_missing"] is True
    assert candidates["Vector"]["official_body_missing"] is False
    assert candidates["Vector"]["official_body_urls"] == ["https://vector.dev/docs/"]
    assert shared.coverage["official_body_total"] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("path", HISTORICAL_SNAPSHOTS)
def test_eighth_to_tenth_material_is_read_only_fixed_input(path):
    if not path.exists():
        pytest.skip(f"historical snapshot missing: {path}")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    state = json.loads(path.read_text(encoding="utf-8"))
    shared = build_shared_evidence(state)
    assert shared.package["sources"] >= 0
    assert "candidates" in shared.coverage
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
