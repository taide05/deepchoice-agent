"""Checkpoint saver adapters that fence and isolate every execution write."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)


class FencedCheckpointSaver(BaseCheckpointSaver[Any]):
    """Expose one logical namespace over epoch-isolated physical storage.

    The product database and checkpoint database cannot share a transaction. A
    stale worker may therefore pass its guard and reach SQLite after ownership
    changes. Epoch-specific physical namespaces make that late write harmless.
    Reads pinned to an accepted checkpoint use its physical namespace, while
    pending writes from that old namespace are intentionally excluded because
    they are not covered by the accepted product checkpoint reference.
    """

    def __init__(
        self,
        delegate: BaseCheckpointSaver[Any] | Any,
        execution_guard: Callable[[], Awaitable[None]],
        *,
        write_namespace: str,
        logical_namespace: str = "",
        read_namespace: str | None = None,
        read_checkpoint_id: str | None = None,
    ) -> None:
        if not callable(execution_guard):
            raise TypeError("execution_guard must be callable")
        if not write_namespace:
            raise ValueError("write_namespace must be non-empty")
        super().__init__(serde=getattr(delegate, "serde", None))
        self._delegate = delegate
        self._execution_guard = execution_guard
        self.logical_namespace = logical_namespace
        self.read_namespace = read_namespace
        self.read_checkpoint_id = read_checkpoint_id
        self.write_namespace = write_namespace
        self._written_checkpoint_ids: set[str] = set()

    @property
    def config_specs(self) -> list:
        return getattr(self._delegate, "config_specs", [])

    def _physical_namespace_for_read(self, config: RunnableConfig) -> str:
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if checkpoint_id in self._written_checkpoint_ids or checkpoint_id is None:
            return self.write_namespace
        if self.read_namespace is not None:
            return self.read_namespace
        return self.write_namespace

    def _physical_config(
        self, config: RunnableConfig, namespace: str
    ) -> RunnableConfig:
        mapped = dict(config)
        configurable = dict(config.get("configurable", {}))
        configurable["checkpoint_ns"] = namespace
        mapped["configurable"] = configurable
        return mapped

    def _logical_config(self, config: RunnableConfig | None) -> RunnableConfig | None:
        if config is None:
            return None
        mapped = dict(config)
        configurable = dict(config.get("configurable", {}))
        configurable["checkpoint_ns"] = self.logical_namespace
        mapped["configurable"] = configurable
        return mapped

    def _logical_tuple(
        self, value: CheckpointTuple | None, *, from_read_namespace: bool
    ) -> CheckpointTuple | None:
        if value is None:
            return None
        return CheckpointTuple(
            config=self._logical_config(value.config),
            checkpoint=value.checkpoint,
            metadata=value.metadata,
            parent_config=self._logical_config(value.parent_config),
            pending_writes=[] if from_read_namespace else value.pending_writes,
        )

    def get(self, config: RunnableConfig) -> Checkpoint | None:
        value = self.get_tuple(config)
        return value.checkpoint if value is not None else None

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        namespace = self._physical_namespace_for_read(config)
        value = self._delegate.get_tuple(self._physical_config(config, namespace))
        return self._logical_tuple(
            value,
            from_read_namespace=(
                self.read_namespace is not None
                and namespace == self.read_namespace
                and namespace != self.write_namespace
            ),
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        namespace = self.write_namespace
        mapped_config = (
            self._physical_config(config, namespace) if config is not None else None
        )
        mapped_before = (
            self._physical_config(before, namespace) if before is not None else None
        )
        for value in self._delegate.list(
            mapped_config, filter=filter, before=mapped_before, limit=limit
        ):
            logical = self._logical_tuple(value, from_read_namespace=False)
            if logical is not None:
                yield logical

    async def aget(self, config: RunnableConfig) -> Checkpoint | None:
        value = await self.aget_tuple(config)
        return value.checkpoint if value is not None else None

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        namespace = self._physical_namespace_for_read(config)
        value = await self._delegate.aget_tuple(
            self._physical_config(config, namespace)
        )
        return self._logical_tuple(
            value,
            from_read_namespace=(
                self.read_namespace is not None
                and namespace == self.read_namespace
                and namespace != self.write_namespace
            ),
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        namespace = self.write_namespace
        mapped_config = (
            self._physical_config(config, namespace) if config is not None else None
        )
        mapped_before = (
            self._physical_config(before, namespace) if before is not None else None
        )
        async for value in self._delegate.alist(
            mapped_config, filter=filter, before=mapped_before, limit=limit
        ):
            logical = self._logical_tuple(value, from_read_namespace=False)
            if logical is not None:
                yield logical

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        await self._execution_guard()
        stored = await self._delegate.aput(
            self._physical_config(config, self.write_namespace),
            checkpoint,
            metadata,
            new_versions,
        )
        checkpoint_id = stored.get("configurable", {}).get("checkpoint_id")
        if isinstance(checkpoint_id, str) and checkpoint_id:
            self._written_checkpoint_ids.add(checkpoint_id)
        logical = self._logical_config(stored)
        if logical is None:  # pragma: no cover
            raise RuntimeError("checkpoint saver returned no configuration")
        return logical

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._execution_guard()
        await self._delegate.aput_writes(
            self._physical_config(config, self.write_namespace),
            writes,
            task_id,
            task_path,
        )

    def get_next_version(self, current: Any | None, channel: None) -> Any:
        return self._delegate.get_next_version(current, channel)

    async def aget_delta_channel_history(
        self, *, config: RunnableConfig, channels: Sequence[str]
    ) -> Any:
        return await super().aget_delta_channel_history(config=config, channels=channels)

    def get_delta_channel_history(
        self, *, config: RunnableConfig, channels: Sequence[str]
    ) -> Any:
        return super().get_delta_channel_history(config=config, channels=channels)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


__all__ = ["FencedCheckpointSaver"]
