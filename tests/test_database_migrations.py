"""Contract tests for the product SQLite database foundation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from deepchoice.persistence import (
    MIGRATIONS,
    Migration,
    MigrationCompatibilityError,
    MigrationExecutionError,
    connect_database,
    run_migrations,
)


def _request() -> str:
    return json.dumps({"query": "compare"})


def _manifest() -> str:
    return json.dumps({"manifest_id": "m1"})


@pytest.mark.asyncio
async def test_fresh_database_has_schema_and_constraints(tmp_path: Path) -> None:
    path = tmp_path / "deepchoice.db"
    connection = await connect_database(path)
    try:
        assert await run_migrations(connection) == (1, 2, 3, 4)
        history = await (await connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        )).fetchall()
        assert history[0][0:2] == (1, "initial_task_and_run_schema")
        assert history[0][2] == "f082716c26fd378becd5ca8fe3e1b6e3ca32c1932136cad1b225b581e6169db7"
        assert history[1][0:2] == (2, "run_version_and_task_history_indexes")
        assert history[1][2] == "6730ecdfdcf9996267a0ed2b5451ee2a316fd727567c0fe083d00d801f43ca54"
        assert history[2][0:2] == (3, "run_deadline_and_checkpoint_references")
        assert history[2][2] == "0daf8d9051a5d952d4412fd4550fac9503c213fa4ff9afb1b3e40f45b344f109"
        assert history[3][0:2] == (4, "durable_task_events_and_legacy_imports")
        assert history[3][2] == "b55cb8ad4d86639851c4fcf6e358b5e4a1d78ff244eaedc644e19f63fa90c93a"

        for table in ("tasks", "runs"):
            names = {
                row[1]
                for row in await (await connection.execute(f"PRAGMA table_info({table})")).fetchall()
            }
            assert names
        task_columns = {
            row[1]
            for row in await (await connection.execute("PRAGMA table_info(tasks)")).fetchall()
        }
        run_columns = {
            row[1]
            for row in await (await connection.execute("PRAGMA table_info(runs)")).fetchall()
        }
        assert "deadline_at" in run_columns
        checkpoint_columns = {
            row[1]
            for row in await (await connection.execute("PRAGMA table_info(run_checkpoints)")).fetchall()
        }
        assert {"run_id", "checkpoint_ns", "storage_checkpoint_ns", "checkpoint_id", "node", "state_schema_version", "execution_epoch", "created_at"} <= checkpoint_columns
        checkpoint_indexes = {
            row[1] for row in await (await connection.execute("PRAGMA index_list(run_checkpoints)")).fetchall()
        }
        assert "idx_run_checkpoints_run_created" in checkpoint_indexes
        event_columns = {
            row[1]
            for row in await (await connection.execute("PRAGMA table_info(task_events)")).fetchall()
        }
        assert {
            "event_id", "task_id", "run_id", "seq", "type",
            "public_payload_json", "created_at",
        } <= event_columns
        import_columns = {
            row[1]
            for row in await (await connection.execute("PRAGMA table_info(legacy_imports)")).fetchall()
        }
        assert {"source_path", "content_sha256", "outcome", "error_code"} <= import_columns
        fk = await (await connection.execute("PRAGMA foreign_key_list(run_checkpoints)")).fetchall()
        assert any(row[2] == "runs" and row[6] == "CASCADE" for row in fk)
        assert {"task_id", "status", "request_json", "latest_run_id", "version"} <= task_columns
        assert {"run_id", "task_id", "status", "manifest_json", "execution_epoch", "version"} <= run_columns
        indexes = {
            row[1]
            for table in ("tasks", "runs")
            for row in await (await connection.execute(f"PRAGMA index_list({table})")).fetchall()
        }
        assert {
            "idx_tasks_status",
            "idx_runs_task_id",
            "idx_runs_status",
            "idx_runs_lease_expires_at",
            "idx_tasks_created_at_task_id",
            "idx_tasks_status_created_at_task_id",
        } <= indexes
        assert any(row[2] == "tasks" for row in await (await connection.execute("PRAGMA foreign_key_list(runs)")).fetchall())

        await connection.execute(
            "INSERT INTO tasks(task_id,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("t1", "queued", _request(), "now", "now"),
        )
        await connection.execute(
            "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("r1", "t1", "queued", _manifest(), "thread", "now", "now"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO tasks(task_id,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("bad", "unknown", _request(), "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO tasks(task_id,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("bad-json", "queued", "not-json", "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,execution_epoch,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    "bad-epoch",
                    "t1",
                    "queued",
                    _manifest(),
                    "thread-bad-epoch",
                    -1,
                    "now",
                    "now",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("bad-manifest", "t1", "queued", "not-json", "thread-2", "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("bad-task", "missing", "queued", _manifest(), "thread-3", "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("r2", "t1", "queued", _manifest(), "thread", "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO tasks(task_id,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("", "queued", _request(), "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("", "t1", "queued", _manifest(), "thread-empty-run", "now", "now"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute("DELETE FROM tasks WHERE task_id = 't1'")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_each_connection_enables_required_pragmas(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        assert (await (await connection.execute("PRAGMA foreign_keys")).fetchone())[0] == 1
        assert (await (await connection.execute("PRAGMA busy_timeout")).fetchone())[0] > 0
        assert (await (await connection.execute("PRAGMA journal_mode")).fetchone())[0].lower() == "wal"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_second_run_is_noop(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        assert await run_migrations(connection) == (1, 2, 3, 4)
        assert await run_migrations(connection) == ()
        assert (await (await connection.execute("SELECT count(*) FROM schema_migrations")).fetchone())[0] == 4
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_existing_v1_database_upgrades_to_v2(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        assert await run_migrations(connection, MIGRATIONS[:1]) == (1,)
        await connection.execute(
            """
            INSERT INTO tasks(
                task_id, status, request_json, latest_run_id, created_at, updated_at
            ) VALUES ('task-v1', 'queued', '{}', 'run-v1', '2026-01-01', '2026-01-01')
            """
        )
        await connection.execute(
            """
            INSERT INTO runs(
                run_id, task_id, status, manifest_json, thread_id, created_at, updated_at
            ) VALUES (
                'run-v1', 'task-v1', 'queued', '{}', 'run-v1',
                '2026-01-01', '2026-01-01'
            )
            """
        )
        assert await run_migrations(connection) == (2, 3, 4)
        versions = await (await connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )).fetchall()
        assert [row[0] for row in versions] == [1, 2, 3, 4]
        assert "version" in {
            row[1] for row in await (await connection.execute("PRAGMA table_info(runs)")).fetchall()
        }
        assert any(
            row[1] == "idx_tasks_status_created_at_task_id"
            for row in await (await connection.execute("PRAGMA index_list(tasks)")).fetchall()
        )
        assert await (await connection.execute(
            "SELECT task_id, status FROM tasks WHERE task_id = 'task-v1'"
        )).fetchone() == ("task-v1", "queued")
        assert await (await connection.execute(
            "SELECT run_id, status, version FROM runs WHERE run_id = 'run-v1'"
        )).fetchone() == ("run-v1", "queued", 0)
        assert await (await connection.execute(
            "SELECT deadline_at FROM runs WHERE run_id = 'run-v1'"
        )).fetchone() == (None,)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_existing_v2_database_upgrades_to_v3_and_preserves_runs(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        assert await run_migrations(connection, MIGRATIONS[:2]) == (1, 2)
        await connection.execute(
            "INSERT INTO tasks(task_id,status,request_json,created_at,updated_at) VALUES ('task-v2','queued','{}','2026-01-01','2026-01-01')"
        )
        await connection.execute(
            "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) VALUES ('run-v2','task-v2','queued','{}','run-v2','2026-01-01','2026-01-01')"
        )
        assert await run_migrations(connection) == (3, 4)
        assert await (await connection.execute("SELECT deadline_at FROM runs WHERE run_id='run-v2'")).fetchone() == (None,)
        await connection.execute(
            "INSERT INTO run_checkpoints(run_id,checkpoint_ns,storage_checkpoint_ns,checkpoint_id,state_schema_version,execution_epoch,created_at) VALUES ('run-v2','','','cp-1',1,1,'now')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            await connection.execute(
                "INSERT INTO run_checkpoints(run_id,checkpoint_ns,storage_checkpoint_ns,checkpoint_id,state_schema_version,execution_epoch,created_at) VALUES ('run-v2','','','cp-1',1,1,'now')"
            )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_existing_v3_database_upgrades_to_v4_and_preserves_runs(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        assert await run_migrations(connection, MIGRATIONS[:3]) == (1, 2, 3)
        await connection.execute(
            "INSERT INTO tasks(task_id,status,request_json,latest_run_id,created_at,updated_at) "
            "VALUES ('task-v3','queued','{}','run-v3','2026-01-01','2026-01-01')"
        )
        await connection.execute(
            "INSERT INTO runs(run_id,task_id,status,manifest_json,thread_id,created_at,updated_at) "
            "VALUES ('run-v3','task-v3','queued','{}','run-v3','2026-01-01','2026-01-01')"
        )
        await connection.commit()

        assert await run_migrations(connection) == (4,)
        assert await (
            await connection.execute("SELECT status FROM tasks WHERE task_id='task-v3'")
        ).fetchone() == ("queued",)
        assert await (
            await connection.execute("SELECT COUNT(*) FROM task_events")
        ).fetchone() == (0,)
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column,value,expected_code",
    [
        ("name", "renamed", "SCHEMA_MIGRATION_NAME_MISMATCH"),
        ("checksum", "0" * 64, "SCHEMA_MIGRATION_CHECKSUM_MISMATCH"),
    ],
)
async def test_history_drift_is_safe_error(
    tmp_path: Path, column: str, value: str, expected_code: str
) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        await run_migrations(connection)
        await connection.execute(f"UPDATE schema_migrations SET {column} = ? WHERE version = 1", (value,))
        with pytest.raises(MigrationCompatibilityError) as error:
            await run_migrations(connection)
        detail = error.value.error_detail
        assert detail.code == expected_code
        if column == "checksum":
            assert detail.category.value == "persistence"
        assert "deepchoice.db" not in detail.message
        assert "UPDATE" not in detail.message
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_future_version_is_rejected(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        await connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT)")
        await connection.execute("INSERT INTO schema_migrations VALUES(99,'future','" + "0" * 64 + "','now')")
        with pytest.raises(MigrationCompatibilityError) as error:
            await run_migrations(connection)
        assert error.value.error_detail.code == "SCHEMA_MIGRATION_FUTURE_VERSION"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_history_gap_is_rejected(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        await connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT)"
        )
        await connection.execute(
            "INSERT INTO schema_migrations VALUES(2,'unknown','" + "0" * 64 + "','now')"
        )
        configured = (MIGRATIONS[0], Migration(2, "second", ("SELECT 1",)))
        with pytest.raises(MigrationCompatibilityError) as error:
            await run_migrations(connection, configured)
        assert error.value.error_detail.code == "SCHEMA_MIGRATION_HISTORY_GAP"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_unknown_version_is_rejected(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        await connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT)"
        )
        await connection.execute(
            "INSERT INTO schema_migrations VALUES(2,'unknown','" + "0" * 64 + "','now')"
        )
        configured = (MIGRATIONS[0], Migration(3, "third", ("SELECT 1",)))
        with pytest.raises(MigrationCompatibilityError) as error:
            await run_migrations(connection, configured)
        assert error.value.error_detail.code == "SCHEMA_MIGRATION_UNKNOWN_VERSION"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_ddl_and_history(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    failing = Migration(1, "fails", ("CREATE TABLE sentinel(value TEXT)", "THIS IS NOT SQL"))
    try:
        with pytest.raises(MigrationExecutionError):
            await run_migrations(connection, (failing,))
        assert (await (await connection.execute("SELECT count(*) FROM sqlite_master WHERE name='sentinel'")).fetchone())[0] == 0
        assert (await (await connection.execute("SELECT count(*) FROM sqlite_master WHERE name='schema_migrations'")).fetchone())[0] == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_concurrent_runners_produce_one_history_row(tmp_path: Path) -> None:
    path = tmp_path / "deepchoice.db"
    first, second = await asyncio.gather(connect_database(path), connect_database(path))
    try:
        results = await asyncio.gather(run_migrations(first), run_migrations(second))
        assert sorted(results) == [(), (1, 2, 3, 4)]
        assert (await (await first.execute("SELECT count(*) FROM schema_migrations")).fetchone())[0] == 4
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_invalid_definitions_are_rejected_before_database_write() -> None:
    invalid = (
        (Migration(0, "bad", ("SELECT 1",)), ValueError),
        (Migration(1, "", ("SELECT 1",)), ValueError),
        (Migration(1, "bad", ()), ValueError),
        (Migration(1, "bad", ("   ",)), ValueError),
    )
    for migration, exception in invalid:
        connection = await aiosqlite.connect(":memory:", isolation_level=None)
        try:
            with pytest.raises(exception):
                await run_migrations(connection, (migration,))
            tables = await (await connection.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            assert tables == []
        finally:
            await connection.close()
    invalid_sequences = [
        (Migration(1, "a", ("SELECT 1",)), Migration(1, "b", ("SELECT 1",))),
        (Migration(2, "a", ("SELECT 1",)), Migration(1, "b", ("SELECT 1",))),
    ]
    for migrations in invalid_sequences:
        connection = await aiosqlite.connect(":memory:", isolation_level=None)
        try:
            with pytest.raises(ValueError):
                await run_migrations(connection, migrations)
        finally:
            await connection.close()


@pytest.mark.asyncio
async def test_product_db_does_not_use_checkpoint_tables(tmp_path: Path) -> None:
    connection = await connect_database(tmp_path / "deepchoice.db")
    try:
        await run_migrations(connection)
        names = {
            row[0]
            for row in await (await connection.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }
        assert "checkpoints" not in names
        assert "checkpoint_writes" not in names
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_cancelled_connection_initialization_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deepchoice.persistence.database as database

    original_connect = database.aiosqlite.connect
    captured: list[aiosqlite.Connection] = []

    async def connect_and_capture(*args: object, **kwargs: object) -> aiosqlite.Connection:
        connection = await original_connect(*args, **kwargs)
        captured.append(connection)
        return connection

    async def cancel_wal(connection: aiosqlite.Connection) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(database.aiosqlite, "connect", connect_and_capture)
    monkeypatch.setattr(database, "_enable_wal", cancel_wal)
    with pytest.raises(asyncio.CancelledError):
        await database.connect_database(tmp_path / "deepchoice.db")
    assert captured and captured[0]._running is False


@pytest.mark.asyncio
async def test_cancelled_migration_rolls_back_and_releases_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deepchoice.persistence.migrations as migration_module

    path = tmp_path / "deepchoice.db"
    first = await connect_database(path)
    second = await connect_database(path)
    original_begin = migration_module._begin_immediate
    began = asyncio.Event()
    release_begin = asyncio.Event()

    async def begin_then_pause(connection: aiosqlite.Connection) -> None:
        await original_begin(connection)
        began.set()
        await release_begin.wait()

    try:
        monkeypatch.setattr(migration_module, "_begin_immediate", begin_then_pause)
        migration_task = asyncio.create_task(run_migrations(first))
        await began.wait()
        migration_task.cancel()
        await asyncio.sleep(0)
        release_begin.set()
        with pytest.raises(asyncio.CancelledError):
            await migration_task
        monkeypatch.setattr(migration_module, "_begin_immediate", original_begin)
        assert first.in_transaction is False
        assert await run_migrations(second) == (1, 2, 3, 4)
    finally:
        await first.close()
        await second.close()
