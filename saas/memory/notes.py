"""Per-bot note library (angel-memory parity).

Notes are Markdown knowledge documents stored in the same encrypted per-bot
library as memories (schema 004: ``notes`` + standalone ``notes_fts``). The
``short_id`` is a short, human-readable, per-library unique handle used by the
LLM tool and the HTTP API to page through the body (``offset``/``limit`` are
**character** offsets, which behave correctly for CJK text).

SQL lives in this module's repository classes; orchestration lives in
:class:`NoteService` so HTTP / LLM tools never build SQL.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from ..clock import Clock, SystemClock
from .storage.repository import (
    _fts_terms,
    _index_text,
    ensure_schema,
)

__all__ = [
    "Note",
    "NoteDraft",
    "NoteService",
    "NoteValidationError",
    "NoteNotFoundError",
    "SqlCipherNotesRepository",
    "InMemoryNotesRepository",
    "notes_repository_for",
    "notes_for_store",
    "generate_short_id",
]

# Ambiguous glyphs (0/O, 1/l/I) removed so ids survive copy/paste and reading.
SHORT_ID_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
SHORT_ID_LENGTH = 6
SHORT_ID_MAX_LENGTH = 8
SHORT_ID_ATTEMPTS = 8

MAX_TITLE_LENGTH = 200
MAX_CONTENT_LENGTH = 200_000
MAX_TAGS = 20
MAX_TAG_LENGTH = 32
DEFAULT_READ_CHARS = 4_000
MAX_READ_CHARS = 20_000
LIST_PAGE_SIZE_MAX = 100


class NoteValidationError(ValueError):
    """Invalid note input (mapped to HTTP 400)."""


class NoteNotFoundError(LookupError):
    """Note short_id does not exist (mapped to HTTP 404)."""


@dataclass
class NoteDraft:
    title: str
    content: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Note:
    id: int
    short_id: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    deleted_at: int = 0

    def summary_dict(self) -> dict[str, Any]:
        preview = " ".join(self.content.split())
        return {
            "id": self.id,
            "short_id": self.short_id,
            "title": self.title,
            "tags": list(self.tags),
            "content_length": len(self.content),
            "preview": preview[:200],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "short_id": self.short_id,
            "title": self.title,
            "tags": list(self.tags),
            "content_length": len(self.content),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_content:
            payload["content"] = self.content
        return payload


def normalize_tags(tags: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = str(raw or "").strip()[:MAX_TAG_LENGTH]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= MAX_TAGS:
            break
    return result


def parse_tags(raw: Any) -> list[str]:
    """Parse the comma-separated DB representation (JSON lists also accepted)."""
    if isinstance(raw, (list, tuple, set)):
        return normalize_tags(raw)
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            import json

            parsed = json.loads(text)
            if isinstance(parsed, list):
                return normalize_tags(parsed)
        except (TypeError, ValueError):
            pass
    return normalize_tags(text.split(","))


def _tags_sql(tags: list[str]) -> str:
    return ",".join(tags)


def generate_short_id(existing: set[str] | None = None) -> str:
    """Generate a readable 6–8 char short id that is unique in the library."""
    taken = existing or set()
    for length in range(SHORT_ID_LENGTH, SHORT_ID_MAX_LENGTH + 1):
        for _ in range(SHORT_ID_ATTEMPTS * 4):
            candidate = "".join(
                secrets.choice(SHORT_ID_ALPHABET) for _ in range(length)
            )
            if candidate not in taken:
                return candidate
    raise NoteValidationError("无法生成唯一的笔记短 ID，请清理笔记库后重试")


def _normalize_short_id(short_id: Any) -> str:
    return str(short_id or "").strip().lower()


def _derive_title(content: str) -> str:
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title[:MAX_TITLE_LENGTH]
        elif stripped:
            return stripped[:MAX_TITLE_LENGTH]
    return "未命名笔记"


def _apply_patch(note: Note, patch: dict[str, Any]) -> Note:
    if "title" in patch:
        title = str(patch.get("title") or "").strip()
        if not title:
            raise NoteValidationError("笔记标题不能为空")
        if len(title) > MAX_TITLE_LENGTH:
            raise NoteValidationError(f"笔记标题不能超过 {MAX_TITLE_LENGTH} 字符")
        note.title = title
    if "content" in patch:
        content = str(patch.get("content") or "")
        if len(content) > MAX_CONTENT_LENGTH:
            raise NoteValidationError(f"笔记正文不能超过 {MAX_CONTENT_LENGTH} 字符")
        note.content = content
    if "tags" in patch:
        tags = patch.get("tags")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise NoteValidationError("tags 必须是字符串数组")
        note.tags = normalize_tags(tags)
    return note


class NoteRepository(Protocol):
    def create(self, draft: NoteDraft, *, now: int) -> Note: ...

    def get_by_short_id(self, short_id: str) -> Note | None: ...

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        q: str | None = None,
    ) -> tuple[list[Note], int]: ...

    def update(self, note: Note, *, now: int) -> Note: ...

    def soft_delete(self, short_id: str, *, now: int) -> bool: ...


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------
class SqlCipherNotesRepository:
    """Notes over the per-bot library connection (schema 004)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_schema(self.conn)

    # -- mapping / index ----------------------------------------------
    def _to_note(self, row: Any) -> Note:
        data = dict(row)
        return Note(
            id=int(data["id"]),
            short_id=str(data.get("short_id") or ""),
            title=str(data.get("title") or ""),
            content=str(data.get("content") or ""),
            tags=parse_tags(data.get("tags")),
            created_at=int(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
            deleted_at=int(data.get("deleted_at") or 0),
        )

    def _index(self, note_id: int) -> None:
        row = self.conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if row is None:
            return
        note = self._to_note(row)
        self.conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        self.conn.execute(
            "INSERT INTO notes_fts(rowid, title, content, tags) VALUES (?,?,?,?)",
            (
                note_id,
                _index_text(note.title),
                _index_text(note.content),
                _index_text(" ".join(note.tags)),
            ),
        )

    def _existing_short_ids(self) -> set[str]:
        rows = self.conn.execute("SELECT short_id FROM notes").fetchall()
        return {str(row["short_id"]) for row in rows}

    # -- writes --------------------------------------------------------
    def create(self, draft: NoteDraft, *, now: int) -> Note:
        short_id = generate_short_id(self._existing_short_ids())
        cursor = self.conn.execute(
            "INSERT INTO notes(short_id, title, content, tags, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                short_id,
                draft.title,
                draft.content,
                _tags_sql(normalize_tags(draft.tags)),
                now,
                now,
            ),
        )
        note_id = int(cursor.lastrowid or 0)
        self._index(note_id)
        self.conn.commit()
        note = self.get_by_short_id(short_id)
        if note is None:  # pragma: no cover - defensive
            raise NoteValidationError("写入笔记失败")
        return note

    def update(self, note: Note, *, now: int) -> Note:
        self.conn.execute(
            "UPDATE notes SET title = ?, content = ?, tags = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at = 0",
            (note.title, note.content, _tags_sql(note.tags), now, note.id),
        )
        self._index(note.id)
        self.conn.commit()
        updated = self.get_by_short_id(note.short_id)
        if updated is None:  # pragma: no cover - defensive
            raise NoteNotFoundError("笔记不存在")
        return updated

    def soft_delete(self, short_id: str, *, now: int) -> bool:
        note = self.get_by_short_id(short_id)
        if note is None:
            return False
        self.conn.execute(
            "UPDATE notes SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, note.id),
        )
        self.conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note.id,))
        self.conn.commit()
        return True

    # -- reads ---------------------------------------------------------
    def get_by_short_id(self, short_id: str) -> Note | None:
        row = self.conn.execute(
            "SELECT * FROM notes WHERE short_id = ? AND deleted_at = 0",
            (_normalize_short_id(short_id),),
        ).fetchone()
        return self._to_note(row) if row else None

    @staticmethod
    def _tag_clause(tag: str, params: list[Any]) -> str:
        params.append(f",{tag},")
        return "instr(',' || n.tags || ',', ?) > 0"

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        q: str | None = None,
    ) -> tuple[list[Note], int]:
        page = max(1, int(page))
        page_size = max(1, min(LIST_PAGE_SIZE_MAX, int(page_size)))
        offset = (page - 1) * page_size
        where = ["n.deleted_at = 0"]
        params: list[Any] = []
        if tag:
            where.append(self._tag_clause(str(tag).strip(), params))
        clause = " AND ".join(where)
        match = _fts_terms(q or "")
        if match:
            join = "FROM notes_fts f JOIN notes n ON n.id = f.rowid"
            match_where = f"{clause} AND notes_fts MATCH ?"
            count_row = self.conn.execute(
                f"SELECT COUNT(*) AS c {join} WHERE {match_where}",
                [*params, match],
            ).fetchone()
            total = int(count_row["c"] if count_row else 0)
            rows = self.conn.execute(
                f"SELECT n.* {join} WHERE {match_where} "
                "ORDER BY bm25(notes_fts), n.updated_at DESC LIMIT ? OFFSET ?",
                [*params, match, page_size, offset],
            ).fetchall()
        else:
            count_row = self.conn.execute(
                f"SELECT COUNT(*) AS c FROM notes n WHERE {clause}", params
            ).fetchone()
            total = int(count_row["c"] if count_row else 0)
            rows = self.conn.execute(
                f"SELECT n.* FROM notes n WHERE {clause} "
                "ORDER BY n.updated_at DESC, n.id DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        return [self._to_note(row) for row in rows], total

    def count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE deleted_at = 0"
        ).fetchone()
        return int(row["c"] if row else 0)


