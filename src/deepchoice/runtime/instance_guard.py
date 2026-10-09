"""Single-instance guard for the SQLite-backed runtime."""

from __future__ import annotations

import asyncio
import inspect
import os
import shlex
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite

from deepchoice.persistence.database import _await_cleanup, _begin_transaction, _is_locked_error


class RuntimeConfigurationError(RuntimeError):
    code = "RUNTIME_SINGLE_WORKER_REQUIRED"


class RuntimeInstanceConflictError(RuntimeError):
    code = "RUNTIME_INSTANCE_CONFLICT"


class RuntimeInstanceLeaseLostError(RuntimeError):
    code = "RUNTIME_INSTANCE_LEASE_LOST"


def _configured_workers(arguments: str) -> str | None:
    try:
        tokens = shlex.split(arguments)
    except ValueError as exc:
        raise RuntimeConfigurationError("worker arguments are invalid") from exc
    for index, token in enumerate(tokens):
        if token in {"--workers", "-w"}:
            return tokens[index + 1] if index + 1 < len(tokens) else ""
        if token.startswith("--workers="):
            return token.partition("=")[2]
    return None


def validate_single_worker_configuration(
    environ: Mapping[str, str] | None = None,
) -> None:
    """Reject known multi-worker settings before the coordinator starts."""

    values = os.environ if environ is None else environ
    configured: list[tuple[str, str]] = []
    for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        if name in values:
            configured.append((name, values[name].strip()))
    for name in ("UVICORN_CMD_ARGS", "GUNICORN_CMD_ARGS"):
        if values.get(name):
            workers = _configured_workers(values[name])
            if workers is not None:
                configured.append((name, workers.strip()))
    for name, value in configured:
        try:
            count = int(value)
        except ValueError as exc:
            raise RuntimeConfigurationError(f"{name} must configure exactly one worker") from exc
        if count != 1:
            raise RuntimeConfigurationError(f"{name} must configure exactly one worker")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class RuntimeInstanceGuard:
    """Acquire and renew the singleton row in ``runtime_instance_leases``."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock,
        *,
        lease_seconds: float = 30.0,
        heartbeat_seconds: float = 10.0,
        owner_token: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and shorter than lease_seconds")
        self._connection = connection
        self._lock = lock
        self._lease_seconds = float(lease_seconds)
        self._heartbeat_seconds = float(heartbeat_seconds)
        self.owner_token = owner_token or str(uuid.uuid4())
        self._clock = clock
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._acquired = False
        self._expires_at: datetime | None = None
        self._monotonic_expiry: float | None = None
        self._last_success: float | None = None
        self._renewal_ms: int | None = None
        self._max_renewal_ms: int | None = None
        self._max_heartbeat_gap_ms: int | None = None
        self._renewals = 0

    @property
    def has_authority(self) -> bool:
        valid = (
            self._acquired and self._expires_at is not None
            and self._monotonic_expiry is not None
            and _utc(self._clock()) < self._expires_at
            and time.monotonic() < self._monotonic_expiry
        )
        if not valid:
            self._acquired = False
        return valid

    def observations(self) -> dict:
        now = time.monotonic()
        return {
            "authority_valid": self.has_authority,
            "heartbeat_success_age_ms": (
                max(0, round((now - self._last_success) * 1000))
                if self._last_success is not None else None
            ),
            "lease_remaining_ms": (
                max(0, min(round((self._monotonic_expiry - now) * 1000),
                           round((self._expires_at - _utc(self._clock())).total_seconds() * 1000)))
                if self._expires_at is not None and self._monotonic_expiry is not None else None
            ),
            "renewal_ms": self._renewal_ms,
            "max_renewal_ms": self._max_renewal_ms,
            "max_heartbeat_gap_ms": self._max_heartbeat_gap_ms,
            "renewals": self._renewals,
        }

    def _accepted(self, expiry: datetime, sampled: float) -> None:
        if self._last_success is not None:
            gap = max(0, round((sampled - self._last_success) * 1000))
            self._max_heartbeat_gap_ms = max(self._max_heartbeat_gap_ms or 0, gap)
        self._expires_at = expiry
        self._monotonic_expiry = sampled + self._lease_seconds
        self._last_success = sampled

    def _now_and_expiry(self) -> tuple[datetime, datetime]:
        now = _utc(self._clock())
        return now, now + timedelta(seconds=self._lease_seconds)

    async def acquire(self) -> None:
        async with self._lock:
            await _begin_transaction(self._connection)
            try:
                now, expiry = self._now_and_expiry()
                sampled = time.monotonic()
                cursor = await self._connection.execute(
                    """
                    INSERT INTO runtime_instance_leases(
                        singleton, owner_token, pid, hostname, started_at, lease_expires_at
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        owner_token=excluded.owner_token,
                        pid=excluded.pid,
                        hostname=excluded.hostname,
                        started_at=excluded.started_at,
                        lease_expires_at=excluded.lease_expires_at
                    WHERE runtime_instance_leases.lease_expires_at <= excluded.started_at
                    """,
                    (
                        self.owner_token,
                        os.getpid(),
                        socket.gethostname(),
                        now.isoformat(),
                        expiry.isoformat(),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeInstanceConflictError(
                        "another DeepChoice runtime instance holds the product database lease"
                    )
                await self._connection.commit()
                self._acquired = True
                self._accepted(expiry, sampled)
            except BaseException:
                await _await_cleanup(self._connection.rollback())
                raise

    async def renew_once(self) -> None:
        if not self.has_authority:
            raise RuntimeInstanceLeaseLostError("runtime instance lease is not held")
        started = time.monotonic()
        async with self._lock:
            try:
                # A failed writer admission has not changed the lease. Retry
                # one transient contention error while no transaction began;
                # UPDATE/commit failures and cancellation are never retried.
                for attempt in range(2):
                    try:
                        await _begin_transaction(self._connection)
                        break
                    except Exception as exc:
                        if attempt or not _is_locked_error(exc) or self._connection.in_transaction:
                            raise
                        await asyncio.sleep(0)
                # Sampling must follow BOTH the shared lock and SQLite writer wait.
                now, expiry = self._now_and_expiry()
                sampled = time.monotonic()
                if not self.has_authority:
                    raise RuntimeInstanceLeaseLostError("runtime instance lease expired")
                cursor = await self._connection.execute(
                    """
                    UPDATE runtime_instance_leases
                    SET lease_expires_at = ?
                    WHERE singleton = 1 AND owner_token = ? AND lease_expires_at > ?
                    """,
                    (expiry.isoformat(), self.owner_token, now.isoformat()),
                )
                if cursor.rowcount != 1:
                    raise RuntimeInstanceLeaseLostError("runtime instance lease was lost")
                await self._connection.commit()
                self._accepted(expiry, sampled)
                self._renewals += 1
                self._renewal_ms = max(0, round((time.monotonic() - started) * 1000))
                self._max_renewal_ms = max(self._max_renewal_ms or 0, self._renewal_ms)
            except BaseException:
                self._acquired = False
                await _await_cleanup(self._connection.rollback())
                raise

    async def _heartbeat(
        self,
        on_lease_lost: Callable[[], Awaitable[Any] | Any],
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_seconds)
                try:
                    await self.renew_once()
                except Exception:
                    # Any failed renewal means this process can no longer prove
                    # exclusive authority. Stop execution before the lease can
                    # be acquired elsewhere; health will report the loss.
                    self._acquired = False
                    try:
                        result = on_lease_lost()
                        if inspect.isawaitable(result):
                            await result
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # The callback is advisory cleanup after authority has
                        # already been revoked. Health remains fail-closed.
                        pass
                    return
        except asyncio.CancelledError:
            raise

    def start_heartbeat(
        self,
        on_lease_lost: Callable[[], Awaitable[Any] | Any],
    ) -> None:
        if not self._acquired:
            raise RuntimeInstanceLeaseLostError("acquire the runtime instance lease first")
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat(on_lease_lost),
            name="deepchoice-instance-lease-heartbeat",
        )

    async def release(self) -> None:
        task, self._heartbeat_task = self._heartbeat_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                # Lease-loss callbacks may include best-effort component
                # shutdown. Always let release finish its own cleanup path.
                pass
        # Cancellation may land after SQLite committed a renewal/acquisition
        # but before its await returned. Cleanup is owner-scoped, not dependent
        # on a local success flag; a replacement owner's row is never deleted.
        async with self._lock:
            await self._connection.execute(
                "DELETE FROM runtime_instance_leases WHERE singleton = 1 AND owner_token = ?",
                (self.owner_token,),
            )
            await self._connection.commit()
        self._acquired = False


__all__ = [
    "RuntimeConfigurationError",
    "RuntimeInstanceConflictError",
    "RuntimeInstanceGuard",
    "RuntimeInstanceLeaseLostError",
    "validate_single_worker_configuration",
]
