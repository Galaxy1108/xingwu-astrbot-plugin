"""Auth, session and read-only user endpoints (docs/API.md §1–§4)."""

from __future__ import annotations

from aiohttp import web

from ..errors import ValidationError
from ..security import random_token
from .app import (
    client_ip,
    clear_session_cookies,
    container_of,
    current_user,
    ok,
    set_session_cookies,
    settings_of,
)

routes = web.RouteTableDef()


def _set_csrf_cookie(
    response: web.Response, settings, token: str, session: dict, now: int
) -> None:
    max_age = max(0, int(session["absolute_expires_at"]) - int(now))
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=max_age,
        path="/",
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_same_site,
    )


def _ensure_csrf(request: web.Request, user: dict, session: dict) -> str:
    container = container_of(request)
    settings = settings_of(request)
    token = request.cookies.get(settings.csrf_cookie_name, "")
    if not token or not container.sessions.validate_csrf(session, token):
        token = random_token(32)
        container.sessions.set_csrf(session["id"], token)
    return token


# ---------------------------------------------------------------- auth
@routes.post("/api/auth/otp/request")
async def otp_request(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    data = container.auth.request_otp(
        str(body.get("email") or ""),
        invite=body.get("invite"),
        ip=client_ip(request),
    )
    return ok(data)


@routes.post("/api/auth/otp/verify")
async def otp_verify(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    settings = settings_of(request)
    result = container.auth.verify_otp(
        str(body.get("email") or ""),
        str(body.get("code") or ""),
        invite=body.get("invite"),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    response = ok(
        {
            "user": result["user"],
            "is_new": result["is_new"],
            "csrf_token": result["session"]["csrf_token"],
        }
    )
    set_session_cookies(
        response, settings, result["session"], now=container.clock.now()
    )
    return response


@routes.post("/api/auth/logout")
async def logout(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    user = request.get("user")
    container.auth.logout(request.get("session_token"), user=user)
    response = ok({})
    clear_session_cookies(response, settings)
    return response


@routes.get("/api/me")
async def me(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    user = current_user(request)
    session = request["session"]
    csrf_token = _ensure_csrf(request, user, session)
    response = ok(
        {
            "user": container.auth.public_user(user),
            "csrf_token": csrf_token,
            "limits": container.auth.quota_for(user["id"]),
            "version": settings.version,
        }
    )
    _set_csrf_cookie(
        response, settings, csrf_token, session, container.clock.now()
    )
    return response


# ------------------------------------------------------------ templates
@routes.get("/api/templates")
async def list_templates(request: web.Request) -> web.Response:
    container = container_of(request)
    current_user(request)
    return ok({"items": container.templates.list(enabled_only=True)})


# ------------------------------------------------------- wallet/read-only
@routes.get("/api/wallet")
async def wallet(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    row = container.db.query_one(
        "SELECT balance FROM wallets WHERE user_id = ?", (user["id"],)
    )
    return ok({"balance": int(row["balance"]) if row else 0, "currency": "points"})


@routes.get("/api/wallet/ledger")
async def wallet_ledger(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    page = max(1, int(request.query.get("page", 1)))
    page_size = min(100, max(1, int(request.query.get("page_size", 20))))
    total = int(
        container.db.scalar(
            "SELECT COUNT(*) AS c FROM ledger WHERE user_id = ?", (user["id"],), 0
        )
    )
    items = container.db.query(
        "SELECT id, delta, type, ref, note, created_at FROM ledger "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user["id"], page_size, (page - 1) * page_size),
    )
    return ok(
        {"items": items, "total": total, "page": page, "page_size": page_size}
    )


@routes.get("/api/access-log")
async def access_log(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    page = max(1, int(request.query.get("page", 1)))
    page_size = min(100, max(1, int(request.query.get("page_size", 20))))
    return ok(
        container.audit.access_log(
            page=page, page_size=page_size, user_id=user["id"]
        )
    )


@routes.get("/api/me/encryption")
async def my_encryption(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    return ok(
        {
            "enabled": bool(user.get("encryption_enabled", 1)),
            "state": user.get("encryption_state", "encrypted"),
            "done": 0,
            "total": 0,
            "eta": None,
        }
    )


# ---------------------------------------------------------------- misc
@routes.get("/api/version")
async def version(request: web.Request) -> web.Response:
    settings = settings_of(request)
    return ok(
        {
            "version": settings.version,
            "dev_mode": bool(settings.dev_mode),
            "build": "m1",
        }
    )


@routes.get("/healthz")
async def healthz(request: web.Request) -> web.Response:
    container = container_of(request)
    try:
        container.db.scalar("SELECT 1 AS ok")
        healthy = True
    except Exception:  # noqa: BLE001
        healthy = False
    return ok({"ok": healthy})
