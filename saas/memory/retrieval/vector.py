"""Reserved: embedding / vector retrieval (phase 2).

Interface is intentionally identical to the other retrievers: add an instance
to ``MemoryService(retrievers=[...])`` and merge/rerank.
"""

from __future__ import annotations

from ..models import Memory, RecallContext


class VectorRetriever:
    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("向量检索计划于第二期实现（见交接文档 §4.5.8）")

    async def retrieve(self, ctx: RecallContext) -> list[Memory]:  # pragma: no cover
        return []
