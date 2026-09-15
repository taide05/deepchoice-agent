"""Stable public contracts shared by the API and research workflow."""

from .api import (
    ResearchRequest,
    ResearchStartedResponse,
    RunRecordResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskRecordResponse,
)
from .errors import DeepChoiceError, ErrorCategory, ErrorDetail, ErrorResponse
from .manifest import (
    CoreAssetRegistry,
    RunManifest,
    build_core_asset_registry,
    build_run_manifest,
    ensure_run_manifest_compatible,
)

__all__ = [
    "DeepChoiceError",
    "ErrorCategory",
    "ErrorDetail",
    "ErrorResponse",
    "CoreAssetRegistry",
    "ResearchRequest",
    "ResearchStartedResponse",
    "RunRecordResponse",
    "RunManifest",
    "TaskDetailResponse",
    "TaskListResponse",
    "TaskRecordResponse",
    "build_run_manifest",
    "build_core_asset_registry",
    "ensure_run_manifest_compatible",
]
