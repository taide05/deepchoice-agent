from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deepchoice.persistence import connect_database, run_migrations
from deepchoice.runtime.instance_guard import (
    RuntimeConfigurationError,
    RuntimeInstanceConflictError,
    RuntimeInstanceGuard,
    RuntimeInstanceLeaseLostError,
    validate_single_worker_configuration,
)
from deepchoice.server.app import lifespan


NOW = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


def test_single_worker_configuration_rejects_known_multi_worker_settings():
    validate_single_worker_configuration({})
    validate_single_worker_configuration({"WEB_CONCURRENCY": "1", "UVICORN_CMD_ARGS": "--workers=1"})
    for values in (
        {"WEB_CONCURRENCY": "2"},
        {"UVICORN_WORKERS": "0"},
        {"UVICORN_CMD_ARGS": "--host 0.0.0.0 --workers 4"},
        {"GUNICORN_CMD_ARGS": "-w 3"},
    ):
        with pytest.raises(RuntimeConfigurationError):
            validate_single_worker_configuration(values)


@pytest.mark.asyncio
async def test_only_one_live_instance_can_hold_database_lease(tmp_path):
    first_connection = await connect_database(tmp_path / "product.db")
    await run_migrations(first_connection)
    second_connection = await connect_database(tmp_path / "product.db")
    first = RuntimeInstanceGuard(first_connection, asyncio.Lock(), owner_token="first", clock=lambda: NOW)
    second = RuntimeInstanceGuard(second_connection, asyncio.Lock(), owner_token="second", clock=lambda: NOW)
    try:
        await first.acquire()
        with pytest.raises(RuntimeInstanceConflictError):
            await second.acquire()
        await first.release()
        await second.acquire()
    finally:
        await first.release()
        await second.release()
        await first_connection.close()
        await second_connection.close()


@pytest.mark.asyncio
async def test_expired_lease_can_be_taken_over_and_old_owner_is_fenced(tmp_path):
    current = NOW
    first_connection = await connect_database(tmp_path / "product.db")
    await run_migrations(first_connection)
    second_connection = await connect_database(tmp_path / "product.db")
    first = RuntimeInstanceGuard(
        first_connection, asyncio.Lock(), lease_seconds=3, heartbeat_seconds=1,
        owner_token="first", clock=lambda: current,
    )
    second = RuntimeInstanceGuard(
        second_connection, asyncio.Lock(), lease_seconds=3, heartbeat_seconds=1,
        owner_token="second", clock=lambda: current,
    )
    try:
        await first.acquire()
        current += timedelta(seconds=4)
        await second.acquire()
        with pytest.raises(RuntimeInstanceLeaseLostError):
            await first.renew_once()
    finally:
        await first.release()
        await second.release()
        await first_connection.close()
        await second_connection.close()


@pytest.mark.asyncio
async def test_heartbeat_stops_runtime_when_lease_authority_is_lost(tmp_path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    guard = RuntimeInstanceGuard(
        connection,
        asyncio.Lock(),
        lease_seconds=0.1,
        heartbeat_seconds=0.02,
        owner_token="owner",
    )
    stopped = asyncio.Event()
    try:
        await guard.acquire()
        await connection.execute(
            "UPDATE runtime_instance_leases SET owner_token='replacement' WHERE singleton=1"
        )
        await connection.commit()
        guard.start_heartbeat(stopped.set)
        await asyncio.wait_for(stopped.wait(), timeout=1)
        with pytest.raises(RuntimeInstanceLeaseLostError):
            await guard.renew_once()
    finally:
        await guard.release()
        await connection.close()


@pytest.mark.asyncio
async def test_lease_loss_callback_failure_does_not_break_release(tmp_path):
    connection = await connect_database(tmp_path / "product.db")
    await run_migrations(connection)
    guard = RuntimeInstanceGuard(
        connection,
        asyncio.Lock(),
        lease_seconds=0.1,
        heartbeat_seconds=0.02,
        owner_token="owner",
    )
    callback_called = asyncio.Event()

    async def fail_after_revocation():
        callback_called.set()
        raise RuntimeError("best-effort shutdown failed")

    try:
        await guard.acquire()
        await connection.execute(
            "UPDATE runtime_instance_leases SET owner_token='replacement' WHERE singleton=1"
        )
        await connection.commit()
        guard.start_heartbeat(fail_after_revocation)
        await asyncio.wait_for(callback_called.wait(), timeout=1)
        await asyncio.sleep(0)
        await guard.release()
    finally:
        await guard.release()
        await connection.close()


def test_second_application_cannot_start_coordinator_on_same_product_database(tmp_path):
    first_app = FastAPI(lifespan=lifespan)
    second_app = FastAPI(lifespan=lifespan)
    for index, application in enumerate((first_app, second_app), start=1):
        application.state.execution_enabled = False
        application.state.product_database_path = tmp_path / "shared-product.db"
        application.state.checkpoint_database_path = tmp_path / f"checkpoint-{index}.db"
        application.state.legacy_snapshot_root = tmp_path / f"legacy-{index}"

    with TestClient(first_app):
        with pytest.raises(RuntimeInstanceConflictError):
            with TestClient(second_app):
                pass
