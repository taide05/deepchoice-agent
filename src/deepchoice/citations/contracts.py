"""Public, JSON-safe citation verification contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CITATION_POLICY_VERSION = "deterministic-citation-v1"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CitationStatus(StrEnum):
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class CitationReason(StrEnum):
    LEXICAL_SUPPORT = "lexical_support"
    CITATION_MISSING = "citation_missing"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_AMBIGUOUS = "source_ambiguous"
    URL_INVALID = "url_invalid"
    SOURCE_LIMIT = "source_limit"
    NOT_PUBLICLY_ACCESSIBLE = "not_publicly_accessible"
    NETWORK_UNCERTAIN = "network_uncertain"
    HTTP_UNCERTAIN = "http_uncertain"
    CONTENT_INSUFFICIENT = "content_insufficient"
    CROSS_LANGUAGE = "cross_language"
    NUMERIC_MISMATCH = "numeric_mismatch"
    NEGATION_CONFLICT = "negation_conflict"
    LEXICAL_MISMATCH = "lexical_mismatch"
    NOT_CITED = "not_cited"


class CitationCheck(_FrozenContract):
    claim_id: str = Field(min_length=1, max_length=64)
    claim_path: str = Field(min_length=1, max_length=240)
    claim_text: str = Field(min_length=1, max_length=500)
    source_title: str | None = Field(default=None, max_length=300)
    canonical_url: str | None = Field(default=None, max_length=2048)
    status: CitationStatus
    reason: CitationReason


class CitationStatusCounts(_FrozenContract):
    verified: int = Field(default=0, ge=0)
    unsupported: int = Field(default=0, ge=0)
    unreachable: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)


class CitationVerification(_FrozenContract):
    schema_version: Literal[1] = 1
    policy_version: Literal["deterministic-citation-v1"] = CITATION_POLICY_VERSION
    status_counts: CitationStatusCounts
    checks: tuple[CitationCheck, ...] = Field(max_length=96)
