"""Offline-capable paired runner: simple baseline vs the candidate graph tail.

The shared collection stops after retrieval + source scoring. Both arms receive
the same source scores, source bodies and evidence budget. The baseline performs
one deterministic evidence serialization -> one synthesis -> the existing citation
binding/report rendering. The candidate arm keeps the existing conflict/evidence
chain/synthesis/self-review tail. No conflict, self-review or retry runs in the
baseline. This is a comparison harness, not a new evaluation platform.
"""
from __future__ import annotations

import copy
import contextlib
import hashlib
import json
from dataclasses import dataclass, field

from ..agents import conclusion_synthesizer as cs
from ..agents import conflict_detector as cd
from ..agents import report_generator as rg
from ..agents import self_reviewer as sr
from ..agents.evidence_chain import EvidenceChainAgent, build_evidence_chain
from ..utils import candidate_identity as cid
from ..utils.candidate_identity import (
    EVIDENCE_INPUT_BUDGET_CHARS,
    evidence_focus_terms_for_state,
    has_factual_content,
    shared_evidence_package,
)


class OfflineGateError(RuntimeError):
    """Raised when a pair run would call an external model without authorization."""


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


# Fields that define the evidence actually shown to a consumer. Per-arm metadata
# (e.g. the disputed flag) must not make two otherwise identical source packages
# look different, while title/body/url/number divergence must.
_EVIDENCE_ENTRY_FIELDS = (
    "number", "source_id", "title", "url", "body", "provenance", "channel",
    "date", "body_url", "body_page_chars", "body_prose_chars",
    "body_stored_chars", "body_page_truncated", "body_stored_truncated",
    "body_truncated", "body_admission",
)


def _entries_signature(entries: list[dict]) -> str:
    normalized = []
    for entry in entries or []:
        normalized.append({key: entry.get(key) for key in _EVIDENCE_ENTRY_FIELDS
                           if key in entry})
    return _canonical_sha256(normalized)


@dataclass
class SharedEvidence:
    chains: list[dict]
    package: dict
    coverage: dict
    entries_signature: str = ""
    package_sha256: str = ""


def _coverage(state: dict, source_scores: list[dict]) -> dict:
    """Per-candidate coverage based on actual URLs/content, not retriever names."""
    candidates = list((state.get("task") or {}).get("candidate_techs") or [])
    records = []
    for source in source_scores or []:
        title = str(source.get("title") or "")
        body = str(source.get("snippet") or source.get("body") or "")
        url = str(source.get("url") or "")
        has_body = bool(has_factual_content(source))
        official_body = bool(
            has_body and source.get("body_page_chars")
            and source.get("source_type") == "official_doc"
        )
        records.append({"url": url, "title": title, "body": body,
                        "has_body": has_body, "official_body": official_body})
    result = {}
    for candidate in candidates:
        mentioned = [
            r for r in records
            if _text_discusses(candidate, r["title"], r["body"])
        ]
        official = [r for r in mentioned if r["official_body"]]
        result[candidate] = {
            "mentioned_source_count": len(mentioned),
            "mentioned_urls": [r["url"] for r in mentioned][:20],
            "official_body_source_count": len(official),
            "official_body_urls": [r["url"] for r in official][:20],
            "official_body_missing": not official,
        }
    return {"candidates": result,
            "official_body_total": sum(1 for r in records if r["official_body"]),
            "source_count": len(records)}


def _text_discusses(candidate: str, title: str, body: str) -> bool:
    from ..utils.candidate_identity import source_text_discusses_candidate
    return source_text_discusses_candidate(candidate, title, body)


def build_shared_evidence(state: dict, *, budget_chars: int | None = None) -> SharedEvidence:
    """Freeze source bodies and the one evidence package both arms may use."""
    source_scores = state.get("source_scores") or []
    chains = build_evidence_chain(source_scores, [])
    from ..agents.conclusion_synthesizer import build_source_registry
    registry = build_source_registry(chains)
    focus = evidence_focus_terms_for_state(state)
    package = shared_evidence_package(
        registry["entries"], focus_terms=focus, budget_chars=budget_chars)
    coverage = _coverage(state, source_scores)
    return SharedEvidence(
        chains=chains, package=package, coverage=coverage,
        entries_signature=_entries_signature(registry["entries"]),
        package_sha256=_canonical_sha256(package),
    )


