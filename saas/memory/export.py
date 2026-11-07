"""JSON snapshot export/import for one bot's memory library.

Snapshot = memories (with tags + strength metadata) + notes. Import is
idempotent: memories are deduplicated by normalized content (and ids are not
reused across libraries), notes by ``short_id`` first and content second.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import (
    DEFAULT_IMPORTANCE,
    MAX_CONTENT_LENGTH,
    MemoryDraft,
    canonical_kind,
    clamp_strength,
    normalize_content,
)

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def _memory_from_item(item: dict[str, Any]) -> MemoryDraft:
    content = str(item.get("content") or "")[:MAX_CONTENT_LENGTH]
    kind = str(item.get("kind") or item.get("memory_type") or "knowledge")
    memory_type = canonical_kind(item.get("memory_type") or kind)
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        importance = int(item.get("importance") or DEFAULT_IMPORTANCE)
    except (TypeError, ValueError):
        importance = DEFAULT_IMPORTANCE
    return MemoryDraft(
        content=content,
        kind=kind,
        memory_type=memory_type,
        reasoning=str(item.get("reasoning") or ""),
        importance=max(1, min(5, importance)),
        pinned=bool(item.get("pinned")),
        tags=[str(tag) for tag in tags if str(tag).strip()],
        metadata=metadata,
        source_conversation_id=str(item.get("source_conversation_id") or ""),
        source_message_id=str(item.get("source_message_id") or ""),
        strength=clamp_strength(item.get("strength")),
    )


def export_snapshot(service: Any, bot_id: str, *, notes: Any | None = None) -> dict[str, Any]:
    """Build a self-contained JSON-serialisable snapshot for ``bot_id``."""
    exported = service.export(bot_id)
    memories = exported.get("items") or []
    note_items: list[dict[str, Any]] = []
    if notes is not None:
        note_page = notes.list(page=1, page_size=100)
        summaries = list(note_page.get("items") or [])
        total = int(note_page.get("total") or 0)
        pages = max(1, (total + 99) // 100)
        for page_number in range(2, pages + 1):
            summaries.extend(
                notes.list(page=page_number, page_size=100).get("items") or []
            )
        for summary in summaries:
            note_items.append(notes.get(summary["short_id"]))
    tags = sorted(
        {tag for item in memories for tag in (item.get("tags") or []) if tag}
    )
    return {
        "version": SNAPSHOT_VERSION,
        "bot_id": bot_id,
        "exported_at": exported.get("exported_at") or 0,
        "count": len(memories),
        "memories": memories,
        "tags": tags,
        "notes_count": len(note_items),
        "notes": note_items,
    }


def _existing_memory_keys(repository: Any) -> set[str]:
    return {
        memory.normalized()
        for memory in repository.list(limit=100_000)
        if not memory.deleted_at
    }


def _existing_note_keys(notes: Any) -> tuple[set[str], set[str]]:
    short_ids: set[str] = set()
    contents: set[str] = set()
    page = notes.list(page=1, page_size=100)
    items = page.get("items") or []
    total = int(page.get("total") or 0)
    page_size = 100
    pages = max(1, (total + page_size - 1) // page_size)
    collected = list(items)
    for page_number in range(2, pages + 1):
        collected.extend(
            notes.list(page=page_number, page_size=page_size).get("items") or []
        )
    for summary in collected:
        short_ids.add(str(summary.get("short_id") or ""))
        full = notes.get(summary["short_id"])
        contents.add(normalize_content(str(full.get("content") or "")))
    return short_ids, contents


def import_snapshot(
    service: Any,
    bot_id: str,
    snapshot: dict[str, Any],
    *,
    notes: Any | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import a snapshot into ``bot_id``; safe to run repeatedly."""
    if not isinstance(snapshot, dict):
        raise ValueError("快照必须是 JSON 对象")
    payload = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else snapshot
    memories = payload.get("memories") or payload.get("items") or []
    note_items = payload.get("notes") or []
    if not isinstance(memories, list):
        memories = []
    if not isinstance(note_items, list):
        note_items = []

    repository = service.store.open(bot_id)
    known_memory_keys = _existing_memory_keys(repository)
    report: dict[str, Any] = {
        "bot_id": bot_id,
        "dry_run": bool(dry_run),
        "memories": {"total": len(memories), "imported": 0, "skipped": 0, "failed": 0},
        "notes": {"total": len(note_items), "imported": 0, "skipped": 0, "failed": 0},
        "errors": [],
    }

    for item in memories:
        if not isinstance(item, dict):
            report["memories"]["skipped"] += 1
            continue
        draft = _memory_from_item(item)
        key = draft.normalized()
        if not key or key in known_memory_keys:
            report["memories"]["skipped"] += 1
            continue
        if dry_run:
            known_memory_keys.add(key)
            report["memories"]["imported"] += 1
            continue
        try:
            result = service.remember(bot_id, draft)
        except Exception as exc:  # noqa: BLE001
            report["memories"]["failed"] += 1
            report["errors"].append(str(exc))
            continue
        if result.get("duplicate"):
            report["memories"]["skipped"] += 1
        else:
            report["memories"]["imported"] += 1
        known_memory_keys.add(key)

    if note_items and notes is not None:
        known_short_ids, known_contents = _existing_note_keys(notes)
        short_id_map: dict[str, str] = {}
        for item in note_items:
            if not isinstance(item, dict):
                report["notes"]["skipped"] += 1
                continue
            short_id = str(item.get("short_id") or "").strip().lower()
            content = str(item.get("content") or "")
            content_key = normalize_content(content)
            if (short_id and short_id in known_short_ids) or (
                content_key and content_key in known_contents
            ):
                report["notes"]["skipped"] += 1
                continue
            if dry_run:
                report["notes"]["imported"] += 1
                if content_key:
                    known_contents.add(content_key)
                if short_id:
                    known_short_ids.add(short_id)
                continue
            try:
                created = notes.create(
                    str(item.get("title") or ""),
                    content,
                    tags=item.get("tags") or [],
                )
            except Exception as exc:  # noqa: BLE001
                report["notes"]["failed"] += 1
                report["errors"].append(str(exc))
                continue
            report["notes"]["imported"] += 1
            if content_key:
                known_contents.add(content_key)
            known_short_ids.add(created["short_id"])
            if short_id:
                short_id_map[short_id] = created["short_id"]
        report["short_id_map"] = short_id_map

    return report


def export_bot(api: Any, bot_id: str) -> dict[str, Any]:
    """Convenience wrapper for :class:`~saas.memory.api.MemoryAPI`."""
    return export_snapshot(api.service, bot_id, notes=api.note_service(bot_id))


def import_bot(
    api: Any,
    bot_id: str,
    snapshot: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    return import_snapshot(
        api.service,
        bot_id,
        snapshot,
        notes=api.note_service(bot_id),
        dry_run=dry_run,
    )


__all__ = [
    "SNAPSHOT_VERSION",
    "export_snapshot",
    "import_snapshot",
    "export_bot",
    "import_bot",
]
