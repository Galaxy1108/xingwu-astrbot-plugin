"""Public use-case facade of the memory module (handoff §4.5.1 ``api.py``)."""

from __future__ import annotations

from typing import Any

from .models import KIND_LABELS, MemoryDraft, Turn
from .service import MemoryService, MemoryValidationError

__all__ = ["MemoryAPI", "MemoryValidationError", "MemoryDraft", "Turn"]


class MemoryAPI:
    """Thin facade used by HTTP routes and LLM tools; never touches SQL."""

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    def remember(
        self,
        bot_id: str,
        content: str,
        *,
        kind: str | None = None,
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
                kind=kind or "fact",
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
        top_k: int = 5,
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
