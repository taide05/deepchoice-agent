"""Bounded, content-free evidence-flow counters for best-effort Trace.

Counts locate structural loss; they do not certify relevance or answer quality.
Absent/malformed observations stay absent rather than becoming zero.
"""
from .call_diagnostics import strict_json


_BINDING_REASONS = (
    "invalid_list", "invalid_kind", "invalid_option", "dropped_item_limit",
    "basis_missing_or_invalid", "basis_invalid_item", "basis_invalid_fact",
    "basis_fact_limit", "basis_invalid_sentences", "basis_source_sentences_mismatch",
    "invalid_fact_ids", "invalid_requirement_ids", "invalid_assumptions",
    "prose_type", "prose_length", "prose_reference", "prose_empty",
)

# Why a dynamic citation fetch did not yield page text. These mirror the
# SafeFetchFailure codes plus the fetch-side classes the verifier already
# distinguishes in its log; without them every non-answer collapses into one
# indistinguishable "unknown" and a deterministic routing refusal cannot be
# told apart from a transient network failure after the run.
_FETCH_CATEGORIES = (
    "safety_rejected", "route_unavailable", "route_unsupported", "dns_uncertain",
    "timeout", "response_rejected", "rate_limited", "admission_denied",
    "transport_uncertain", "unexpected_error", "reached",
)


def _fields(*names):
    return {name: (name,) for name in names}


_PATHS = {
    "source_evaluator": {
        **_fields("sources_scored", "candidate_excluded_count",
                  "audited_seed_scope_excluded_count", "navigation_excluded_count"),
        "scope_offered": ("source_scope_proposal", "offered"),
        "scope_accepted": ("source_scope_proposal", "accepted"),
    },
    "evidence_chain": _fields("total_chains", "strong", "moderate", "weak", "disputed"),
    "conclusion_synthesizer": {
        **_fields("source_facts_received", "source_facts_bound"),
        **{key: ("staged_generation", key) for key in (
            "facts_received", "facts_bound", "facts_reviewable", "questions_planned", "judgment_calls",
            "rows_received", "rows_selected", "rows_rejected_shape",
            "rows_rejected_question", "rows_dropped_item_limit", "provider_errors",
        )},
        "analyses_received": ("analysis_binding", "received"),
        "analyses_bound": ("analysis_binding", "retained"),
        **{"binding_rejected_" + key: ("analysis_binding", "rejected", key)
           for key in _BINDING_REASONS},
    },
    "citation_validator": {
        **_fields("verified", "unsupported", "unreachable", "unknown",
                  "analyses_received", "analyses_rebound"),
        **{"citation_fetch_" + key: ("citation_fetch", key) for key in _FETCH_CATEGORIES},
    },
    "self_reviewer": {
        **{key: ("analysis_review", key) for key in (
            "submitted", "reviewed", "retained", "revised", "withdrawn", "unaddressed")},
        **_fields("targeted_review_attempts"),
    },
}
_ANALYSIS_NODES = frozenset({
    "conclusion_synthesizer", "citation_validator", "self_reviewer",
})


def _safe_counts(node, counts):
    if not isinstance(counts, dict):
        return None
    allowed = set(_PATHS.get(node, {}))
    if node in _ANALYSIS_NODES:
        allowed.add("analyses_returned")
    result = {key: counts[key] for key in allowed if key in counts
              and type(counts[key]) is int and 0 <= counts[key] <= 10000}
    return result or None


def node_stage_counts(node, result):
    """Project only the current node's known counters, never copy summaries."""
    if node not in _PATHS or not isinstance(result, dict):
        return None
    counts = {}
    signals = result.get("quality_signals")
    if isinstance(signals, list):
        for signal in signals[:64]:
            if not isinstance(signal, dict) or signal.get("agent") != node:
                continue
            for key, path in _PATHS[node].items():
                value = signal
                for part in path:
                    value = value.get(part) if isinstance(value, dict) else None
                counts[key] = value
            break
    recommendation = result.get("final_recommendation")
    if node in _ANALYSIS_NODES and isinstance(recommendation, dict):
        rows = recommendation.get("decision_analysis")
        if isinstance(rows, list):
            counts["analyses_returned"] = len(rows)
    return _safe_counts(node, counts)


def public_stage_counts(node, value):
    """Read the same allowlist from product Trace; historical absence is null."""
    if not isinstance(value, str) or len(value) > 16384:
        return None
    try:
        summary = strict_json(value)
    except (TypeError, ValueError, RecursionError):
        return None
    return _safe_counts(node, summary.get("stage_counts")) if isinstance(summary, dict) else None
