"""Small offline evaluation helpers; not a general evaluation platform."""
from .simple_baseline import (
    OfflineGateError,
    SharedEvidence,
    build_shared_evidence,
    run_baseline,
    run_candidate,
    run_pair,
)

__all__ = [
    "OfflineGateError", "SharedEvidence", "build_shared_evidence",
    "run_baseline", "run_candidate", "run_pair",
]
