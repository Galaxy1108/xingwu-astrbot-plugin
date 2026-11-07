"""Notes + consolidation HTTP endpoints (angel-memory parity).

Registered by the app factory (``saas/web/app.py``) with ``app.add_routes``.
Every endpoint requires a logged-in user (session middleware) and verifies that
the Bot belongs to the current user; cross-tenant access is a 404.
"""

from __future__ import annotations

from aiohttp import web

from ..memory.consolidation import MemoryConsolidator
from ..errors import NotFound, ValidationError
from ..memory.notes import NoteNotFoundError, NoteValidationError, notes_for_store
from ..memory.service import MemoryValidationError
from .app import client_ip, container_of, current_user, ok


routes = web.RouteTableDef()


def _owned(container, request: web.Request, bot_id: str) -> dict:
    """Same semantics as ``routes_bots._owned`` (kept local to avoid coupling)."""
    user = current_user(request)
    return container.bots.get_for_user(user["id"], bot_id)


def _bot_and_notes(container, request: web.Request):
    bot_id = request.match_info["bot_id"]
    bot = _owned(container, request, bot_id)
    if not bot["memory_db"]:
        raise NotFound("该 Bot 尚未创建记忆库")
    return bot, notes_for_store(container.memory_store, bot["id"], clock=container.clock)


def _int_query(request: web.Request, name: str, default: int) -> int:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} 必须是整数", field=name) from None


# ------------------------------------------------------------------- notes
@routes.get("/api/bots/{bot_id}/notes")
async def list_notes(request: web.Request) -> web.Response:
    container = container_of(request)
    _, notes = _bot_and_notes(container, request)
    page = _int_query(request, "page", 1)
    page_size = _int_query(request, "page_size", 20)
    data = notes.list(
        page=page,
        page_size=page_size,
        tag=(request.query.get("tag") or "").strip() or None,
        q=(request.query.get("q") or "").strip() or None,
    )
    return ok(data)


@routes.post("/api/bots/{bot_id}/notes")
async def create_note(request: web.Request) -> web.Response:
    container = container_of(request)
    _, notes = _bot_and_notes(container, request)
    body = await request.json()
    try:
        note = notes.create(
            str(body.get("title") or ""),
            str(body.get("content") or ""),
            tags=body.get("tags") or [],
        )
    except NoteValidationError as exc:
        raise ValidationError(str(exc)) from None
    return ok({"note": note}, status=201)


@routes.get("/api/bots/{bot_id}/notes/{short_id}")
async def get_note(request: web.Request) -> web.Response:
    container = container_of(request)
    _, notes = _bot_and_notes(container, request)
    try:
        note = notes.get(request.match_info["short_id"])
    except NoteNotFoundError as exc:
        raise NotFound(str(exc)) from None
    return ok({"note": note})


@routes.patch("/api/bots/{bot_id}/notes/{short_id}")
async def patch_note(request: web.Request) -> web.Response:
    container = container_of(request)
    _, notes = _bot_and_notes(container, request)
    body = await request.json()
    try:
        note = notes.update(request.match_info["short_id"], body)
    except NoteNotFoundError as exc:
        raise NotFound(str(exc)) from None
    except NoteValidationError as exc:
        raise ValidationError(str(exc)) from None
    return ok({"note": note})


@routes.delete("/api/bots/{bot_id}/notes/{short_id}")
async def delete_note(request: web.Request) -> web.Response:
    container = container_of(request)
    _, notes = _bot_and_notes(container, request)
    try:
        notes.delete(request.match_info["short_id"])
    except NoteNotFoundError as exc:
        raise NotFound(str(exc)) from None
    return ok({"deleted": True})


@routes.get("/api/bots/{bot_id}/notes/{short_id}/read")
async def read_note(request: web.Request) -> web.Response:
    container = container_of(request)
    _, notes = _bot_and_notes(container, request)
    offset = _int_query(request, "offset", 0)
    limit = _int_query(request, "limit", 4000)
    try:
        page = notes.read(request.match_info["short_id"], offset=offset, limit=limit)
    except NoteNotFoundError as exc:
        raise NotFound(str(exc)) from None
    except NoteValidationError as exc:
        raise ValidationError(str(exc)) from None
    return ok(page)


# ------------------------------------------------------------ consolidate
@routes.post("/api/bots/{bot_id}/memories/consolidate")
async def consolidate_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    bot = _owned(container, request, bot_id)
    if not bot["memory_db"]:
        raise NotFound("该 Bot 尚未创建记忆库")
    body = {}
    if request.can_read_body:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - empty/invalid body means defaults
            body = {}
    dry_run = bool(body.get("dry_run", False)) if isinstance(body, dict) else False
    consolidator = MemoryConsolidator(
        container.memory_store,
        clock=container.clock,
        events=getattr(container.memory_service, "events", None),
    )
    try:
        report = consolidator.consolidate_bot(bot["id"], dry_run=dry_run)
    except MemoryValidationError as exc:  # pragma: no cover - defensive
        raise ValidationError(str(exc)) from None
    user = current_user(request)
    container.audit.log(
        actor_id=user["id"],
        actor_role=str(user.get("role") or "user"),
        action="memory.consolidated",
        target_type="bot",
        target_id=bot["id"],
        ip=client_ip(request),
        detail={
            "dry_run": dry_run,
            "merged_records": report.get("merged_records", 0),
            "decayed": len(report.get("decayed") or []),
            "forgotten": len(report.get("forgotten") or []),
        },
    )
    return ok(report)
