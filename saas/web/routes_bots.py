"""Bot + QR + memory-stub endpoints (docs/API.md §3)."""

from __future__ import annotations

import json

from aiohttp import web

from ..errors import AppError, NotFound, ValidationError
from ..memory.service import MemoryValidationError
from .app import client_ip, container_of, current_user, ok, settings_of

routes = web.RouteTableDef()


def _with_sandbox(container, bot: dict) -> dict:
    from ..sandbox_policy import SETTINGS_KEY, detect_platform, normalize_policy

    policy = normalize_policy(container.settings_store.get(SETTINGS_KEY, {}))
    settings = dict(bot.get("settings") or {})
    agent_enabled = settings.get("agent_enabled")
    if agent_enabled is None:
        agent_enabled = bool(policy["enabled"])
    effective = bool(policy["enabled"] and agent_enabled)
    platform_info = detect_platform()
    bot = dict(bot)
    bot["sandbox"] = {
        "enabled": effective,
        "policy_enabled": bool(policy["enabled"]),
        "agent_enabled": bool(agent_enabled),
        "user_configurable": bool(policy["allow_user_config"]),
        "runtime": policy["runtime"] if effective else "none",
        "booter": policy["booter"],
        "platform": platform_info,
        "limits": policy["limits"],
        "require_admin": bool(policy["require_admin"]),
    }
    return bot


def _with_qr(container, bot: dict) -> dict:
    bot = _with_sandbox(container, bot)
    session = container.qr.active_session(bot["id"])
    if session is not None:
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
    if body.get("enabled") is True and bot.get("admin_disabled"):
        reason = str(bot.get("disabled_reason") or "")
        message = "该 Bot 已被管理员停用，不能自行启用"
        if reason:
            message = f"{message}：{reason}"
        raise AppError(message, code="admin_disabled", status=403, extra={"reason": reason})
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
    if "settings" in body:
        incoming = body.get("settings") or {}
        if not isinstance(incoming, dict):
            raise ValidationError("settings 必须是对象", field="settings")
        current = dict((bot.get("settings") or {}))
        patch_config: dict[str, Any] = {}
        if "agent_enabled" in incoming:
            from ..sandbox_policy import SETTINGS_KEY, config_patch, normalize_policy

            policy = normalize_policy(container.settings_store.get(SETTINGS_KEY, {}))
            if not policy["enabled"]:
                raise AppError("管理员尚未启用 Agent 能力", code="sandbox_disabled", status=409)
            if not policy["allow_user_config"]:
                raise AppError(
                    "Agent 能力由管理员统一管理，用户不能单独修改",
                    code="sandbox_locked",
                    status=403,
                )
            current["agent_enabled"] = bool(incoming["agent_enabled"])
            patch_config.update(config_patch(policy, agent_enabled=current["agent_enabled"]))
        if "streaming" in incoming:
            current["streaming"] = bool(incoming["streaming"])
            patch_config["provider_settings.streaming_response"] = current["streaming"]
        if "compression_max_turns" in incoming:
            try:
                turns = int(incoming["compression_max_turns"])
            except (TypeError, ValueError):
                raise ValidationError("compression_max_turns 必须是整数", field="settings") from None
            if turns < 1 or turns > 100:
                raise ValidationError("compression_max_turns 需在 1–100", field="settings")
            current["compression_max_turns"] = turns
            patch_config["agent_runner.config.compression.max_turns"] = turns
        if "compression_overflow_strategy" in incoming:
            strategy = str(incoming["compression_overflow_strategy"] or "")
            if strategy not in {"truncate_by_turns", "llm_compress"}:
                raise ValidationError("上下文压缩策略不合法", field="settings")
            current["compression_overflow_strategy"] = strategy
            patch_config["agent_runner.config.compression.overflow_strategy"] = strategy
        if patch_config:
            try:
                await container.port.update_config(bot["conf_id"], patch_config)
            except Exception as exc:  # noqa: BLE001
                raise AppError("保存 Bot 设置失败", code="config_update_failed", status=502) from exc
        snapshot = dict(bot.get("snapshot") or {})
        snapshot["settings"] = current
        container.db.execute(
            "UPDATE bots SET snapshot = ?, updated_at = ? WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), container.clock.now(), bot_id),
        )
        container.audit.log(
            actor_id=user["id"], actor_role=user.get("role", "user"),
            action="bot.settings_updated", target_type="bot", target_id=bot_id,
            ip=client_ip(request), detail={"settings": current},
        )
        bot = container.bots.get_for_user(user["id"], bot_id)
    if "model_profile_id" in body:
        profile_id = str(body.get("model_profile_id") or "").strip()
        if profile_id:
            profile = container.db.query_one(
                "SELECT id FROM model_profiles WHERE id = ? AND enabled = 1",
                (profile_id,),
            )
            if profile is None:
                raise ValidationError("模型配置不存在或已停用", field="model_profile_id")
        snapshot = dict(bot.get("snapshot") or {})
        snapshot["model_profile_id"] = profile_id
        container.db.execute(
            "UPDATE bots SET snapshot = ?, updated_at = ? WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), container.clock.now(), bot_id),
        )
        container.audit.log(
            actor_id=user["id"],
            actor_role=user.get("role", "user"),
            action="bot.model_updated",
            target_type="bot",
            target_id=bot_id,
            ip=client_ip(request),
            detail={"model_profile_id": profile_id},
        )
        bot = container.bots.get_for_user(user["id"], bot_id)
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
def _memory_store(container, request):
    bot = _owned(container, request, request.match_info["bot_id"])
    if not bot["memory_db"]:
        raise NotFound("该 Bot 尚未创建记忆库")
    return bot


