"""Connection factory for DeepChoice's product database.

This database is deliberately separate from LangGraph's ``checkpoints.db``.
The caller owns every returned connection and must close it, preferably with
``async with`` or in a ``finally`` block. Importing this module never opens or
creates a database.
"""

import asyncio
from pathlib import Path
from typing import Awaitable

import aiosqlite

from deepchoice.contracts.errors import DeepChoiceError, ErrorCategory


DEFAULT_DB_PATH = Path("outputs/deepchoice.db")


class DatabaseConnectionError(DeepChoiceError):
    """A safe public error for product-database connection failures."""

    def __init__(self, *, retryable: bool = False) -> None:
        super().__init__(
            "The product database is unavailable.",
            category=ErrorCategory.PERSISTENCE,
            code="DATABASE_CONNECTION_FAILED",
            status_code=503,
            retryable=retryable,
            action="Retry after confirming that the database storage is available.",
            scope="database",
        )


def _is_locked_error(exc: BaseException) -> bool:
    """Classify SQLite contention without exposing the original error."""

    if not isinstance(exc, aiosqlite.OperationalError):
        return False
    error_code = getattr(exc, "sqlite_errorcode", None)
    # SQLITE_BUSY=5 and SQLITE_LOCKED=6. Extended codes keep the base value in
    # their low byte.
    if isinstance(error_code, int) and error_code & 0xFF in {5, 6}:
        return True
    # Python/SQLite versions do not always attach sqlite_errorcode.
    message = str(exc).lower()
    return "locked" in message or "busy" in message


async def _await_cleanup(awaitable: Awaitable[object]) -> None:
    """Finish cleanup even if the calling task is cancelled more than once."""

    cleanup_task = asyncio.ensure_future(awaitable)
    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not cleanup_task.cancelled():
        try:
            cleanup_task.result()
        except Exception:
            pass


async def _enable_wal(connection: aiosqlite.Connection) -> None:
    """Enable WAL with bounded retry for concurrent database initialization."""

    attempts = 4
    for attempt in range(attempts):
        cursor: aiosqlite.Cursor | None = None
        try:
            cursor = await connection.execute("PRAGMA journal_mode = WAL")
            # Fetching the result finalizes this state-changing PRAGMA before a
            # concurrently opening process makes its own attempt.
            await cursor.fetchone()
            await cursor.close()
            return
        except Exception as exc:
            if cursor is not None:
                try:
                    await cursor.close()
                except Exception:
                    pass
            if not _is_locked_error(exc) or attempt == attempts - 1:
                raise
            await asyncio.sleep(0.025 * (2**attempt))


async def connect_database(
    path: str | Path = DEFAULT_DB_PATH,
    *,
    busy_timeout_ms: int = 5_000,
) -> aiosqlite.Connection:
    """Open and configure a caller-owned product database connection.

    The connection uses explicit transaction control (``isolation_level=None``),
    enforces foreign keys, waits briefly for concurrent writers, and enables WAL
    mode. Schema creation is handled separately by :func:`run_migrations`.
    """

    if type(busy_timeout_ms) is not int or busy_timeout_ms <= 0:
        raise ValueError("busy_timeout_ms must be a positive integer")
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be a string or Path")

    connection: aiosqlite.Connection | None = None
    try:
        database_path = Path(path)
        is_memory = str(path) == ":memory:"
        if not is_memory:
            database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(path), isolation_level=None)
        cursor = await connection.execute("PRAGMA foreign_keys = ON")
        await cursor.close()
        cursor = await connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        await cursor.close()
        await _enable_wal(connection)

        cursor = await connection.execute("PRAGMA foreign_keys")
        foreign_keys_row = await cursor.fetchone()
        await cursor.close()
        cursor = await connection.execute("PRAGMA busy_timeout")
        busy_timeout_row = await cursor.fetchone()
        await cursor.close()
        cursor = await connection.execute("PRAGMA journal_mode")
        journal_mode_row = await cursor.fetchone()
        await cursor.close()

        foreign_keys = foreign_keys_row[0] if foreign_keys_row else None
        actual_timeout = busy_timeout_row[0] if busy_timeout_row else None
        journal_mode = str(journal_mode_row[0]).lower() if journal_mode_row else None
        expected_journal_modes = {"memory"} if is_memory else {"wal"}
        if (
            foreign_keys != 1
            or actual_timeout != busy_timeout_ms
            or journal_mode not in expected_journal_modes
        ):
            raise RuntimeError("database pragma verification failed")
        return connection
    except asyncio.CancelledError:
        if connection is not None:
            await _await_cleanup(connection.close())
        raise
    except Exception as exc:
        if connection is not None:
            try:
                await connection.close()
            except Exception:
                pass
        raise DatabaseConnectionError(retryable=_is_locked_error(exc)) from None


__all__ = ["DEFAULT_DB_PATH", "DatabaseConnectionError", "connect_database"]
