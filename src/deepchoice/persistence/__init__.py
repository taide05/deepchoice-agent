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
from .records import RunRecord, TaskRecord, TaskWithRun
from .repository import (
    RepositoryOperationError,
    RunNotFoundError,
    RunRepository,
    SQLiteTaskRunRepository,
    TaskNotFoundError,
    TaskRepository,
    TaskVersionConflictError,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "MIGRATIONS",
    "DatabaseConnectionError",
    "Migration",
    "MigrationCompatibilityError",
    "MigrationExecutionError",
    "RepositoryOperationError",
    "RunNotFoundError",
    "RunRecord",
    "RunRepository",
    "SQLiteTaskRunRepository",
    "TaskNotFoundError",
    "TaskRecord",
    "TaskRepository",
    "TaskVersionConflictError",
    "TaskWithRun",
    "connect_database",
    "run_migrations",
]