@routes.get("/api/bots/{bot_id}/memories")
async def list_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _memory_store(container, request)
    try:
        page = int(request.query.get("page", 1))
        page_size = int(request.query.get("page_size", 20))
    except (TypeError, ValueError):
        raise ValidationError("page/page_size 必须是整数") from None
    data = container.memory_api.list(
        bot["id"],
        page=page,
        page_size=page_size,
        kind=(request.query.get("kind") or "").strip() or None,
        tag=(request.query.get("tag") or "").strip() or None,
        q=(request.query.get("q") or "").strip() or None,
    )
    return ok(data)


@routes.get("/api/bots/{bot_id}/memories/{memory_id}")
async def get_memory(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _memory_store(container, request)
    try:
        memory_id = int(request.match_info["memory_id"])
    except (TypeError, ValueError):
        raise ValidationError("memory_id 必须是整数") from None
    item = container.memory_api.get(bot["id"], memory_id)
    if item is None:
        raise NotFound("记忆不存在")
    return ok({"memory": item})


@routes.patch("/api/bots/{bot_id}/memories/{memory_id}")
async def patch_memory(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _memory_store(container, request)
    body = await request.json()
    try:
        memory_id = int(request.match_info["memory_id"])
        item = container.memory_api.update(bot["id"], memory_id, body)
    except MemoryValidationError as exc:
        raise ValidationError(str(exc)) from None
    except (TypeError, ValueError):
        raise ValidationError("memory_id 必须是整数") from None
    return ok({"memory": item})


@routes.delete("/api/bots/{bot_id}/memories/{memory_id}")
async def delete_memory(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _memory_store(container, request)
    try:
        memory_id = int(request.match_info["memory_id"])
        container.memory_api.delete(bot["id"], memory_id)
    except MemoryValidationError as exc:
        raise NotFound(str(exc)) from None
    except (TypeError, ValueError):
        raise ValidationError("memory_id 必须是整数") from None
    return ok({"deleted": True})


@routes.post("/api/bots/{bot_id}/memories/search")
async def search_memories(request: web.Request) -> web.Response:
    container = container_of(request)
    bot = _memory_store(container, request)
    body = await request.json()
    query = str(body.get("q") or body.get("query") or "").strip()
    if not query:
        raise ValidationError("请输入检索关键词", field="q")
    try:
        limit = int(body.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    data = container.memory_api.list(
        bot["id"],
        page=1,
        page_size=max(1, min(100, limit)),
        kind=body.get("kind"),
        q=query,
    )
    return ok(data)


@routes.post("/api/bots/{bot_id}/memories/export")
async def export_memories(request: web.Request) -> web.Response:
    from ..memory.export import export_bot

    container = container_of(request)
    bot = _memory_store(container, request)
    return ok(export_bot(container.memory_api, bot["id"]))


@routes.post("/api/bots/{bot_id}/memories/import")
async def import_memories(request: web.Request) -> web.Response:
    from ..memory.export import import_bot

    container = container_of(request)
    bot = _memory_store(container, request)
    body = await request.json()
    snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else body
    try:
        report = import_bot(
            container.memory_api,
            bot["id"],
            snapshot,
            dry_run=bool(body.get("dry_run")),
        )
    except ValueError as exc:
        raise ValidationError(str(exc), field="snapshot") from None
    return ok(report)


# ------------------------------------------------------------ dev helpers
# Enabled only when SAAS_DEV_MODE=true; used by the demo UI and E2E tests.
@routes.post("/api/dev/bots/{bot_id}/conversations")
async def dev_add_conversation(request: web.Request) -> web.Response:
    container = container_of(request)
    settings = settings_of(request)
    if not settings.dev_mode:
        raise NotFound()
    user = current_user(request)
    bot = container.bots.get_for_user(user["id"], request.match_info["bot_id"])
    body = await request.json()
    history = body.get("history")
    if not isinstance(history, list):
        history = [
            {"role": "user", "content": str(body.get("content") or "你好")},
            {"role": "assistant", "content": str(body.get("reply") or "你好，有什么可以帮你？")},
        ]
    cid = await container.conversations.add_conversation(
        bot_id=bot["id"], history=history, title=str(body.get("title") or "测试对话")
    )
    return ok({"conversation_id": cid})


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
