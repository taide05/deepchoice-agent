"""Durable product-database primitives.

Connections returned by :func:`connect_database` are always caller-owned and
must be closed by that caller. Importing this package has no filesystem effects.
"""

from .database import DEFAULT_DB_PATH, DatabaseConnectionError, connect_database
from .migrations import (
    MIGRATIONS,
    Migration,
    MigrationCompatibilityError,
    MigrationExecutionError,
    run_migrations,
)
from .records import (
    CheckpointReference,
    DecisionResolutionResult,
    LegacyImportRecord,
    RecoveryRun,
    RunLeaseGrant,
    RunRecord,
    RunResultRecord,
    TaskRecord,
    TaskEventCursor,
    TaskEventRecord,
    TaskWithRun,
)
from .repository import (
    CheckpointNotAvailableError,
    DecisionConflictError,
    DecisionExpiredError,
    DecisionNotFoundError,
    RepositoryOperationError,
    RunLeaseLostError,
    RunNotFoundError,
    RunRepository,
    SQLiteTaskRunRepository,
    TaskNotFoundError,
    TaskRepository,
    TaskVersionConflictError,
)

__all__ = [
    "CheckpointNotAvailableError",
    "DecisionConflictError",
    "DecisionExpiredError",
    "DecisionNotFoundError",
    "DecisionResolutionResult",
    "DEFAULT_DB_PATH",
    "MIGRATIONS",
    "DatabaseConnectionError",
    "Migration",
    "MigrationCompatibilityError",
    "MigrationExecutionError",
    "LegacyImportRecord",
    "RepositoryOperationError",
    "RunNotFoundError",
    "RunLeaseLostError",
    "RunRecord",
    "RunResultRecord",
    "CheckpointReference",
    "RecoveryRun",
    "RunLeaseGrant",
    "RunRepository",
    "SQLiteTaskRunRepository",
    "TaskNotFoundError",
    "TaskEventCursor",
    "TaskEventRecord",
    "TaskRecord",
    "TaskRepository",
    "TaskVersionConflictError",
    "TaskWithRun",
    "connect_database",
    "run_migrations",
]
