"""Typed persistence contracts for the one supported HITL decision gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from deepchoice.security.input_limits import validate_safe_text


DecisionAction = Literal["provide_context", "limited_report", "cancel"]
DecisionStatus = Literal["pending", "resolved", "expired", "cancelled"]
ALLOWED_DECISION_ACTIONS: tuple[DecisionAction, ...] = (
    "provide_context",
    "limited_report",
    "cancel",
)
DECISION_TTL = timedelta(days=7)
MAX_SUPPLEMENTAL_INPUT_CHARS = 4_000
MAX_DECISION_GAPS = 12


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionResolution(_FrozenModel):
    action: DecisionAction
    supplemental_input: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SUPPLEMENTAL_INPUT_CHARS),
    ] | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> "DecisionResolution":
        if self.action == "provide_context":
            if self.supplemental_input is None:
                raise ValueError("provide_context requires supplemental_input")
            validate_safe_text(self.supplemental_input)
        elif self.supplemental_input is not None:
            raise ValueError("supplemental_input is only allowed for provide_context")
        return self

    def body_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class DecisionPause(_FrozenModel):
    decision_id: str = Field(min_length=1, max_length=100)
    kind: Literal["evidence-insufficient"] = "evidence-insufficient"
    reason: str = Field(min_length=1, max_length=500)
    gaps: tuple[str, ...] = Field(max_length=MAX_DECISION_GAPS)
    allowed_actions: tuple[DecisionAction, ...] = ALLOWED_DECISION_ACTIONS
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_public_text(self) -> "DecisionPause":
        if self.allowed_actions != ALLOWED_DECISION_ACTIONS:
            raise ValueError("decision actions do not match the supported policy")
        validate_safe_text(self.reason)
        for gap in self.gaps:
            if not gap or len(gap) > 500:
                raise ValueError("decision gaps must contain bounded text")
            validate_safe_text(gap)
        return self


class DecisionRecord(_FrozenModel):
    decision_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    kind: Literal["evidence-insufficient"]
    status: DecisionStatus
    reason: str
    gaps: tuple[str, ...]
    allowed_actions: tuple[DecisionAction, ...]
    checkpoint_ns: str = ""
    storage_checkpoint_ns: str = ""
    checkpoint_id: str = Field(min_length=1)
    state_schema_version: int = Field(gt=0)
    pause_execution_epoch: int = Field(ge=1)
    expires_at: datetime
    resolution: DecisionResolution | None = None
    resolution_body_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    resolved_at: datetime | None = None


__all__ = [
    "ALLOWED_DECISION_ACTIONS",
    "DECISION_TTL",
    "DecisionAction",
    "DecisionPause",
    "DecisionRecord",
    "DecisionResolution",
    "DecisionStatus",
    "MAX_SUPPLEMENTAL_INPUT_CHARS",
]
