"""Deterministic minimum-evidence gate and budget-limited report fallback."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from deepchoice.agents.evidence_chain import build_evidence_chain
from deepchoice.agents.report_generator import FORMAT_RENDERERS
from deepchoice.utils.decision_contract import restrict_recommendation
from deepchoice.utils.evidence import is_navigation_placeholder

from .contracts import RunBudgetPolicy
from .errors import BudgetExceededError


MINIMUM_USABLE_CHAINS = 3
MINIMUM_DISTINCT_HOSTS = 2
_SUBSTANTIAL_STRENGTHS = frozenset({"moderate", "strong"})
BUDGET_PARTIAL_FAILURE = "budget_exhausted"


def _canonical_http_url(url: Any) -> tuple[str, str] | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urlsplit(url.strip())
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        # Accessing port validates malformed/non-numeric/out-of-range ports.
        _ = parsed.port
        hostname = parsed.hostname.rstrip(".").lower()
        hostname = hostname.encode("idna").decode("ascii") if hostname else ""
        if not hostname:
            return None
        host_for_netloc = f"[{hostname}]" if ":" in hostname else hostname
        port = parsed.port
        if port is not None and not (
            (parsed.scheme.lower() == "http" and port == 80)
            or (parsed.scheme.lower() == "https" and port == 443)
        ):
            host_for_netloc = f"{host_for_netloc}:{port}"
        canonical = urlunsplit(
            (
                parsed.scheme.lower(),
                host_for_netloc,
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
        return canonical, hostname
    except (UnicodeError, ValueError):
        return None


def _bounded_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]


def _disputed_urls(conflicts: Any) -> set[str]:
    urls: set[str] = set()
    if not isinstance(conflicts, list):
        return urls
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        for side in ("source_a", "source_b"):
            source = conflict.get(side)
            url = source.get("url") if isinstance(source, dict) else None
            canonical = _canonical_http_url(url)
            if canonical is not None:
                urls.add(canonical[0])
    return urls


def _locally_build_chains(state: dict[str, Any]) -> list[dict[str, Any]]:
    source_scores = state.get("source_scores")
    conflicts = state.get("conflicts")
    if not isinstance(source_scores, list) or not isinstance(conflicts, list):
        return []
    # Keep the existing deterministic scoring semantics, while dropping malformed
    # partial records that could otherwise make the fallback itself fail.
    valid_scores = []
    for item in source_scores:
        score = item.get("total_score") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("url"), str)
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
        ):
            continue
        normalized = dict(item)
        if not isinstance(normalized.get("supporting_sources"), list):
            normalized["supporting_sources"] = []
        valid_scores.append(normalized)
    valid_conflicts = []
    for item in conflicts:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        for side in ("source_a", "source_b"):
            if not isinstance(normalized.get(side), dict):
                normalized[side] = {}
        valid_conflicts.append(normalized)
    return build_evidence_chain(valid_scores, valid_conflicts)


def usable_evidence_chains(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return chains satisfying the structural fallback evidence contract.

    This is intentionally not claim-level coverage. It only establishes that a
    restricted report can cite a small, non-disputed, multi-host evidence base.
    """

    raw_chains = state.get("evidence_chains")
    chains = (
        raw_chains
        if isinstance(raw_chains, list) and raw_chains
        else _locally_build_chains(state)
    )
    disputed = _disputed_urls(state.get("conflicts"))
    usable: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for chain in chains:
        if not isinstance(chain, dict) or chain.get("disputed"):
            continue
        conclusion = _bounded_text(chain.get("conclusion"), maximum=500)
        sources = chain.get("sources")
        if not isinstance(sources, list):
            continue
        valid_sources: list[dict[str, Any]] = []
        chain_urls: set[str] = set()
        is_disputed = False
        for source in sources:
            if not isinstance(source, dict):
                continue
            if is_navigation_placeholder(source.get("snippet")):
                continue
            url = source.get("url")
            canonical = _canonical_http_url(url)
            if canonical is None:
                continue
            canonical_url, _hostname = canonical
            if canonical_url in disputed:
                is_disputed = True
                break
            score = source.get("score")
            if (
                canonical_url in seen_urls
                or canonical_url in chain_urls
                or not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not math.isfinite(score)
                or score < 4
            ):
                continue
            title = _bounded_text(source.get("title"), maximum=300)
            snippet = _bounded_text(source.get("snippet"), maximum=2_000)
            if not conclusion or not (title or snippet):
                continue
            chain_urls.add(canonical_url)
            valid_sources.append(
                {
                    "url": canonical_url,
                    "title": title,
                    "snippet": snippet,
                    "score": score,
                }
            )
        if valid_sources and not is_disputed:
            maximum_score = max(source["score"] for source in valid_sources)
            strengths = ("weak", "moderate", "strong")
            original = chain.get("evidence_strength")
            original_rank = strengths.index(original) if isinstance(original, str) and original in strengths else 0
            score_rank = 2 if maximum_score >= 8 else 1 if maximum_score >= 6 else 0
            if len(valid_sources) != len(sources):
                # Removed sources cannot carry forward a prior corroboration label.
                score_rank = min(score_rank, 1)
            # A restricted projection may inherit a label, never create support.
            strength = strengths[min(original_rank, score_rank)]
            seen_urls.update(source["url"] for source in valid_sources)
            usable.append(
                {
                    "conclusion": conclusion,
                    "sources": valid_sources,
                    "evidence_strength": strength,
                    "disputed": False,
                }
            )
    return usable


