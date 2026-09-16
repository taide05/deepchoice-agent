"""Deterministic citation verification contracts and helpers."""

from .contracts import (
    CITATION_POLICY_VERSION,
    CitationCheck,
    CitationReason,
    CitationStatus,
    CitationStatusCounts,
    CitationVerification,
)
from .verifier import canonicalize_source_url, verify_citations

__all__ = [
    "CITATION_POLICY_VERSION",
    "CitationCheck",
    "CitationReason",
    "CitationStatus",
    "CitationStatusCounts",
    "CitationVerification",
    "canonicalize_source_url",
    "verify_citations",
]
