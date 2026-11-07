"""Pure dataclasses for the memory module (no IO, no framework imports)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryKind(str, Enum):
    """Canonical memory types (angel-memory parity).

    ``fact`` is the legacy spelling of ``knowledge`` (very old libraries store
    it). It remains an accepted input/filter value via :func:`canonical_kind`
    and :func:`kind_variants`, but new writes should use ``knowledge``.
    """

    KNOWLEDGE = "knowledge"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    EVENT = "event"
    EMOTION = "emotion"
    NOTE = "note"
    # Legacy alias: ``fact`` is the old spelling of ``knowledge``. Kept as an
    # enum alias so ``MemoryKind.FACT.value == "knowledge"``.
    FACT = "knowledge"


# Explicit string keys: ``MemoryKind.FACT`` is an alias of KNOWLEDGE, but the
# legacy ``fact`` label must stay available for old rows.
KIND_LABELS: dict[str, str] = {
    "knowledge": "知识",
    "preference": "偏好",
    "relationship": "关系",
    "event": "事件",
    "emotion": "情感",
    "note": "笔记",
    "fact": "事实",
}

# Kinds that may be written by the LLM tool / command parser (``fact`` is the
# legacy spelling of knowledge and stays accepted through ``KIND_LABELS``).
TOOL_KINDS: tuple[str, ...] = (
    "knowledge",
    "preference",
    "relationship",
    "event",
    "emotion",
    "note",
)

# ``fact`` is the legacy spelling of ``knowledge``. Filters expand the pair so
# old libraries (kind='fact') and new libraries (kind='knowledge') behave
# identically without rewriting historical rows.
KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "fact": ("knowledge", "fact"),
    "knowledge": ("knowledge", "fact"),
}

DEFAULT_IMPORTANCE = 3
DEFAULT_STRENGTH = 50
MIN_STRENGTH = 0
MAX_STRENGTH = 100
MAX_CONTENT_LENGTH = 4000


def canonical_kind(kind: Any) -> str:
    """Return the canonical memory type (``fact`` → ``knowledge``)."""
    text = str(kind or "").strip().lower()
    if not text:
        return MemoryKind.KNOWLEDGE.value
    if text == "fact":
        return MemoryKind.KNOWLEDGE.value
    if text in KIND_LABELS:
        return text
    return MemoryKind.KNOWLEDGE.value


def kind_variants(kind: Any) -> tuple[str, ...]:
    """SQL/in-memory filter values matching ``kind`` (legacy alias aware)."""
    text = str(kind or "").strip().lower()
    if not text:
        return ()
    return KIND_ALIASES.get(text, (text,))


def clamp_strength(value: Any, default: int = DEFAULT_STRENGTH) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(MIN_STRENGTH, min(MAX_STRENGTH, number))


def normalize_content(text: str) -> str:
    """Whitespace/punctuation-insensitive key used for 24h dedupe."""
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


@dataclass
class MemoryDraft:
    content: str
    kind: str = MemoryKind.KNOWLEDGE.value
    reasoning: str = ""
    importance: int = DEFAULT_IMPORTANCE
    pinned: bool = False
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_conversation_id: str = ""
    source_message_id: str = ""
    # Angel-memory parity fields. ``memory_type`` defaults to the canonical
    # form of ``kind`` when omitted.
    memory_type: str = ""
    strength: int = DEFAULT_STRENGTH

    def normalized(self) -> str:
        return normalize_content(self.content)

    def effective_memory_type(self) -> str:
        return canonical_kind(self.memory_type or self.kind)


@dataclass
class Memory:
    id: int
    content: str
    kind: str = MemoryKind.KNOWLEDGE.value
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
    memory_type: str = ""
    strength: int = DEFAULT_STRENGTH
    access_count: int = 0
    last_decay_at: int = 0

    def normalized(self) -> str:
        return normalize_content(self.content)

    def effective_memory_type(self) -> str:
        return canonical_kind(self.memory_type or self.kind)

    def to_dict(self) -> dict[str, Any]:
        memory_type = self.effective_memory_type()
        return {
            "id": self.id,
            "kind": self.kind,
            "kind_label": KIND_LABELS.get(self.kind, self.kind),
            "memory_type": memory_type,
            "memory_type_label": KIND_LABELS.get(memory_type, memory_type),
            "content": self.content,
            "reasoning": self.reasoning,
            "importance": self.importance,
            "strength": self.strength,
            "access_count": self.access_count,
            "last_decay_at": self.last_decay_at,
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
