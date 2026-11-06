"""Admin endpoints (docs/API.md §5). All routes require ``role=admin``."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..errors import AppError, Forbidden, ValidationError
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()


def require_admin(request: web.Request) -> dict[str, Any]:
    user = current_user(request)
    if user.get("role") != "admin":
        raise Forbidden("需要管理员权限")
    return user


def _paging(request: web.Request) -> tuple[int, int]:
    try:
        page = max(1, int(request.query.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(100, max(1, int(request.query.get("page_size", 20))))
    except (TypeError, ValueError):
        page_size = 20
    return page, page_size


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


# ----------------------------------------------------------------- users
@routes.get("/api/admin/users")
async def admin_list_users(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    q = (request.query.get("q") or "").strip()
    status = (request.query.get("status") or "").strip()
    where = ["u.status != 'deleted'"]
    params: list[Any] = []
    if q:
        where.append("u.email LIKE ?")
        params.append(f"%{q}%")
    if status in {"active", "disabled"}:
        where.append("u.status = ?")
        params.append(status)
    clause = " AND ".join(where)
    total = int(
        container.db.scalar(
            f"SELECT COUNT(*) AS c FROM users u WHERE {clause}", params, 0
        )
    )
    rows = container.db.query(
        "SELECT u.*, "
        "(SELECT COUNT(*) FROM bots b WHERE b.user_id = u.id AND b.status != 'deleted') AS bot_count, "
        "(SELECT balance FROM wallets w WHERE w.user_id = u.id) AS balance "
        f"FROM users u WHERE {clause} ORDER BY u.created_at DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    )
    items = []
    for row in rows:
        items.append(
            {
                **container.auth.public_user(row),
                "bot_count": int(row.get("bot_count") or 0),
                "balance": int(row.get("balance") or 0),
                "quota": container.auth.quota_for(row["id"]),
            }
        )
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@routes.patch("/api/admin/users/{user_id}")
async def admin_patch_user(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    user_id = request.match_info["user_id"]
    if "status" in body and body["status"] is not None:
        container.auth.set_user_status(
            user_id,
            str(body["status"]),
            actor_id=admin["id"],
            ip=client_ip(request),
        )
        if body["status"] == "disabled":
            await container.bots.disable_all_for_user(user_id, ip=client_ip(request))
    if "quota" in body and body["quota"] is not None:
        if not isinstance(body["quota"], dict):
            raise ValidationError("quota 必须是对象", field="quota")
        container.auth.update_quota(
            user_id, body["quota"], actor_id=admin["id"], ip=client_ip(request)
        )
    user = container.auth.get_user(user_id)
    if user is None:
        raise AppError("用户不存在", code="not_found", status=404)
    return ok({"user": container.auth.user_with_limits(user)})


# --------------------------------------------------------------- invites
@routes.post("/api/admin/invites")
async def admin_create_invite(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    invite = container.invites.create(
        created_by=admin["id"],
        max_uses=int(body.get("max_uses") or 1),
        ttl_hours=body.get("ttl_hours"),
        note=str(body.get("note") or ""),
    )
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="invite.created",
        target_type="invite",
        target_id=invite["code_hint"],
        ip=client_ip(request),
        detail={"max_uses": invite["max_uses"]},
    )
    return ok({"invite": invite}, status=201)


@routes.get("/api/admin/invites")
async def admin_list_invites(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    return ok(container.invites.list(page=page, page_size=page_size))


@routes.delete("/api/admin/invites/{code_prefix}")
async def admin_revoke_invite(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    revoked = container.invites.revoke(request.match_info["code_prefix"])
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="invite.revoked",
        target_type="invite",
        target_id=request.match_info["code_prefix"],
        ip=client_ip(request),
    )
    return ok({"revoked": revoked})


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


# ------------------------------------------------------------ audit/logs
@routes.get("/api/admin/audit")
async def admin_audit(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    return ok(
        container.audit.list(
            page=page,
            page_size=page_size,
            action=(request.query.get("action") or "").strip() or None,
            actor_id=(request.query.get("actor_id") or "").strip() or None,
            target_id=(request.query.get("target_id") or "").strip() or None,
        )
    )


@routes.get("/api/admin/access-log")
async def admin_access_log(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    return ok(container.audit.access_log(page=page, page_size=page_size))


# -------------------------------------------------------------- encryption
@routes.get("/api/admin/users/{user_id}/encryption")
async def admin_user_encryption(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    user = container.auth.get_user(request.match_info["user_id"])
    if user is None:
        raise AppError("用户不存在", code="not_found", status=404)
    return ok(
        {
            "user_id": user["id"],
            "enabled": bool(user.get("encryption_enabled", 1)),
            "state": user.get("encryption_state", "encrypted"),
        }
    )


@routes.put("/api/admin/users/{user_id}/encryption")
async def admin_set_encryption(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    enabled = bool(body.get("enabled", True))
    if not enabled:
        raise Forbidden("管理员不能关闭用户加密（只能强制开启）")
    user_id = request.match_info["user_id"]
    user = container.auth.get_user(user_id)
    if user is None:
        raise AppError("用户不存在", code="not_found", status=404)
    container.db.execute(
        "UPDATE users SET encryption_enabled = 1, encryption_state = 'encrypted', "
        "encryption_changed_at = ?, encryption_changed_by = ? WHERE id = ?",
        (container.clock.now(), admin["id"], user_id),
    )
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="user.encryption_forced_on",
        target_type="user",
        target_id=user_id,
        ip=client_ip(request),
    )
    return ok({"user_id": user_id, "enabled": True, "state": "encrypted"})


# ------------------------------------------------------------------ orders
@routes.post("/api/admin/orders")
async def admin_create_order(request: web.Request) -> web.Response:
    require_admin(request)
    raise AppError(
        "手动充值将在 M3 提供（本期只做额度账本模型）",
        code="not_implemented",
        status=501,
    )


@routes.post("/api/admin/orders/{order_id}/confirm")
async def admin_confirm_order(request: web.Request) -> web.Response:
    require_admin(request)
    raise AppError(
        "手动充值将在 M3 提供（本期只做额度账本模型）",
        code="not_implemented",
        status=501,
    )
