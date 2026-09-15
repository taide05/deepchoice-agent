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

_V6_STATEMENTS: Final[tuple[str, ...]] = (
    """
CREATE TABLE run_results (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE RESTRICT
        CHECK (length(run_id) > 0),
    result_schema_version INTEGER NOT NULL CHECK (result_schema_version = 1),
    snapshot_json TEXT NOT NULL
        CHECK (json_valid(snapshot_json) AND json_type(snapshot_json) = 'object'),
    report TEXT NOT NULL CHECK (length(trim(report)) > 0),
    report_format TEXT NOT NULL
        CHECK (report_format IN ('what_why_how', 'evidence_first', 'comparison_matrix')),
    created_at TEXT NOT NULL
)
""".strip(),
    """
CREATE TRIGGER run_results_reject_update
BEFORE UPDATE ON run_results
BEGIN
    SELECT RAISE(ABORT, 'run_results are immutable');
END
""".strip(),
    """
CREATE TRIGGER run_results_reject_delete
BEFORE DELETE ON run_results
BEGIN
    SELECT RAISE(ABORT, 'run_results are immutable');
END
""".strip(),
)

_V7_STATEMENTS: Final[tuple[str, ...]] = (
    """
CREATE TABLE runtime_instance_leases (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    owner_token TEXT NOT NULL CHECK (length(owner_token) > 0),
    pid INTEGER NOT NULL CHECK (pid > 0),
    hostname TEXT NOT NULL CHECK (length(hostname) > 0),
    started_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL
)
""".strip(),
)

