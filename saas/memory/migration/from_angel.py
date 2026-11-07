"""One-off import from astrbot_plugin_angel_memory (handoff §4.5.7).

The original database is opened read-only and never modified. Besides the
classic ``memory``/``memories`` table (``judgment`` → content, ``reasoning``,
``scope``, ``created_at``), the current angel memory plugin stores rows in
``memory_records`` with ``memory_type``/``strength`` + ``global_tags`` /
``memory_tag_rel`` relations. Notes live in a table named ``notes``/``note``
(or on disk, indexed by ``note_index_records`` — pass ``notes_dir`` to import
those Markdown files as well).

Imports are idempotent: memories dedupe on ``(normalized content, created_at)``
within the 24h dedupe window / exact content set, notes on normalized content.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ..api import MemoryAPI
from ..models import MemoryDraft, canonical_kind, clamp_strength, normalize_content

_MEMORY_TABLES = ("memory_records", "memories", "memory")
_NOTE_TABLES = ("notes", "note")

_MEMORY_TYPE_MAP = {
    "知识记忆": "knowledge",
    "事件记忆": "event",
    "技能记忆": "knowledge",
    "任务记忆": "event",
    "情感记忆": "emotion",
    "关系记忆": "relationship",
    "knowledge": "knowledge",
    "fact": "knowledge",
    "preference": "preference",
    "relationship": "relationship",
    "event": "event",
    "emotion": "emotion",
    "note": "note",
}

_TAG_SPLIT = re.compile(r"[,，;；\s]+")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def inspect_source(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"angel_memory 数据库不存在：{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        columns: dict[str, list[str]] = {}
        for table in tables:
            columns[table] = [
                row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            ]
    finally:
        conn.close()
    return {"path": str(path), "tables": tables, "columns": columns}


def _parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple, set)):
        return [str(tag).strip() for tag in raw if str(tag).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(tag).strip() for tag in parsed if str(tag).strip()]
        except (TypeError, ValueError):
            pass
    return [tag.strip() for tag in _TAG_SPLIT.split(text) if tag.strip()]


def _map_memory_type(raw: Any, fallback: str = "knowledge") -> str:
    text = str(raw or "").strip()
    if not text:
        return canonical_kind(fallback)
    return _MEMORY_TYPE_MAP.get(text, canonical_kind(text))


def _map_strength(raw: Any) -> int:
    """Angel strength is an open-ended accumulator; map it into 0–100.

    ``1`` (fresh angel memory) → 10, ``5`` → 50, ``10`` → 100. Missing values
    keep the module default (50).
    """
    if raw is None:
        return 50
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return 50
    return clamp_strength(max(10, number * 10))


def _importance_for(strength: int) -> int:
    if strength >= 80:
        return 5
    if strength >= 60:
        return 4
    if strength >= 40:
        return 3
    if strength >= 20:
        return 2
    return 1


def _load_memory_tag_map(conn: sqlite3.Connection, tables: set[str]) -> dict[str, list[str]]:
    if not {"global_tags", "memory_tag_rel"}.issubset(tables):
        return {}
    conn.row_factory = sqlite3.Row
    tag_map: dict[str, list[str]] = {}
    try:
        rows = conn.execute(
            "SELECT r.memory_id AS memory_id, g.name AS name "
            "FROM memory_tag_rel r JOIN global_tags g ON g.id = r.tag_id"
        ).fetchall()
    except sqlite3.DatabaseError:
        return {}
    for row in rows:
        tag_map.setdefault(str(row["memory_id"]), []).append(str(row["name"]))
    return tag_map


def _read_memory_rows(
    conn: sqlite3.Connection, limit: int
) -> tuple[list[dict[str, Any]], str, dict[str, list[str]]]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    table = next((name for name in _MEMORY_TABLES if name in tables), None)
    if table is None:
        raise ValueError("源数据库中未找到 memory / memories / memory_records 表")
    conn.row_factory = sqlite3.Row
    tag_map = _load_memory_tag_map(conn, tables)
    rows = conn.execute(
        f'SELECT * FROM "{table}" LIMIT ?', (limit,)
    ).fetchall()
    return [dict(row) for row in rows], table, tag_map


def _read_note_rows(
    conn: sqlite3.Connection, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    table = next((name for name in _NOTE_TABLES if name in tables), None)
    if table is None:
        return [], None
    columns = _table_columns(conn, table)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).fetchall()
    notes: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        content = str(
            data.get("content")
            or data.get("body")
            or data.get("markdown")
            or data.get("judgment")
            or ""
        )
        title = str(data.get("title") or data.get("heading_h1") or "").strip()
        notes.append(
            {
                "title": title,
                "content": content,
                "tags": _parse_tags(data.get("tags") or data.get("tag") or ""),
                "short_id": str(data.get("short_id") or ""),
                "columns": columns,
            }
        )
    return notes, table


def _read_note_files(
    conn: sqlite3.Connection, raw_dir: str | Path, limit: int
) -> list[dict[str, Any]]:
    """Read angel ``note_index_records`` + Markdown files as note candidates."""
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "note_index_records" not in tables:
        return []
    root = Path(raw_dir)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT source_file_path, heading_h1 FROM note_index_records LIMIT ?",
        (limit,),
    ).fetchall()
    notes: list[dict[str, Any]] = []
    for row in rows:
        relative = str(row["source_file_path"] or "").replace("\\", "/").strip()
        if not relative:
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        notes.append(
            {
                "title": str(row["heading_h1"] or path.stem).strip(),
                "content": content,
                "tags": [],
                "short_id": "",
            }
        )
    return notes


def _existing_note_contents(api: MemoryAPI, bot_id: str) -> set[str]:
    contents: set[str] = set()
    try:
        notes = api.note_service(bot_id)
        page = notes.list(page=1, page_size=100)
        total = int(page.get("total") or 0)
        pages = max(1, (total + 99) // 100)
        summaries = list(page.get("items") or [])
        for page_number in range(2, pages + 1):
            summaries.extend(
                notes.list(page=page_number, page_size=100).get("items") or []
            )
        for summary in summaries:
            full = notes.get(summary["short_id"])
            contents.add(normalize_content(str(full.get("content") or "")))
    except Exception:  # noqa: BLE001 - never fail the memory import on notes
        return contents
    return contents


def import_from_angel(
    db_path: str | Path,
    api: MemoryAPI,
    *,
    bot_id: str,
    scope_map: dict[str, str] | None = None,
    limit: int = 100_000,
    dry_run: bool = False,
    notes_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Map angel_memory rows (memories + notes) into the per-bot library."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"angel_memory 数据库不存在：{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows, memory_table, tag_map = _read_memory_rows(conn, limit)
        note_rows, note_table = _read_note_rows(conn, limit)
        if notes_dir is not None:
            note_rows = [*note_rows, *_read_note_files(conn, notes_dir, limit)]
    finally:
        conn.close()

    mapping = scope_map or {}
    report: dict[str, Any] = {
        "source": str(path),
        "memory_table": memory_table,
        "note_table": note_table,
        "total": len(rows),
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "notes": {
            "total": len(note_rows),
            "imported": 0,
            "skipped": 0,
            "failed": 0,
        },
    }
    for data in rows:
        scope = str(data.get("memory_scope") or data.get("scope") or "")
        target_bot = mapping.get(scope, bot_id)
        if target_bot != bot_id:
            report["skipped"] += 1
            continue
        content_column = "judgment" if "judgment" in data else "content"
        content = str(data.get(content_column) or "").strip()
        if not content:
            report["skipped"] += 1
            continue
        memory_type = _map_memory_type(
            data.get("memory_type") or data.get("kind"), fallback="knowledge"
        )
        strength = _map_strength(data.get("strength"))
        raw_tags = data.get("tags")
        tags = _parse_tags(raw_tags) if raw_tags else []
        if not tags:
            tags = tag_map.get(str(data.get("id") or ""), [])
        source_created_at = data.get("created_at")
        if dry_run:
            report["imported"] += 1
            continue
        try:
            result = api.service.remember(
                target_bot,
                MemoryDraft(
                    content=content[:4000],
                    kind=memory_type,
                    memory_type=memory_type,
                    strength=strength,
                    reasoning=str(data.get("reasoning") or ""),
                    importance=_importance_for(strength),
                    pinned=bool(data.get("is_active")),
                    tags=tags,
                    source_conversation_id=str(
                        data.get("source_conversation_id") or ""
                    ),
                    source_message_id=str(data.get("source_message_id") or ""),
                    metadata={
                        "imported_from": "angel_memory",
                        **(
                            {"source_created_at": source_created_at}
                            if source_created_at
                            else {}
                        ),
                    },
                ),
            )
            if result.get("duplicate"):
                report["skipped"] += 1
            else:
                report["imported"] += 1
        except Exception as exc:  # noqa: BLE001
            report["failed"] += 1
            report["errors"].append(str(exc))

    if note_rows:
        known_contents = _existing_note_contents(api, bot_id)
        for note in note_rows:
            content = str(note.get("content") or "").strip()
            if not content:
                report["notes"]["skipped"] += 1
                continue
            key = normalize_content(content)
            if key in known_contents:
                report["notes"]["skipped"] += 1
                continue
            if dry_run:
                known_contents.add(key)
                report["notes"]["imported"] += 1
                continue
            try:
                api.note_create(
                    bot_id,
                    str(note.get("title") or ""),
                    content,
                    tags=note.get("tags") or [],
                )
            except Exception as exc:  # noqa: BLE001
                report["notes"]["failed"] += 1
                report["errors"].append(str(exc))
                continue
            known_contents.add(key)
            report["notes"]["imported"] += 1

    report["dry_run"] = dry_run
    return report
