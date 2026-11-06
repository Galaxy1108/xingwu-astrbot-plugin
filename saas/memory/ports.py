"""Ports of the memory module (handoff §4.5.2)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import Memory, MemoryDraft, RecallContext, RecallHit, Turn


@runtime_checkable
class MemoryRepository(Protocol):
    def add(self, draft: MemoryDraft, *, now: int) -> int: ...

    def get(self, memory_id: int) -> Memory | None: ...

    def update(self, memory: Memory, *, now: int) -> None: ...

    def soft_delete(self, memory_id: int, *, now: int) -> None: ...

    def list(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> list[Memory]: ...

    def search_fts(
        self,
        query: str,
        limit: int,
        *,
        kind: str | None = None,
        since: int | None = None,
    ) -> list[RecallHit]: ...

    def count(self, *, kind: str | None = None, tag: str | None = None) -> int: ...

    def touch_recalled(self, memory_ids: list[int], *, now: int) -> None: ...


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, ctx: RecallContext) -> list[Memory]: ...


@runtime_checkable
class Extractor(Protocol):
    async def extract(self, turns: list[Turn], *, max_items: int) -> list[MemoryDraft]: ...


@runtime_checkable
class EventBus(Protocol):
    def publish(self, event: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class MemoryStore(Protocol):
    def open(self, bot_id: str) -> MemoryRepository: ...

    def close(self, bot_id: str) -> None: ...

    def close_all(self) -> None: ...