_V8_STATEMENTS: Final[tuple[str, ...]] = (
    """
CREATE TABLE run_budget_policies (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE RESTRICT
        CHECK (length(run_id) > 0),
    policy_schema_version INTEGER NOT NULL CHECK (policy_schema_version = 1),
    policy_version TEXT NOT NULL CHECK (length(policy_version) > 0),
    policy_json TEXT NOT NULL CHECK (
        json_valid(policy_json)
        AND json_type(policy_json) = 'object'
        AND json_extract(policy_json, '$.policy_schema_version') = policy_schema_version
        AND json_type(policy_json, '$.policy_version') = 'text'
        AND json_extract(policy_json, '$.policy_version') = policy_version
    ),
    price_catalog_version TEXT NOT NULL CHECK (
        length(price_catalog_version) > 0
        AND json_type(policy_json, '$.price_catalog_version') = 'text'
        AND json_extract(policy_json, '$.price_catalog_version') = price_catalog_version
    ),
    created_at TEXT NOT NULL
)
""".strip(),
    "CREATE INDEX idx_run_budget_policies_catalog ON run_budget_policies(price_catalog_version, run_id)",
    """
CREATE TRIGGER run_budget_policies_reject_update
BEFORE UPDATE ON run_budget_policies
BEGIN
    SELECT RAISE(ABORT, 'run budget policies are immutable');
END
""".strip(),
    """
CREATE TRIGGER run_budget_policies_reject_delete
BEFORE DELETE ON run_budget_policies
BEGIN
    SELECT RAISE(ABORT, 'run budget policies are immutable');
END
""".strip(),
    """
CREATE TABLE node_attempts (
    node_attempt_id TEXT PRIMARY KEY CHECK (length(node_attempt_id) > 0),
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE
        CHECK (length(run_id) > 0),
    execution_epoch INTEGER NOT NULL CHECK (execution_epoch >= 1),
    node_name TEXT NOT NULL CHECK (length(node_name) > 0),
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    status TEXT NOT NULL CHECK (
        status IN (
            'started', 'succeeded', 'failed', 'cancelled',
            'timed_out', 'interrupted', 'unknown'
        )
    ),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary_json TEXT NOT NULL CHECK (
        json_valid(summary_json) AND json_type(summary_json) = 'object'
    ),
    UNIQUE (run_id, execution_epoch, node_name, attempt_no),
    UNIQUE (run_id, execution_epoch, node_attempt_id),
    CHECK (
        (status = 'started' AND ended_at IS NULL)
        OR (status <> 'started' AND ended_at IS NOT NULL)
    )
)
""".strip(),
    "CREATE INDEX idx_node_attempts_run_started ON node_attempts(run_id, execution_epoch, started_at, attempt_no)",
    """
CREATE TABLE external_calls (
    call_id TEXT PRIMARY KEY CHECK (length(call_id) > 0),
    run_id TEXT NOT NULL CHECK (length(run_id) > 0),
    execution_epoch INTEGER NOT NULL CHECK (execution_epoch >= 1),
    node_attempt_id TEXT NOT NULL CHECK (length(node_attempt_id) > 0),
    call_no INTEGER NOT NULL CHECK (call_no >= 1),
    kind TEXT NOT NULL CHECK (kind IN ('llm', 'retrieval', 'http', 'other')),
    provider TEXT NOT NULL CHECK (length(provider) > 0),
    operation TEXT NOT NULL CHECK (length(operation) > 0),
    status TEXT NOT NULL CHECK (
        status IN (
            'started', 'succeeded', 'failed', 'cancelled',
            'timed_out', 'interrupted', 'unknown'
        )
    ),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    request_summary_json TEXT NOT NULL CHECK (
        json_valid(request_summary_json) AND json_type(request_summary_json) = 'object'
    ),
    result_summary_json TEXT NOT NULL CHECK (
        json_valid(result_summary_json) AND json_type(result_summary_json) = 'object'
    ),
    usage_summary_json TEXT NOT NULL CHECK (
        json_valid(usage_summary_json) AND json_type(usage_summary_json) = 'object'
    ),
    UNIQUE (run_id, node_attempt_id, call_no),
    UNIQUE (run_id, execution_epoch, call_id),
    UNIQUE (run_id, execution_epoch, node_attempt_id, call_id),
    FOREIGN KEY (run_id, execution_epoch, node_attempt_id)
        REFERENCES node_attempts(run_id, execution_epoch, node_attempt_id)
        ON DELETE RESTRICT,
    CHECK (
        (status = 'started' AND ended_at IS NULL)
        OR (status <> 'started' AND ended_at IS NOT NULL)
    )
)
""".strip(),
    "CREATE INDEX idx_external_calls_run_started ON external_calls(run_id, execution_epoch, started_at, call_no)",
    "CREATE INDEX idx_external_calls_attempt ON external_calls(run_id, node_attempt_id, call_no)",
    """
CREATE TABLE trace_events (
    trace_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE
        CHECK (length(run_id) > 0),
    execution_epoch INTEGER NOT NULL CHECK (execution_epoch >= 1),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    event_type TEXT NOT NULL CHECK (length(event_type) > 0),
    node_attempt_id TEXT,
    call_id TEXT,
    summary_json TEXT NOT NULL CHECK (
        json_valid(summary_json) AND json_type(summary_json) = 'object'
    ),
    created_at TEXT NOT NULL,
    UNIQUE (run_id, seq),
    FOREIGN KEY (run_id, execution_epoch, node_attempt_id)
        REFERENCES node_attempts(run_id, execution_epoch, node_attempt_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (run_id, execution_epoch, node_attempt_id, call_id)
        REFERENCES external_calls(
            run_id, execution_epoch, node_attempt_id, call_id
        )
        ON DELETE RESTRICT,
    CHECK (node_attempt_id IS NULL OR length(node_attempt_id) > 0),
    CHECK (call_id IS NULL OR length(call_id) > 0),
    CHECK (call_id IS NULL OR node_attempt_id IS NOT NULL)
)
""".strip(),
    "CREATE INDEX idx_trace_events_run_sequence ON trace_events(run_id, seq)",
    "CREATE INDEX idx_trace_events_attempt ON trace_events(run_id, node_attempt_id, seq)",
    "CREATE INDEX idx_trace_events_call ON trace_events(run_id, call_id, seq)",
    """
CREATE TRIGGER trace_events_reject_update
BEFORE UPDATE ON trace_events
BEGIN
    SELECT RAISE(ABORT, 'trace events are append-only');
END
""".strip(),
    """
CREATE TRIGGER trace_events_reject_delete
BEFORE DELETE ON trace_events
BEGIN
    SELECT RAISE(ABORT, 'trace events are append-only');
END
""".strip(),
    """
CREATE TABLE budget_ledger (
    ledger_entry_id TEXT PRIMARY KEY CHECK (length(ledger_entry_id) > 0),
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE
        CHECK (length(run_id) > 0),
    execution_epoch INTEGER NOT NULL CHECK (execution_epoch >= 1),
    call_id TEXT CHECK (call_id IS NULL OR length(call_id) > 0),
    reservation_id TEXT NOT NULL CHECK (length(reservation_id) > 0),
    entry_sequence INTEGER NOT NULL CHECK (entry_sequence >= 1),
    status TEXT NOT NULL CHECK (
        status IN ('reserved', 'settled', 'released', 'unknown_spend')
    ),
    resource TEXT NOT NULL CHECK (
        resource IN (
            'input_tokens', 'output_tokens', 'total_tokens', 'cost_micro_usd',
            'llm_calls', 'retrieval_calls', 'http_calls',
            'active_milliseconds', 'wall_clock_milliseconds'
        )
    ),
    reserved_amount INTEGER NOT NULL CHECK (reserved_amount >= 0),
    actual_amount INTEGER CHECK (actual_amount IS NULL OR actual_amount >= 0),
    price_status TEXT NOT NULL CHECK (
        price_status IN ('priced', 'unknown', 'not_applicable')
    ),
    price_catalog_version TEXT NOT NULL CHECK (length(price_catalog_version) > 0),
    summary_json TEXT NOT NULL CHECK (
        json_valid(summary_json) AND json_type(summary_json) = 'object'
    ),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    settled_at TEXT,
    UNIQUE (run_id, execution_epoch, reservation_id, entry_sequence),
    CHECK (
        (status IN ('reserved', 'released') AND actual_amount IS NULL)
        OR (status IN ('settled', 'unknown_spend') AND actual_amount IS NOT NULL)
    ),
    CHECK (status <> 'unknown_spend' OR actual_amount = reserved_amount),
    CHECK (
        (status = 'reserved' AND settled_at IS NULL)
        OR (status <> 'reserved' AND settled_at IS NOT NULL)
    ),
    FOREIGN KEY (run_id, execution_epoch, call_id)
        REFERENCES external_calls(run_id, execution_epoch, call_id)
        ON DELETE RESTRICT
)
""".strip(),
    "CREATE INDEX idx_budget_ledger_run_created ON budget_ledger(run_id, execution_epoch, created_at, entry_sequence)",
    "CREATE INDEX idx_budget_ledger_reservation ON budget_ledger(run_id, execution_epoch, reservation_id, entry_sequence)",
    """
CREATE TRIGGER budget_ledger_reject_update
BEFORE UPDATE ON budget_ledger
BEGIN
    SELECT RAISE(ABORT, 'budget ledger is append-only');
END
""".strip(),
    """
CREATE TRIGGER budget_ledger_reject_delete
BEFORE DELETE ON budget_ledger
BEGIN
    SELECT RAISE(ABORT, 'budget ledger is append-only');
END
""".strip(),
)

