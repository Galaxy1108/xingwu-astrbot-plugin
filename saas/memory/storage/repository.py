"""SQLite implementation of :class:`saas.memory.ports.MemoryRepository`.

This is the only place in the memory module that writes SQL.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..models import (
    Memory,
    MemoryDraft,
    RecallHit,
    parse_metadata,
)
from .sqlcipher import dict_row_factory


_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9_]+")


def tokenize_text(text: str) -> list[str]:
    """Index/query tokenizer: CJK unigrams+bigrams and ASCII words.

    FTS5's unicode61 does not segment Chinese, so we pre-tokenize: each CJK run
    contributes its characters and adjacent bigrams, making 2+ char substring
    searches (杭州/咖啡/独立开发) work. ASCII words are kept whole.
    """
    tokens: list[str] = []
    for run in _CJK_RUN.findall(text or ""):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    tokens.extend(word.lower() for word in _WORD.findall(text or ""))
    return tokens


def _index_text(*parts: str) -> str:
    seen: dict[str, None] = {}
    for part in parts:
        for token in tokenize_text(part):
            if token:
                seen.setdefault(token, None)
    return " ".join(seen)


def _fts_terms(query: str) -> str:
    """Turn user input into a safe FTS5 MATCH expression (quoted AND terms)."""
    tokens = _index_text(query).split()
    if not tokens:
        return ""
    # Prefer multi-character tokens: bigrams/words are far more selective than
    # CJK unigrams and keep 10k-row queries well under the 20ms budget.
    selective = [token for token in tokens if len(token) >= 2]
    chosen = selective or tokens
    escaped = [token.replace('"', '""') for token in chosen[:8]]
    return " ".join(f'"{token}"' for token in escaped)


class SqlCipherRepository:
    """Repository over an already-keyed SQLCipher connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = dict_row_factory

    # -- mapping -------------------------------------------------------
    def _tags(self, memory_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag",
            (memory_id,),
        ).fetchall()
        return [str(row["tag"]) for row in rows]

    def _to_memory(self, row: Any) -> Memory:
        data = dict(row)
        return Memory(
            id=int(data["id"]),
            content=str(data.get("content") or ""),
            kind=str(data.get("kind") or "fact"),
            reasoning=str(data.get("reasoning") or ""),
            importance=int(data.get("importance") or 3),
            pinned=bool(data.get("pinned")),
            tags=self._tags(int(data["id"])),
            metadata=parse_metadata(data.get("metadata")),
            source_conversation_id=str(data.get("source_conversation_id") or ""),
            source_message_id=str(data.get("source_message_id") or ""),
            embedding=data.get("embedding"),
            created_at=int(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
            last_recalled_at=int(data.get("last_recalled_at") or 0),
            recall_count=int(data.get("recall_count") or 0),
            deleted_at=int(data.get("deleted_at") or 0),
        )

    # -- writes --------------------------------------------------------
    def add(self, draft: MemoryDraft, *, now: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO memories(kind, content, reasoning, importance, pinned, "
            "source_conversation_id, source_message_id, metadata, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                draft.kind,
                draft.content,
                draft.reasoning,
                max(1, min(5, int(draft.importance))),
                1 if draft.pinned else 0,
                draft.source_conversation_id,
                draft.source_message_id,
                json.dumps(draft.metadata or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        memory_id = int(cursor.lastrowid or 0)
        for tag in sorted({t.strip() for t in draft.tags if t and t.strip()}):
            self.conn.execute(
                "INSERT OR IGNORE INTO memory_tags(memory_id, tag) VALUES (?, ?)",
                (memory_id, tag[:64]),
            )
        self._index(memory_id)
        self.conn.commit()
        return memory_id

    def get(self, memory_id: int) -> Memory | None:
        row = self.conn.execute(
            "SELECT * FROM memories WHERE id = ? AND deleted_at = 0", (memory_id,)
        ).fetchone()
        return self._to_memory(row) if row else None

    def update(self, memory: Memory, *, now: int) -> None:
        self.conn.execute(
            "UPDATE memories SET kind = ?, content = ?, reasoning = ?, importance = ?, "
            "pinned = ?, metadata = ?, updated_at = ? WHERE id = ? AND deleted_at = 0",
            (
                memory.kind,
                memory.content,
                memory.reasoning,
                max(1, min(5, int(memory.importance))),
                1 if memory.pinned else 0,
                json.dumps(memory.metadata or {}, ensure_ascii=False),
                now,
                memory.id,
            ),
        )
        self.conn.execute("DELETE FROM memory_tags WHERE memory_id = ?", (memory.id,))
        for tag in sorted({t.strip() for t in memory.tags if t and t.strip()}):
            self.conn.execute(
                "INSERT OR IGNORE INTO memory_tags(memory_id, tag) VALUES (?, ?)",
                (memory.id, tag[:64]),
            )
        self._index(memory.id)
        self.conn.commit()

    def soft_delete(self, memory_id: int, *, now: int) -> None:
        self.conn.execute(
            "UPDATE memories SET deleted_at = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at = 0",
            (now, now, memory_id),
        )
        self.conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        self.conn.commit()

    def touch_recalled(self, memory_ids: list[int], *, now: int) -> None:
        if not memory_ids:
            return
        placeholders = ",".join("?" for _ in memory_ids)
        self.conn.execute(
            f"UPDATE memories SET last_recalled_at = ?, recall_count = recall_count + 1 "
            f"WHERE id IN ({placeholders})",
            [now, *memory_ids],
        )
        self.conn.commit()

    def _index(self, memory_id: int) -> None:
        memory = self.get(memory_id)
        if memory is None:
            return
        self.conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        self.conn.execute(
            "INSERT INTO memories_fts(rowid, content, reasoning, tags) VALUES (?,?,?,?)",
            (
                memory_id,
                _index_text(memory.content, memory.reasoning),
                "",
                _index_text(" ".join(memory.tags)),
            ),
        )

    # -- reads ---------------------------------------------------------
    def list(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        where = ["m.deleted_at = 0"]
        params: list[Any] = []
        if kind:
            where.append("m.kind = ?")
            params.append(kind)
        if cursor is not None:
            where.append("m.id < ?")
            params.append(int(cursor))
        clause = " AND ".join(where)
        params.append(limit)
        if tag:
            sql = (
                "SELECT m.* FROM memories m "
                "JOIN memory_tags t ON t.memory_id = m.id "
                f"WHERE {clause} AND t.tag = ? "
                "ORDER BY m.pinned DESC, m.id DESC LIMIT ?"
            )
            params.insert(-1, tag)
        else:
            sql = (
                f"SELECT m.* FROM memories m WHERE {clause} "
                "ORDER BY m.pinned DESC, m.id DESC LIMIT ?"
            )
        rows = self.conn.execute(sql, params).fetchall()
        return [self._to_memory(row) for row in rows]

    def search_fts(
        self,
        query: str,
        limit: int,
        *,
        kind: str | None = None,
        since: int | None = None,
    ) -> list[RecallHit]:
        match = _fts_terms(query)
        if not match:
            return []
        where = ["memories_fts MATCH ?", "m.deleted_at = 0"]
        params: list[Any] = [match]
        if kind:
            where.append("m.kind = ?")
            params.append(kind)
        if since:
            where.append("m.created_at >= ?")
            params.append(int(since))
        params.append(limit)
        sql = (
            "SELECT m.*, bm25(memories_fts) AS rank FROM memories_fts "
            "JOIN memories m ON m.id = memories_fts.rowid "
            f"WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?"
        )
        rows = self.conn.execute(sql, params).fetchall()
        hits = []
        for row in rows:
            # bm25 returns negative values (smaller = better); expose a positive score.
            score = -float(row["rank"] or 0.0)
            hits.append(RecallHit(memory=self._to_memory(row), score=score, source="fts"))
        return hits

    def find_duplicate(self, content: str, *, since: int) -> Memory | None:
        from ..models import normalize_content

        key = normalize_content(content)
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE deleted_at = 0 AND created_at >= ? "
            "ORDER BY id DESC",
            (since,),
        ).fetchall()
        for row in rows:
            memory = self._to_memory(row)
            if memory.normalized() == key:
                return memory
        return None

    def count(self, *, kind: str | None = None, tag: str | None = None) -> int:
        where = ["m.deleted_at = 0"]
        params: list[Any] = []
        if kind:
            where.append("m.kind = ?")
            params.append(kind)
        if tag:
            where.append(
                "EXISTS(SELECT 1 FROM memory_tags t WHERE t.memory_id = m.id AND t.tag = ?)"
            )
            params.append(tag)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM memories m WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
        return int(row["c"] if row else 0)
