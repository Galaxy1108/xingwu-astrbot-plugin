"""Bot + QR + memory-stub endpoints (docs/API.md §3)."""

from __future__ import annotations

from aiohttp import web

from ..errors import AppError, NotFound, ValidationError
from .app import client_ip, container_of, current_user, ok, settings_of

routes = web.RouteTableDef()


def _with_qr(container, bot: dict) -> dict:
    session = container.qr.active_session(bot["id"])
    if session is not None:
        bot = dict(bot)
        bot["qr"] = session
    return bot


def _owned(container, request: web.Request, bot_id: str) -> dict:
    user = current_user(request)
    bot = container.bots.get_for_user(user["id"], bot_id)
    return bot


# ------------------------------------------------------------------ bots
@routes.get("/api/bots")
async def list_bots(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    items = [
        _with_qr(container, bot) for bot in container.bots.list_for_user(user["id"])
    ]
    return ok({"items": items})


@routes.post("/api/bots")
async def create_bot(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    bot = await container.bots.create(
        user_id=user["id"],
        name=str(body.get("name") or ""),
        template_id=str(body.get("template_id") or ""),
        platform=str(body.get("platform") or ""),
        ip=client_ip(request),
    )
    return ok({"bot": _with_qr(container, bot)}, status=201)


@routes.get("/api/bots/{bot_id}")
async def get_bot(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _owned(container, request, request.match_info["bot_id"])
    return ok({"bot": _with_qr(container, bot)})


@routes.patch("/api/bots/{bot_id}")
async def patch_bot(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    bot_id = request.match_info["bot_id"]
    bot = _owned(container, request, bot_id)
    if "name" in body and body["name"] is not None:
        bot = await container.bots.rename(
            user_id=user["id"],
            bot_id=bot_id,
            name=str(body["name"]),
            ip=client_ip(request),
        )
    if "enabled" in body and body["enabled"] is not None:
        bot = await container.bots.set_enabled(
            user_id=user["id"],
            bot_id=bot_id,
            enabled=bool(body["enabled"]),
            ip=client_ip(request),
        )
    return ok({"bot": _with_qr(container, bot)})


@routes.delete("/api/bots/{bot_id}")
async def delete_bot(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    bot_id = request.match_info["bot_id"]
    _owned(container, request, bot_id)
    await container.bots.delete(
        user_id=user["id"],
        bot_id=bot_id,
        confirm_name=str(body.get("confirm_name") or ""),
        ip=client_ip(request),
    )
    container.qr.cancel(bot_id)
    return ok({"deleted": True})


# -------------------------------------------------------------------- QR
@routes.post("/api/bots/{bot_id}/qr/start")
async def qr_start(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    qr = await container.qr.start(
        user_id=user["id"],
        bot_id=request.match_info["bot_id"],
        ip=client_ip(request),
    )
    return ok({"qr": qr})


@routes.get("/api/bots/{bot_id}/qr/poll")
async def qr_poll(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    qr = await container.qr.poll(
        user_id=user["id"],
        bot_id=request.match_info["bot_id"],
        ip=client_ip(request),
    )
    return ok({"qr": qr})


@routes.post("/api/bots/{bot_id}/qr/finalize")
async def qr_finalize(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    bot = await container.qr.finalize(
        user_id=user["id"],
        bot_id=request.match_info["bot_id"],
        ip=client_ip(request),
    )
    return ok({"bot": _with_qr(container, bot)})


# --------------------------------------------------------------- memories
def _memory_stub() -> dict:
    return {"items": [], "total": 0, "page": 1, "page_size": 20}


@routes.get("/api/bots/{bot_id}/memories")
async def list_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _owned(container, request, request.match_info["bot_id"])
    if not bot["memory_db"]:
        raise NotFound("该 Bot 尚未创建记忆库")
    return ok(_memory_stub())


@routes.get("/api/bots/{bot_id}/memories/{memory_id}")
async def get_memory(request: web.Request) -> web.Response:
    container = container_of(request)
    _owned(container, request, request.match_info["bot_id"])
    raise NotFound("记忆不存在")


@routes.patch("/api/bots/{bot_id}/memories/{memory_id}")
async def patch_memory(request: web.Request) -> web.Response:
    container = container_of(request)
    _owned(container, request, request.match_info["bot_id"])
    raise NotFound("记忆不存在")


@routes.delete("/api/bots/{bot_id}/memories/{memory_id}")
async def delete_memory(request: web.Request) -> web.Response:
    container = container_of(request)
    _owned(container, request, request.match_info["bot_id"])
    raise NotFound("记忆不存在")


@routes.post("/api/bots/{bot_id}/memories/search")
async def search_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    _owned(container, request, request.match_info["bot_id"])
    return ok({"items": []})


@routes.post("/api/bots/{bot_id}/memories/export")
async def export_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    _owned(container, request, request.match_info["bot_id"])
    raise AppError(
        "记忆导出将在 M2 提供", code="not_implemented", status=501
    )


@routes.post("/api/bots/{bot_id}/memories/import")
async def import_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    _owned(container, request, request.match_info["bot_id"])
    raise AppError(
        "记忆导入将在 M2 提供", code="not_implemented", status=501
    )


# ------------------------------------------------------------ dev helpers
# Enabled only when SAAS_DEV_MODE=true; used by the demo UI and E2E tests.
@routes.post("/api/dev/qr/{bot_id}/confirm")
async def dev_qr_confirm(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    if not settings.dev_mode:
        raise NotFound()
    user = current_user(request)
    bot = container.bots.get_for_user(user["id"], request.match_info["bot_id"])
    port = container.port
    if not hasattr(port, "simulate_scan_complete"):
        raise AppError("当前后端不支持模拟扫码", code="not_implemented", status=501)
    port.simulate_scan_complete(bot["id"])
    return ok({"bot_id": bot["id"], "status": "created"})


@routes.post("/api/dev/qr/{bot_id}/scanned")
async def dev_qr_scanned(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    if not settings.dev_mode:
        raise NotFound()
    user = current_user(request)
    bot = container.bots.get_for_user(user["id"], request.match_info["bot_id"])
    port = container.port
    if not hasattr(port, "simulate_scan"):
        raise AppError("当前后端不支持模拟扫码", code="not_implemented", status=501)
    port.simulate_scan(bot["id"])
    return ok({"bot_id": bot["id"], "status": "scanned"})


@routes.post("/api/dev/qr/{bot_id}/expire")
async def dev_qr_expire(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    if not settings.dev_mode:
        raise NotFound()
    user = current_user(request)
    bot = container.bots.get_for_user(user["id"], request.match_info["bot_id"])
    session = container.qr._sessions.get(bot["id"])
    if session is None:
        raise AppError("没有进行中的扫码会话", code="qr_expired", status=410)
    session.expires_at = container.qr.clock.now() - 1
    return ok({"bot_id": bot["id"], "expires_at": session.expires_at, "status": "expired"})
