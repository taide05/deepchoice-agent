import json
from pathlib import Path
from pydantic import BaseModel, Field


class TaskConfig(BaseModel):
    query: str
    scene_context: str = "team"
    constraints: list[str] = Field(default_factory=list)
    report_format: str = "what_why_how"

    def model_post_init(self, __context):
        valid_scenes = {"solo", "team", "enterprise"}
        if self.scene_context not in valid_scenes:
            raise ValueError(f"scene_context must be one of {valid_scenes}")
        valid_formats = {"what_why_how", "evidence_first", "comparison_matrix"}
        if self.report_format not in valid_formats:
            raise ValueError(f"report_format must be one of {valid_formats}")


def load_task(path: str) -> TaskConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaskConfig(**raw)
