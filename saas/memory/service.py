"""MemoryService: orchestration only (validate → dedupe → write → index → event)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..clock import Clock, SystemClock
from .models import (
    KIND_LABELS,
    MAX_CONTENT_LENGTH,
    Memory,
    MemoryDraft,
    RecallContext,
    Turn,
    estimate_tokens,
    normalize_content,
)
from .ports import EventBus, Extractor, MemoryRepository, Retriever
from .retrieval.fts import FtsRetriever
from .retrieval.rules import RulesReranker

logger = logging.getLogger(__name__)


class MemoryValidationError(ValueError):
    """Invalid memory input (mapped to HTTP 400 by the API layer)."""


class LoggingEventBus:
    def publish(self, event: str, payload: dict[str, Any]) -> None:
        logger.info("memory event %s: %s", event, payload)


def default_retrievers(repository: MemoryRepository, *, top_k: int) -> list[Retriever]:
    return [FtsRetriever(repository), RulesReranker(top_k=top_k)]


class MemoryService:
    def __init__(
        self,
        store,
        *,
        clock: Clock | None = None,
        retriever_factory: Callable[[MemoryRepository], list[Retriever]] | None = None,
        extractor: Extractor | None = None,
        events: EventBus | None = None,
        dedupe_window_seconds: int = 86400,
        default_top_k: int = 5,
        token_budget: int = 800,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self._retriever_factory = retriever_factory
        self.extractor = extractor
        self.events = events
        self.dedupe_window_seconds = dedupe_window_seconds
        self.default_top_k = default_top_k
        self.token_budget = token_budget

    # -- helpers -------------------------------------------------------
    def _repo(self, bot_id: str) -> MemoryRepository:
        return self.store.open(bot_id)

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.events is not None:
            try:
                self.events.publish(event, payload)
            except Exception:  # noqa: BLE001
                logger.warning("memory event publish failed: %s", event, exc_info=True)

    def _retrievers(self, repo: MemoryRepository, top_k: int) -> list[Retriever]:
        if self._retriever_factory is not None:
            return self._retriever_factory(repo)
        return default_retrievers(repo, top_k=top_k)

    # -- write ---------------------------------------------------------
    def remember(self, bot_id: str, draft: MemoryDraft) -> dict[str, Any]:
        content = (draft.content or "").strip()
        if not content:
            raise MemoryValidationError("记忆内容不能为空")
        if len(content) > MAX_CONTENT_LENGTH:
            raise MemoryValidationError(f"记忆内容不能超过 {MAX_CONTENT_LENGTH} 字符")
        kind = draft.kind if draft.kind in KIND_LABELS else "fact"
        importance = max(1, min(5, int(draft.importance or 3)))
        now = self.clock.now()
        repo = self._repo(bot_id)
        duplicate = None
        finder = getattr(repo, "find_duplicate", None)
        if callable(finder):
            duplicate = finder(content, since=now - self.dedupe_window_seconds)
        elif hasattr(repo, "list"):
            key = normalize_content(content)
            for memory in repo.list(limit=200):
                if memory.normalized() == key and (
                    now - memory.created_at <= self.dedupe_window_seconds
                ):
                    duplicate = memory
                    break
        if duplicate is not None:
            return {"memory": duplicate.to_dict(), "created": False, "duplicate": True}
        memory_id = repo.add(
            MemoryDraft(
                content=content,
                kind=kind,
                reasoning=(draft.reasoning or "").strip(),
                importance=importance,
                pinned=bool(draft.pinned),
                tags=[tag.strip()[:64] for tag in (draft.tags or []) if tag.strip()],
                metadata=dict(draft.metadata or {}),
                source_conversation_id=draft.source_conversation_id,
                source_message_id=draft.source_message_id,
            ),
            now=now,
        )
        memory = repo.get(memory_id)
        if memory is None:  # pragma: no cover - defensive
            raise MemoryValidationError("写入记忆失败")
        self._emit(
            "memory.created",
            {"bot_id": bot_id, "memory_id": memory_id, "kind": kind},
        )
        return {"memory": memory.to_dict(), "created": True, "duplicate": False}

    async def extract_and_remember(
        self, bot_id: str, turns: list[Turn], *, max_items: int = 3
    ) -> list[dict[str, Any]]:
        if self.extractor is None or not turns:
            return []
        drafts = await self.extractor.extract(turns, max_items=max_items)
        results = []
        for draft in drafts[:max_items]:
            try:
                results.append(self.remember(bot_id, draft))
            except MemoryValidationError:
                continue
        return results

    # -- read ----------------------------------------------------------
    async def recall(
        self,
        bot_id: str,
        query: str,
        *,
        top_k: int | None = None,
        kind: str | None = None,
        token_budget: int | None = None,
    ) -> list[Memory]:
        repo = self._repo(bot_id)
        limit = int(top_k or self.default_top_k)
        ctx = RecallContext(
            bot_id=bot_id,
            query=(query or "").strip(),
            top_k=limit,
            kind=kind,
            now=self.clock.now(),
            token_budget=int(token_budget or self.token_budget),
        )
        memories: list[Memory] = []
        for retriever in self._retrievers(repo, limit):
            result = await retriever.retrieve(ctx)
            if result:
                memories = result
        # Token-budget trim keeps prompt injection bounded.
        selected: list[Memory] = []
        used = 0
        for memory in memories:
            cost = estimate_tokens(memory.content) + 2
            if selected and used + cost > ctx.token_budget:
                break
            selected.append(memory)
            used += cost
        if selected:
            repo.touch_recalled([m.id for m in selected], now=ctx.now)
            self._emit(
                "memory.recalled",
                {"bot_id": bot_id, "query": ctx.query, "ids": [m.id for m in selected]},
            )
        return selected

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
        repo = self._repo(bot_id)
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        if q and q.strip():
            hits = repo.search_fts(q.strip(), 200, kind=kind)
            memories = [hit.memory for hit in hits]
            total = len(memories)
            start = (page - 1) * page_size
            memories = memories[start : start + page_size]
        else:
            memories = repo.list(kind=kind, tag=tag, limit=page_size * page)
            total = repo.count(kind=kind, tag=tag)
            memories = memories[(page - 1) * page_size :]
        return {
            "items": [memory.to_dict() for memory in memories],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get(self, bot_id: str, memory_id: int) -> Memory | None:
        return self._repo(bot_id).get(int(memory_id))

    def update(self, bot_id: str, memory_id: int, patch: dict[str, Any]) -> Memory:
        repo = self._repo(bot_id)
        memory = repo.get(int(memory_id))
        if memory is None:
            raise MemoryValidationError("记忆不存在")
        if "content" in patch:
            content = str(patch["content"] or "").strip()
            if not content or len(content) > MAX_CONTENT_LENGTH:
                raise MemoryValidationError("记忆内容长度不合法")
            memory.content = content
        if "kind" in patch:
            if patch["kind"] not in KIND_LABELS:
                raise MemoryValidationError("未知的记忆类型")
            memory.kind = str(patch["kind"])
        if "reasoning" in patch:
            memory.reasoning = str(patch["reasoning"] or "")
        if "importance" in patch:
            memory.importance = max(1, min(5, int(patch["importance"])))
        if "pinned" in patch:
            memory.pinned = bool(patch["pinned"])
        if "tags" in patch:
            tags = patch["tags"]
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                raise MemoryValidationError("tags 必须是字符串数组")
            memory.tags = [t.strip()[:64] for t in tags if t.strip()]
        if "metadata" in patch:
            if not isinstance(patch["metadata"], dict):
                raise MemoryValidationError("metadata 必须是对象")
            memory.metadata = patch["metadata"]
        repo.update(memory, now=self.clock.now())
        updated = repo.get(int(memory_id))
        if updated is None:  # pragma: no cover
            raise MemoryValidationError("记忆不存在")
        self._emit("memory.updated", {"bot_id": bot_id, "memory_id": memory_id})
        return updated

    def delete(self, bot_id: str, memory_id: int) -> None:
        repo = self._repo(bot_id)
        if repo.get(int(memory_id)) is None:
            raise MemoryValidationError("记忆不存在")
        repo.soft_delete(int(memory_id), now=self.clock.now())
        self._emit("memory.deleted", {"bot_id": bot_id, "memory_id": memory_id})

    def export(self, bot_id: str) -> dict[str, Any]:
        repo = self._repo(bot_id)
        memories = repo.list(limit=100_000)
        return {
            "bot_id": bot_id,
            "exported_at": self.clock.now(),
            "count": len(memories),
            "items": [memory.to_dict() for memory in memories],
        }

    def stats(self, bot_id: str) -> dict[str, Any]:
        repo = self._repo(bot_id)
        return {"total": repo.count()}

    # -- prompt formatting ---------------------------------------------
    @staticmethod
    def format_for_prompt(memories: list[Memory], *, limit: int | None = None) -> str:
        rows = memories[: limit or len(memories)]
        if not rows:
            return ""
        lines = ["[记忆]"]
        for memory in rows:
            date = datetime.fromtimestamp(memory.created_at).strftime("%Y-%m-%d")
            label = KIND_LABELS.get(memory.kind, memory.kind)
            lines.append(f"- ({label}) {memory.content} ({date})")
        return "\n".join(lines)

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
