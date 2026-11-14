"""Admin endpoints (docs/API.md §5). All routes require ``role=admin``."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from ..appeals import appeals_of
from ..auth.oauth import OAUTH_PROVIDERS, OAUTH_SECRET_MASK, OAUTH_SETTINGS_KEY
from ..bans import bans_of
from ..errors import AppError, Forbidden, ValidationError
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


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
        "(SELECT balance FROM wallets w WHERE w.user_id = u.id) AS balance, "
        "(SELECT COALESCE(SUM(delta),0) FROM ledger l WHERE l.user_id = u.id AND delta > 0 AND type = 'grant') AS granted_points, "
        "(SELECT COALESCE(SUM(-delta),0) FROM ledger l WHERE l.user_id = u.id AND delta < 0) AS deducted_points, "
        "(SELECT COALESCE(used_tokens,0) FROM quotas q WHERE q.user_id = u.id) AS used_tokens "
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
                "granted_points": int(row.get("granted_points") or 0),
                "deducted_points": int(row.get("deducted_points") or 0),
                "used_tokens": int(row.get("used_tokens") or 0),
                "quota": container.auth.quota_for(row["id"]),
            }
        )
    # Batch-load pending appeals so the list can show the「有申诉」chip without N+1.
    user_ids = [item["id"] for item in items]
    pending_map: dict[str, Any] = {}
    appeal_count: dict[str, int] = {}
    if user_ids:
        placeholders = ",".join("?" for _ in user_ids)
        for appeal_row in container.db.query(
            f"SELECT * FROM appeals WHERE status = 'pending' "
            f"AND user_id IN ({placeholders}) ORDER BY created_at DESC, rowid DESC",
            user_ids,
        ):
            pending_map.setdefault(
                appeal_row["user_id"], appeals_of(container).serialize(appeal_row)
            )
        for count_row in container.db.query(
            f"SELECT user_id, COUNT(*) AS c FROM appeals "
            f"WHERE user_id IN ({placeholders}) GROUP BY user_id",
            user_ids,
        ):
            appeal_count[count_row["user_id"]] = int(count_row["c"] or 0)
    for item in items:
        item["pending_appeal"] = pending_map.get(item["id"])
        item["appeal_count"] = appeal_count.get(item["id"], 0)
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@routes.patch("/api/admin/users/{user_id}")
async def admin_patch_user(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    user_id = request.match_info["user_id"]
    if "status" in body and body["status"] is not None:
        status = str(body["status"])
        reason = str(body.get("reason") or "")
        if status == "disabled":
            await bans_of(container).ban_user(
                user_id,
                reason=reason,
                actor_id=admin["id"],
                ip=client_ip(request),
            )
        elif status == "active":
            await bans_of(container).unban_user(
                user_id,
                reason=reason,
                actor_id=admin["id"],
                ip=client_ip(request),
            )
        else:
            raise ValidationError("status 只能是 active 或 disabled", field="status")
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


# ------------------------------------------------------------- overview
@routes.get("/api/admin/sandbox")
async def admin_sandbox(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    from ..sandbox_policy import SETTINGS_KEY, detect_platform, normalize_policy

    raw = container.settings_store.get(SETTINGS_KEY, {}) or {}
    policy = normalize_policy(raw)
    platform_info = detect_platform()
    bots = []
    for row in container.db.query(
        "SELECT b.id, b.name, b.status, b.snapshot, u.email AS owner_email "
        "FROM bots b LEFT JOIN users u ON u.id = b.user_id "
        "WHERE b.status != 'deleted' ORDER BY b.created_at DESC"
    ):
        try:
            snapshot = json.loads(row["snapshot"] or "{}")
        except (TypeError, ValueError):
            snapshot = {}
        settings = snapshot.get("settings") or {}
        agent_enabled = settings.get("agent_enabled")
        if agent_enabled is None:
            agent_enabled = bool(policy["enabled"])
        effective = bool(policy["enabled"] and agent_enabled)
        runtime_override = str(settings.get("sandbox_runtime") or "")
        effective_runtime = policy["runtime"] if effective else "none"
        if effective and runtime_override in {"local", "sandbox"}:
            effective_runtime = runtime_override
        bots.append(
            {
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "owner_email": row["owner_email"] or "",
                "agent_enabled": bool(agent_enabled),
                "runtime": effective_runtime,
            }
        )
    return ok({"policy": policy, "platform": platform_info, "bots": bots})


@routes.put("/api/admin/sandbox")
async def admin_update_sandbox(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    from ..errors import ValidationError
    from ..sandbox_policy import (
        SETTINGS_KEY,
        config_patch,
        detect_platform,
        install_runtime_limits,
        validate_policy,
    )

    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    platform_info = detect_platform()
    try:
        policy = validate_policy(body.get("policy", body), platform_info=platform_info)
    except ValueError as exc:
        raise ValidationError(str(exc), field="policy") from None
    container.settings_store.set(SETTINGS_KEY, policy, actor_id=admin["id"])
    updated = 0
    for row in container.db.query(
        "SELECT id, conf_id, snapshot FROM bots "
        "WHERE status != 'deleted' AND conf_id != ''"
    ):
        try:
            snapshot = json.loads(row["snapshot"] or "{}")
        except (TypeError, ValueError):
            snapshot = {}
        settings = snapshot.get("settings") or {}
        agent_enabled = settings.get("agent_enabled")
        if agent_enabled is None:
            agent_enabled = bool(policy["enabled"])
        try:
            await container.port.update_config(
                row["conf_id"],
                config_patch(
                    policy,
                    agent_enabled=bool(agent_enabled),
                    runtime_override=str(settings.get("sandbox_runtime") or ""),
                ),
            )
            updated += 1
        except Exception:  # noqa: BLE001
            logger.warning("应用沙盒配置失败：%s", row["id"], exc_info=True)
    limits_installed = install_runtime_limits(policy)
    container.audit.log(
        actor_id=admin["id"], actor_role="admin", action="sandbox.updated",
        target_type="system", target_id="", ip=client_ip(request),
        detail={"policy": policy, "bots_updated": updated, "limits_installed": limits_installed},
    )
    return ok(
        {
            "policy": policy,
            "platform": platform_info,
            "bots_updated": updated,
            "limits_installed": limits_installed,
        }
    )


@routes.get("/api/admin/error-logs")
async def admin_error_logs(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    return ok(
        container.error_logs.list(
            page=page,
            page_size=page_size,
            level=(request.query.get("level") or "").strip() or None,
            q=(request.query.get("q") or "").strip() or None,
        )
    )


@routes.delete("/api/admin/error-logs")
async def admin_clear_error_logs(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    removed = container.error_logs.clear(older_than_days=30)
    container.audit.log(
        actor_id=admin["id"], actor_role="admin",
        action="error_logs.cleared", target_type="system", target_id="",
        ip=client_ip(request), detail={"removed": removed},
    )
    return ok({"removed": removed})


@routes.get("/api/admin/logs")
async def admin_backend_logs(request: web.Request) -> web.Response:
    require_admin(request)
    from ..observe import log_buffer

    buffer = log_buffer()
    if buffer is None:
        return ok({"items": [], "available": False})
    try:
        lines = int(request.query.get("lines", 200))
    except (TypeError, ValueError):
        lines = 200
    level = (request.query.get("level") or "").strip().upper()
    return ok({"items": buffer.tail(lines=lines, level=level), "available": True})


@routes.get("/api/admin/overview")
async def admin_overview(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    return ok(container.billing.overview())


# --------------------------------------------------------------- invites
@routes.post("/api/admin/invites")
async def admin_create_invite(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    try:
        max_uses = int(body.get("max_uses") or 1)
        ttl_hours = body.get("ttl_hours")
        if ttl_hours is not None:
            ttl_hours = int(ttl_hours)
    except (TypeError, ValueError):
        raise ValidationError("max_uses / ttl_hours 必须是整数") from None
    invite = container.invites.create(
        created_by=admin["id"],
        max_uses=max_uses,
        ttl_hours=ttl_hours,
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
def _log_access(container, admin, bot_row, resource, resource_id, ip, reason=""):
    container.db.execute(
        "INSERT INTO content_access_logs(admin_id, user_id, bot_id, resource, "
        "resource_id, reason, ip, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            admin["id"],
            bot_row["user_id"],
            bot_row["id"],
            resource,
            resource_id,
            reason,
            ip,
            container.clock.now(),
        ),
    )


def _owner_encrypted(container, bot_row) -> bool:
    user = container.db.query_one(
        "SELECT encryption_enabled, encryption_state FROM users WHERE id = ?",
        (bot_row["user_id"],),
    )
    if user is None:
        return False
    return bool(user["encryption_enabled"]) and user["encryption_state"] != "plaintext"


def _require_content_confirm(request: web.Request, container, bot_row) -> bool:
    """Encrypted tenants require an explicit confirmation before decryption."""
    if not _owner_encrypted(container, bot_row):
        return False
    value = (request.query.get("confirm") or "").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    raise AppError(
        "对方已启用加密，确定要查看吗？这将解密内容并记录本次访问（用户可见）。",
        code="confirmation_required",
        status=403,
        extra={"encrypted": True},
    )


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


@routes.get("/api/admin/users/{user_id}/encryption")
async def admin_user_encryption(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    user = container.auth.get_user(request.match_info["user_id"])
    if user is None:
        raise AppError("用户不存在", code="not_found", status=404)
    status = container.encryption.status(user["id"])
    return ok({"user_id": user["id"], **status})


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
    status = await container.encryption.start(
        user_id=user_id,
        enabled=True,
        actor_id=admin["id"],
        actor_role="admin",
        ip=client_ip(request),
        reason="admin_force_enable",
    )
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="user.encryption_forced_on",
        target_type="user",
        target_id=user_id,
        ip=client_ip(request),
    )
    return ok({"user_id": user_id, **status})


# ------------------------------------------------------------------ orders
@routes.get("/api/admin/orders")
async def admin_list_orders(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    return ok(container.billing.orders(page=page, page_size=page_size))


@routes.post("/api/admin/orders")
async def admin_create_order(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    try:
        credits = int(body.get("credits") or 0)
        amount = float(body.get("amount_cny") or 0)
    except (TypeError, ValueError):
        raise ValidationError("credits/amount_cny 必须是数字") from None
    result = container.billing.create_order(
        admin_id=admin["id"],
        user_id=str(body.get("user_id") or ""),
        credits=credits,
        amount_cny=amount,
        external_ref=body.get("external_ref"),
        note=str(body.get("note") or ""),
        ip=client_ip(request),
    )
    return ok(result, status=200 if result.get("idempotent") else 201)


@routes.post("/api/admin/orders/{order_id}/confirm")
async def admin_confirm_order(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    result = container.billing.confirm_order(
        order_id=request.match_info["order_id"],
        admin_id=admin["id"],
        ip=client_ip(request),
    )
    return ok(result)


@routes.post("/api/admin/ledger")
async def admin_adjust_ledger(request: web.Request) -> web.Response:
    """Manual add/deduct (writes ledger; never edits the balance directly)."""
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    try:
        delta = int(body.get("delta") or 0)
    except (TypeError, ValueError):
        raise ValidationError("delta 必须是整数", field="delta") from None
    result = container.billing.adjust(
        admin_id=admin["id"],
        user_id=str(body.get("user_id") or ""),
        delta=delta,
        reason=str(body.get("reason") or ""),
        idem_key=body.get("idem_key"),
        ip=client_ip(request),
    )
    return ok(result)


@routes.post("/api/admin/users/{user_id}/wallet/reconcile")
async def admin_reconcile_wallet(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    return ok(container.billing.reconcile(request.match_info["user_id"]))


# ---------------------------------------------------- redemption codes (M5)
def redemption_of(container):
    """Return the wired ``RedemptionService`` (lazy fallback for older roots)."""
    from ..redemption import RedemptionService

    service = getattr(container, "redemptions", None) or getattr(
        container, "redemption", None
    )
    if service is None:
        service = RedemptionService(
            container.db,
            audit=getattr(container, "audit", None),
            clock=getattr(container, "clock", None),
        )
        container.redemptions = service
    return service


def _metering_of(container):
    from ..metering import MeteringService

    service = getattr(container, "metering", None)
    if service is None:
        service = MeteringService(
            container.db,
            audit=getattr(container, "audit", None),
            clock=getattr(container, "clock", None),
            settings_store=getattr(container, "settings_store", None),
            catalog=getattr(container, "models", None),
        )
        container.metering = service
    return service


@routes.get("/api/admin/redemption-codes")
async def admin_list_redemption_codes(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    status = (request.query.get("status") or "").strip() or None
    return ok(
        redemption_of(container).list_codes(
            page=page, page_size=page_size, status=status
        )
    )


@routes.post("/api/admin/redemption-codes")
async def admin_create_redemption_codes(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    container = container_of(request)
    points = body.get("points")
    if points is None:
        points = body.get("credits")
    count = body.get("count")
    if count is None:
        count = body.get("quantity", 1)
    codes = redemption_of(container).generate(
        points=points,
        note=str(body.get("note") or ""),
        count=count,
        max_uses=body.get("max_uses", 1),
        expires_at=body.get("expires_at"),
        actor=admin["id"],
        ip=client_ip(request),
    )
    return ok({"codes": codes, "count": len(codes)}, status=201)


@routes.patch("/api/admin/redemption-codes/{identifier}")
async def admin_patch_redemption_code(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    container = container_of(request)
    service = redemption_of(container)
    disabled = bool(body.get("disabled", True))
    if disabled:
        item = service.disable(
            request.match_info["identifier"],
            actor_id=admin["id"],
            ip=client_ip(request),
        )
    else:
        item = service.set_disabled(
            request.match_info["identifier"],
            False,
            actor_id=admin["id"],
            ip=client_ip(request),
        )
    return ok({"disabled": item["disabled"], "code": item})


@routes.post("/api/admin/redemption-codes/{identifier}/disable")
async def admin_disable_redemption_code(request: web.Request) -> web.Response:
    """Console-compatible alias (POST …/{id-or-code}/disable)."""
    admin = require_admin(request)
    container = container_of(request)
    item = redemption_of(container).disable(
        request.match_info["identifier"],
        actor_id=admin["id"],
        ip=client_ip(request),
    )
    return ok({"disabled": True, "code": item})


@routes.delete("/api/admin/redemption-codes/{identifier}")
async def admin_delete_redemption_code(request: web.Request) -> web.Response:
    """Soft delete == disable (keeps already-granted ledger history)."""
    admin = require_admin(request)
    container = container_of(request)
    redemption_of(container).disable(
        request.match_info["identifier"],
        actor_id=admin["id"],
        ip=client_ip(request),
    )
    return ok({"deleted": True, "disabled": True})


@routes.post("/api/me/redeem")
async def redeem_code(request: web.Request) -> web.Response:
    user = current_user(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    result = redemption_of(container_of(request)).redeem(
        user["id"],
        str(body.get("code") or ""),
        ip=client_ip(request),
    )
    return ok(result)


# -------------------------------------------------- admin user detail (M5)
@routes.get("/api/admin/users/{user_id}")
async def admin_user_detail(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    user_id = request.match_info["user_id"]
    user = container.auth.get_user(user_id)
    if user is None:
        raise AppError("用户不存在", code="not_found", status=404)

    now = container.clock.now()
    quota = container.auth.quota_for(user_id)
    balance = int(
        container.db.scalar(
            "SELECT balance FROM wallets WHERE user_id = ?", (user_id,), 0
        )
        or 0
    )
    bots = [
        {
            **bot,
            "user_id": user_id,
            "owner_email": user.get("email", ""),
        }
        for bot in container.bots.list_for_user(user_id)
    ]
    summary = dict(_metering_of(container).usage_summary(user_id, days=30))
    summary["requests"] = summary.get("records", 0)
    by_bot = container.db.query(
        "SELECT u.bot_id AS bot_id, COALESCE(b.name, '') AS bot_name, "
        "COALESCE(SUM(u.points), 0) AS points, "
        "COALESCE(SUM(u.tokens_in + u.tokens_out), 0) AS tokens, "
        "COUNT(*) AS requests "
        "FROM usage_records u LEFT JOIN bots b ON b.id = u.bot_id "
        "WHERE u.user_id = ? AND u.created_at >= ? "
        "GROUP BY u.bot_id ORDER BY points DESC, u.bot_id ASC",
        (user_id, now - 30 * 86400),
    )
    for row in by_bot:
        row["points"] = int(row.get("points") or 0)
        row["tokens"] = int(row.get("tokens") or 0)
        row["requests"] = int(row.get("requests") or 0)
    recent_ledger = container.db.query(
        "SELECT id, delta, type, ref, note, created_at FROM ledger "
        "WHERE user_id = ? ORDER BY id DESC LIMIT 5",
        (user_id,),
    )
    usage = {"summary30d": summary, "summary": summary, "by_bot": by_bot}
    appeals = appeals_of(container)
    detail = {
        **container.auth.public_user(user),
        "pending_appeal": appeals.pending_for_user(user_id),
        "appeal_count": int(
            container.db.scalar(
                "SELECT COUNT(*) AS c FROM appeals WHERE user_id = ?", (user_id,), 0
            )
            or 0
        ),
        "bot_count": len(bots),
        "balance": balance,
        "wallet": {"balance": balance},
        "quota": quota,
        "bots": bots,
        "usage": usage,
        "recent_ledger": recent_ledger,
    }
    # ``user`` carries the full detail for the console drawer; the same
    # sections are also exposed at the top level for older API consumers.
    return ok({**detail, "user": detail})


@routes.get("/api/admin/users/{user_id}/usage")
async def admin_user_usage(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    user_id = request.match_info["user_id"]
    if container.auth.get_user(user_id) is None:
        raise AppError("用户不存在", code="not_found", status=404)
    page, page_size = _paging(request)
    service = _metering_of(container)
    data = service.usage_list(user_id, page=page, page_size=page_size)
    names = {
        row["id"]: row["name"]
        for row in container.db.query(
            "SELECT id, name FROM bots WHERE user_id = ?", (user_id,)
        )
    }
    for item in data.get("items", []):
        item["bot_name"] = names.get(item.get("bot_id", ""), "")
        item["tokens"] = int(item.get("tokens_in") or 0) + int(
            item.get("tokens_out") or 0
        )
        item["requests"] = 1
    summary = dict(service.usage_summary(user_id, days=30))
    summary["requests"] = summary.get("records", 0)
    data["summary"] = summary
    return ok(data)


# ------------------------------------------------- admin bot disable (M6)
async def _optional_body(request: web.Request) -> dict[str, Any]:
    """Notes on appeal approve/reject are optional; an empty body is fine."""
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - optional payload; middleware catches bad JSON
        return {}
    return body if isinstance(body, dict) else {}


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


# ------------------------------------------------ OAuth provider settings
def _oauth_callback_url(request: web.Request, config: dict[str, str]) -> str:
    if config.get("redirect_uri"):
        return str(config["redirect_uri"])
    return f"{request.url.origin()}/api/auth/oauth/github/callback"


def _masked_github(container, request: web.Request) -> dict[str, Any]:
    config = container.oauth.github_config()
    has_secret = bool(config["client_secret"])
    return {
        "client_id": config["client_id"],
        "client_secret": OAUTH_SECRET_MASK if has_secret else "",
        "redirect_uri": config["redirect_uri"],
        "has_secret": has_secret,
        # The current console reads ``has_client_secret``; keep both names so
        # older/newer clients can mask the field without an extra round-trip.
        "has_client_secret": has_secret,
        "enabled": container.oauth.github_enabled(),
        "callback_url": _oauth_callback_url(request, config),
    }


@routes.get("/api/admin/settings/oauth")
async def admin_get_oauth_settings(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    return ok({"github": _masked_github(container, request)})


@routes.put("/api/admin/settings/oauth")
async def admin_update_oauth_settings(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是对象")
    github = body.get("github")
    if not isinstance(github, dict):
        # The console sends a flat payload (``{client_id, client_secret,
        # redirect_uri, enabled}``); accept both shapes for compatibility.
        if any(
            key in body
            for key in ("client_id", "client_secret", "redirect_uri", "enabled")
        ):
            github = body
        else:
            raise ValidationError("github 配置不能为空", field="github")
    container = container_of(request)
    store = getattr(container, "settings_store", None)
    if store is None:
        raise AppError(
            "平台设置存储不可用", code="not_implemented", status=501
        )
    stored = store.get(OAUTH_SETTINGS_KEY)
    merged = dict(stored) if isinstance(stored, dict) else {}
    # Deep merge: only the keys present in the request change; the rest of the
    # stored configuration (including unknown future keys) is preserved.
    for key in ("client_id", "redirect_uri"):
        if key not in github:
            continue
        value = str(github.get(key) or "").strip()
        if value:
            merged[key] = value
        else:
            merged.pop(key, None)
    if "enabled" in github:
        merged["enabled"] = bool(github.get("enabled"))
    if "client_secret" in github:
        value = str(github.get("client_secret") or "").strip()
        if value == OAUTH_SECRET_MASK:
            pass  # masked placeholder: keep the stored secret untouched
        elif value:
            merged["client_secret"] = value
        else:
            merged.pop("client_secret", None)
    if merged:
        store.set(OAUTH_SETTINGS_KEY, merged, actor_id=admin["id"])
    else:
        store.delete(OAUTH_SETTINGS_KEY)
    config = container.oauth.github_config()
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action="oauth.settings_updated",
        target_type="platform",
        target_id=OAUTH_SETTINGS_KEY,
        ip=client_ip(request),
        # Never write the secret (or a reversible hint) into the audit log.
        detail={
            "provider": "github",
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "has_secret": bool(config["client_secret"]),
        },
    )
    return ok({"github": _masked_github(container, request)})


@routes.post("/api/admin/settings/oauth/test")
async def admin_test_oauth_settings(request: web.Request) -> web.Response:
    require_admin(request)
    body = await _optional_body(request)
    provider = str(body.get("provider") or "github").strip().lower()
    if provider not in OAUTH_PROVIDERS:
        raise ValidationError("不支持的第三方登录方式", field="provider")
    container = container_of(request)
    config = container.oauth.github_config()
    callback_url = _oauth_callback_url(request, config)
    missing: list[str] = []
    if not config["client_id"]:
        missing.append("client_id")
    if not config["client_secret"]:
        missing.append("client_secret")
    if not callback_url:
        missing.append("redirect_uri")
    if missing:
        raise ValidationError(
            "GitHub OAuth 配置不完整：" + "、".join(missing),
            field=missing[0],
            extra={"missing": missing},
        )
    return ok(
        {
            "provider": provider,
            "enabled": container.oauth.github_enabled(),
            "callback_url": callback_url,
        }
    )
