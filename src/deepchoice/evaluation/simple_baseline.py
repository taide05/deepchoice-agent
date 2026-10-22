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
import contextvars
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


class EvidenceMismatchError(RuntimeError):
    """Raised before a model dispatch when a consumer's evidence differs from the freeze."""


_CONSUMER = contextvars.ContextVar("pair_evidence_consumer", default="")


@contextlib.contextmanager
def _consumer(name: str):
    token = _CONSUMER.set(name)
    try:
        yield
    finally:
        _CONSUMER.reset(token)


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


# Fields that define the evidence actually shown to a consumer. Per-arm metadata
# (e.g. the disputed flag) must not make two otherwise identical source packages
# look different, while title/body/url/number divergence must.
_EVIDENCE_ENTRY_FIELDS = (
    "number", "source_id", "title", "url", "body", "provenance", "channel",
    "source_owner", "source_kind", "source_type", "body_identity_verified",
    "fetch_status", "date", "body_url", "body_page_chars", "body_prose_chars",
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
    """Per-candidate coverage from row identity, not retriever labels."""
    candidates = list((state.get("task") or {}).get("candidate_techs") or [])
    official_rows = {}
    for channel in state.get("search_results") or []:
        if channel.get("source") != "official":
            continue
        for row in channel.get("results") or []:
            if row.get("url"):
                official_rows[row["url"]] = row
    records = []
    for source in source_scores or []:
        url = str(source.get("url") or "")
        title = str(source.get("title") or "")
        body = str(source.get("snippet") or source.get("body") or "")
        official_row = official_rows.get(url) or {}
        owner = source.get("source_owner") or official_row.get("source_owner") or ""
        has_body_marker = (source.get("has_body")
                           if "has_body" in source else official_row.get("has_body"))
        has_fetched_body = bool(
            has_body_marker is True
            and (source.get("body_identity_verified") is True
                 or official_row.get("body_identity_verified") is True)
            and (source.get("body_page_chars") or official_row.get("body_page_chars"))
        )
        records.append({
            "url": url, "title": title, "body": body, "owner": owner,
            "has_body": bool(has_factual_content(source)),
            "official_body": has_fetched_body,
        })
    result = {}
    for candidate in candidates:
        mentioned = [
            r for r in records
            if _text_discusses(candidate, r["title"], r["body"])
        ]
        official = {}
        for r in mentioned:
            if not r["official_body"]:
                continue
            if (r["owner"] and _same_source_owner(candidate, r["owner"])) \
                    or _source_url_matches(candidate, r["url"]):
                official.setdefault(r["url"], r)
        official = list(official.values())
        result[candidate] = {
            "mentioned_source_count": len(mentioned),
            "mentioned_urls": [r["url"] for r in mentioned][:20],
            "official_body_source_count": len(official),
            "official_body_urls": [r["url"] for r in official][:20],
            "official_body_missing": not official,
        }
    unique_official = {r["url"] for r in records if r["official_body"]}
    return {"candidates": result,
            "official_body_total": len(unique_official),
            "source_count": len(records)}


def _text_discusses(candidate: str, title: str, body: str) -> bool:
    from ..utils.candidate_identity import source_text_discusses_candidate
    return source_text_discusses_candidate(candidate, title, body)


def _same_source_owner(candidate: str, owner: str) -> bool:
    return (candidate or "").strip().casefold() == (owner or "").strip().casefold()


def _source_url_matches(candidate: str, url: str) -> bool:
    from ..utils.candidate_identity import source_url_identity_match
    return source_url_identity_match(candidate, url)


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
        signature = _entries_signature(entries)
        record = {
            "package": copy.deepcopy(shared.package),
            "package_sha256": _canonical_sha256(shared.package),
            "entries_signature": signature,
            "entries_match": signature == shared.entries_signature,
            "consumer": _CONSUMER.get(),
        }
        observed.append(record)
        if not record["entries_match"]:
            # Do not let a mismatched source set/order/body reach the model with
            # the frozen package. The arm fails before its model dispatch.
            raise EvidenceMismatchError(
                "source entries differ from the frozen evidence package: "
                f"observed {signature[:16]} frozen {shared.entries_signature[:16]}")
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


def _model_allowed(call_model_fn, allow_external: bool,
                   allow_model: bool | None) -> bool:
    if call_model_fn is not None:
        return True
    if allow_model is not None:
        return bool(allow_model)
    return bool(allow_external)


async def run_baseline(state: dict, *, call_model_fn=None,
                       budget_chars: int | None = None,
                       allow_external: bool = False,
                       allow_model: bool | None = None,
                       shared_evidence: SharedEvidence | None = None) -> dict:
    """Run only the simple baseline arm. Offline unless a model is authorized."""
    if not _model_allowed(call_model_fn, allow_external, allow_model):
        raise OfflineGateError(
            "baseline requires an injected call_model_fn or allow_model=True")
    shared = shared_evidence or build_shared_evidence(
        state, budget_chars=budget_chars)
    baseline = _baseline_state(state, shared)
    shared_signal = baseline["quality_signals"][-1]
    shared_prefix_len = len(state.get("token_usage") or [])
    actual_packages: list[dict] = []
    with _evidence_budget(budget_chars), _injected_model(call_model_fn), \
            _freeze_evidence_package(shared, actual_packages), \
            _consumer("baseline_synthesis"):
        synth = await cs.ConclusionSynthesizerAgent().run(baseline)
        baseline.update(synth)
    with _consumer("baseline_report"):
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
                        allow_model: bool | None = None,
                        allow_supplementary_search: bool = False,
                        shared_evidence: SharedEvidence | None = None) -> dict:
    """Run the existing candidate tail; no supplementary search after the freeze."""
    if not _model_allowed(call_model_fn, allow_external, allow_model):
        raise OfflineGateError(
            "candidate arm requires an injected call_model_fn or allow_model=True")
    shared = shared_evidence or build_shared_evidence(
        state, budget_chars=budget_chars)
    candidate = _candidate_state(state)
    shared_prefix_len = len(state.get("token_usage") or [])
    actual_packages: list[dict] = []
    with _evidence_budget(budget_chars), _injected_model(call_model_fn), \
            _freeze_evidence_package(shared, actual_packages):
        conflicts = await cd.ConflictDetectorAgent(
            # The pair freezes evidence before this arm. Conflict judgment may
            # use the saved material; it may never add retrieval unless an
            # operator explicitly combines it with supplementary-search budget.
            gather_evidence=bool(allow_supplementary_search)).run(candidate)
        candidate.update(conflicts)
        chains = await EvidenceChainAgent().run(candidate)
        candidate.update(chains)
        with _consumer("candidate_synthesis"):
            synth = await cs.ConclusionSynthesizerAgent().run(candidate)
            candidate.update(synth)
        with _consumer("candidate_report"):
            report = await rg.ReportGeneratorAgent().run(candidate)
            candidate.update(report)
        with _consumer("candidate_self_review"):
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
                   allow_external: bool = False,
                   allow_model: bool | None = None,
                   allow_supplementary_search: bool = False,
                   shared_retrieval_counts: dict | None = None) -> dict:
    """Run both arms from one fixed post-scoring state.

    `shared_retrieval_counts` carries dispatch counters from the one shared
    collection. It is optional and is never inferred from the result-row count.
    """
    shared = build_shared_evidence(state, budget_chars=budget_chars)
    baseline = await run_baseline(
        state, call_model_fn=call_model_fn, budget_chars=budget_chars,
        allow_external=allow_external, allow_model=allow_model,
        shared_evidence=shared)
    candidate = await run_candidate(
        state, call_model_fn=call_model_fn, budget_chars=budget_chars,
        allow_external=allow_external, allow_model=allow_model,
        allow_supplementary_search=allow_supplementary_search,
        shared_evidence=shared)
    baseline_records = baseline["actual_evidence_records"]
    candidate_records = candidate["actual_evidence_records"]
    records = baseline_records + candidate_records

    def _record_matches(record: dict) -> bool:
        return (record.get("package_sha256") == shared.package_sha256
                and record.get("entries_signature") == shared.entries_signature
                and record.get("entries_match") is True)

    by_consumer = {}
    for record in records:
        by_consumer.setdefault(record.get("consumer") or "", []).append(record)
    required_consumers = ("baseline_synthesis", "candidate_synthesis",
                          "candidate_self_review")
    consumer_checks = {
        consumer: bool(by_consumer.get(consumer))
        and all(_record_matches(record) for record in by_consumer.get(consumer, []))
        for consumer in required_consumers
    }
    counts = shared_retrieval_counts or {}
    return {
        "shared_evidence": shared,
        "baseline": baseline,
        "candidate": candidate,
        # Materialize the frozen package at the actual consumer boundary. Both
        # arms and each required consumer must have consumed it.
        "evidence_equal": bool(baseline_records) and bool(candidate_records)
        and all(_record_matches(record) for record in records)
        and all(consumer_checks.values()),
        "actual_evidence_package_count": len(records),
        "baseline_actual_package_count": len(baseline_records),
        "candidate_actual_package_count": len(candidate_records),
        "consumer_evidence_checks": consumer_checks,
        "actual_evidence_entries_mismatch": any(
            record.get("entries_signature") != shared.entries_signature
            for record in records),
        "shared_retrieval_source_envelopes": len(state.get("search_results") or []),
        "shared_retrieval_http_requests": counts.get("http_requests"),
        "shared_retrieval_http_requests_known": counts.get("http_requests") is not None,
        "shared_retrieval_http_requests_complete": bool(counts.get("http_requests_complete")),
        "shared_retrieval_tavily_posts": counts.get("tavily_posts"),
        "shared_retrieval_official_http_requests": counts.get("official_http_requests"),
        "shared_retrieval_llm_requests": counts.get("llm_requests"),
        "baseline_incremental_calls": sum(
            row.get("calls", 0) for row in baseline["token_usage"]),
        "candidate_incremental_calls": sum(
            row.get("calls", 0) for row in candidate["token_usage"]),
        "allow_supplementary_search": bool(allow_supplementary_search),
    }


def default_evidence_budget() -> int:
    return EVIDENCE_INPUT_BUDGET_CHARS
