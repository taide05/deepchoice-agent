"""Persistent per-authorization admission ledger for paid batch collection.

The ledger is deliberately independent of a batch output directory, temporary
product database, or experiment ID. It is a small SQLite file and uses the
existing batch/collector path; it is not a scheduler or a second run store.

Rules
- One immutable authorization_id owns one cap.
- A reservation is written before the product POST and is never silently
  released because a response was lost.
- A later process with a different owner sees an unresolved reservation and
  must reconcile it with the product task before sending anything new.
- New directories, experiment IDs, and restarts do not reset the count when the
  same ledger file is reused. A different ledger path is a different explicit
  authorization file, not a reset mechanism.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import uuid


class AuthorizationError(Exception):
    """Base class for admission failures."""


class AuthorizationExceeded(AuthorizationError):
    """The authorization has no unused execution slot."""


class AuthorizationUnsettled(AuthorizationError):
    """A prior submission is unknown and must be reconciled first."""


class AuthorizationDuplicate(AuthorizationError):
    """This case already has a reservation under this authorization."""


_TERMINAL = {
    "settled", "failed", "reconciled", "cancelled",
    "completed", "completed_with_warnings", "timed_out",
}
TERMINAL_OUTCOMES = frozenset(_TERMINAL)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BatchAuthorizationLedger:
    """A bounded, monotonic execution counter shared across restarts."""

    def __init__(
        self,
        path: str | Path,
        *,
        authorization_id: str,
        cap: int,
        prior_used: int = 0,
        owner_token: str | None = None,
    ) -> None:
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            raise ValueError("authorization_id must be a non-empty string")
        if type(cap) is not int or cap < 0:
            raise ValueError("cap must be a non-negative integer")
        if type(prior_used) is not int or prior_used < 0:
            raise ValueError("prior_used must be a non-negative integer")
        self.path = Path(path)
        self.authorization_id = authorization_id.strip()
        self.cap = cap
        self.prior_used = prior_used
        self.owner_token = owner_token or uuid.uuid4().hex
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connect().close()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, timeout=10.0, isolation_level=None,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS authorization (
                    authorization_id TEXT PRIMARY KEY,
                    cap INTEGER NOT NULL,
                    prior_used INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    token TEXT PRIMARY KEY,
                    authorization_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    owner_token TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_id TEXT,
                    sequence INTEGER NOT NULL,
                    reserved_at TEXT NOT NULL,
                    settled_at TEXT,
                    UNIQUE (authorization_id, case_id)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT cap, prior_used FROM authorization WHERE authorization_id = ?",
                    (self.authorization_id,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO authorization "
                        "(authorization_id, cap, prior_used, created_at) VALUES (?, ?, ?, ?)",
                        (self.authorization_id, self.cap, self.prior_used, _now()),
                    )
                elif row != (self.cap, self.prior_used):
                    raise AuthorizationError(
                        "authorization ledger identity changed: "
                        f"cap/prior_used={(row[0], row[1])}, requested={(self.cap, self.prior_used)}"
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def reserve(self, case_id: str, experiment_id: str) -> str:
        """Atomically reserve one slot before product dispatch."""
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id must be a non-empty string")
        if not isinstance(experiment_id, str) or not experiment_id:
            raise ValueError("experiment_id must be a non-empty string")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unresolved = connection.execute(
                "SELECT case_id, status FROM reservations "
                "WHERE authorization_id = ? AND status NOT IN "
                "('settled', 'failed', 'reconciled', 'cancelled', "
                "'completed', 'completed_with_warnings', 'timed_out') "
                "AND owner_token != ? ORDER BY sequence LIMIT 1",
                (self.authorization_id, self.owner_token),
            ).fetchone()
            if unresolved is not None:
                raise AuthorizationUnsettled(
                    "prior submission is unresolved and requires reconciliation: "
                    f"{unresolved[0]} ({unresolved[1]})"
                )
            duplicate = connection.execute(
                "SELECT status FROM reservations WHERE authorization_id = ? AND case_id = ?",
                (self.authorization_id, case_id),
            ).fetchone()
            if duplicate is not None:
                if duplicate[0] not in _TERMINAL:
                    raise AuthorizationUnsettled(
                        f"case already has an unresolved reservation: {case_id}"
                    )
                raise AuthorizationDuplicate(
                    f"case already consumed an execution under this authorization: {case_id}"
                )
            used = connection.execute(
                "SELECT ? + COUNT(*) FROM reservations WHERE authorization_id = ?",
                (self.prior_used, self.authorization_id),
            ).fetchone()[0]
            if used >= self.cap:
                raise AuthorizationExceeded(
                    f"authorization {self.authorization_id} has no execution slot "
                    f"({used}/{self.cap})"
                )
            token = uuid.uuid4().hex
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM reservations "
                "WHERE authorization_id = ?",
                (self.authorization_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO reservations "
                "(token, authorization_id, case_id, experiment_id, owner_token, "
                "status, task_id, sequence, reserved_at) "
                "VALUES (?, ?, ?, ?, ?, 'reserved', NULL, ?, ?)",
                (token, self.authorization_id, case_id, experiment_id,
                 self.owner_token, sequence, _now()),
            )
            connection.execute("COMMIT")
            return token
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def mark_submitted(self, token: str, task_id: str) -> None:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be a non-empty string")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE reservations SET status = 'submitted', task_id = ? "
                    "WHERE token = ? AND authorization_id = ? AND status = 'reserved'",
                    (task_id, token, self.authorization_id),
                )
                if cursor.rowcount != 1:
                    raise AuthorizationError("reservation is not in a reservable state")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def settle(self, token: str, outcome: str) -> None:
        """Record a terminal observed outcome; never release the consumed slot."""
        if outcome not in TERMINAL_OUTCOMES:
            raise ValueError("outcome must be a recognized terminal outcome")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE reservations SET status = ?, settled_at = ? "
                    "WHERE token = ? AND authorization_id = ? "
                    "AND status IN ('reserved', 'submitted')",
                    (outcome, _now(), token, self.authorization_id),
                )
                if cursor.rowcount != 1:
                    raise AuthorizationError("reservation is not unsettled")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def reconcile(self, token: str, *, outcome: str, task_id: str | None = None) -> None:
        """Explicitly reconcile an unknown submission after checking the product task.

        This does not permit a new reservation by itself; the consumed slot stays
        counted. It only replaces the unknown state with an observed outcome.
        """
        if outcome not in TERMINAL_OUTCOMES:
            raise ValueError("outcome must be a recognized terminal outcome")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE reservations SET status = ?, task_id = COALESCE(?, task_id), "
                    "settled_at = ? WHERE token = ? AND authorization_id = ? "
                    "AND status IN ('reserved', 'submitted')",
                    (outcome, task_id, _now(), token, self.authorization_id),
                )
                if cursor.rowcount != 1:
                    raise AuthorizationError("unknown reservation")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def reservation(self, token: str) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT token, case_id, experiment_id, status, task_id "
                "FROM reservations WHERE token = ? AND authorization_id = ?",
                (token, self.authorization_id),
            ).fetchone()
        if row is None:
            raise AuthorizationError("unknown reservation")
        return {"token": row[0], "case_id": row[1], "experiment_id": row[2],
                "status": row[3], "task_id": row[4]}

    def unresolved(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT token, case_id, experiment_id, owner_token, status, task_id "
                "FROM reservations WHERE authorization_id = ? AND status NOT IN "
                "('settled', 'failed', 'reconciled', 'cancelled', "
                "'completed', 'completed_with_warnings', 'timed_out') ORDER BY sequence",
                (self.authorization_id,),
            ).fetchall()
        return [
            {"token": row[0], "case_id": row[1], "experiment_id": row[2],
             "owner_token": row[3], "status": row[4], "task_id": row[5]}
            for row in rows
        ]

    def status(self) -> dict:
        with self._connection() as connection:
            used = connection.execute(
                "SELECT COUNT(*) FROM reservations WHERE authorization_id = ?",
                (self.authorization_id,),
            ).fetchone()[0]
            active = connection.execute(
                "SELECT COUNT(*) FROM reservations WHERE authorization_id = ? "
                "AND status NOT IN ('settled', 'failed', 'reconciled', 'cancelled', "
                "'completed', 'completed_with_warnings', 'timed_out')",
                (self.authorization_id,),
            ).fetchone()[0]
            by_status = dict(connection.execute(
                "SELECT status, COUNT(*) FROM reservations WHERE authorization_id = ? "
                "GROUP BY status ORDER BY status",
                (self.authorization_id,),
            ).fetchall())
        return {
            "authorization_id": self.authorization_id,
            "cap": self.cap,
            "prior_used": self.prior_used,
            "reserved": active,
            "total_reservations": used,
            "used": self.prior_used + used,
            "remaining": max(0, self.cap - self.prior_used - used),
            "by_status": by_status,
        }
