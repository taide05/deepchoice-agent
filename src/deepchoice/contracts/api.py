from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from ..security.input_limits import MAX_RESEARCH_TEXT_CHARS, validate_safe_text

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
LifecycleStatusValue = Literal[
    "queued",
    "running",
    "waiting_for_input",
    "cancelling",
    "completed",
    "completed_with_warnings",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
]
ReportFormatValue = Literal[
    "what_why_how", "evidence_first", "comparison_matrix"
]


class ResearchRequest(BaseModel):
    """Validated input accepted by the research pipeline.

    Limits are deliberately generous enough for normal research requests while
    bounding accidental or hostile payload expansion before work is scheduled.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    query: QueryText
    scene_context: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    constraints: list[ShortText] = Field(default_factory=list, max_length=50)
    candidate_techs: list[ShortText] = Field(default_factory=list, max_length=50)
    complexity: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    report_format: ReportFormatValue = "what_why_how"
    sub_questions: list[ShortText] = Field(default_factory=list, max_length=20)
    gather_evidence: bool = True
    language: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None

    @model_validator(mode="after")
    def validate_text_boundary(self) -> "ResearchRequest":
        values = [self.query]
        values.extend(
            value
            for value in (self.scene_context, self.complexity, self.language)
            if value is not None
        )
        values.extend(self.constraints)
        values.extend(self.candidate_techs)
        values.extend(self.sub_questions)
        for value in values:
            validate_safe_text(value)
        if sum(len(value) for value in values) > MAX_RESEARCH_TEXT_CHARS:
            raise ValueError("aggregate request text exceeds the allowed size")
        return self


class ResearchStartedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    task_id: str
    status: Literal["started"] = "started"
    manifest_id: str


class TaskRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    schema_version: Literal[1] = 1
    task_id: str
    status: LifecycleStatusValue
    request: ResearchRequest
    latest_run_id: str | None
    cancel_requested_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class RunRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    schema_version: Literal[1] = 1
    run_id: str
    task_id: str
    status: LifecycleStatusValue
    manifest_id: str
    started_at: datetime | None
    ended_at: datetime | None
    deadline_at: datetime | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class TaskDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    task: TaskRecordResponse
    latest_run: RunRecordResponse | None


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    items: tuple[TaskDetailResponse, ...]
    next_cursor: str | None = None


class TaskReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    task_id: str
    run_id: str
    format: ReportFormatValue
    report: str


class ObservabilityNodeAttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str
    attempt_no: int
    status: Literal[
        "started", "succeeded", "failed", "cancelled", "timed_out", "interrupted", "unknown"
    ]
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None


class ObservabilityExternalCallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["llm", "retrieval", "http", "other"]
    node_name: str
    node_attempt_no: int
    retry_no: int | None = None
    provider: str
    operation: str
    call_no: int
    status: Literal[
        "started", "succeeded", "failed", "cancelled", "timed_out", "interrupted", "unknown"
    ]
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    usage: dict[str, int] | None = None


class ObservabilityTotalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_attempts: int = Field(ge=0)
    node_retries: int = Field(ge=0)
    external_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    retrieval_calls: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    token_usage_complete: bool


class ObservabilityBudgetResourceResponse(BaseModel):
    """Allowlisted accounting totals for one configured budget resource."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "unavailable"]
    hard_limit: int | None = Field(default=None, ge=0)
    settled: int | None = Field(default=None, ge=0)
    unknown_spend: int | None = Field(default=None, ge=0)
    reserved: int | None = Field(default=None, ge=0)
    remaining: int | None = Field(default=None, ge=0)
    soft_limit_reached: bool | None = None
    exhausted: bool | None = None


class ObservabilityBudgetSummaryResponse(BaseModel):
    """Safe latest-run budget view; excludes ledger and execution identifiers."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "unavailable"]
    policy_version: Literal["standard-observe-v1", "standard-enforced-v1"] | None = None
    tier: Literal["standard"] | None = None
    enforcement_mode: Literal["observe_only", "enforced"] | None = None
    soft_limit_ratio: float | None = Field(default=None, gt=0, le=1)
    admission_denied: bool = False
    denied_resource: Literal[
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_micro_usd",
        "llm_calls",
        "retrieval_calls",
        "http_calls",
        "active_milliseconds",
        "wall_clock_milliseconds",
    ] | None = None
    price_availability: Literal["priced", "unavailable"]
    resources: dict[str, ObservabilityBudgetResourceResponse] = Field(default_factory=dict)


class TaskObservabilityResponse(BaseModel):
    """Allowlisted latest-run telemetry; never includes private trace identifiers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    task_id: str
    run_id: str | None = None
    availability: Literal["available", "unavailable"]
    unavailable_reason: Literal[
        "no_latest_run", "latest_run_missing", "trace_not_recorded"
    ] | None = None
    budget_policy_availability: Literal["available", "unavailable"]
    budget_policy_unavailable_reason: Literal[
        "no_latest_run", "latest_run_missing", "historical_run"
    ] | None = None
    budget: ObservabilityBudgetSummaryResponse
    nodes: tuple[ObservabilityNodeAttemptResponse, ...] = ()
    calls: tuple[ObservabilityExternalCallResponse, ...] = ()
    totals: ObservabilityTotalsResponse
