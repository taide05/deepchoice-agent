"""Durable task-event replay helpers used by the HTTP SSE adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel

from deepchoice.persistence.records import TaskEventCursor, TaskEventRecord, TaskWithRun
from deepchoice.runtime.lifecycle import TaskStatus


class TaskEventReader(Protocol):
    async def list_task_events(
        self, task_id: str, *, after_event_id: int = 0, limit: int = 100
    ) -> tuple[TaskEventRecord, ...]: ...

    async def get_task_event_cursor(
        self, task_id: str, *, cursor: int
    ) -> TaskEventCursor: ...

    async def get_task(self, task_id: str) -> TaskWithRun | None: ...


SnapshotLoader = Callable[[str], Awaitable[BaseModel | dict[str, Any]]]

_TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.COMPLETED_WITH_WARNINGS,
    TaskStatus.FAILED,
    TaskStatus.TIMED_OUT,
    TaskStatus.CANCELLED,
    TaskStatus.INTERRUPTED,
}


def parse_last_event_id(value: str | None) -> int:
    """Parse the SSE header without accepting signs, whitespace, or overflow."""

    if value is None or value == "":
        return 0
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise ValueError("Last-Event-ID must be a non-negative integer")
    parsed = int(value)
    if parsed > 9_223_372_036_854_775_807:
        raise ValueError("Last-Event-ID is outside the supported range")
    return parsed


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported SSE JSON value: {type(value).__name__}")


def format_sse_event(
    *, event: str, data: dict[str, Any], event_id: int | None = None
) -> str:
    """Encode one event using the stable single-line JSON SSE representation."""

    if not event or "\n" in event or "\r" in event:
        raise ValueError("event must be a non-empty single-line value")
    if event_id is not None and (type(event_id) is not int or event_id < 0):
        raise ValueError("event_id must be a non-negative integer")
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(
        "data: "
        + json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=_json_default,
        )
    )
    return "\n".join(lines) + "\n\n"


async def iter_task_event_sse(
    repository: TaskEventReader,
    task_id: str,
    *,
    last_event_id: int,
    snapshot_loader: SnapshotLoader,
    batch_size: int = 100,
    poll_interval: float = 0.25,
) -> AsyncIterator[str]:
    """Replay durable events, resync invalid cursors, and close at terminal catch-up."""

    if type(last_event_id) is not int or last_event_id < 0:
        raise ValueError("last_event_id must be a non-negative integer")
    if type(batch_size) is not int or not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if poll_interval < 0:
        raise ValueError("poll_interval must be non-negative")

    cursor = last_event_id
    bounds = await repository.get_task_event_cursor(task_id, cursor=cursor)
    if not bounds.cursor_valid:
        snapshot = await snapshot_loader(task_id)
        cursor = bounds.latest_event_id or 0
        yield format_sse_event(
            event="resync_required",
            event_id=cursor if cursor else None,
            data={"snapshot": snapshot, "latest_event_id": cursor},
        )

    while True:
        events = await repository.list_task_events(
            task_id, after_event_id=cursor, limit=batch_size
        )
        for record in events:
            cursor = record.event_id
            yield format_sse_event(
                event=record.type,
                event_id=record.event_id,
                data={
                    "seq": record.seq,
                    "run_id": record.run_id,
                    "created_at": record.created_at,
                    **record.public_payload,
                },
            )

        current = await repository.get_task(task_id)
        if current is None:
            return
        bounds = await repository.get_task_event_cursor(task_id, cursor=cursor)
        if (
            current.task.status in _TERMINAL_TASK_STATUSES
            and cursor >= (bounds.latest_event_id or 0)
        ):
            return
        if events and len(events) == batch_size:
            continue
        await asyncio.sleep(poll_interval)


__all__ = [
    "TaskEventReader",
    "format_sse_event",
    "iter_task_event_sse",
    "parse_last_event_id",
]