def _baseline_state(state: dict, shared: SharedEvidence) -> dict:
    baseline = copy.deepcopy(state)
    baseline["conflicts"] = []
    baseline["conflict_check"] = {}
    baseline["evidence_chains"] = copy.deepcopy(shared.chains)
    baseline["quality_signals"] = list(state.get("quality_signals") or []) + [{
        "agent": "simple_baseline_shared_evidence",
        "evidence_input_budget_chars": shared.package["budget_chars"],
        "evidence_full_included": shared.package["full_included"],
        "evidence_sources": shared.package["sources"],
        "evidence_visible_chars": shared.package["visible_chars"],
        "candidate_coverage": copy.deepcopy(shared.coverage),
        "arm": "baseline",
    }]
    return baseline


def _candidate_state(state: dict) -> dict:
    candidate = copy.deepcopy(state)
    candidate["conflicts"] = []
    candidate["conflict_check"] = {}
    candidate["evidence_chains"] = []
    return candidate


@contextlib.contextmanager
def _evidence_budget(budget_chars):
    if budget_chars is None:
        yield
        return
    saved = cid.EVIDENCE_INPUT_BUDGET_CHARS
    cid.EVIDENCE_INPUT_BUDGET_CHARS = int(budget_chars)
    try:
        yield
    finally:
        cid.EVIDENCE_INPUT_BUDGET_CHARS = saved


@contextlib.contextmanager
def _freeze_evidence_package(shared: SharedEvidence, observed: list[dict]):
    """Make the recorded package the one the actual consumers receive.

    `_summarize_chains` and `_source_register_text` resolve the package builder
    through `candidate_identity.shared_evidence_package`. During an arm this
    wrapper returns the frozen package and records every actual request, so the
    equality check is against real consumption rather than a fresh recomputation.
    """
    original = cid.shared_evidence_package

    def frozen_package(entries, **kwargs):
        observed.append({
            "package": copy.deepcopy(shared.package),
            "package_sha256": _canonical_sha256(shared.package),
            "entries_signature": _entries_signature(entries),
            "entries_match": _entries_signature(entries) == shared.entries_signature,
        })
        return copy.deepcopy(shared.package)

    cid.shared_evidence_package = frozen_package
    try:
        yield
    finally:
        cid.shared_evidence_package = original


@contextlib.contextmanager
def _injected_model(call_model_fn):
    if call_model_fn is None:
        yield
        return
    modules = (cd, cs, sr)
    saved = [module.call_model for module in modules]
    try:
        for module in modules:
            module.call_model = call_model_fn
        yield
    finally:
        for module, original in zip(modules, saved):
            module.call_model = original


def _incremental_token_usage(state: dict, shared_prefix_len: int,
                             arm: str) -> list[dict]:
    rows = list(state.get("token_usage") or [])[shared_prefix_len:]
    return [dict(row, arm=arm) for row in rows]


async def run_baseline(state: dict, *, call_model_fn=None,
                       budget_chars: int | None = None,
                       allow_external: bool = False,
                       shared_evidence: SharedEvidence | None = None) -> dict:
    """Run only the simple baseline arm. Offline unless an injected model or flag."""
    if call_model_fn is None and not allow_external:
        raise OfflineGateError(
            "baseline requires an injected call_model_fn or allow_external=True")
    shared = shared_evidence or build_shared_evidence(
        state, budget_chars=budget_chars)
    baseline = _baseline_state(state, shared)
    shared_signal = baseline["quality_signals"][-1]
    shared_prefix_len = len(state.get("token_usage") or [])
    actual_packages: list[dict] = []
    with _evidence_budget(budget_chars), _injected_model(call_model_fn), \
            _freeze_evidence_package(shared, actual_packages):
        synth = await cs.ConclusionSynthesizerAgent().run(baseline)
        baseline.update(synth)
        report = await rg.ReportGeneratorAgent().run(baseline)
        baseline.update(report)
    baseline["quality_signals"] = [shared_signal] + list(
        baseline.get("quality_signals") or [])
    return {
        "arm": "baseline",
        "state": baseline,
        "report": baseline.get("report", ""),
        "final_recommendation": baseline.get("final_recommendation") or {},
        "quality_signals": baseline.get("quality_signals") or [],
        "token_usage": _incremental_token_usage(baseline, shared_prefix_len, "baseline"),
        "shared_evidence": shared,
        "evidence_package": shared.package,
        "actual_evidence_records": actual_packages,
        "actual_evidence_packages": [record["package"] for record in actual_packages],
        "coverage": shared.coverage,
    }


