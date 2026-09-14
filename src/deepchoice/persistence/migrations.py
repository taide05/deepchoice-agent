"""Versioned, transactional schema migrations for the product database."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Final, Sequence

import aiosqlite

from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory

from .database import _await_cleanup, _is_locked_error


_SCHEMA_MIGRATIONS_SQL: Final = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL CHECK (length(name) > 0),
    checksum TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()

_STATUS_CHECK: Final = (
    "'queued', 'running', 'waiting_for_input', 'cancelling', 'completed', "
    "'completed_with_warnings', 'failed', 'timed_out', 'cancelled', 'interrupted'"
)


@dataclass(frozen=True, slots=True)
class Migration:
    """One immutable migration whose checksum covers all executable content."""

    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = json.dumps(
            {
                "name": self.name,
                "statements": self.statements,
                "version": self.version,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


_V1_STATEMENTS: Final[tuple[str, ...]] = (
    _SCHEMA_MIGRATIONS_SQL,
    f"""
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY CHECK (length(task_id) > 0),
    status TEXT NOT NULL CHECK (status IN ({_STATUS_CHECK})),
    request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    latest_run_id TEXT CHECK (latest_run_id IS NULL OR length(latest_run_id) > 0),
    cancel_requested_at TEXT,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
""".strip(),
    f"""
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY CHECK (length(run_id) > 0),
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT
        CHECK (length(task_id) > 0),
    status TEXT NOT NULL CHECK (status IN ({_STATUS_CHECK})),
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    thread_id TEXT NOT NULL UNIQUE CHECK (length(thread_id) > 0),
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    execution_epoch INTEGER NOT NULL DEFAULT 0 CHECK (execution_epoch >= 0),
    lease_owner TEXT,
    lease_expires_at TEXT,
    started_at TEXT,
    ended_at TEXT,
    error_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
""".strip(),
    "CREATE INDEX idx_tasks_status ON tasks(status)",
    "CREATE INDEX idx_runs_task_id ON runs(task_id)",
    "CREATE INDEX idx_runs_status ON runs(status)",
    "CREATE INDEX idx_runs_lease_expires_at ON runs(lease_expires_at)",
)

_V2_STATEMENTS: Final[tuple[str, ...]] = (
    "ALTER TABLE runs ADD COLUMN version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0)",
    "CREATE INDEX idx_tasks_created_at_task_id ON tasks(created_at DESC, task_id DESC)",
    "CREATE INDEX idx_tasks_status_created_at_task_id ON tasks(status, created_at DESC, task_id DESC)",
)

_V3_STATEMENTS: Final[tuple[str, ...]] = (
    "ALTER TABLE runs ADD COLUMN deadline_at TEXT",
    """
CREATE TABLE run_checkpoints (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE
        CHECK (length(run_id) > 0),
    checkpoint_ns TEXT NOT NULL,
    storage_checkpoint_ns TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL CHECK (length(checkpoint_id) > 0),
    node TEXT,
    state_schema_version INTEGER NOT NULL CHECK (state_schema_version > 0),
    execution_epoch INTEGER NOT NULL CHECK (execution_epoch >= 1),
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, storage_checkpoint_ns, checkpoint_id)
)
""".strip(),
    "CREATE INDEX idx_run_checkpoints_run_created ON run_checkpoints(run_id, created_at DESC)",
)

_V4_STATEMENTS: Final[tuple[str, ...]] = (
    """
CREATE TABLE task_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE
        CHECK (length(task_id) > 0),
    run_id TEXT REFERENCES runs(run_id) ON DELETE CASCADE
        CHECK (run_id IS NULL OR length(run_id) > 0),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    type TEXT NOT NULL CHECK (length(type) > 0),
    public_payload_json TEXT NOT NULL
        CHECK (json_valid(public_payload_json) AND json_type(public_payload_json) = 'object'),
    created_at TEXT NOT NULL,
    UNIQUE (task_id, seq)
)
""".strip(),
    "CREATE INDEX idx_task_events_task_event ON task_events(task_id, event_id)",
    "CREATE INDEX idx_task_events_run_event ON task_events(run_id, event_id)",
    """
CREATE TABLE legacy_imports (
    source_path TEXT NOT NULL CHECK (length(source_path) > 0),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    outcome TEXT NOT NULL CHECK (outcome IN ('imported', 'error')),
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    error_code TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (source_path, content_sha256),
    CHECK (
        (outcome = 'imported' AND error_code IS NULL)
        OR
        (outcome = 'error' AND task_id IS NULL AND run_id IS NULL AND error_code IS NOT NULL)
    )
)
""".strip(),
)

_V5_STATEMENTS: Final[tuple[str, ...]] = (
    "ALTER TABLE legacy_imports RENAME TO legacy_imports_v4",
    """
CREATE TABLE legacy_imports (
    source_path TEXT NOT NULL CHECK (length(source_path) > 0),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    outcome TEXT NOT NULL CHECK (outcome IN ('imported', 'error')),
    task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    run_id TEXT REFERENCES runs(run_id) ON DELETE RESTRICT,
    error_code TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (source_path, content_sha256),
    CHECK (
        (
            outcome = 'imported'
            AND task_id IS NOT NULL
            AND run_id IS NOT NULL
            AND error_code IS NULL
        )
        OR
        (
            outcome = 'error'
            AND task_id IS NULL
            AND run_id IS NULL
            AND error_code IS NOT NULL
        )
    )
)
""".strip(),
    """
INSERT INTO legacy_imports(
    source_path, content_sha256, outcome, task_id, run_id,
    error_code, imported_at
)
SELECT source_path, content_sha256, outcome, task_id, run_id,
       error_code, imported_at
