"""Shared helpers for the ``/api/admin/*`` route modules.

This module defines no routes. It is imported by ``routes_admin_*`` and by the
``routes_admin`` aggregator, so it must never import those modules back.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..errors import AppError, Forbidden
from .app import current_user


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


async def _optional_body(request: web.Request) -> dict[str, Any]:
    """Notes on appeal approve/reject are optional; an empty body is fine."""
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - optional payload; middleware catches bad JSON
        return {}
    return body if isinstance(body, dict) else {}


# -------------------------------------------------------------- content access
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


# ------------------------------------------------------------ lazy services
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
