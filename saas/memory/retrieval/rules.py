"""Rule-based reranking: 0.5*BM25 + 0.3*importance + 0.2*recency, pinned first.

The BM25 component is normalised inside the candidate set so the three signals
are comparable. Kept deliberately small and deterministic for golden-set tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import Memory, RecallContext, RecallHit

DAY = 86400


def _recency(created_at: int, now: int) -> float:
    if not created_at or not now:
        return 0.0
    age_days = max(0.0, (now - created_at) / DAY)
    # Half-life of 30 days → 1.0 for fresh, 0.5 after a month.
    return 0.5 ** (age_days / 30.0)


class RulesReranker:
    def __init__(self, *, top_k: int = 5) -> None:
        self.top_k = top_k

    async def retrieve(self, ctx: RecallContext) -> list[Memory]:
        hits: list[RecallHit] = list(ctx.candidates)
        if not hits:
            return []
        max_score = max((hit.score for hit in hits), default=0.0) or 1.0
        now = ctx.now or int(datetime.now(tz=timezone.utc).timestamp())
        ranked: list[tuple[float, RecallHit]] = []
        for hit in hits:
            memory = hit.memory
            bm25 = max(0.0, hit.score) / max_score
            importance = max(0.0, min(5, memory.importance)) / 5.0
            recency = _recency(memory.created_at, now)
            score = 0.5 * bm25 + 0.3 * importance + 0.2 * recency
            if memory.pinned:
                score += 10.0  # pinned memories always lead
            ranked.append((score, hit))
        ranked.sort(key=lambda item: (item[0], item[1].memory.id), reverse=True)
        top = ranked[: self.top_k]
        # Expose the final scores for callers that want them.
        for score, hit in ranked:
            hit.score = score
        return [hit.memory for _, hit in top]
