"""MemoryService: orchestration only (validate → dedupe → write → index → event).

Retrieval pipeline
------------------
* No platform settings (or embedding/rerank disabled): unchanged legacy path —
  ``FtsRetriever`` → ``RulesReranker``.
* Embedding enabled: query embedding + vector candidates fused with the FTS
  ranking via Reciprocal Rank Fusion (RRF, ``k`` default 60).
* Rerank enabled: the fused (or FTS) candidates are sent to a Cohere/Jina
  compatible reranker.  Any rerank failure logs a warning and falls back to
  ``RulesReranker`` — recall never raises because of an upstream outage.
* Explicit ``retrievers`` (constructor or ``recall(..., retrievers=...)``)
  still drive the legacy sequential pipeline, which keeps existing callers and
  tests working.

Vector maintenance
------------------
``remember`` / ``update`` / ``delete`` keep ``memory_vectors`` in sync when
embedding is configured.  Embedding calls are async; the synchronous write
methods schedule them on the running event loop as best-effort tasks whose
failures are only logged (a write never fails because of an embedding outage).
Tests/graceful shutdown can await :meth:`MemoryService.wait_for_vector_tasks`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..clock import Clock, SystemClock
from .models import (
    KIND_LABELS,
    MAX_CONTENT_LENGTH,
    Memory,
    MemoryDraft,
    RecallContext,
    RecallHit,
    Turn,
    canonical_kind,
    clamp_strength,
    estimate_tokens,
    normalize_content,
)
from .ports import EventBus, Extractor, MemoryRepository, Retriever
from .retrieval.embedding import EmbeddingClient
from .retrieval.fts import FtsRetriever
from .retrieval.rerank import RerankClient
from .retrieval.rules import RulesReranker
from .vector_store import MemoryVectorStore

logger = logging.getLogger(__name__)

MEMORY_SETTINGS_KEY = "memory.retrieval"
MASKED_API_KEY = "••••••••"

DEFAULT_EMBEDDING_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "base_url": "",
    "api_key": "",
    "model": "",
    "dimensions": 1536,
    "timeout_seconds": 20,
    "batch_size": 32,
}

DEFAULT_RERANK_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "base_url": "",
    "api_key": "",
    "model": "",
    "top_n": 10,
    "timeout_seconds": 20,
}

DEFAULT_BEHAVIOR_SETTINGS: dict[str, Any] = {
    "vector_candidate_limit": 50,
    "rerank_candidate_limit": 30,
    "rrf_k": 60,
    "recall_top_k": 5,
    "auto_inject": True,
    "auto_extract": True,
}

# value → (minimum, maximum) for every integer setting.
_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "dimensions": (1, 8192),
    "timeout_seconds": (1, 120),
    "batch_size": (1, 256),
    "top_n": (1, 100),
    "vector_candidate_limit": (1, 1000),
    "rerank_candidate_limit": (1, 1000),
    "rrf_k": (1, 100),
    "recall_top_k": (1, 50),
}


# --------------------------------------------------------------------------
# settings helpers (shared with the admin HTTP route)
# --------------------------------------------------------------------------
def default_memory_settings() -> dict[str, Any]:
    """Fresh copy of the full settings document (plaintext api_key included)."""
    return {
        "embedding": dict(DEFAULT_EMBEDDING_SETTINGS),
        "rerank": dict(DEFAULT_RERANK_SETTINGS),
        "behavior": dict(DEFAULT_BEHAVIOR_SETTINGS),
    }


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
    return default


def _as_int(value: Any, default: int, *, name: str) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    minimum, maximum = _INT_BOUNDS.get(name, (None, None))  # type: ignore[assignment]
    if minimum is not None:
        number = max(int(minimum), number)
    if maximum is not None:
        number = min(int(maximum), number)
    return number


def normalize_memory_settings(raw: Any) -> dict[str, Any]:
    """Deep-merge ``raw`` over defaults and coerce every field.

    Tolerant by design: malformed values fall back to the previous/default
    value instead of raising, so a hand-edited or older settings blob can never
    break recall.  ``api_key`` is kept in plaintext in memory; masking happens
    only at the HTTP boundary (:func:`mask_memory_settings`).
    """
    result = default_memory_settings()
    if not isinstance(raw, dict):
        return result
    for section in ("embedding", "rerank", "behavior"):
        incoming = raw.get(section)
        if not isinstance(incoming, dict):
            continue
        target = result[section]
        for key, value in incoming.items():
            if key not in target:
                continue
            if key in {"enabled", "auto_inject", "auto_extract"}:
                target[key] = _as_bool(value, bool(target[key]))
            elif key in {"base_url", "model", "api_key"}:
                target[key] = str(value or "").strip()
            elif key in _INT_BOUNDS:
                target[key] = _as_int(value, int(target[key]), name=key)
    return result


def mask_memory_settings(raw: Any) -> dict[str, Any]:
    """Return the admin-facing document: masked key + ``has_api_key``."""
    settings = normalize_memory_settings(raw)
    masked = default_memory_settings()
    for section in ("embedding", "rerank"):
        value = dict(settings[section])
        has_key = bool(value.get("api_key"))
        value["api_key"] = MASKED_API_KEY if has_key else ""
        value["has_api_key"] = has_key
        masked[section] = value
    masked["behavior"] = dict(settings["behavior"])
    return masked


@dataclass(frozen=True)
class EmbeddingSettings:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    dimensions: int = 1536
    timeout_seconds: float = 20.0
    batch_size: int = 32

    @property
    def configured(self) -> bool:
        """True only when enabled *and* enough information to call the API."""
        return bool(self.enabled and self.base_url and self.model)


@dataclass(frozen=True)
class RerankSettings:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    top_n: int = 10
    timeout_seconds: float = 20.0

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)


@dataclass(frozen=True)
class BehaviorSettings:
    vector_candidate_limit: int = 50
    rerank_candidate_limit: int = 30
    rrf_k: int = 60
    recall_top_k: int = 5
    auto_inject: bool = True
    auto_extract: bool = True


@dataclass(frozen=True)
class MemoryRetrievalSettings:
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = field(default_factory=RerankSettings)
    behavior: BehaviorSettings = field(default_factory=BehaviorSettings)

    @classmethod
    def from_raw(cls, raw: Any) -> "MemoryRetrievalSettings":
        data = normalize_memory_settings(raw)
        return cls(
            embedding=EmbeddingSettings(**data["embedding"]),
            rerank=RerankSettings(**data["rerank"]),
            behavior=BehaviorSettings(**data["behavior"]),
        )

    @property
    def active(self) -> bool:
        return self.embedding.configured or self.rerank.configured


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[int]], *, k: int = 60
) -> list[tuple[int, float]]:
    """Fuse ranked memory-id lists with Reciprocal Rank Fusion.

    ``score = Σ 1 / (k + rank)`` (rank is 1-based).  Ties are broken by the
    best rank, then by descending memory id so the result is deterministic.
    """
    try:
        fusion_k = max(1, int(k or 60))
    except (TypeError, ValueError):
        fusion_k = 60
    scores: dict[int, float] = {}
    best_rank: dict[int, int] = {}
    for ranked in ranked_lists:
        for rank, raw_id in enumerate(ranked, start=1):
            try:
                memory_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (fusion_k + rank)
            previous = best_rank.get(memory_id)
            best_rank[memory_id] = rank if previous is None else min(previous, rank)
    return sorted(
        scores.items(),
        key=lambda item: (-item[1], best_rank[item[0]], -item[0]),
    )


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
        retrievers: list[Retriever] | None = None,
        extractor: Extractor | None = None,
        events: EventBus | None = None,
        dedupe_window_seconds: int = 86400,
        default_top_k: int = 5,
        token_budget: int = 800,
        settings_store: Any = None,
        settings_key: str = MEMORY_SETTINGS_KEY,
        retrieval_settings: dict[str, Any] | None = None,
        embedding_client: Any = None,
        rerank_client: Any = None,
        embedding_client_factory: (
            Callable[[EmbeddingSettings], Any] | None
        ) = None,
        rerank_client_factory: Callable[[RerankSettings], Any] | None = None,
        vector_store_factory: Callable[[MemoryRepository], Any] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self._retriever_factory = retriever_factory
        self._injected_retrievers = list(retrievers) if retrievers is not None else None
        self.extractor = extractor
        self.events = events
        self.dedupe_window_seconds = dedupe_window_seconds
        self.default_top_k = default_top_k
        self.token_budget = token_budget
        # ``settings_store`` is any object with ``get(key, default)``; the
        # platform SettingsStore satisfies it.  ``retrieval_settings`` is an
        # explicit dict override (mainly for tests / embedding before wiring).
        self.settings_store = settings_store
        self.settings_key = settings_key
        self._retrieval_settings = retrieval_settings
        self.embedding_client = embedding_client
        self.rerank_client = rerank_client
        self.embedding_client_factory = embedding_client_factory
        self.rerank_client_factory = rerank_client_factory
        self.vector_store_factory = vector_store_factory
        self._vector_tasks: set[asyncio.Task] = set()

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
        if self._injected_retrievers is not None:
            return list(self._injected_retrievers)
        if self._retriever_factory is not None:
            return self._retriever_factory(repo)
        return default_retrievers(repo, top_k=top_k)

    async def _run_retrievers(
        self, retrievers: Sequence[Retriever], ctx: RecallContext
    ) -> list[Memory]:
        memories: list[Memory] = []
        for retriever in retrievers:
            try:
                result = await retriever.retrieve(ctx)
            except Exception:  # noqa: BLE001 - recall must never 500
                logger.warning(
                    "记忆检索器失败，已跳过：%s", type(retriever).__name__, exc_info=True
                )
                continue
            if result:
                memories = result
        return memories

    # -- settings ------------------------------------------------------
    def _raw_settings(self) -> dict[str, Any] | None:
        if self._retrieval_settings is not None:
            return self._retrieval_settings
        if self.settings_store is None:
            return None
        try:
            raw = self.settings_store.get(self.settings_key, None)
        except Exception:  # noqa: BLE001 - settings must never break recall
            logger.warning("读取记忆检索设置失败，使用默认值", exc_info=True)
            return None
        return raw if isinstance(raw, dict) and raw else None

    def _load_retrieval_settings(self) -> MemoryRetrievalSettings:
        return MemoryRetrievalSettings.from_raw(self._raw_settings())

    # -- client plumbing ----------------------------------------------
    def _embedding_client_for(self, settings: EmbeddingSettings):
        if self.embedding_client is not None:
            return self.embedding_client, False
        if self.embedding_client_factory is not None:
            return self.embedding_client_factory(settings), True
        return (
            EmbeddingClient(
                base_url=settings.base_url,
                api_key=settings.api_key,
                model=settings.model,
                dimensions=settings.dimensions,
                timeout_seconds=settings.timeout_seconds,
                batch_size=settings.batch_size,
            ),
            True,
        )

    def _rerank_client_for(self, settings: RerankSettings):
        if self.rerank_client is not None:
            return self.rerank_client, False
        if self.rerank_client_factory is not None:
            return self.rerank_client_factory(settings), True
        return (
            RerankClient(
                base_url=settings.base_url,
                api_key=settings.api_key,
                model=settings.model,
                top_n=settings.top_n,
                timeout_seconds=settings.timeout_seconds,
            ),
            True,
        )

    @staticmethod
    async def _close_client(client: Any, owned: bool) -> None:
        if not owned or client is None:
            return
        closer = getattr(client, "close", None)
        if not callable(closer):
            return
        try:
            outcome = closer()
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception:  # noqa: BLE001
            logger.debug("关闭记忆检索客户端失败", exc_info=True)

    def _vector_store(self, repo: MemoryRepository) -> MemoryVectorStore:
        if self.vector_store_factory is not None:
            return self.vector_store_factory(repo)
        return MemoryVectorStore(repo)

    @staticmethod
    def _has_vector_backend(repo: MemoryRepository) -> bool:
        """In-memory repositories have no SQL connection / vector table."""
        return getattr(repo, "conn", None) is not None

    # -- vector maintenance (best effort) ------------------------------
    def _spawn_vector_task(self, coroutine) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("当前没有事件循环，跳过记忆向量同步")
            return
        task = loop.create_task(coroutine)
        self._vector_tasks.add(task)
        task.add_done_callback(self._vector_tasks.discard)

    def _schedule_vector_upsert(
        self, bot_id: str, memory_id: int, content: str
    ) -> None:
        settings = self._load_retrieval_settings()
        if not settings.embedding.configured:
            return
        if not self._has_vector_backend(self._repo(bot_id)):
            return
        self._spawn_vector_task(
            self._sync_memory_vector(
                bot_id, int(memory_id), content, settings.embedding
            )
        )

    async def _sync_memory_vector(
        self,
        bot_id: str,
        memory_id: int,
        content: str,
        settings: EmbeddingSettings,
    ) -> None:
        client = None
        owned = False
        try:
            client, owned = self._embedding_client_for(settings)
            vector = await client.embed_one(content)
            repo = self._repo(bot_id)
            # Guard against races: the memory may have been edited/deleted
            # while the embedding request was in flight.
            current = repo.get(memory_id)
            if current is None or current.content != content:
                return
            self._vector_store(repo).upsert(
                memory_id,
                vector,
                model=settings.model,
                now=self.clock.now(),
            )
        except Exception:  # noqa: BLE001 - maintenance must not affect writes
            logger.warning(
                "记忆向量写入失败（bot=%s memory=%s），已忽略",
                bot_id,
                memory_id,
                exc_info=True,
            )
        finally:
            await self._close_client(client, owned)

    def _delete_vector_safely(self, repo: MemoryRepository, memory_id: int) -> None:
        if not self._has_vector_backend(repo):
            return
        try:
            self._vector_store(repo).delete(int(memory_id))
        except Exception:  # noqa: BLE001 - maintenance must not affect writes
            logger.warning("记忆向量删除失败（memory=%s），已忽略", memory_id, exc_info=True)

    async def wait_for_vector_tasks(self, timeout: float | None = None) -> None:
        """Await in-flight vector maintenance tasks (tests / shutdown)."""
        tasks = [task for task in self._vector_tasks if not task.done()]
        if not tasks:
            return
        gather = asyncio.gather(*tasks, return_exceptions=True)
        if timeout is None:
            await gather
        else:
            try:
                await asyncio.wait_for(gather, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("等待记忆向量任务超时（%ss）", timeout)

    # -- write ---------------------------------------------------------
    def remember(self, bot_id: str, draft: MemoryDraft) -> dict[str, Any]:
        content = (draft.content or "").strip()
        if not content:
            raise MemoryValidationError("记忆内容不能为空")
        if len(content) > MAX_CONTENT_LENGTH:
            raise MemoryValidationError(f"记忆内容不能超过 {MAX_CONTENT_LENGTH} 字符")
        kind = draft.kind if draft.kind in KIND_LABELS else canonical_kind(draft.kind)
        memory_type = canonical_kind(draft.memory_type or kind)
        importance = max(1, min(6, int(draft.importance or 3)))
        strength = clamp_strength(draft.strength)
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
                memory_type=memory_type,
                strength=strength,
            ),
            now=now,
        )
        memory = repo.get(memory_id)
        if memory is None:  # pragma: no cover - defensive
            raise MemoryValidationError("写入记忆失败")
        # Best effort: keep the vector index in sync with the new content.
        self._schedule_vector_upsert(bot_id, memory_id, memory.content)
        self._emit(
            "memory.created",
            {
                "bot_id": bot_id,
                "memory_id": memory_id,
                "kind": kind,
                "memory_type": memory_type,
            },
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
        retrievers: Sequence[Retriever] | None = None,
    ) -> list[Memory]:
        repo = self._repo(bot_id)
        settings = self._load_retrieval_settings()
        raw_settings = self._raw_settings()
        if top_k is not None:
            limit = max(1, int(top_k))
        elif raw_settings:
            limit = int(settings.behavior.recall_top_k or self.default_top_k)
        else:
            limit = int(self.default_top_k)
        ctx = RecallContext(
            bot_id=bot_id,
            query=(query or "").strip(),
            top_k=limit,
            kind=kind,
            now=self.clock.now(),
            token_budget=int(token_budget or self.token_budget),
        )
        if retrievers is not None:
            # Explicit injection keeps the legacy sequential pipeline intact.
            memories = await self._run_retrievers(list(retrievers), ctx)
        elif settings.active:
            memories = await self._recall_hybrid(repo, ctx, settings, limit)
        else:
            memories = await self._run_retrievers(
                self._retrievers(repo, limit), ctx
            )
        # Always-inject memories (importance=6 / pinned) bypass retrieval ranking.
        always = self.always_recall(bot_id)
        if always:
            seen = {memory.id for memory in memories}
            memories = [m for m in always if m.id not in seen] + [
                m for m in memories if m.id in seen or m.id not in {x.id for x in always}
            ]
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

    async def _recall_hybrid(
        self,
        repo: MemoryRepository,
        ctx: RecallContext,
        settings: MemoryRetrievalSettings,
        limit: int,
    ) -> list[Memory]:
        """FTS (+ vector) candidates → RRF → rerank (rules fallback)."""
        candidate_limit = max(
            limit,
            settings.behavior.vector_candidate_limit,
            settings.behavior.rerank_candidate_limit,
        )
        if self._retriever_factory is not None:
            base_retrievers = self._retriever_factory(repo)
        else:
            base_retrievers = [FtsRetriever(repo, candidate_limit=candidate_limit)]
        base_memories = await self._run_retrievers(base_retrievers, ctx)
        fts_hits = list(ctx.candidates)
        if not fts_hits and base_memories:
            # A custom retriever may return memories without filling
            # ``ctx.candidates``; keep them usable for rerank/RRF.
            fts_hits = [
                RecallHit(memory=memory, score=0.0, source="retriever")
                for memory in base_memories
            ]
        memory_map: dict[int, Memory] = {
            hit.memory.id: hit.memory for hit in fts_hits
        }
        fts_ranked = [hit.memory.id for hit in fts_hits]

        vector_ranked: list[int] = []
        if settings.embedding.configured:
            vector_ranked = await self._vector_candidate_ids(
                repo, ctx, settings, memory_map
            )

        if vector_ranked:
            fused = reciprocal_rank_fusion(
                [fts_ranked, vector_ranked], k=settings.behavior.rrf_k
            )
            fused_hits = [
                RecallHit(memory=memory_map[memory_id], score=score, source="rrf")
                for memory_id, score in fused
                if memory_id in memory_map
            ]
            ctx.candidates = fused_hits
            candidates = [hit.memory for hit in fused_hits]
        else:
            candidates = [hit.memory for hit in fts_hits]

        if settings.rerank.configured and candidates:
            reranked = await self._rerank_memories(ctx, candidates, settings, limit)
            if reranked is not None:
                return reranked
            # Rerank failed → rules rerank over the same candidates (no 500).
            return await RulesReranker(top_k=limit).retrieve(ctx)

        if vector_ranked:
            return candidates[:limit]
        if not fts_hits:
            return []
        return await RulesReranker(top_k=limit).retrieve(ctx)

    async def _vector_candidate_ids(
        self,
        repo: MemoryRepository,
        ctx: RecallContext,
        settings: MemoryRetrievalSettings,
        memory_map: dict[int, Memory],
    ) -> list[int]:
        if not ctx.query.strip():
            return []
        if not self._has_vector_backend(repo):
            return []
        client = None
        owned = False
        try:
            client, owned = self._embedding_client_for(settings.embedding)
            query_vector = await client.embed_one(ctx.query)
            hits = self._vector_store(repo).search(
                query_vector,
                settings.behavior.vector_candidate_limit,
                kind=ctx.kind,
                since=ctx.since,
                model=settings.embedding.model,
            )
        except Exception:  # noqa: BLE001 - recall falls back to FTS
            logger.warning("记忆向量召回失败，已回退 FTS 结果", exc_info=True)
            return []
        finally:
            await self._close_client(client, owned)

        ranked: list[int] = []
        for hit in hits:
            memory_id = int(hit.memory_id)
            if memory_id not in memory_map:
                memory = repo.get(memory_id)
                if memory is not None:
                    memory_map[memory_id] = memory
            if memory_id in memory_map:
                ranked.append(memory_id)
        return ranked

    async def _rerank_memories(
        self,
        ctx: RecallContext,
        candidates: list[Memory],
        settings: MemoryRetrievalSettings,
        limit: int,
    ) -> list[Memory] | None:
        top_candidates = candidates[: settings.behavior.rerank_candidate_limit]
        if not top_candidates:
            return []
        client = None
        owned = False
        try:
            client, owned = self._rerank_client_for(settings.rerank)
            results = await client.rerank(
                ctx.query,
                [memory.content for memory in top_candidates],
                top_n=settings.rerank.top_n or len(top_candidates),
            )
            if not results:
                raise ValueError("rerank 返回空结果")
        except Exception:  # noqa: BLE001 - fall back to rules, never 500
            logger.warning("记忆重排失败，回退规则重排", exc_info=True)
            return None
        finally:
            await self._close_client(client, owned)

        ordered: list[Memory] = []
        ordered_ids: set[int] = set()
        seen_indexes: set[int] = set()
        for result in results:
            index = int(getattr(result, "index", -1))
            if 0 <= index < len(top_candidates) and index not in seen_indexes:
                memory = top_candidates[index]
                ordered.append(memory)
                ordered_ids.add(memory.id)
                seen_indexes.add(index)
        for memory in top_candidates:  # keep candidates the reranker dropped
            if memory.id not in ordered_ids:
                ordered.append(memory)
        return ordered[:limit]

    def list(
        self,
        bot_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        kind: str | None = None,
        tag: str | None = None,
        q: str | None = None,
        importance: int | None = None,
    ) -> dict[str, Any]:
        repo = self._repo(bot_id)
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        if q and q.strip():
            hits = repo.search_fts(q.strip(), 200, kind=kind)
            memories = [
                hit.memory
                for hit in hits
                if importance is None or hit.memory.importance == importance
            ]
            total = len(memories)
            start = (page - 1) * page_size
            memories = memories[start : start + page_size]
        else:
            memories = repo.list(
                kind=kind,
                tag=tag,
                limit=page_size * page,
                importance=importance,
            )
            total = repo.count(kind=kind, tag=tag, importance=importance)
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
        content_changed = False
        if "content" in patch:
            content = str(patch["content"] or "").strip()
            if not content or len(content) > MAX_CONTENT_LENGTH:
                raise MemoryValidationError("记忆内容长度不合法")
            content_changed = content != memory.content
            memory.content = content
        if "kind" in patch:
            if patch["kind"] not in KIND_LABELS:
                raise MemoryValidationError("未知的记忆类型")
            memory.kind = str(patch["kind"])
            if "memory_type" not in patch:
                memory.memory_type = canonical_kind(memory.kind)
        if "memory_type" in patch:
            if patch["memory_type"] not in KIND_LABELS:
                raise MemoryValidationError("未知的记忆类型")
            memory.memory_type = canonical_kind(patch["memory_type"])
        if "strength" in patch:
            memory.strength = clamp_strength(patch["strength"])
        if "reasoning" in patch:
            memory.reasoning = str(patch["reasoning"] or "")
        if "importance" in patch:
            memory.importance = max(1, min(6, int(patch["importance"])))
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
        if content_changed:
            settings = self._load_retrieval_settings()
            if settings.embedding.configured:
                self._schedule_vector_upsert(bot_id, int(memory_id), updated.content)
            else:
                # Content changed but embedding is off: drop the stale vector.
                self._delete_vector_safely(repo, int(memory_id))
        self._emit("memory.updated", {"bot_id": bot_id, "memory_id": memory_id})
        return updated

    def delete(self, bot_id: str, memory_id: int) -> None:
        repo = self._repo(bot_id)
        if repo.get(int(memory_id)) is None:
            raise MemoryValidationError("记忆不存在")
        repo.soft_delete(int(memory_id), now=self.clock.now())
        self._delete_vector_safely(repo, int(memory_id))
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

    async def reindex_bot(
        self, bot_id: str, *, batch_size: int | None = None, limit: int = 100_000
    ) -> dict[str, Any]:
        """Backfill embeddings for existing memories (used by scripts/memory_reindex.py).

        Embedding must be enabled in admin settings; otherwise this is a no-op.
        """
        repo = self._repo(bot_id)
        if not self._has_vector_backend(repo):
            return {"bot_id": bot_id, "ok": False, "reason": "vector_backend_unavailable"}
        settings = self._load_retrieval_settings()
        embedding = settings.embedding
        if not embedding.enabled:
            return {"bot_id": bot_id, "ok": False, "reason": "embedding_disabled"}
        memories = [
            memory for memory in repo.list(limit=limit) if (memory.content or "").strip()
        ]
        if not memories:
            return {"bot_id": bot_id, "ok": True, "indexed": 0, "total": 0}
        client, owned = self._embedding_client_for(embedding)
        store = self._vector_store(repo)
        size = max(1, int(batch_size or embedding.batch_size or 32))
        indexed = 0
        try:
            for start in range(0, len(memories), size):
                batch = memories[start : start + size]
                vectors = await client.embed([memory.content for memory in batch])
                for memory, vector in zip(batch, vectors):
                    if not vector:
                        continue
                    store.upsert(
                        memory.id,
                        vector,
                        model=embedding.model,
                        now=self.clock.now(),
                    )
                    indexed += 1
        finally:
            if owned:
                try:
                    await client.close()
                except Exception:  # noqa: BLE001
                    logger.warning("关闭 embedding 客户端失败", exc_info=True)
        return {
            "bot_id": bot_id,
            "ok": True,
            "indexed": indexed,
            "total": len(memories),
            "model": embedding.model,
        }

    def always_recall(self, bot_id: str, *, limit: int = 100) -> list[Memory]:
        """Memories marked importance=6 (or pinned) are injected on every turn."""
        try:
            rows = self._repo(bot_id).list(limit=limit)
        except Exception:  # noqa: BLE001
            return []
        selected = [
            memory
            for memory in rows
            if int(memory.importance or 0) >= 6 or bool(memory.pinned)
        ]
        return selected[:limit]

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


__all__ = [
    "DEFAULT_BEHAVIOR_SETTINGS",
    "DEFAULT_EMBEDDING_SETTINGS",
    "DEFAULT_RERANK_SETTINGS",
    "MASKED_API_KEY",
    "MEMORY_SETTINGS_KEY",
    "BehaviorSettings",
    "EmbeddingSettings",
    "MemoryRetrievalSettings",
    "MemoryService",
    "MemoryValidationError",
    "RerankSettings",
    "default_memory_settings",
    "default_retrievers",
    "mask_memory_settings",
    "normalize_memory_settings",
    "reciprocal_rank_fusion",
]
