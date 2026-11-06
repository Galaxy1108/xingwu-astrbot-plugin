"""In-memory repository: identical behaviour to SqlCipherRepository.

Used by contract tests (handoff §4.5.10) and by future unit tests of the
service layer, so the orchestration code never needs a real SQLCipher file.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Memory, MemoryDraft, RecallHit, normalize_content


class InMemoryRepository:
    def __init__(self) -> None:
        self._items: dict[int, Memory] = {}
        self._next_id = 1

    def _copy(self, memory: Memory) -> Memory:
        return Memory(
            id=memory.id,
            content=memory.content,
            kind=memory.kind,
            reasoning=memory.reasoning,
            importance=memory.importance,
            pinned=memory.pinned,
            tags=list(memory.tags),
            metadata=dict(memory.metadata),
            source_conversation_id=memory.source_conversation_id,
            source_message_id=memory.source_message_id,
            embedding=memory.embedding,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            last_recalled_at=memory.last_recalled_at,
            recall_count=memory.recall_count,
            deleted_at=memory.deleted_at,
        )

    def add(self, draft: MemoryDraft, *, now: int) -> int:
        memory_id = self._next_id
        self._next_id += 1
        self._items[memory_id] = Memory(
            id=memory_id,
            content=draft.content,
            kind=draft.kind,
            reasoning=draft.reasoning,
            importance=max(1, min(5, int(draft.importance))),
            pinned=bool(draft.pinned),
            tags=sorted({t.strip() for t in draft.tags if t and t.strip()}),
            metadata=dict(draft.metadata),
            source_conversation_id=draft.source_conversation_id,
            source_message_id=draft.source_message_id,
            created_at=now,
            updated_at=now,
        )
        return memory_id

    def get(self, memory_id: int) -> Memory | None:
        memory = self._items.get(memory_id)
        if memory is None or memory.deleted_at:
            return None
        return self._copy(memory)

    def update(self, memory: Memory, *, now: int) -> None:
        current = self._items.get(memory.id)
        if current is None or current.deleted_at:
            return
        self._items[memory.id] = Memory(
            id=memory.id,
            content=memory.content,
            kind=memory.kind,
            reasoning=memory.reasoning,
            importance=max(1, min(5, int(memory.importance))),
            pinned=bool(memory.pinned),
            tags=sorted({t.strip() for t in memory.tags if t and t.strip()}),
            metadata=dict(memory.metadata),
            source_conversation_id=memory.source_conversation_id,
            source_message_id=memory.source_message_id,
            embedding=memory.embedding,
            created_at=current.created_at,
            updated_at=now,
            last_recalled_at=current.last_recalled_at,
            recall_count=current.recall_count,
            deleted_at=0,
        )

    def soft_delete(self, memory_id: int, *, now: int) -> None:
        memory = self._items.get(memory_id)
        if memory is not None and not memory.deleted_at:
            memory.deleted_at = now
            memory.updated_at = now

    def touch_recalled(self, memory_ids: list[int], *, now: int) -> None:
        for memory_id in memory_ids:
            memory = self._items.get(memory_id)
            if memory is not None and not memory.deleted_at:
                memory.last_recalled_at = now
                memory.recall_count += 1

    def list(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        items = [
            self._copy(memory)
            for memory in self._items.values()
            if not memory.deleted_at
            and (kind is None or memory.kind == kind)
            and (tag is None or tag in memory.tags)
            and (cursor is None or memory.id < cursor)
        ]
        items.sort(key=lambda item: (item.pinned, item.id), reverse=True)
        return items[:limit]

    def search_fts(
        self,
        query: str,
        limit: int,
        *,
        kind: str | None = None,
        since: int | None = None,
    ) -> list[RecallHit]:
        terms = [term for term in re.split(r"\s+", (query or "").strip()) if term]
        if not terms:
            return []
        hits: list[RecallHit] = []
        for memory in self._items.values():
            if memory.deleted_at or (kind and memory.kind != kind):
                continue
            if since and memory.created_at < since:
                continue
            haystack = " ".join(
                [memory.content, memory.reasoning, " ".join(memory.tags)]
            ).lower()
            matched = sum(1 for term in terms if term.lower() in haystack)
            if matched:
                hits.append(
                    RecallHit(
                        memory=self._copy(memory),
                        score=float(matched),
                        source="memory",
                    )
                )
        hits.sort(key=lambda hit: (hit.score, hit.memory.id), reverse=True)
        return hits[:limit]

    def count(self, *, kind: str | None = None, tag: str | None = None) -> int:
        return sum(
            1
            for memory in self._items.values()
            if not memory.deleted_at
            and (kind is None or memory.kind == kind)
            and (tag is None or tag in memory.tags)
        )

    def find_duplicate(self, content: str, *, since: int) -> Memory | None:
        key = normalize_content(content)
        for memory in self._items.values():
            if memory.deleted_at or memory.created_at < since:
                continue
            if memory.normalized() == key:
                return self._copy(memory)
        return None

    # -- test helpers ---------------------------------------------------
    def raw_items(self) -> dict[int, Memory]:
        return self._items

    def seed(self, memory: Memory) -> Memory:
        self._items[memory.id] = memory
        self._next_id = max(self._next_id, memory.id + 1)
        return memory
