"""FTS5 BM25 candidate retrieval (first stage of the pipeline)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Memory, RecallContext

if TYPE_CHECKING:
    from ..ports import MemoryRepository


class FtsRetriever:
    def __init__(self, repository: "MemoryRepository", *, candidate_limit: int = 50) -> None:
        self.repository = repository
        self.candidate_limit = candidate_limit

    async def retrieve(self, ctx: RecallContext) -> list[Memory]:
        if not ctx.query.strip():
            return []
        hits = self.repository.search_fts(
            ctx.query,
            self.candidate_limit,
            kind=ctx.kind,
            since=ctx.since,
        )
        ctx.candidates = hits
        return [hit.memory for hit in hits]
