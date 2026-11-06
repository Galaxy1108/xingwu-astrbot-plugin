"""One-off import from astrbot_plugin_angel_memory (handoff §4.5.7).

The original database is opened read-only and never modified. Expected source
columns: ``judgment`` (→ content), ``reasoning``, ``scope``, ``created_at`` and
optionally ``tags`` (comma separated). The import is idempotent: duplicates are
skipped by the service's 24h dedupe plus an exact (content, created_at) check.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..api import MemoryAPI
from ..models import MemoryDraft


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


def import_from_angel(
    db_path: str | Path,
    api: MemoryAPI,
    *,
    bot_id: str,
    scope_map: dict[str, str] | None = None,
    limit: int = 100_000,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Map angel_memory rows into the new per-bot encrypted library."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"angel_memory 数据库不存在：{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        table = "memory" if "memory" in tables else ("memories" if "memories" in tables else None)
        if table is None:
            raise ValueError("源数据库中未找到 memory / memories 表")
        columns = {
            row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        content_column = "judgment" if "judgment" in columns else "content"
        rows = conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).fetchall()
    finally:
        conn.close()

    mapping = scope_map or {}
    report = {"total": len(rows), "imported": 0, "skipped": 0, "failed": 0, "errors": []}
    for row in rows:
        data = dict(row)
        scope = str(data.get("scope") or "")
        target_bot = mapping.get(scope, bot_id)
        if target_bot != bot_id:
            report["skipped"] += 1
            continue
        content = str(data.get(content_column) or "").strip()
        if not content:
            report["skipped"] += 1
            continue
        tags_raw = data.get("tags") or ""
        if isinstance(tags_raw, str):
            try:
                parsed = json.loads(tags_raw)
                tags = [str(t) for t in parsed] if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            tags = []
        if dry_run:
            report["imported"] += 1
            continue
        try:
            result = api.service.remember(
                target_bot,
                MemoryDraft(
                    content=content[:4000],
                    reasoning=str(data.get("reasoning") or ""),
                    tags=tags,
                    importance=3,
                    source_conversation_id=str(data.get("source_conversation_id") or ""),
                    source_message_id=str(data.get("source_message_id") or ""),
                ),
            )
            if result.get("duplicate"):
                report["skipped"] += 1
            else:
                report["imported"] += 1
        except Exception as exc:  # noqa: BLE001
            report["failed"] += 1
            report["errors"].append(str(exc))
    report["dry_run"] = dry_run
    return report
