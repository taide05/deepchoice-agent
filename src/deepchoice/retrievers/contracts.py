import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be non-empty")
    return value


class RetrievalRequest(BaseModel):
    """Stable input contract shared by all retrievers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    query: str
    sub_questions: tuple[str, ...] = Field(default=(), max_length=20)
    max_results: int = Field(default=7, ge=1, le=100)
    adapted_queries: tuple[str, ...] = Field(default=(), max_length=20)
    # Deterministic capability flags from the original request. Only the local
    # Chroma retriever may receive non-empty values; never put scene text here.
    local_scene_needs: tuple[Literal["backup", "full_text_search", "task_recovery"], ...] = Field(
        default=(), max_length=3
    )
    # Hash of the local Chroma collection bytes and audited sidecars. This is
    # an internal cache identity, not a user-supplied scene or public result.
    local_collection_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # Hash-only mutable official-discovery input identity for retrieval cache.
    official_mapping_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    _query_non_empty = field_validator("query")(_non_empty)

    @field_validator("query")
    @classmethod
    def _query_bounded(cls, value: str) -> str:
        if len(value) > 4000:
            raise ValueError("query must be at most 4000 characters")
        return value

    @field_validator("sub_questions", "adapted_queries")
    @classmethod
    def _items_non_empty(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _non_empty(value)
            if len(value) > 1000:
                raise ValueError("items must be at most 1000 characters")
        return values

    @field_validator("local_scene_needs")
    @classmethod
    def _unique_local_needs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("local_scene_needs must be unique")
        return values


class PartialRetrievalError(Exception):
    """Internal acquired results plus a failed optional read; never serialized."""

    def __init__(self, results: list[dict], failure: Exception):
        super().__init__("Optional retrieval was incomplete")
        self.results = results
        self.failure = failure


class RetrievalResult(BaseModel):
    """Stable result envelope returned by every retriever."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 1
    source: str
    status: Literal["success", "partial", "failed"]
    results: list[dict] = Field(default_factory=list)
    error: str | None = None
    latency_ms: int = Field(ge=0)

    _source_non_empty = field_validator("source")(_non_empty)

    @model_validator(mode="after")
    def validate_status_fields(self) -> "RetrievalResult":
        if self.status == "success" and self.error is not None:
            raise ValueError("successful retrieval must not contain an error")
        if self.status == "partial":
            if self.schema_version != 2 or not self.results:
                raise ValueError("partial retrieval requires schema v2 and acquired results")
            if (self.error is None or len(self.error) > 128 or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_]*(?:\(\)|: HTTP [1-5][0-9]{2})?", self.error)):
                raise ValueError("partial retrieval requires a bounded public error type/status")
        if self.status == "failed":
            if self.results:
                raise ValueError("failed retrieval must have no results")
            if self.error is None or not self.error.strip():
                raise ValueError("failed retrieval must contain a non-empty error")
        return self


@runtime_checkable
class RetrieverPort(Protocol):
    source: str

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        ...
