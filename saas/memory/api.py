"""Public use-case facade of the memory module (handoff §4.5.1 ``api.py``)."""

from __future__ import annotations

from typing import Any

from .models import KIND_LABELS, MemoryDraft, Turn
from .service import MemoryService, MemoryValidationError

__all__ = ["MemoryAPI", "MemoryValidationError", "MemoryDraft", "Turn"]


class MemoryAPI:
    """Thin facade used by HTTP routes and LLM tools; never touches SQL."""

    def __init__(self, service: MemoryService, *, notes_factory=None) -> None:
        self.service = service
        self._notes_factory = notes_factory

    # -- memories ------------------------------------------------------
    def remember(
        self,
        bot_id: str,
        content: str,
        *,
        kind: str | None = None,
        memory_type: str | None = None,
        strength: int | None = None,
        tags: list[str] | None = None,
        importance: int | None = None,
        reasoning: str = "",
        pinned: bool = False,
        metadata: dict[str, Any] | None = None,
        source_conversation_id: str = "",
        source_message_id: str = "",
    ) -> dict[str, Any]:
        return self.service.remember(
            bot_id,
            MemoryDraft(
                content=content,
                kind=kind or memory_type or "knowledge",
                memory_type=memory_type or "",
                strength=50 if strength is None else strength,
                tags=tags or [],
                importance=importance or 3,
                reasoning=reasoning,
                pinned=pinned,
                metadata=metadata or {},
                source_conversation_id=source_conversation_id,
                source_message_id=source_message_id,
            ),
        )

    async def recall(
        self,
        bot_id: str,
        query: str,
        *,
        top_k: int | None = None,
        kind: str | None = None,
        token_budget: int | None = None,
    ) -> list[dict[str, Any]]:
        memories = await self.service.recall(
            bot_id, query, top_k=top_k, kind=kind, token_budget=token_budget
        )
        return [memory.to_dict() for memory in memories]

    def list(
        self,
        bot_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        kind: str | None = None,
        tag: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        return self.service.list(
            bot_id, page=page, page_size=page_size, kind=kind, tag=tag, q=q
        )

    def get(self, bot_id: str, memory_id: int) -> dict[str, Any] | None:
        memory = self.service.get(bot_id, memory_id)
        return memory.to_dict() if memory else None

    def update(self, bot_id: str, memory_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        return self.service.update(bot_id, memory_id, patch).to_dict()

    def delete(self, bot_id: str, memory_id: int) -> None:
        self.service.delete(bot_id, memory_id)

    def export(self, bot_id: str) -> dict[str, Any]:
        return self.service.export(bot_id)

    def stats(self, bot_id: str) -> dict[str, Any]:
        return self.service.stats(bot_id)

    async def extract_and_remember(
        self, bot_id: str, turns: list[Turn], *, max_items: int = 3
    ) -> list[dict[str, Any]]:
        return await self.service.extract_and_remember(bot_id, turns, max_items=max_items)

    # -- notes ---------------------------------------------------------
    def note_service(self, bot_id: str):
        """Lazily open the note library that shares the bot's memory database."""
        if self._notes_factory is not None:
            return self._notes_factory(bot_id)
        from .notes import notes_for_store

        return notes_for_store(
            self.service.store, bot_id, clock=self.service.clock
        )

    def note_create(
        self,
        bot_id: str,
        title: str,
        content: str,
        *,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.note_service(bot_id).create(title, content, tags=tags)

    def note_read(
        self,
        bot_id: str,
        short_id: str,
        *,
        offset: int = 0,
        limit: int = 4000,
    ) -> dict[str, Any]:
        return self.note_service(bot_id).read(short_id, offset=offset, limit=limit)

    def note_list(
        self,
        bot_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        return self.note_service(bot_id).list(
            page=page, page_size=page_size, tag=tag, q=q
        )

    def note_get(self, bot_id: str, short_id: str) -> dict[str, Any]:
        return self.note_service(bot_id).get(short_id)

    def note_update(
        self, bot_id: str, short_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return self.note_service(bot_id).update(short_id, patch)

    def note_delete(self, bot_id: str, short_id: str) -> None:
        self.note_service(bot_id).delete(short_id)

    # -- consolidation / snapshots ------------------------------------
    def consolidate(self, bot_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        from .consolidation import MemoryConsolidator

        consolidator = MemoryConsolidator(
            self.service.store,
            clock=self.service.clock,
            events=self.service.events,
        )
        return consolidator.consolidate_bot(bot_id, dry_run=dry_run)

    def consolidate_bot(self, bot_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        """Alias matching the consolidation module's public function name."""
        return self.consolidate(bot_id, dry_run=dry_run)

    def export_snapshot(self, bot_id: str) -> dict[str, Any]:
        from .export import export_snapshot

        try:
            notes = self.note_service(bot_id)
        except Exception:  # noqa: BLE001 - export must work without notes too
            notes = None
        return export_snapshot(self.service, bot_id, notes=notes)

    def import_snapshot(
        self, bot_id: str, snapshot: dict[str, Any], *, dry_run: bool = False
    ) -> dict[str, Any]:
        from .export import import_snapshot

        try:
            notes = self.note_service(bot_id)
        except Exception:  # noqa: BLE001
            notes = None
        return import_snapshot(
            self.service, bot_id, snapshot, notes=notes, dry_run=dry_run
        )

    # -- prompt formatting ---------------------------------------------
    @staticmethod
    def kinds() -> dict[str, str]:
        return dict(KIND_LABELS)

    @staticmethod
    def format_for_prompt(memories: list[dict[str, Any]]) -> str:
        from .models import Memory

        objects = [
            Memory(
                id=int(item.get("id") or 0),
                content=str(item.get("content") or ""),
                kind=str(item.get("kind") or "fact"),
                created_at=int(item.get("created_at") or 0),
            )
            for item in memories
        ]
        return MemoryService.format_for_prompt(objects)
