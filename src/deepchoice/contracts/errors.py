from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deepchoice.security.redaction import redact_text, redact_value


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    SECURITY = "security"
    BUDGET = "budget"
    TIMEOUT = "timeout"
    EXTERNAL_SERVICE = "external_service"
    CONTRACT = "contract"
    PERSISTENCE = "persistence"
    COMPATIBILITY = "compatibility"
    INTERNAL = "internal"
    # Compatibility categories for the current API surface. New code should
    # prefer one of the more specific categories above.
    NOT_FOUND = "not_found"
    REQUEST = "request"
    RESEARCH = "research"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ErrorCategory
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False
    action: str | None = Field(default=None, max_length=500)
    scope: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)
    trace_id: str | None = Field(default=None, max_length=200)
    details: Any | None = None

    @field_validator("message", "action", "provider", mode="before")
    @classmethod
    def _redact_text_fields(cls, value: Any) -> Any:
        if value is None:
            return None
        return redact_text(value, max_length=2000)

    @field_validator("details", mode="before")
    @classmethod
    def _redact_details(cls, value: Any) -> Any:
        return redact_value(value) if value is not None else None


class ErrorResponse(BaseModel):
    """Unified error envelope; ``detail`` remains for API compatibility."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    detail: Any
    error: ErrorDetail


class DeepChoiceError(Exception):
    """Expected application error carrying a safe, stable public contract."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.RESEARCH,
        code: str = "RESEARCH_ERROR",
        status_code: int = 500,
        retryable: bool = False,
        action: str | None = None,
        scope: str | None = None,
        provider: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        details: Any | None = None,
    ) -> None:
        safe_message = redact_text(message, max_length=2000)
        super().__init__(safe_message)
        self.error_detail = ErrorDetail(
            category=category,
            code=code,
            message=safe_message,
            retryable=retryable,
            action=action,
            scope=scope,
            provider=provider,
            task_id=task_id,
            run_id=run_id,
            trace_id=trace_id,
            details=details,
        )
        self.status_code = status_code


def normalize_error(exc: Exception) -> ErrorDetail:
    if isinstance(exc, DeepChoiceError):
        return exc.error_detail
    # Budget exceptions deliberately do not depend on the API contract module,
    # so import them lazily here to keep their low-level fallback boundary safe.
    from deepchoice.budget_errors import (
        BudgetExceededError,
        BudgetInsufficientEvidenceError,
    )

    if isinstance(exc, BudgetInsufficientEvidenceError):
        return ErrorDetail(
            category=ErrorCategory.BUDGET,
            code=exc.code,
            message="The run budget was exhausted before enough evidence was collected.",
            retryable=False,
            action="Retry with a larger budget or a narrower research question.",
            scope="run",
        )
    if isinstance(exc, BudgetExceededError):
        return ErrorDetail(
            category=ErrorCategory.BUDGET,
            code=exc.code,
            message="The run reached its configured budget limit.",
            retryable=False,
            action="Use the restricted result when available, or retry with a larger budget.",
            scope="run",
        )
    return ErrorDetail(
        category=ErrorCategory.INTERNAL,
        code="RESEARCH_FAILED",
        message="Research failed",
        retryable=False,
        action="Inspect the task status and retry when the underlying issue is resolved.",
    )
