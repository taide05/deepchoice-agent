from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


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
    report_format: Literal["what_why_how", "evidence_first", "comparison_matrix"] = "what_why_how"
    sub_questions: list[ShortText] = Field(default_factory=list, max_length=20)
    gather_evidence: bool = True
    language: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None


class ResearchStartedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    task_id: str
    status: Literal["started"] = "started"
    manifest_id: str