async def run_candidate(state: dict, *, call_model_fn=None,
                        budget_chars: int | None = None,
                        allow_external: bool = False,
                        shared_evidence: SharedEvidence | None = None) -> dict:
    """Run the existing candidate tail from the same post-scoring cutoff."""
    if call_model_fn is None and not allow_external:
        raise OfflineGateError(
            "candidate arm requires an injected call_model_fn or allow_external=True")
    shared = shared_evidence or build_shared_evidence(
        state, budget_chars=budget_chars)
    candidate = _candidate_state(state)
    shared_prefix_len = len(state.get("token_usage") or [])
    actual_packages: list[dict] = []
    with _evidence_budget(budget_chars), _injected_model(call_model_fn), \
            _freeze_evidence_package(shared, actual_packages):
        conflicts = await cd.ConflictDetectorAgent(
            gather_evidence=allow_external).run(candidate)
        candidate.update(conflicts)
        chains = await EvidenceChainAgent().run(candidate)
        candidate.update(chains)
        synth = await cs.ConclusionSynthesizerAgent().run(candidate)
        candidate.update(synth)
        report = await rg.ReportGeneratorAgent().run(candidate)
        candidate.update(report)
        review = await sr.SelfReviewerAgent().run(candidate)
        candidate.update(review)
    return {
        "arm": "candidate",
        "state": candidate,
        "report": candidate.get("report", ""),
        "final_recommendation": candidate.get("final_recommendation") or {},
        "quality_signals": candidate.get("quality_signals") or [],
        "token_usage": _incremental_token_usage(candidate, shared_prefix_len, "candidate"),
        "shared_evidence": shared,
        "actual_evidence_records": actual_packages,
        "actual_evidence_packages": [record["package"] for record in actual_packages],
        "coverage": shared.coverage,
    }


async def run_pair(state: dict, *, call_model_fn=None,
                   budget_chars: int | None = None,
                   allow_external: bool = False) -> dict:
    """Run both arms from one fixed post-scoring state."""
    shared = build_shared_evidence(state, budget_chars=budget_chars)
    baseline = await run_baseline(
        state, call_model_fn=call_model_fn, budget_chars=budget_chars,
        allow_external=allow_external, shared_evidence=shared)
    candidate = await run_candidate(
        state, call_model_fn=call_model_fn, budget_chars=budget_chars,
        allow_external=allow_external, shared_evidence=shared)
    baseline_records = baseline["actual_evidence_records"]
    candidate_records = candidate["actual_evidence_records"]
    records = baseline_records + candidate_records

    def _record_matches(record: dict) -> bool:
        return (record.get("package_sha256") == shared.package_sha256
                and record.get("entries_signature") == shared.entries_signature
                and record.get("entries_match") is True)

    return {
        "shared_evidence": shared,
        "baseline": baseline,
        "candidate": candidate,
        # Materialize the frozen package at the actual consumer boundary. Both
        # arms must have consumed it; comparing recomputations is not enough.
        "evidence_equal": (bool(baseline_records) and bool(candidate_records)
                           and all(_record_matches(record) for record in records)),
        "actual_evidence_package_count": len(records),
        "baseline_actual_package_count": len(baseline_records),
        "candidate_actual_package_count": len(candidate_records),
        "actual_evidence_entries_mismatch": any(
            record.get("entries_signature") != shared.entries_signature
            for record in records),
        "baseline_incremental_calls": sum(
            row.get("calls", 0) for row in baseline["token_usage"]),
        "candidate_incremental_calls": sum(
            row.get("calls", 0) for row in candidate["token_usage"]),
        "shared_retrieval_requests": len(state.get("search_results") or []),
    }


def default_evidence_budget() -> int:
    return EVIDENCE_INPUT_BUDGET_CHARS
