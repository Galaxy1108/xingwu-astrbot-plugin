"""用户管理：列表、状态/配额修改、详情、加密设置（admin 路由）。"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from ..appeals import appeals_of
from ..bans import bans_of
from ..errors import AppError, Forbidden, ValidationError
from .admin_common import (
    _metering_of,
    _paging,
    require_admin,
)
from .app import client_ip, container_of, ok

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


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