# ---------------------------------------------------------------------------
# In-memory implementation (tests / InMemoryStore)
# ---------------------------------------------------------------------------
class InMemoryNotesRepository:
    def __init__(self) -> None:
        self._items: dict[int, Note] = {}
        self._next_id = 1

    def _copy(self, note: Note) -> Note:
        return Note(
            id=note.id,
            short_id=note.short_id,
            title=note.title,
            content=note.content,
            tags=list(note.tags),
            created_at=note.created_at,
            updated_at=note.updated_at,
            deleted_at=note.deleted_at,
        )

    def create(self, draft: NoteDraft, *, now: int) -> Note:
        existing = {note.short_id for note in self._items.values()}
        note = Note(
            id=self._next_id,
            short_id=generate_short_id(existing),
            title=draft.title,
            content=draft.content,
            tags=normalize_tags(draft.tags),
            created_at=now,
            updated_at=now,
        )
        self._next_id += 1
        self._items[note.id] = note
        return self._copy(note)

    def update(self, note: Note, *, now: int) -> Note:
        current = self._items.get(note.id)
        if current is None or current.deleted_at:
            raise NoteNotFoundError("笔记不存在")
        updated = Note(
            id=current.id,
            short_id=current.short_id,
            title=note.title,
            content=note.content,
            tags=normalize_tags(note.tags),
            created_at=current.created_at,
            updated_at=now,
        )
        self._items[current.id] = updated
        return self._copy(updated)

    def soft_delete(self, short_id: str, *, now: int) -> bool:
        note = self.get_by_short_id(short_id)
        if note is None:
            return False
        raw = self._items[note.id]
        raw.deleted_at = now
        raw.updated_at = now
        return True

    def get_by_short_id(self, short_id: str) -> Note | None:
        wanted = _normalize_short_id(short_id)
        for note in self._items.values():
            if note.deleted_at == 0 and note.short_id == wanted:
                return self._copy(note)
        return None

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        q: str | None = None,
    ) -> tuple[list[Note], int]:
        page = max(1, int(page))
        page_size = max(1, min(LIST_PAGE_SIZE_MAX, int(page_size)))
        terms = [term for term in str(q or "").lower().split() if term]
        items = []
        for note in self._items.values():
            if note.deleted_at:
                continue
            if tag and tag not in note.tags:
                continue
            if terms:
                haystack = " ".join(
                    [note.title, note.content, " ".join(note.tags)]
                ).lower()
                if not all(term in haystack for term in terms):
                    continue
            items.append(self._copy(note))
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    def count(self) -> int:
        return sum(1 for note in self._items.values() if not note.deleted_at)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------
