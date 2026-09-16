"""Trace DTOs and ports; persistence wiring starts after Phase 2-A."""

from .contracts import (
    ExternalCall,
    ExternalCallKind,
    NodeAttempt,
    RunTrace,
    TraceEvent,
    TraceSink,
    TraceStatus,
)
from .runtime import RuntimeTraceRecorder, current_trace_recorder
from .sqlite import SQLiteTraceSink, SQLiteTraceStore, StaleTraceAuthorityError

__all__ = [
    "ExternalCall",
    "ExternalCallKind",
    "NodeAttempt",
    "RunTrace",
    "RuntimeTraceRecorder",
    "SQLiteTraceSink",
    "SQLiteTraceStore",
    "StaleTraceAuthorityError",
    "TraceEvent",
    "TraceSink",
    "TraceStatus",
    "current_trace_recorder",
]
