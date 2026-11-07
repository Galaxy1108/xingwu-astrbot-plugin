"""SQLite implementation of :class:`saas.memory.ports.MemoryRepository`.

This is the only place in the memory module that writes SQL (the note library
in ``saas/memory/notes.py`` shares the same connection and reuses the helpers
defined here).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Iterable

from ..models import (
    DEFAULT_STRENGTH,
    Memory,
    MemoryDraft,
    RecallHit,
    canonical_kind,
    clamp_strength,
    kind_variants,
    parse_metadata,
)
from .sqlcipher import dict_row_factory


_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9_]+")

# Schema 004 (angel parity). It is applied here as well because
# ``MemoryStorage.open_library`` historically did not run pending migrations:
# libraries created before 004 would otherwise miss notes/strength columns.
_SCHEMA_004_TABLES = """
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  short_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  deleted_at INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  title, content, tags, tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS memory_vectors (
  memory_id INTEGER PRIMARY KEY,
  model TEXT NOT NULL DEFAULT '',
  dim INTEGER NOT NULL DEFAULT 0,
  vector BLOB NOT NULL,
  updated_at INTEGER NOT NULL
);
"""

_SCHEMA_004_MEMORY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("memory_type", "TEXT NOT NULL DEFAULT 'knowledge'"),
    ("strength", "INTEGER NOT NULL DEFAULT 50"),
    ("access_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_decay_at", "INTEGER NOT NULL DEFAULT 0"),
)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    names: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            names.add(str(row.get("name")))
        else:  # sqlite3.Row / tuple
            names.add(str(row[1]))
    return names


def _first_value(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def ensure_schema(conn: sqlite3.Connection) -> bool:
    """Idempotently apply schema 004 to a per-bot library.

    Returns ``True`` when the legacy ``memories`` table was upgraded (columns
    added and ``memory_type`` backfilled from ``kind``). Safe to call on every
    connection open: ``CREATE ... IF NOT EXISTS`` plus column checks make it a
    no-op on already-upgraded libraries, and migration version 4 is recorded in
    ``schema_migrations`` for observability.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    conn.executescript(_SCHEMA_004_TABLES)
    columns = _column_names(conn, "memories")
    added_memory_type = False
    for name, ddl in _SCHEMA_004_MEMORY_COLUMNS:
        if name in columns:
            continue
        conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")
        if name == "memory_type":
            added_memory_type = True
    if added_memory_type:
        # ALTER TABLE fills every legacy row with the column default
        # ('knowledge'); restore the real type from the legacy ``kind`` value.
        conn.execute(
            "UPDATE memories SET memory_type = kind "
            "WHERE kind IN ('preference','relationship','event','emotion','note') "
            "AND (memory_type IS NULL OR memory_type = '' OR memory_type = 'knowledge')"
        )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (4, ?)",
        (int(time.time()),),
    )
    conn.commit()
    return added_memory_type


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
        ensure_schema(self.conn)

    # -- mapping -------------------------------------------------------
    def _tags(self, memory_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag",
            (memory_id,),
        ).fetchall()
        return [str(row["tag"]) for row in rows]

    def _to_memory(self, row: Any) -> Memory:
        data = dict(row)
        kind = str(data.get("kind") or "fact")
        return Memory(
            id=int(data["id"]),
            content=str(data.get("content") or ""),
            kind=kind,
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
            memory_type=str(
                data.get("memory_type") or canonical_kind(kind)
            ),
            strength=clamp_strength(
                data.get("strength", DEFAULT_STRENGTH), DEFAULT_STRENGTH
            ),
            access_count=int(data.get("access_count") or 0),
            last_decay_at=int(data.get("last_decay_at") or 0),
        )

    # -- writes --------------------------------------------------------
    def add(self, draft: MemoryDraft, *, now: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO memories(kind, memory_type, content, reasoning, importance, "
            "strength, pinned, access_count, last_decay_at, source_conversation_id, "
            "source_message_id, metadata, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                draft.kind,
                draft.effective_memory_type(),
                draft.content,
                draft.reasoning,
                max(1, min(5, int(draft.importance))),
                clamp_strength(draft.strength),
                1 if draft.pinned else 0,
                0,
                0,
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
            "UPDATE memories SET kind = ?, memory_type = ?, content = ?, reasoning = ?, "
            "importance = ?, strength = ?, pinned = ?, metadata = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at = 0",
            (
                memory.kind,
                memory.effective_memory_type(),
                memory.content,
                memory.reasoning,
                max(1, min(5, int(memory.importance))),
                clamp_strength(memory.strength),
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
            f"UPDATE memories SET last_recalled_at = ?, recall_count = recall_count + 1, "
            f"access_count = access_count + 1 WHERE id IN ({placeholders})",
            [now, *memory_ids],
        )
        self.conn.commit()

    def apply_decay(
        self, decays: Iterable[tuple[int, int]], *, now: int
    ) -> int:
        """Persist strength decay for ``(memory_id, strength)`` pairs."""
        rows = [
            (clamp_strength(strength), int(now), int(now), int(memory_id))
            for memory_id, strength in decays
        ]
        if not rows:
            return 0
        self.conn.executemany(
            "UPDATE memories SET strength = ?, last_decay_at = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at = 0",
            rows,
        )
        self.conn.commit()
        return len(rows)

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
    @staticmethod
    def _kind_clause(kind: str | None, params: list[Any], *, prefix: str = "m.") -> str:
        variants = kind_variants(kind)
        if not variants:
            return ""
        placeholders = ",".join("?" for _ in variants)
        params.extend(variants)
        return f"{prefix}kind IN ({placeholders})"

    def list(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
        since: int | None = None,
        until: int | None = None,
    ) -> list[Memory]:
        where = ["m.deleted_at = 0"]
        params: list[Any] = []
        kind_clause = self._kind_clause(kind, params)
        if kind_clause:
            where.append(kind_clause)
        if cursor is not None:
            where.append("m.id < ?")
            params.append(int(cursor))
        if since is not None:
            where.append("m.created_at >= ?")
            params.append(int(since))
        if until is not None:
            where.append("m.created_at <= ?")
            params.append(int(until))
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
        kind_clause = self._kind_clause(kind, params)
        if kind_clause:
            where.append(kind_clause)
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

    def count(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
    ) -> int:
        where = ["m.deleted_at = 0"]
        params: list[Any] = []
        kind_clause = self._kind_clause(kind, params)
        if kind_clause:
            where.append(kind_clause)
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