_NOTES_ATTR = "_notes_repository"


def notes_repository_for(repository: Any) -> Any:
    """Return (and cache) the notes repository bound to a memory repository."""
    cached = getattr(repository, _NOTES_ATTR, None)
    conn = getattr(repository, "conn", None)
    if conn is not None:
        if not isinstance(cached, SqlCipherNotesRepository):
            cached = SqlCipherNotesRepository(conn)
            setattr(repository, _NOTES_ATTR, cached)
        return cached
    if not isinstance(cached, InMemoryNotesRepository):
        cached = InMemoryNotesRepository()
        setattr(repository, _NOTES_ATTR, cached)
    return cached


def notes_for_store(store: Any, bot_id: str, *, clock: Clock | None = None) -> "NoteService":
    repository = store.open(bot_id)
    return NoteService(notes_repository_for(repository), clock=clock)


# ---------------------------------------------------------------------------
# Service (orchestration; no SQL)
# ---------------------------------------------------------------------------
class NoteService:
    def __init__(
        self,
        repository: NoteRepository,
        *,
        clock: Clock | None = None,
        events: Any | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or SystemClock()
        self.events = events

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.events is None:
            return
        try:
            self.events.publish(event, payload)
        except Exception:  # noqa: BLE001
            pass

    # -- write ---------------------------------------------------------
    def create(
        self,
        title: str,
        content: str,
        *,
        tags: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        body = str(content or "")
        if not body.strip():
            raise NoteValidationError("笔记内容不能为空")
        if len(body) > MAX_CONTENT_LENGTH:
            raise NoteValidationError(f"笔记正文不能超过 {MAX_CONTENT_LENGTH} 字符")
        clean_title = str(title or "").strip()
        if not clean_title:
            clean_title = _derive_title(body)
        if len(clean_title) > MAX_TITLE_LENGTH:
            raise NoteValidationError(f"笔记标题不能超过 {MAX_TITLE_LENGTH} 字符")
        tag_list = list(tags or [])
        if not all(isinstance(tag, str) for tag in tag_list):
            raise NoteValidationError("tags 必须是字符串数组")
        note = self.repository.create(
            NoteDraft(title=clean_title, content=body, tags=normalize_tags(tag_list)),
            now=self.clock.now(),
        )
        self._emit(
            "note.created",
            {"note_id": note.id, "short_id": note.short_id, "title": note.title},
        )
        return note.to_dict()

    def update(self, short_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        note = self._require(short_id)
        _apply_patch(note, patch or {})
        updated = self.repository.update(note, now=self.clock.now())
        self._emit(
            "note.updated",
            {"note_id": updated.id, "short_id": updated.short_id},
        )
        return updated.to_dict()

    def delete(self, short_id: str) -> None:
        if not self.repository.soft_delete(_normalize_short_id(short_id), now=self.clock.now()):
            raise NoteNotFoundError("笔记不存在")
        self._emit("note.deleted", {"short_id": _normalize_short_id(short_id)})

    # -- read ----------------------------------------------------------
    def _require(self, short_id: str) -> Note:
        note = self.repository.get_by_short_id(_normalize_short_id(short_id))
        if note is None:
            raise NoteNotFoundError("笔记不存在")
        return note

    def get(self, short_id: str) -> dict[str, Any]:
        return self._require(short_id).to_dict()

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(LIST_PAGE_SIZE_MAX, int(page_size)))
        notes, total = self.repository.list(
            page=page,
            page_size=page_size,
            tag=(tag or "").strip() or None,
            q=(q or "").strip() or None,
        )
        return {
            "items": [note.summary_dict() for note in notes],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        if not str(query or "").strip():
            raise NoteValidationError("请输入检索关键词")
        return self.list(page=1, page_size=limit, q=str(query))

    def read(
        self,
        short_id: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_READ_CHARS,
    ) -> dict[str, Any]:
        note = self._require(short_id)
        text = note.content
        total = len(text)
        try:
            start = int(offset)
        except (TypeError, ValueError):
            raise NoteValidationError("offset 必须是整数") from None
        try:
            size = int(limit)
        except (TypeError, ValueError):
            raise NoteValidationError("limit 必须是整数") from None
        start = max(0, min(start, total))
        size = max(1, min(MAX_READ_CHARS, size))
        chunk = text[start : start + size]
        end = start + len(chunk)
        has_more = end < total
        return {
            "short_id": note.short_id,
            "title": note.title,
            "content": chunk,
            "offset": start,
            "limit": size,
            "total_length": total,
            "has_more": has_more,
            "next_offset": end if has_more else None,
            "note": note.summary_dict(),
        }

    def stats(self) -> dict[str, Any]:
        return {"total": self.repository.count()}
