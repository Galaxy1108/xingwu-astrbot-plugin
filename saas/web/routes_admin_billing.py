"""计费：概览、订单、手动账本、钱包对账、兑换码、用户用量（admin 路由），以及普通用户兑换接口 /api/me/redeem。"""

from __future__ import annotations

import logging

from aiohttp import web

from ..errors import AppError, ValidationError
from .admin_common import (
    _metering_of,
    _paging,
    redemption_of,
    require_admin,
)
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


@routes.get("/api/admin/overview")
async def admin_overview(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    return ok(container.billing.overview())


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