FROM legacy_imports_v4
""".strip(),
    "DROP TABLE legacy_imports_v4",
)

MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(version=1, name="initial_task_and_run_schema", statements=_V1_STATEMENTS),
    Migration(version=2, name="run_version_and_task_history_indexes", statements=_V2_STATEMENTS),
    Migration(version=3, name="run_deadline_and_checkpoint_references", statements=_V3_STATEMENTS),
    Migration(version=4, name="durable_task_events_and_legacy_imports", statements=_V4_STATEMENTS),
    Migration(version=5, name="tighten_legacy_import_invariants", statements=_V5_STATEMENTS),
)


class MigrationCompatibilityError(DeepChoiceError):
    """The stored schema history is incompatible with this application."""

    def __init__(
        self,
        *,
        code: str,
        category: ErrorCategory = ErrorCategory.COMPATIBILITY,
    ) -> None:
        super().__init__(
            "The product database schema is incompatible with this application version.",
            category=category,
            code=code,
            status_code=500,
            retryable=False,
            action="Use a compatible application build or restore the expected schema history.",
            scope="database_schema",
        )


class MigrationExecutionError(DeepChoiceError):
    """A migration could not be applied, expressed without internal details."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__(
            "The product database schema could not be updated.",
            category=ErrorCategory.PERSISTENCE,
            code="SCHEMA_MIGRATION_FAILED",
            status_code=503 if retryable else 500,
            retryable=retryable,
            action="Retry later." if retryable else "Inspect database health before retrying.",
            scope="database_schema",
        )


def _validate_migrations(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    if isinstance(migrations, (str, bytes)):
        raise TypeError("migrations must be a sequence of Migration values")
    configured = tuple(migrations)
    if not configured:
        raise ValueError("at least one migration is required")

    previous_version = 0
    for migration in configured:
        if type(migration) is not Migration:
            raise TypeError("all migrations must be Migration values")
        if type(migration.version) is not int or migration.version <= 0:
            raise ValueError("migration versions must be positive integers")
        if migration.version <= previous_version:
            raise ValueError("migration versions must be unique and strictly increasing")
        if not isinstance(migration.name, str) or not migration.name.strip():
            raise ValueError("migration names must be non-empty strings")
        if not isinstance(migration.statements, tuple) or not migration.statements:
            raise ValueError("migration statements must be a non-empty tuple")
        if any(
            not isinstance(statement, str) or not statement.strip()
            for statement in migration.statements
        ):
            raise ValueError("migration statements must be non-empty strings")
        previous_version = migration.version
    return configured


def _verify_history(
    rows: Sequence[tuple[int, str, str]], configured: tuple[Migration, ...]
) -> None:
    configured_versions = {migration.version for migration in configured}
    if any(version > configured[-1].version for version, _, _ in rows):
        raise MigrationCompatibilityError(code="SCHEMA_MIGRATION_FUTURE_VERSION")
    if any(version not in configured_versions for version, _, _ in rows):
        raise MigrationCompatibilityError(code="SCHEMA_MIGRATION_UNKNOWN_VERSION")
    if len(rows) > len(configured):
        raise MigrationCompatibilityError(code="SCHEMA_MIGRATION_UNKNOWN_VERSION")

    for index, (version, name, checksum) in enumerate(rows):
        expected = configured[index]
        if version != expected.version:
            raise MigrationCompatibilityError(code="SCHEMA_MIGRATION_HISTORY_GAP")
        if name != expected.name:
            raise MigrationCompatibilityError(code="SCHEMA_MIGRATION_NAME_MISMATCH")
        if checksum != expected.checksum:
            raise MigrationCompatibilityError(
                code="SCHEMA_MIGRATION_CHECKSUM_MISMATCH",
                category=ErrorCategory.PERSISTENCE,
            )


async def _safe_rollback(connection: aiosqlite.Connection) -> None:
    await _await_cleanup(connection.rollback())


async def _begin_immediate(connection: aiosqlite.Connection) -> None:
    cursor = await connection.execute("BEGIN IMMEDIATE")
    await cursor.close()


def _has_open_transaction(connection: aiosqlite.Connection) -> bool:
    try:
        return connection.in_transaction
    except Exception:
        return False


async def run_migrations(
    connection: aiosqlite.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> tuple[int, ...]:
    """Apply pending migrations atomically and return versions applied now.

    The caller retains ownership of ``connection``. Definitions are validated
    before any database write. ``BEGIN IMMEDIATE`` serializes concurrent runners;
    history is then re-read under the write lock before applying each migration.
    """

    configured = _validate_migrations(migrations)
    begin_task: asyncio.Task[None] | None = None
    try:
        begin_task = asyncio.create_task(_begin_immediate(connection))
        await asyncio.shield(begin_task)
        await connection.execute(_SCHEMA_MIGRATIONS_SQL)
        cursor = await connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        )
        try:
            history = await cursor.fetchall()
        finally:
            await cursor.close()
        _verify_history(history, configured)

        applied: list[int] = []
        for migration in configured[len(history) :]:
            for statement in migration.statements:
                await connection.execute(statement)
            await connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )
            applied.append(migration.version)
        await connection.commit()
        return tuple(applied)
    except asyncio.CancelledError:
        if begin_task is not None:
            await _await_cleanup(begin_task)
        if _has_open_transaction(connection):
            await _safe_rollback(connection)
        raise
    except DeepChoiceError:
        if _has_open_transaction(connection):
            await _safe_rollback(connection)
        raise
    except Exception as exc:
        if _has_open_transaction(connection):
            await _safe_rollback(connection)
        raise MigrationExecutionError(retryable=_is_locked_error(exc)) from None


__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationCompatibilityError",
    "MigrationExecutionError",
    "run_migrations",
]
