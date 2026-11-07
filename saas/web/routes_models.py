"""Model catalog + usage metering HTTP routes (docs/API.md §5, M4).

``routes`` is registered by the composition root (``saas.web.app.create_app``);
the Lead owns that wiring.  The service accessors below prefer the wired
``container.models`` / ``container.metering`` attributes and fall back to
constructing them lazily so the routes also work in isolation (tests, dev
shell) without a container change.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..errors import Forbidden, ValidationError
from ..metering import MeteringService
from ..model_catalog import ModelCatalogService
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()


# --------------------------------------------------------------- services
def catalog_of(container: Any) -> ModelCatalogService:
    catalog = getattr(container, "models", None) or getattr(
        container, "model_catalog", None
    )
    if catalog is None:
        catalog = ModelCatalogService(
            container.db,
            key_manager=container.key_manager,
            audit=getattr(container, "audit", None),
            clock=getattr(container, "clock", None),
        )
        container.models = catalog
    return catalog


def metering_of(container: Any) -> MeteringService:
    metering = getattr(container, "metering", None)
    if metering is None:
        metering = MeteringService(
            container.db,
            audit=getattr(container, "audit", None),
            clock=getattr(container, "clock", None),
            settings_store=getattr(container, "settings_store", None),
            catalog=catalog_of(container),
        )
        container.metering = metering
    return metering


# ----------------------------------------------------------------- helpers
def require_admin(request: web.Request) -> dict[str, Any]:
    user = current_user(request)
    if user.get("role") != "admin":
        raise Forbidden("需要管理员权限")
    return user


def _paging(request: web.Request, *, default_size: int = 20) -> tuple[int, int]:
    try:
        page = max(1, int(request.query.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(100, max(1, int(request.query.get("page_size", default_size))))
    except (TypeError, ValueError):
        page_size = default_size
    return page, page_size


# ------------------------------------------------------------ admin: models
@routes.get("/api/admin/models")
async def admin_list_models(request: web.Request) -> web.Response:
    require_admin(request)
    page, page_size = _paging(request, default_size=100)
    enabled_only = str(request.query.get("enabled", "")).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return ok(
        catalog_of(container_of(request)).list(
            enabled_only=enabled_only, page=page, page_size=page_size
        )
    )


@routes.post("/api/admin/models")
async def admin_create_model(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    model = catalog_of(container).create(
        body, actor_id=admin["id"], ip=client_ip(request)
    )
    return ok({"model": model}, status=201)


@routes.patch("/api/admin/models/{model_id}")
async def admin_update_model(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    container = container_of(request)
    model = catalog_of(container).update(
        request.match_info["model_id"],
        body,
        actor_id=admin["id"],
        ip=client_ip(request),
    )
    return ok({"model": model})


@routes.delete("/api/admin/models/{model_id}")
async def admin_delete_model(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    result = catalog_of(container).delete(
        request.match_info["model_id"], actor_id=admin["id"], ip=client_ip(request)
    )
    return ok(result)


@routes.post("/api/admin/models/{model_id}/test")
async def admin_test_model(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    result = await catalog_of(container).test_connection(
        request.match_info["model_id"]
    )
    return ok(result)


# ---------------------------------------------------------- admin: usage
@routes.post("/api/admin/usage")
async def admin_record_usage(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    container = container_of(request)
    result = metering_of(container).record_usage(
        str(body.get("user_id") or ""),
        str(body.get("bot_id") or ""),
        str(body.get("model_id") or ""),
        body.get("tokens_in", 0),
        body.get("tokens_out", 0),
        ref=str(body.get("ref") or ""),
        idem_key=body.get("idem_key"),
        actor_id=admin["id"],
        ip=client_ip(request),
    )
    status = 200 if result.get("idempotent") else 201
    return ok(result, status=status)


@routes.get("/api/admin/usage")
async def admin_usage(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    page, page_size = _paging(request)
    user_id = (request.query.get("user_id") or "").strip() or None
    metering = metering_of(container)
    data = metering.usage_list(user_id, page=page, page_size=page_size)
    if user_id:
        data["summary"] = metering.usage_summary(user_id, days=30)
    return ok(data)


# ------------------------------------------------------------ user: models
@routes.get("/api/models")
async def list_models(request: web.Request) -> web.Response:
    current_user(request)  # authentication only
    container = container_of(request)
    return ok({"items": catalog_of(container).public_list()})


@routes.get("/api/me/usage")
async def my_usage(request: web.Request) -> web.Response:
    user = current_user(request)
    container = container_of(request)
    page, page_size = _paging(request)
    metering = metering_of(container)
    data = metering.usage_list(
        user["id"], page=page, page_size=page_size
    )
    data["summary"] = metering.usage_summary(user["id"], days=30)
    return ok(data)
