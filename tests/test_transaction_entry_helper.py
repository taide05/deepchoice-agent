"""SQLite worker-queue and cleanup boundaries for transaction admission."""

import asyncio
import sqlite3
import threading

import pytest

from deepchoice.persistence.database import _begin_transaction, connect_database


@pytest.mark.asyncio
async def test_cancel_queued_begin_drains_rollback_despite_second_cancel(tmp_path):
    path = tmp_path / "queued.db"
    connection = await connect_database(path)
    blocker = await connect_database(path)
    entered = threading.Event()
    pending = None
    try:
        await blocker.execute("BEGIN IMMEDIATE")
        await connection.set_trace_callback(
            lambda sql: entered.set() if sql == "BEGIN IMMEDIATE" else None
        )
        pending = asyncio.create_task(_begin_transaction(connection))
        assert await asyncio.to_thread(entered.wait, 2)
        # SQLite is blocked by the other writer: checking in_transaction now
        # would miss a BEGIN already dispatched into its worker queue.
        assert not connection.in_transaction
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        await blocker.rollback()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 2)
        assert not connection.in_transaction
        await _begin_transaction(connection)
        await connection.rollback()
    finally:
        await blocker.rollback()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await blocker.close()
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("immediate", [True, False])
async def test_entry_close_failure_rolls_back_but_nested_begin_preserves_owner(
    tmp_path, monkeypatch, immediate
):
    connection = await connect_database(tmp_path / "close.db")
    real_execute = connection.execute

    class FailedClose:
        async def close(self):
            raise RuntimeError("fixture close failure")

    async def execute(sql, parameters=()):
        cursor = await real_execute(sql, parameters)
        await cursor.close()
        return FailedClose()

    try:
        monkeypatch.setattr(connection, "execute", execute)
        with pytest.raises(RuntimeError, match="fixture close failure"):
            await _begin_transaction(connection, immediate=immediate)
        assert not connection.in_transaction
        monkeypatch.setattr(connection, "execute", real_execute)
        await connection.execute("CREATE TABLE owner_data (value TEXT)")
        await _begin_transaction(connection, immediate=immediate)
        await connection.execute("INSERT INTO owner_data VALUES ('preserve')")
        with pytest.raises(sqlite3.OperationalError):
            await _begin_transaction(connection, immediate=immediate)
        assert connection.in_transaction
        await connection.commit()
        cursor = await connection.execute("SELECT value FROM owner_data")
        assert await cursor.fetchall() == [("preserve",)]
        await cursor.close()
    finally:
        await connection.close()
