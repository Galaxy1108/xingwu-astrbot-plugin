"""Bot 管理：模板、AstrBot 配置档、Bot 列表/停用/删除、管理员停止、Bot 内容访问（会话/记忆/笔记）、申诉审核（admin 路由）。"""

from __future__ import annotations

import logging

from aiohttp import web

from ..appeals import appeals_of
from ..bans import bans_of
from ..errors import AppError, ValidationError
from .admin_common import (
    _log_access,
    _optional_body,
    _paging,
    _require_content_confirm,
    require_admin,
)
from .app import client_ip, container_of, ok

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


# ------------------------------------------------------------- templates
@routes.get("/api/admin/templates")
async def admin_list_templates(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    return ok({"items": container.templates.list()})


@routes.post("/api/admin/templates")
async def admin_create_template(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    template = container.templates.create(body, actor_id=admin["id"])
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="template.created",
        target_type="template",
        target_id=template["id"],
        ip=client_ip(request),
        detail={"name": template["name"]},
    )
    return ok({"template": template}, status=201)


@routes.patch("/api/admin/templates/{template_id}")
async def admin_update_template(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    template = container.templates.update(
        request.match_info["template_id"], body
    )
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="template.updated",
        target_type="template",
        target_id=template["id"],
        ip=client_ip(request),
    )
    return ok({"template": template})


@routes.delete("/api/admin/templates/{template_id}")
async def admin_delete_template(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    template = container.templates.disable(request.match_info["template_id"])
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="template.disabled",
        target_type="template",
        target_id=template["id"],
        ip=client_ip(request),
    )
    return ok({"deleted": True})


# ------------------------------------------------------ AstrBot profiles
@routes.get("/api/admin/conf-profiles")
async def admin_conf_profiles(request: web.Request) -> web.Response:
    """AstrBot configuration profiles that a template can clone from."""
    require_admin(request)
    container = container_of(request)
    try:
        items = await container.port.list_conf_profiles()
    except Exception:  # noqa: BLE001
        items = [{"id": "default", "name": "默认配置", "is_default": True}]
    if not items:
        items = [{"id": "default", "name": "默认配置", "is_default": True}]
    return ok({"items": items})


# ------------------------------------------------------------------ bots
@routes.get("/api/admin/bots")
async def admin_list_bots(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    return ok(container.bots.list_all(page=page, page_size=page_size))


@routes.post("/api/admin/bots/{bot_id}/disable")
async def admin_disable_bot(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    bot = await container.bots.set_enabled(
        user_id=row["user_id"],
        bot_id=bot_id,
        enabled=False,
        ip=client_ip(request),
        actor_id=admin["id"],
        actor_role="admin",
    )
    return ok({"bot": bot})


@routes.delete("/api/admin/bots/{bot_id}")
async def admin_delete_bot(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    await container.bots.delete(
        user_id=row["user_id"],
        bot_id=bot_id,
        confirm_name=str(body.get("confirm_name") or ""),
        ip=client_ip(request),
        actor_id=admin["id"],
        actor_role="admin",
    )
    container.qr.cancel(bot_id)
    return ok({"deleted": True})


@routes.get("/api/admin/bots/{bot_id}/conversations")
async def admin_bot_conversations(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    confirmed = _require_content_confirm(request, container, row)
    items = await container.conversations.list_for_bot(bot_id, decrypt=True)
    _log_access(
        container,
        admin,
        row,
        "conversation",
        bot_id,
        client_ip(request),
        "confirmed_encrypted" if confirmed else "",
    )
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="content.accessed",
        target_type="bot",
        target_id=bot_id,
        ip=client_ip(request),
        detail={"resource": "conversation", "forced_decrypt": confirmed},
    )
    return ok({"items": items, "total": len(items)})


@routes.get("/api/admin/bots/{bot_id}/memories")
async def admin_bot_memories(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    confirmed = _require_content_confirm(request, container, row)
    page, page_size = _paging(request)
    data = container.memory_api.list(
        bot_id,
        page=page,
        page_size=page_size,
        kind=(request.query.get("kind") or "").strip() or None,
        q=(request.query.get("q") or "").strip() or None,
        importance=int(request.query["importance"])
        if (request.query.get("importance") or "").strip().isdigit()
        else None,
    )
    _log_access(
        container,
        admin,
        row,
        "memory",
        bot_id,
        client_ip(request),
        "confirmed_encrypted" if confirmed else "",
    )
    return ok(data)


@routes.patch("/api/admin/bots/{bot_id}/memories/{memory_id}")
async def admin_patch_memory(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    _require_content_confirm(request, container, row)
    body = await request.json()
    from ..memory.service import MemoryValidationError

    try:
        item = container.memory_api.update(bot_id, int(request.match_info["memory_id"]), body)
    except (MemoryValidationError, ValueError) as exc:
        raise ValidationError(str(exc)) from None
    _log_access(
        container, admin, row, "memory", request.match_info["memory_id"], client_ip(request), "edit"
    )
    return ok({"memory": item})


@routes.delete("/api/admin/bots/{bot_id}/memories/{memory_id}")
async def admin_delete_memory(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    _require_content_confirm(request, container, row)
    container.memory_api.delete(bot_id, int(request.match_info["memory_id"]))
    _log_access(
        container, admin, row, "memory", request.match_info["memory_id"], client_ip(request), "delete"
    )
    return ok({"deleted": True})


@routes.post("/api/admin/bots/{bot_id}/memories/export")
async def admin_export_memories(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    if not body.get("confirm"):
        raise ValidationError("导出需要二次确认", field="confirm")
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    _require_content_confirm(request, container, row)
    data = container.memory_api.export(bot_id)
    _log_access(container, admin, row, "memory_export", bot_id, client_ip(request), "export")
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="memory.exported",
        target_type="bot",
        target_id=bot_id,
        ip=client_ip(request),
        detail={"count": data.get("count", 0)},
    )
    return ok(data)


@routes.get("/api/admin/bots/{bot_id}/notes")
async def admin_list_notes(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    confirmed = _require_content_confirm(request, container, row)
    page, page_size = _paging(request)
    data = container.memory_api.note_list(
        bot_id,
        page=page,
        page_size=page_size,
        q=(request.query.get("q") or "").strip() or None,
        tag=(request.query.get("tag") or "").strip() or None,
    )
    _log_access(
        container,
        admin,
        row,
        "note",
        bot_id,
        client_ip(request),
        "confirmed_encrypted" if confirmed else "",
    )
    return ok(data)


@routes.get("/api/admin/bots/{bot_id}/notes/{short_id}")
async def admin_read_note(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    _require_content_confirm(request, container, row)
    return ok(
        container.memory_api.note_read(
            bot_id,
            request.match_info["short_id"],
            offset=int(request.query.get("offset", 0)),
            limit=int(request.query.get("limit", 4000)),
        )
    )


@routes.delete("/api/admin/bots/{bot_id}/notes/{short_id}")
async def admin_delete_note(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    _require_content_confirm(request, container, row)
    container.memory_api.note_delete(bot_id, request.match_info["short_id"])
    _log_access(container, admin, row, "note_delete", bot_id, client_ip(request))
    return ok({"deleted": True})


@routes.post("/api/admin/bots/{bot_id}/memories/import")
async def admin_import_memories(request: web.Request) -> web.Response:
    from ..memory.export import import_bot

    admin = require_admin(request)
    container = container_of(request)
    bot_id = request.match_info["bot_id"]
    row = container.db.query_one("SELECT * FROM bots WHERE id = ?", (bot_id,))
    if row is None or row["status"] == "deleted":
        raise AppError("Bot 不存在", code="not_found", status=404)
    _require_content_confirm(request, container, row)
    body = await request.json()
    snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else body
    try:
        report = import_bot(
            container.memory_api, bot_id, snapshot, dry_run=bool(body.get("dry_run"))
        )
    except ValueError as exc:
        raise ValidationError(str(exc), field="snapshot") from None
    _log_access(container, admin, row, "memory_import", bot_id, client_ip(request))
    return ok(report)


@routes.patch("/api/admin/bots/{bot_id}")
async def admin_patch_bot(request: web.Request) -> web.Response:
    """Admin-level stop/start; independent from the owner's enabled toggle."""
    admin = require_admin(request)
    body = await request.json()
    if not isinstance(body, dict) or "disabled" not in body:
        raise ValidationError("disabled 不能为空", field="disabled")
    disabled = body.get("disabled")
    if not isinstance(disabled, bool):
        raise ValidationError("disabled 必须是布尔值", field="disabled")
    container = container_of(request)
    bot = await bans_of(container).set_bot_admin_disabled(
        request.match_info["bot_id"],
        disabled,
        str(body.get("reason") or ""),
        actor_id=admin["id"],
        ip=client_ip(request),
    )
    return ok({"bot": bot})


# ------------------------------------------------------- appeals (M6)
@routes.get("/api/admin/appeals")
async def admin_list_appeals(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    status = (request.query.get("status") or "").strip() or None
    return ok(
        appeals_of(container).list_admin(
            status=status, page=page, page_size=page_size
        )
    )


@routes.post("/api/admin/appeals/{appeal_id}/approve")
async def admin_approve_appeal(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await _optional_body(request)
    container = container_of(request)
    appeal = await appeals_of(container).approve(
        request.match_info["appeal_id"],
        admin_id=admin["id"],
        note=str(body.get("note") or ""),
        ip=client_ip(request),
    )
    return ok({"appeal": appeal})


@routes.post("/api/admin/appeals/{appeal_id}/reject")
async def admin_reject_appeal(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await _optional_body(request)
    container = container_of(request)
    appeal = await appeals_of(container).reject(
        request.match_info["appeal_id"],
        admin_id=admin["id"],
        note=str(body.get("note") or ""),
        ip=client_ip(request),
    )
    return ok({"appeal": appeal})