def minimum_evidence_gaps(state: dict[str, Any]) -> tuple[str, ...]:
    """Fixed public reasons for structural insufficiency, not claim verification."""

    chains = usable_evidence_chains(state)
    hosts = {
        host
        for chain in chains
        for source in chain.get("sources", [])
        if isinstance(source, dict)
        if (canonical := _canonical_http_url(source.get("url"))) is not None
        if (host := canonical[1])
    }
    gaps: list[str] = []
    if len(chains) < MINIMUM_USABLE_CHAINS:
        gaps.append(f"Fewer than {MINIMUM_USABLE_CHAINS} non-disputed usable evidence chains are available.")
    if len(hosts) < MINIMUM_DISTINCT_HOSTS:
        gaps.append(f"Fewer than {MINIMUM_DISTINCT_HOSTS} distinct valid HTTP(S) hostnames are available in usable evidence.")
    if not any(chain.get("evidence_strength") in _SUBSTANTIAL_STRENGTHS for chain in chains):
        gaps.append("No usable evidence chain has moderate or strong evidence strength.")
    return tuple(gaps)


def minimum_evidence_is_met(state: dict[str, Any]) -> bool:
    return not minimum_evidence_gaps(state)


def build_budget_limited_state(
    partial_state: dict[str, Any],
    *,
    request: dict[str, Any],
    policy: RunBudgetPolicy,
    error: BudgetExceededError,
) -> dict[str, Any] | None:
    """Build a public-reportable state without making any external call."""

    state = dict(partial_state)
    state["task"] = dict(request)
    chains = usable_evidence_chains(state)
    state["evidence_chains"] = chains
    if not minimum_evidence_is_met(state):
        return None

    conflicts = state.get("conflicts")
    state["conflicts"] = [
        item
        for item in conflicts
        if isinstance(item, dict)
        and isinstance(item.get("source_a", {}), dict)
        and isinstance(item.get("source_b", {}), dict)
    ] if isinstance(conflicts, list) else []
    if not isinstance(state.get("final_recommendation"), dict):
        state["final_recommendation"] = {}
    gaps = state.get("knowledge_gaps")
    state["knowledge_gaps"] = (
        [item for item in gaps if isinstance(item, str)]
        if isinstance(gaps, list)
        else []
    )

    resource = getattr(error.resource, "value", str(error.resource))
    marker = {
        "limited": True,
        "policy_version": policy.policy_version,
        "exhausted_resource": resource,
        "minimum_evidence_met": True,
        "reason": BudgetExceededError.code,
    }
    state["budget_limited"] = marker
    failures = state.get("partial_failures")
    public_failures = (
        [item for item in failures if isinstance(item, str)]
        if isinstance(failures, list)
        else []
    )
    if BUDGET_PARTIAL_FAILURE not in public_failures:
        public_failures.append(BUDGET_PARTIAL_FAILURE)
    state["partial_failures"] = public_failures

    query = str(request.get("query", ""))
    state["final_recommendation"] = restrict_recommendation(
        state.get("final_recommendation", {}), query
    )
    is_zh = any("一" <= char <= "鿿" for char in query)
    note = (
        "预算已触顶；以下内容仅基于触顶前取得的最低结构性证据，不代表完整比较。"
        if is_zh
        else "The run budget was exhausted. This restricted report uses only the minimum structural evidence collected before the limit and is not a complete comparison."
    )
    state["data_source_note"] = note
    renderer = FORMAT_RENDERERS.get(
        request.get("report_format", "what_why_how"),
        FORMAT_RENDERERS["what_why_how"],
    )
    rendered = renderer(state)
    banner = (
        "> **预算受限报告**：研究因预算上限提前结束。"
        if is_zh
        else "> **Budget-limited report:** Research stopped at the configured budget cap."
    )
    state["report"] = f"{banner}\n\n{rendered}"
    quality = state.get("quality_signals")
    quality_signals = list(quality) if isinstance(quality, list) else []
    quality_signals.append(
        {
            "agent": "budget_limiter",
            "minimum_evidence_met": True,
            "usable_chains": len(chains),
            "structural_only": True,
        }
    )
    state["quality_signals"] = quality_signals
    return state


__all__ = [
    "BUDGET_PARTIAL_FAILURE",
    "MINIMUM_DISTINCT_HOSTS",
    "MINIMUM_USABLE_CHAINS",
    "build_budget_limited_state",
    "minimum_evidence_gaps",
    "minimum_evidence_is_met",
    "usable_evidence_chains",
]
