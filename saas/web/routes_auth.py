"""Auth, session and read-only user endpoints (docs/API.md §1–§4)."""

from __future__ import annotations

from urllib.parse import urlencode

from aiohttp import web

from ..appeals import appeals_of
from ..errors import AppError, ValidationError
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


def _wants_json(request: web.Request) -> bool:
    return "application/json" in request.headers.get("Accept", "").lower()


def _session_payload(result: dict) -> dict:
    session = result.get("session") or {}
    return {
        "user": result["user"],
        "csrf_token": session.get("csrf_token", ""),
        "recovery_available": bool(result.get("recovery_available", False)),
    }


def _oauth_callback_url(request: web.Request, provider: str) -> str:
    return f"{request.url.origin()}/api/auth/oauth/{provider}/callback"



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
        password=body.get("password"),
        username=body.get("username"),
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


# ------------------------------------------------------------ password auth
@routes.post("/api/auth/password/register")
async def password_register(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    settings = settings_of(request)
    result = container.auth.register_with_password(
        invite=str(body.get("invite") or ""),
        username=str(body.get("username") or ""),
        password=str(body.get("password") or ""),
        display_name=str(body.get("display_name") or ""),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    response = ok(_session_payload(result))
    set_session_cookies(
        response, settings, result["session"], now=container.clock.now()
    )
    return response


@routes.post("/api/auth/password/login")
async def password_login(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    settings = settings_of(request)
    result = container.auth.password_login(
        str(body.get("identifier") or ""),
        str(body.get("password") or ""),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    response = ok(_session_payload(result))
    set_session_cookies(
        response, settings, result["session"], now=container.clock.now()
    )
    return response


@routes.post("/api/auth/password/reset/request")
async def password_reset_request(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    return ok(
        container.auth.request_password_reset(
            str(body.get("email") or ""), ip=client_ip(request)
        )
    )


@routes.post("/api/auth/password/reset")
async def password_reset(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    return ok(
        container.auth.reset_password(
            str(body.get("email") or ""),
            str(body.get("code") or ""),
            str(body.get("password") or ""),
            ip=client_ip(request),
        )
    )


# ---------------------------------------------------------- e-mail binding
@routes.post("/api/auth/email/bind/request")
async def email_bind_request(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    return ok(
        container.auth.request_email_bind(
            user["id"], str(body.get("email") or ""), ip=client_ip(request)
        )
    )


@routes.post("/api/auth/email/bind")
async def email_bind(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    updated = container.auth.bind_email(
        user["id"],
        str(body.get("email") or ""),
        str(body.get("code") or ""),
        ip=client_ip(request),
    )
    return ok({"user": container.auth.public_user(updated)})


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
    user_payload = container.auth.public_user(user)
    # The banned-user notice screen reads this to hide/disable the appeal form.
    user_payload["pending_appeal"] = appeals_of(container).pending_for_user(user["id"])
    response = ok(
        {
            "user": user_payload,
            "csrf_token": csrf_token,
            "limits": container.auth.quota_for(user["id"]),
            "version": settings.version,
            "astrbot_dashboard_url": settings.astrbot_dashboard_url,
            "is_admin": user.get("role") == "admin",
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
    return ok(
        {
            "balance": container.billing.balance(user["id"]),
            "currency": "points",
            "ledger_total": container.billing.recompute_balance(user["id"]),
        }
    )


@routes.get("/api/wallet/ledger")
async def wallet_ledger(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    page = max(1, int(request.query.get("page", 1)))
    page_size = min(100, max(1, int(request.query.get("page_size", 20))))
    return ok(container.billing.ledger(user["id"], page=page, page_size=page_size))


@routes.get("/api/wallet/usage")
async def wallet_usage(request: web.Request) -> web.Response:
    """Daily ledger in/out + running balance for the usage chart."""
    container = container_of(request)
    user = current_user(request)
    try:
        days = int(request.query.get("days", 14))
    except (TypeError, ValueError):
        raise ValidationError("days 必须是整数") from None
    return ok(container.billing.usage_series(user["id"], days=days))


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


def _encryption_payload(container, user_id: str) -> dict:
    status = container.encryption.status(user_id)
    job = status.get("job") or {}
    return {
        "enabled": status["enabled"],
        "state": status["state"],
        "changed_at": status.get("changed_at"),
        "done": job.get("done", 0),
        "total": job.get("total", 0),
        "percent": job.get("percent", 0),
        "eta": None,
        "job": job or None,
    }


@routes.patch("/api/me/profile")
async def update_profile(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    container = container_of(request)
    user = current_user(request)
    changed = {
        key: body[key]
        for key in ("display_name", "username")
        if key in body
    }
    updated = container.auth.update_profile(
        user["id"], ip=client_ip(request), **changed
    )
    return ok({"user": container.auth.public_user(updated)})


@routes.post("/api/me/password")
async def set_my_password(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    updated = container.auth.set_password(
        user["id"],
        str(body.get("new_password") or ""),
        current_password=(
            None
            if body.get("current_password") is None
            else str(body.get("current_password") or "")
        ),
        ip=client_ip(request),
    )
    return ok({"user": container.auth.public_user(updated)})


# ------------------------------------------------------------------ OAuth
@routes.get("/api/me/oauth")
async def my_oauth(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    return ok({"items": container.oauth.list_identities(user["id"])})


@routes.post("/api/me/oauth/{provider}/unbind")
async def unbind_oauth(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    return ok(
        container.oauth.unbind(
            user["id"],
            request.match_info["provider"],
            ip=client_ip(request),
        )
    )


@routes.get("/api/auth/oauth/providers")
async def oauth_providers(request: web.Request) -> web.Response:
    container = container_of(request)
    return ok({"providers": container.oauth.providers()})


@routes.get("/api/auth/oauth/{provider}/start")
async def oauth_start(request: web.Request) -> web.Response:
    container = container_of(request)
    provider = request.match_info["provider"]
    mode = (request.query.get("mode") or "login").strip()
    user_id = ""
    if mode == "bind":
        user = current_user(request)
        user_id = str(user["id"])
    result = container.oauth.start(
        provider,
        mode,
        user_id=user_id,
        invite=request.query.get("invite") or "",
        redirect=request.query.get("redirect") or "",
        callback_url=_oauth_callback_url(request, provider),
    )
    return ok(result)


@routes.get("/api/auth/oauth/{provider}/callback")
async def oauth_callback(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    provider = request.match_info["provider"]
    current = request.get("user") or {}
    try:
        result = await container.oauth.callback(
            provider,
            request.query.get("code") or "",
            request.query.get("state") or "",
            current_user_id=str(current.get("id") or ""),
            ip=client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            callback_url=_oauth_callback_url(request, provider),
        )
    except AppError as exc:
        if _wants_json(request):
            raise
        target = "/console/oauth/callback?" + urlencode({"error": exc.code})
        return web.HTTPFound(target)
    except Exception:  # noqa: BLE001 - never leak provider internals in redirects
        if _wants_json(request):
            raise
        target = "/console/oauth/callback?" + urlencode(
            {"error": "oauth_provider_error"}
        )
        return web.HTTPFound(target)

    session = result.get("session")
    if _wants_json(request):
        payload: dict = {
            "user": result["user"],
            "csrf_token": (session or {}).get("csrf_token", ""),
            "next": result.get("next") or "",
            "mode": result.get("mode") or "login",
            "is_new": bool(result.get("is_new")),
        }
        response: web.Response = ok(payload)
    else:
        params = {"ok": "1"}
        if result.get("next"):
            params["next"] = str(result["next"])
        response = web.HTTPFound(
            "/console/oauth/callback?" + urlencode(params)
        )
    if session:
        set_session_cookies(
            response, settings, session, now=container.clock.now()
        )
    return response



@routes.get("/api/me/encryption")
async def my_encryption(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    return ok(_encryption_payload(container, user["id"]))


@routes.get("/api/me/encryption/job")
async def my_encryption_job(request: web.Request) -> web.Response:
    container = container_of(request)
    user = current_user(request)
    return ok(_encryption_payload(container, user["id"]))


@routes.put("/api/me/encryption")
async def set_my_encryption(request: web.Request) -> web.Response:
    body = await request.json()
    container = container_of(request)
    user = current_user(request)
    enabled = bool(body.get("enabled", True))
    if not enabled:
        confirm = str(body.get("confirm") or "").strip()
        if confirm != "确认解密":
            raise ValidationError("请输入「确认解密」以继续", field="confirm")
    status = await container.encryption.start(
        user_id=user["id"],
        enabled=enabled,
        actor_id=user["id"],
        actor_role="user",
        ip=client_ip(request),
    )
    response = ok(_encryption_payload(container, user["id"]), status=202)
    return response


# ---------------------------------------------------------------- misc
@routes.get("/api/version")
async def version(request: web.Request) -> web.Response:
    settings = settings_of(request)
    return ok(
        {
            "version": settings.version,
            "dev_mode": bool(settings.dev_mode),
            "build": "0.5.0",
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


# --------------------------------------------------------------- appeals
@routes.get("/api/me/appeals")
async def my_appeals(request: web.Request) -> web.Response:
    user = current_user(request)
    container = container_of(request)
    return ok({"items": appeals_of(container).list_for_user(user["id"])})


@routes.post("/api/appeals")
async def create_appeal(request: web.Request) -> web.Response:
    """Available to banned users too (the ban gate allow-lists this path)."""
    user = current_user(request)
    body = await request.json()
    container = container_of(request)
    appeal = appeals_of(container).create(
        user["id"],
        str(body.get("target_type") or ""),
        str(body.get("target_id") or ""),
        str(body.get("reason") or ""),
        ip=client_ip(request),
    )
    return ok({"appeal": appeal}, status=201)
