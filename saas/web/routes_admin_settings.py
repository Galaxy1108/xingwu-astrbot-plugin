"""设置类：沙盒策略（含后台批量应用任务）、健康检查、错误日志、后端日志、邀请码、审计与访问日志、第三方登录配置（admin 路由）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from ..auth.oauth import OAUTH_PROVIDERS, OAUTH_SECRET_MASK, OAUTH_SETTINGS_KEY
from ..errors import AppError, ValidationError
from .admin_common import (
    _optional_body,
    _paging,
    require_admin,
)
from ..jobs import jobs_of
from .app import client_ip, container_of, ok

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


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


def _sandbox_targets(container, policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Bots whose AstrBot config must follow the sandbox policy (snapshot at save time)."""
    targets: list[dict[str, Any]] = []
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
        targets.append(
            {
                "bot_id": row["id"],
                "conf_id": row["conf_id"],
                "agent_enabled": bool(agent_enabled),
                "runtime_override": str(settings.get("sandbox_runtime") or ""),
            }
        )
    return targets


async def _apply_sandbox_job(
    container, job, *, policy: dict[str, Any], targets: list[dict[str, Any]], actor_id: str
) -> None:
    """Push the policy to every target bot; one bot's failure never stops the rest."""
    from ..sandbox_policy import config_patch

    store = jobs_of(container)
    for target in targets:
        try:
            await container.port.update_config(
                target["conf_id"],
                config_patch(
                    policy,
                    agent_enabled=target["agent_enabled"],
                    runtime_override=target["runtime_override"],
                ),
            )
        except Exception as exc:  # noqa: BLE001 - recorded on the job, not raised
            logger.warning("应用沙盒配置失败：%s", target["bot_id"], exc_info=True)
            # Only the exception type is exposed: messages may echo credentials.
            store.record_failure(job, target["bot_id"], f"应用失败（{type(exc).__name__}）")
            continue
        store.record_success(job)
    container.audit.log(
        actor_id=actor_id, actor_role="admin", action="sandbox.applied",
        target_type="system", target_id=job.id, ip="",
        detail={"job_id": job.id, "total": job.total, "done": job.done, "failed": job.failed},
    )


@routes.put("/api/admin/sandbox")
async def admin_update_sandbox(request: web.Request) -> web.Response:
    """Save + validate the policy synchronously; apply it to bots in the background (202)."""
    admin = require_admin(request)
    container = container_of(request)
    from ..sandbox_policy import (
        SETTINGS_KEY,
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
    limits_installed = install_runtime_limits(policy)
    targets = _sandbox_targets(container, policy)
    store = jobs_of(container)
    job = store.create("sandbox.apply", total=len(targets))
    store.start(
        job,
        lambda current: _apply_sandbox_job(
            container, current, policy=policy, targets=targets, actor_id=admin["id"]
        ),
    )
    container.audit.log(
        actor_id=admin["id"], actor_role="admin", action="sandbox.updated",
        target_type="system", target_id="", ip=client_ip(request),
        detail={
            "policy": policy,
            "bots_total": len(targets),
            "job_id": job.id,
            "limits_installed": limits_installed,
        },
    )
    return ok(
        {
            "job_id": job.id,
            "total": job.total,
            "status": job.status,
            "policy": policy,
            "platform": platform_info,
            "limits_installed": limits_installed,
        },
        status=202,
    )


@routes.get("/api/admin/sandbox/jobs/{job_id}")
async def admin_sandbox_job(request: web.Request) -> web.Response:
    require_admin(request)
    job = jobs_of(container_of(request)).get(request.match_info["job_id"])
    if job is None or job.kind != "sandbox.apply":
        raise AppError("任务不存在", code="not_found", status=404)
    return ok(job.snapshot())


@routes.get("/api/admin/health/detail")
async def admin_health_detail(request: web.Request) -> web.Response:
    require_admin(request)
    from .routes_auth import health_snapshot

    return ok(health_snapshot(container_of(request)))


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
