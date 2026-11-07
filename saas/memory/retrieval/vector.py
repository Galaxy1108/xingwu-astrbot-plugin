"""Embedding-backed vector retriever (second stage of the hybrid pipeline).

The retriever is a thin adapter over :class:`saas.memory.vector_store
.MemoryVectorStore`; it owns no HTTP session.  Callers inject a ready
``EmbeddingClient`` (usually built from the platform memory settings), so the
same client can be reused between the query embedding and memory writes.

Failure is non-fatal: a vector backend error yields ``[]`` and logs a warning,
letting the FTS stage continue (recall must not 500 on an embedding outage).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models import Memory, RecallContext, RecallHit
from ..vector_store import MemoryVectorStore, VectorStoreError

if TYPE_CHECKING:  # pragma: no cover
    from ..ports import MemoryRepository
    from .embedding import EmbeddingClient

logger = logging.getLogger(__name__)


class VectorRetriever:
    def __init__(
        self,
        repository: "MemoryRepository",
        *,
        embedding_client: "EmbeddingClient",
        model: str = "",
        candidate_limit: int = 50,
    ) -> None:
        self.repository = repository
        self.embedding_client = embedding_client
        self.model = str(model or "")
        try:
            self.candidate_limit = max(1, int(candidate_limit))
        except (TypeError, ValueError):
            self.candidate_limit = 50

    async def retrieve(self, ctx: RecallContext) -> list[Memory]:
        if not ctx.query.strip():
            return []
        try:
            query_vector = await self.embedding_client.embed_one(ctx.query)
            store = MemoryVectorStore(self.repository)
            hits = store.search(
                query_vector,
                self.candidate_limit,
                kind=ctx.kind,
                since=ctx.since,
                model=self.model or None,
            )
        except (VectorStoreError, ValueError):
            logger.warning("向量检索失败，已跳过", exc_info=True)
            return []
        except Exception:  # noqa: BLE001 - upstream/transport errors are non-fatal
            logger.warning("向量检索失败，已跳过", exc_info=True)
            return []

        recall_hits: list[RecallHit] = []
        for hit in hits:
            memory = self.repository.get(hit.memory_id)
            if memory is None:
                continue
            recall_hits.append(
                RecallHit(memory=memory, score=float(hit.score), source="vector")
            )
        ctx.candidates = recall_hits
        return [hit.memory for hit in recall_hits]


__all__ = ["VectorRetriever"]
