"""Reserved: LLM-based extraction (phase 2)."""

from __future__ import annotations

from ..models import MemoryDraft, Turn


class LlmExtractor:
    """Placeholder that keeps the port shape stable for phase 2."""

    def __init__(self, provider=None, *, max_items: int = 3, every_n_turns: int = 6) -> None:
        self.provider = provider
        self.max_items = max_items
        self.every_n_turns = every_n_turns

    async def extract(self, turns: list[Turn], *, max_items: int = 3) -> list[MemoryDraft]:
        # No model calls in M2; explicit commands and the LLM tool cover writes.
        return []