_V9_STATEMENTS: Final[tuple[str, ...]] = (
    """
CREATE TABLE retrieval_cache (
    cache_key_sha256 TEXT PRIMARY KEY CHECK (
        length(cache_key_sha256) = 64
        AND cache_key_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    result_json TEXT NOT NULL CHECK (
        json_valid(result_json) AND json_type(result_json) = 'object'
    ),
    payload_bytes INTEGER NOT NULL CHECK (
        payload_bytes >= 0 AND payload_bytes <= 524288
        AND payload_bytes = length(CAST(result_json AS BLOB))
    ),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
""".strip(),
    "CREATE INDEX idx_retrieval_cache_expires_at ON retrieval_cache(expires_at)",
)

_V10_STATEMENTS: Final[tuple[str, ...]] = (
    "CREATE UNIQUE INDEX idx_runs_task_run_identity ON runs(task_id, run_id)",
    """
CREATE UNIQUE INDEX idx_run_checkpoints_hitl_identity
ON run_checkpoints(
    run_id, checkpoint_ns, storage_checkpoint_ns, checkpoint_id,
    state_schema_version, execution_epoch
)
""".strip(),
    """
CREATE TABLE hitl_decisions (
    decision_id TEXT PRIMARY KEY CHECK (length(decision_id) BETWEEN 1 AND 100),
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT
        CHECK (length(task_id) > 0),
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT
        CHECK (length(run_id) > 0),
    kind TEXT NOT NULL CHECK (kind = 'evidence-insufficient'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'resolved', 'expired', 'cancelled')),
    request_json TEXT NOT NULL CHECK (
        json_valid(request_json) AND json_type(request_json) = 'object'
        AND length(CAST(request_json AS BLOB)) <= 32768
    ),
    checkpoint_ns TEXT NOT NULL,
    storage_checkpoint_ns TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL CHECK (length(checkpoint_id) > 0),
    state_schema_version INTEGER NOT NULL CHECK (state_schema_version > 0),
    pause_execution_epoch INTEGER NOT NULL CHECK (pause_execution_epoch >= 1),
    expires_at TEXT NOT NULL,
    resolution_json TEXT CHECK (
        resolution_json IS NULL OR (
            json_valid(resolution_json) AND json_type(resolution_json) = 'object'
            AND length(CAST(resolution_json AS BLOB)) <= 32768
        )
    ),
    resolution_body_sha256 TEXT CHECK (
        resolution_body_sha256 IS NULL OR (
            length(resolution_body_sha256) = 64
            AND resolution_body_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (run_id, storage_checkpoint_ns, checkpoint_id)
        REFERENCES run_checkpoints(run_id, storage_checkpoint_ns, checkpoint_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (task_id, run_id)
        REFERENCES runs(task_id, run_id) ON DELETE RESTRICT,
    FOREIGN KEY (
        run_id, checkpoint_ns, storage_checkpoint_ns, checkpoint_id,
        state_schema_version, pause_execution_epoch
    ) REFERENCES run_checkpoints(
        run_id, checkpoint_ns, storage_checkpoint_ns, checkpoint_id,
        state_schema_version, execution_epoch
    ) ON DELETE RESTRICT,
    CHECK (
        (status = 'pending' AND resolution_json IS NULL
            AND resolution_body_sha256 IS NULL AND resolved_at IS NULL)
        OR
        (status IN ('resolved', 'cancelled') AND resolution_json IS NOT NULL
            AND resolution_body_sha256 IS NOT NULL AND resolved_at IS NOT NULL)
        OR
        (status = 'expired' AND resolution_json IS NULL
            AND resolution_body_sha256 IS NULL AND resolved_at IS NOT NULL)
    )
)
""".strip(),
    """
CREATE UNIQUE INDEX idx_hitl_decisions_one_pending_run
ON hitl_decisions(run_id) WHERE status = 'pending'
""".strip(),
    "CREATE INDEX idx_hitl_decisions_task_created ON hitl_decisions(task_id, created_at DESC)",
    "CREATE INDEX idx_hitl_decisions_expiry ON hitl_decisions(status, expires_at)",
)

MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(version=1, name="initial_task_and_run_schema", statements=_V1_STATEMENTS),
    Migration(version=2, name="run_version_and_task_history_indexes", statements=_V2_STATEMENTS),
    Migration(version=3, name="run_deadline_and_checkpoint_references", statements=_V3_STATEMENTS),
    Migration(version=4, name="durable_task_events_and_legacy_imports", statements=_V4_STATEMENTS),
    Migration(version=5, name="tighten_legacy_import_invariants", statements=_V5_STATEMENTS),
    Migration(version=6, name="immutable_run_results", statements=_V6_STATEMENTS),
    Migration(version=7, name="single_runtime_instance_lease", statements=_V7_STATEMENTS),
    Migration(version=8, name="trace_and_budget_contract_schema", statements=_V8_STATEMENTS),
    Migration(version=9, name="retrieval_result_cache", statements=_V9_STATEMENTS),
    Migration(version=10, name="single_hitl_decision_gate", statements=_V10_STATEMENTS),
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
