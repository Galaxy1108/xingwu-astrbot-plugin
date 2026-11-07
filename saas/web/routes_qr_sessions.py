"""Pre-Bot QR onboarding endpoints (docs/API.md §3, new console flow).

``routes`` is registered by ``saas.web.app.create_app``; the service is built
lazily from the container so the composition root needs no extra wiring.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..errors import AppError, NotFound
from ..qr_sessions import QrSessionService
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()


def qr_sessions_of(container: Any) -> QrSessionService:
    service = getattr(container, "qr_sessions", None)
    if service is None:
        service = QrSessionService(
            container.db,
            bots=container.bots,
            port=container.port,
            settings=container.settings,
            audit=container.audit,
            clock=container.clock,
        )
        container.qr_sessions = service
    return service


# ------------------------------------------------------------------ sessions
@routes.post("/api/qr/sessions")
async def create_qr_session(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    data = await qr_sessions_of(container).create_session(
        user_id=user["id"],
        platform=str(body.get("platform") or ""),
        name=str(body.get("name") or ""),
        template_id=str(body.get("template_id") or ""),
        model_profile_id=str(body.get("model_profile_id") or ""),
        ip=client_ip(request),
    )
    return ok(data, status=201)


@routes.get("/api/qr/sessions/{session_id}")
async def get_qr_session(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    data = await qr_sessions_of(container).get_session(
        user_id=user["id"], session_id=request.match_info["session_id"]
    )
    return ok(data)


@routes.get("/api/qr/sessions/{session_id}/poll")
async def poll_qr_session(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    data = await qr_sessions_of(container).poll(
        user_id=user["id"],
        session_id=request.match_info["session_id"],
        ip=client_ip(request),
    )
    return ok(data)


@routes.post("/api/qr/sessions/{session_id}/finalize")
async def finalize_qr_session(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    bot = await qr_sessions_of(container).finalize(
        user_id=user["id"],
        session_id=request.match_info["session_id"],
        ip=client_ip(request),
    )
    return ok({"bot": bot})


@routes.delete("/api/qr/sessions/{session_id}")
async def cancel_qr_session(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    await qr_sessions_of(container).cancel(
        user_id=user["id"],
        session_id=request.match_info["session_id"],
        ip=client_ip(request),
    )
    return ok({"cancelled": True})


# ------------------------------------------------------------ dev helpers
async def _dev_temp_platform(container, request: web.Request) -> str:
    if not container.settings.dev_mode:
        raise NotFound()
    user = current_user(request)
    data = await qr_sessions_of(container).get_session(
        user_id=user["id"], session_id=request.match_info["session_id"]
    )
    return str(data["session"]["temp_platform_id"])


@routes.post("/api/dev/qr-sessions/{session_id}/scanned")
async def dev_qr_session_scanned(request: web.Request) -> web.Response:
    container = container_of(request)
    temp_id = await _dev_temp_platform(container, request)
    port = container.port
    if not hasattr(port, "simulate_scan"):
        raise AppError("当前后端不支持模拟扫码", code="not_implemented", status=501)
    port.simulate_scan(temp_id)
    return ok({"temp_platform_id": temp_id, "status": "scanned"})


@routes.post("/api/dev/qr-sessions/{session_id}/confirm")
async def dev_qr_session_confirm(request: web.Request) -> web.Response:
    container = container_of(request)
    temp_id = await _dev_temp_platform(container, request)
    port = container.port
    if not hasattr(port, "simulate_scan_complete"):
        raise AppError("当前后端不支持模拟扫码", code="not_implemented", status=501)
    port.simulate_scan_complete(temp_id)
    return ok({"temp_platform_id": temp_id, "status": "confirmed"})


@routes.post("/api/dev/qr-sessions/{session_id}/expire")
async def dev_qr_session_expire(request: web.Request) -> web.Response:
    container = container_of(request)
    service = qr_sessions_of(container)
    user = current_user(request)
    session_id = request.match_info["session_id"]
    if not container.settings.dev_mode:
        raise NotFound()
    await service.get_session(user_id=user["id"], session_id=session_id)
    service.db.execute(
        "UPDATE qr_sessions SET expires_at = ? WHERE id = ?",
        (container.clock.now() - 1, session_id),
    )
    return ok({"session_id": session_id, "status": "expired"})


__all__ = ["routes", "qr_sessions_of"]
