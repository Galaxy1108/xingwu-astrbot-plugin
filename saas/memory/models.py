"""Pure dataclasses for the memory module (no IO, no framework imports)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    NOTE = "note"


KIND_LABELS: dict[str, str] = {
    MemoryKind.FACT.value: "事实",
    MemoryKind.PREFERENCE.value: "偏好",
    MemoryKind.EVENT.value: "事件",
    MemoryKind.NOTE.value: "笔记",
}

DEFAULT_IMPORTANCE = 3
MAX_CONTENT_LENGTH = 4000


def normalize_content(text: str) -> str:
    """Whitespace/punctuation-insensitive key used for 24h dedupe."""
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


@dataclass
class MemoryDraft:
    content: str
    kind: str = MemoryKind.FACT.value
    reasoning: str = ""
    importance: int = DEFAULT_IMPORTANCE
    pinned: bool = False
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_conversation_id: str = ""
    source_message_id: str = ""

    def normalized(self) -> str:
        return normalize_content(self.content)


@dataclass
class Memory:
    id: int
    content: str
    kind: str = MemoryKind.FACT.value
    reasoning: str = ""
    importance: int = DEFAULT_IMPORTANCE
    pinned: bool = False
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_conversation_id: str = ""
    source_message_id: str = ""
    embedding: bytes | None = None
    created_at: int = 0
    updated_at: int = 0
    last_recalled_at: int = 0
    recall_count: int = 0
    deleted_at: int = 0

    def normalized(self) -> str:
        return normalize_content(self.content)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "kind_label": KIND_LABELS.get(self.kind, self.kind),
            "content": self.content,
            "reasoning": self.reasoning,
            "importance": self.importance,
            "pinned": bool(self.pinned),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "source_conversation_id": self.source_conversation_id,
            "source_message_id": self.source_message_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_recalled_at": self.last_recalled_at,
            "recall_count": self.recall_count,
        }


@dataclass
class RecallHit:
    memory: Memory
    score: float = 0.0
    source: str = "fts"


@dataclass
class Turn:
    role: str
    content: str
    message_id: str = ""
    conversation_id: str = ""


@dataclass
class RecallContext:
    bot_id: str
    query: str
    top_k: int = 5
    kind: str | None = None
    tags: list[str] | None = None
    since: int | None = None
    now: int = 0
    token_budget: int = 800
    candidates: list[RecallHit] = field(default_factory=list)


def parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def estimate_tokens(text: str) -> int:
    """Cheap token budget estimate (CJK ≈ 1 char/token, ASCII ≈ 4 chars/token)."""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    other = len(text or "") - cjk
    return cjk + max(1, other // 4)
