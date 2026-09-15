"""Versioned SQLite retrieval cache and run-scoped single-flight coordination."""

from __future__ import annotations

import asyncio
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import aiosqlite

from deepchoice.persistence.database import _await_cleanup
from deepchoice.retrievers.contracts import RetrievalRequest, RetrievalResult


RETRIEVAL_CACHE_POLICY_VERSION = "retrieval-cache-v1"
MAX_CACHE_ENTRY_BYTES = 512 * 1024
_SOURCE_TTLS = {
    "tavily": timedelta(hours=1),
    "community": timedelta(hours=1),
    "official": timedelta(hours=6),
    "github": timedelta(hours=6),
    "chroma": timedelta(hours=6),
    "arxiv": timedelta(hours=24),
}


def parse_retrieval_cache_enabled(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    raise ValueError("RETRIEVAL_CACHE_ENABLED must be a supported boolean value")


def _normalize_strings(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value)
    if isinstance(value, list):
        return [_normalize_strings(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_strings(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_strings(item) for key, item in value.items()}
    return value


def build_retrieval_cache_key(
    *,
    source: str,
    request: RetrievalRequest,
    manifest_id: str,
    policy_version: str = RETRIEVAL_CACHE_POLICY_VERSION,
) -> str:
    """Hash canonical key material without lowering, sorting, or deduplicating inputs."""

    material = {
        "cache_policy_version": unicodedata.normalize("NFKC", policy_version),
        "manifest_id": unicodedata.normalize("NFKC", manifest_id),
        "request": _normalize_strings(request.model_dump(mode="json")),
        "source": unicodedata.normalize("NFKC", source),
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ttl_for_source(source: str) -> timedelta:
    return _SOURCE_TTLS.get(source, timedelta(hours=1))


@dataclass(slots=True)
class _SingleFlightState:
    event: asyncio.Event
    released: asyncio.Event
    invocation: tuple[object, bool] | None = None
    error: Exception | None = None
    retry: bool = False
    published: bool = False


@dataclass(frozen=True, slots=True)
class SingleFlightClaim:
    is_leader: bool
    _state: _SingleFlightState

    @property
    def event(self) -> asyncio.Event:
        return self._state.event

    @property
    def released(self) -> asyncio.Event:
        return self._state.released

    @property
    def invocation(self) -> tuple[object, bool] | None:
        return self._state.invocation

    @property
    def error(self) -> Exception | None:
        return self._state.error

    @property
    def retry(self) -> bool:
        return self._state.retry


class SQLiteRetrievalCache:
    """Fail-open cache storage; budget and Trace remain outside this adapter."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        lock: asyncio.Lock,
        *,
        enabled: bool = True,
        max_entry_bytes: int = MAX_CACHE_ENTRY_BYTES,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        policy_version: str = RETRIEVAL_CACHE_POLICY_VERSION,
    ) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        if type(max_entry_bytes) is not int or max_entry_bytes <= 0:
            raise ValueError("max_entry_bytes must be a positive integer")
        self._connection = connection
        self._lock = lock
        self.enabled = enabled
        self.max_entry_bytes = max_entry_bytes
        self._clock = clock
        self.policy_version = policy_version
        self._flights: dict[tuple[str, str], _SingleFlightState] = {}
        self._flight_lock = asyncio.Lock()

    def make_key(
        self, *, source: str, request: RetrievalRequest, manifest_id: str
    ) -> str:
        return build_retrieval_cache_key(
            source=source,
            request=request,
            manifest_id=manifest_id,
            policy_version=self.policy_version,
        )

    async def get(self, cache_key: str) -> RetrievalResult | None:
        if not self.enabled:
            return None
        cursor: aiosqlite.Cursor | None = None
        try:
            async with self._lock:
                cursor = await self._connection.execute(
                    """
                    SELECT result_json, payload_bytes, expires_at
                    FROM retrieval_cache WHERE cache_key_sha256 = ?
                    """,
                    (cache_key,),
                )
                row = await cursor.fetchone()
                await cursor.close()
                cursor = None
        except asyncio.CancelledError:
            if cursor is not None:
                await _await_cleanup(cursor.close())
            raise
        except Exception:
            if cursor is not None:
                try:
                    await cursor.close()
                except Exception:
                    pass
            return None
        if row is None:
            return None
        try:
            raw = str(row[0])
            declared_size = int(row[1])
            actual_size = len(raw.encode("utf-8"))
            expires_at = datetime.fromisoformat(str(row[2]).replace("Z", "+00:00"))
            now = self._clock()
            if (
                declared_size < 0
                or declared_size > self.max_entry_bytes
                or actual_size > self.max_entry_bytes
                or declared_size != actual_size
                or expires_at.tzinfo is None
                or now.tzinfo is None
                or now.utcoffset() is None
                or expires_at <= now
            ):
                return None
            result = RetrievalResult.model_validate_json(raw)
            return result if result.status == "success" else None
        except Exception:
            return None

    async def put(
        self,
        cache_key: str,
        result: object,
        *,
        source: str,
    ) -> bool:
        if not self.enabled:
            return False
        try:
            validated = RetrievalResult.model_validate(result)
            if validated.status != "success":
                return False
            raw = validated.model_dump_json()
            payload_size = len(raw.encode("utf-8"))
            if payload_size > self.max_entry_bytes:
                return False
            created_at = self._clock()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                return False
            expires_at = created_at + ttl_for_source(source)
            async with self._lock:
                cursor: aiosqlite.Cursor | None = None
                try:
                    timestamp = created_at.astimezone(UTC).isoformat().replace(
                        "+00:00", "Z"
                    )
                    cursor = await self._connection.execute(
                        """
                        DELETE FROM retrieval_cache
                        WHERE cache_key_sha256 IN (
                            SELECT cache_key_sha256 FROM retrieval_cache
                            WHERE expires_at <= ?
                            ORDER BY expires_at, cache_key_sha256
                            LIMIT 100
                        )
                        """,
                        (timestamp,),
                    )
                    await cursor.close()
                    cursor = None
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO retrieval_cache(
                            cache_key_sha256, result_json, payload_bytes,
                            created_at, expires_at
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(cache_key_sha256) DO UPDATE SET
                            result_json = excluded.result_json,
                            payload_bytes = excluded.payload_bytes,
                            created_at = excluded.created_at,
                            expires_at = excluded.expires_at
                        """,
                        (
                            cache_key,
                            raw,
                            payload_size,
                            timestamp,
                            expires_at.astimezone(UTC)
                            .isoformat()
                            .replace("+00:00", "Z"),
                        ),
                    )
                    await cursor.close()
                    cursor = None
                except asyncio.CancelledError:
                    if cursor is not None:
                        await _await_cleanup(cursor.close())
                    raise
                except Exception:
                    if cursor is not None:
                        await _await_cleanup(cursor.close())
                    return False
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    async def claim(self, run_id: str, cache_key: str) -> SingleFlightClaim:
        identity = (run_id, cache_key)
        async with self._flight_lock:
            state = self._flights.get(identity)
            if state is not None:
                return SingleFlightClaim(is_leader=False, _state=state)
            state = _SingleFlightState(
                event=asyncio.Event(),
                released=asyncio.Event(),
            )
            self._flights[identity] = state
            return SingleFlightClaim(is_leader=True, _state=state)

    async def wait(self, claim: SingleFlightClaim) -> None:
        await asyncio.shield(claim.event.wait())

    def publish(
        self,
        claim: SingleFlightClaim,
        *,
        invocation: tuple[object, bool] | None = None,
        error: Exception | None = None,
        retry: bool = False,
    ) -> None:
        """Publish one leader outcome without persisting it as a cache entry."""

        state = claim._state
        if state.published:
            return
        state.invocation = invocation
        state.error = error
        state.retry = retry
        state.published = True
        state.event.set()

    async def complete(
        self, run_id: str, cache_key: str, claim: SingleFlightClaim
    ) -> None:
        if not claim.is_leader:
            return
        identity = (run_id, cache_key)
        async with self._flight_lock:
            if self._flights.get(identity) is claim._state:
                self._flights.pop(identity, None)
            if not claim._state.published:
                claim._state.retry = True
                claim._state.published = True
                claim._state.event.set()
            claim._state.released.set()


__all__ = [
    "MAX_CACHE_ENTRY_BYTES",
    "RETRIEVAL_CACHE_POLICY_VERSION",
    "SQLiteRetrievalCache",
    "SingleFlightClaim",
    "build_retrieval_cache_key",
    "parse_retrieval_cache_enabled",
    "ttl_for_source",
]
