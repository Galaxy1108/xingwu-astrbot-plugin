"""aiohttp console application: JSON API + static Vue console.

Run standalone (``scripts/dev_server.py``) or from the AstrBot plugin entry.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from ..config import Settings
from ..container import Container
from ..errors import AppError, CsrfError, Unauthorized

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {
    "/api/auth/otp/request",
    "/api/auth/otp/verify",
    "/api/version",
    "/healthz",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def ok(data: Any = None, *, status: int = 200, headers=None) -> web.Response:
    payload = {"ok": True, "data": {} if data is None else data}
    return web.json_response(payload, status=status, headers=headers)


def fail(error: AppError) -> web.Response:
    headers = {}
    if isinstance(error, CsrfError):
        headers["X-CSRF-Error"] = "1"
    return web.json_response(
        {"ok": False, "error": error.to_dict()}, status=error.status, headers=headers
    )


def container_of(request: web.Request) -> Container:
    return request.app["container"]


def settings_of(request: web.Request) -> Settings:
    return request.app["container"].settings


def current_user(request: web.Request) -> dict[str, Any]:
    user = request.get("user")
    if user is None:
        raise Unauthorized("请先登录")
    return user


def client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote or ""


# --------------------------------------------------------------------------
# middlewares
# --------------------------------------------------------------------------
@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except AppError as error:
        return fail(error)
    except web.HTTPException:
        raise
    except json.JSONDecodeError:
        return fail(AppError("请求体不是合法 JSON", code="validation_error", status=400))
    except Exception:  # noqa: BLE001
        logger.exception("未处理异常：%s %s", request.method, request.path)
        return fail(AppError("服务器内部错误，请稍后重试"))


@web.middleware
async def session_middleware(request: web.Request, handler):
    settings = settings_of(request)
    token = request.cookies.get(settings.cookie_name)
    request["session_token"] = token
    resolved = container_of(request).sessions.resolve(token)
    if resolved is not None:
        request["user"], request["session"] = resolved
    if request.path.startswith("/api") and request.path not in PUBLIC_PATHS:
        if request.get("user") is None:
            return fail(Unauthorized("登录已失效，请重新登录"))
    return await handler(request)


@web.middleware
async def csrf_middleware(request: web.Request, handler):
    if request.method not in UNSAFE_METHODS:
        return await handler(request)
    if request.path in PUBLIC_PATHS:
        return await handler(request)
    user = request.get("user")
    if user is None:
        return await handler(request)
    settings = settings_of(request)
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    session = request.get("session") or {}
    service = container_of(request).sessions
    if not (
        cookie_token
        and header_token
        and cookie_token == header_token
        and service.validate_csrf(session, cookie_token)
    ):
        return fail(CsrfError("CSRF 校验失败，请刷新页面重试"))
    return await handler(request)


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path.startswith("/console") or response.content_type == "text/html":
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self'; connect-src 'self'; "
            "font-src 'self' data: https://fonts.gstatic.com;",
        )
    return response


# --------------------------------------------------------------------------
# session cookies
# --------------------------------------------------------------------------
def set_session_cookies(
    response: web.Response,
    settings: Settings,
    session: dict[str, Any],
    *,
    now: int,
) -> None:
    max_age = max(0, int(session["absolute_expires_at"]) - int(now))
    response.set_cookie(
        settings.cookie_name,
        session["token"],
        max_age=max_age,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_same_site,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        session["csrf_token"],
        max_age=max_age,
        path="/",
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_same_site,
    )


def clear_session_cookies(response: web.Response, settings: Settings) -> None:
    for name in (settings.cookie_name, settings.csrf_cookie_name):
        response.del_cookie(
            name, path="/", secure=settings.cookie_secure, samesite=settings.cookie_same_site
        )


# --------------------------------------------------------------------------
# static console (history routing → index.html fallback)
# --------------------------------------------------------------------------
async def console_static(request: web.Request) -> web.StreamResponse:
    settings = settings_of(request)
    dist: Path = settings.console_dist
    tail = request.match_info.get("tail", "") or ""
    if not dist.exists():
        return web.Response(
            text=(
                "控制台未构建：请在 web/ 下执行 `npm install && npm run build`。\n"
                f"期望目录：{dist}"
            ),
            status=503,
            content_type="text/plain",
        )
    candidate = (dist / tail).resolve()
    if dist.resolve() not in candidate.parents and candidate != dist.resolve():
        raise web.HTTPNotFound()
    if tail and candidate.is_file():
        response = web.FileResponse(candidate)
        # Vite emits content-hashed assets; index.html must never be cached.
        if tail.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response
    index = dist / "index.html"
    if index.exists():
        response = web.FileResponse(index)
        response.headers["Cache-Control"] = "no-cache"
        return response
    raise web.HTTPNotFound()


async def root_redirect(request: web.Request) -> web.Response:
    raise web.HTTPFound("/console/")


# --------------------------------------------------------------------------
# app factory
# --------------------------------------------------------------------------
def create_app(container: Container) -> web.Application:
    app = web.Application(
        middlewares=[
            error_middleware,
            security_headers_middleware,
            session_middleware,
            csrf_middleware,
        ],
        client_max_size=2 * 1024 * 1024,
    )
    # Imported here to avoid a circular import with the route modules.
    from . import routes_admin, routes_auth, routes_bots

    app["container"] = container
    app.add_routes(routes_auth.routes)
    app.add_routes(routes_bots.routes)
    app.add_routes(routes_admin.routes)
    app.router.add_get("/", root_redirect)
    app.router.add_get("/console", root_redirect)
    app.router.add_get("/console/{tail:.*}", console_static)
    return app
