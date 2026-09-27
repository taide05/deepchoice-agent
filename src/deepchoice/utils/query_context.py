"""Explicit request projection for analysis and adaptation prompts.

The API owns admission limits. Preserve accepted text instead of clipping user
requirements or replacing a free-text scene with a coarse classification.
Private state and arbitrary task extensions must not enter this projection.
"""

from typing import Any


def query_request_context(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": task["query"],
        "scene_context": task.get("scene_context"),
        "candidate_techs": task.get("candidate_techs", []),
        "constraints": task.get("constraints", []),
        "sub_questions": task.get("sub_questions", []),
    }
