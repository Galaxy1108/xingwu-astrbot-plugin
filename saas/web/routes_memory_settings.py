"""Admin memory API settings (embedding / rerank / recall behavior).

Routes
------
``GET  /api/admin/settings/memory``       full document, keys masked.
``PUT  /api/admin/settings/memory``       partial deep merge, masked key = keep.
``POST /api/admin/settings/memory/test``  real upstream probe (502 on failure).

The ``routes`` table is registered by ``saas.web.app.create_app`` (the Lead
owns that wiring); this module only depends on ``container.settings_store`` and
``container.audit``.

PUT ``api_key`` semantics (shared with the console form):
* omitted or ``••••••••`` → keep the stored key;
* ``""``                    → clear the key;
* any other string          → replace the key.

Secrets are never returned over HTTP: GET/PUT answer with a mask plus
``has_api_key``.  Audit details only record booleans/section names.
"""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web

from ..errors import AppError, Forbidden, ValidationError
from ..memory.retrieval.embedding import EmbeddingClient, MemoryApiError
from ..memory.retrieval.rerank import RerankClient
from ..memory.service import (
    MASKED_API_KEY,
    MEMORY_SETTINGS_KEY,
    mask_memory_settings,
    normalize_memory_settings,
)
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()

_REQUIRED = object()


# --------------------------------------------------------------------------
# permissions / settings access
# --------------------------------------------------------------------------
def require_admin(request: web.Request) -> dict[str, Any]:
    user = current_user(request)
    if user.get("role") != "admin":
        raise Forbidden("需要管理员权限")
    return user


def _settings_of(container: Any) -> dict[str, Any]:
    raw = container.settings_store.get(MEMORY_SETTINGS_KEY, {})
    return normalize_memory_settings(raw)


# --------------------------------------------------------------------------
# validation helpers
# --------------------------------------------------------------------------
def _bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValidationError(f"{field} 必须是布尔值", field=field)


def _int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{field} 必须是 {minimum}–{maximum} 的整数", field=field)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"{field} 必须是 {minimum}–{maximum} 的整数", field=field
        ) from None
    if number < minimum or number > maximum:
        raise ValidationError(
            f"{field} 必须是 {minimum}–{maximum} 的整数", field=field
        )
    return number


def _text(value: Any, field: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValidationError(f"{field} 过长（最多 {limit} 字符）", field=field)
    return text


def _url(value: Any, field: str) -> str:
    text = _text(value, field, limit=500)
    if text and not text.lower().startswith(("http://", "https://")):
        raise ValidationError(
            f"{field} 必须以 http:// 或 https:// 开头", field=field
        )
    return text


def _api_key(value: Any, field: str = "api_key") -> str | None:
    """Return the new key, ``""`` to clear, or ``None`` for 'keep stored'."""
    if value is None:
        return None
    text = str(value)
    if text == MASKED_API_KEY:
        return None
    text = text.strip()
    if len(text) > 4096:
        raise ValidationError("api_key 过长", field=field)
    return text


def _validated_embedding(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "enabled" in payload:
        result["enabled"] = _bool(payload["enabled"], "embedding.enabled")
    if "base_url" in payload:
        result["base_url"] = _url(payload["base_url"], "embedding.base_url")
    if "model" in payload:
        result["model"] = _text(payload["model"], "embedding.model", limit=200)
    if "dimensions" in payload:
        result["dimensions"] = _int(
            payload["dimensions"], "embedding.dimensions", 1, 8192
        )
    if "timeout_seconds" in payload:
        result["timeout_seconds"] = _int(
            payload["timeout_seconds"], "embedding.timeout_seconds", 1, 120
        )
    if "batch_size" in payload:
        result["batch_size"] = _int(
            payload["batch_size"], "embedding.batch_size", 1, 256
        )
    if "api_key" in payload:
        result["api_key"] = _api_key(payload["api_key"], "embedding.api_key")
    return result


def _validated_rerank(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "enabled" in payload:
        result["enabled"] = _bool(payload["enabled"], "rerank.enabled")
    if "base_url" in payload:
        result["base_url"] = _url(payload["base_url"], "rerank.base_url")
    if "model" in payload:
        result["model"] = _text(payload["model"], "rerank.model", limit=200)
    if "top_n" in payload:
        result["top_n"] = _int(payload["top_n"], "rerank.top_n", 1, 100)
    if "timeout_seconds" in payload:
        result["timeout_seconds"] = _int(
            payload["timeout_seconds"], "rerank.timeout_seconds", 1, 120
        )
    if "api_key" in payload:
        result["api_key"] = _api_key(payload["api_key"], "rerank.api_key")
    return result


def _validated_behavior(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    bounds = {
        "vector_candidate_limit": (1, 1000),
        "rerank_candidate_limit": (1, 1000),
        "rrf_k": (1, 100),
        "recall_top_k": (1, 50),
    }
    for key, (minimum, maximum) in bounds.items():
        if key in payload:
            result[key] = _int(payload[key], f"behavior.{key}", minimum, maximum)
    return result


def _merge_settings(
    current: dict[str, Any], body: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Deep-merge a validated PUT body over ``current``.

    Returns the merged document plus the names of sections that actually
    changed (for the audit trail).
    """
    merged = normalize_memory_settings(current)
    changed: list[str] = []
    validators = {
        "embedding": _validated_embedding,
        "rerank": _validated_rerank,
        "behavior": _validated_behavior,
    }
    for section, validator in validators.items():
        incoming = body.get(section, _REQUIRED)
        if incoming is _REQUIRED:
            continue
        if incoming is None:
            continue
        if not isinstance(incoming, dict):
            raise ValidationError(f"{section} 必须是对象", field=section)
        validated = validator(incoming)
        applied = False
        for key, value in validated.items():
            if value is None:  # masked api_key → keep stored value
                continue
            if merged[section].get(key) != value:
                merged[section][key] = value
                applied = True
        if applied:
            changed.append(section)
    return merged, changed


def _audit(
    container: Any,
    admin: dict[str, Any],
    request: web.Request,
    action: str,
    detail: dict[str, Any],
) -> None:
    container.audit.log(
        actor_id=admin["id"],
        actor_role="admin",
        action=action,
        target_type="setting",
        target_id=MEMORY_SETTINGS_KEY,
        ip=client_ip(request),
        detail=detail,
    )


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@routes.get("/api/admin/settings/memory")
async def get_memory_settings(request: web.Request) -> web.Response:
    require_admin(request)
    container = container_of(request)
    return ok(mask_memory_settings(_settings_of(container)))


@routes.put("/api/admin/settings/memory")
async def put_memory_settings(request: web.Request) -> web.Response:
    admin = require_admin(request)
    container = container_of(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    merged, changed = _merge_settings(_settings_of(container), body)
    container.settings_store.set(
        MEMORY_SETTINGS_KEY, merged, actor_id=admin["id"]
    )
    _audit(
        container,
        admin,
        request,
        "memory.settings_updated",
        {
            "sections": changed,
            "embedding_enabled": bool(merged["embedding"].get("enabled")),
            "rerank_enabled": bool(merged["rerank"].get("enabled")),
            "embedding_has_api_key": bool(merged["embedding"].get("api_key")),
            "rerank_has_api_key": bool(merged["rerank"].get("api_key")),
        },
    )
    return ok(mask_memory_settings(merged))


@routes.post("/api/admin/settings/memory/test")
async def test_memory_settings(request: web.Request) -> web.Response:
    admin = require_admin(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    kind = str(body.get("kind") or "").strip()
    if kind not in {"embedding", "rerank"}:
        raise ValidationError("kind 必须是 embedding 或 rerank", field="kind")

    container = container_of(request)
    settings = _settings_of(container)
    section = settings[kind]
    base_url = str(section.get("base_url") or "").strip()
    model = str(section.get("model") or "").strip()
    if not base_url or not model:
        raise ValidationError(f"请先配置 {kind} 的 base_url 与 model", field="base_url")

    started = time.monotonic()
    try:
        if kind == "embedding":
            client = EmbeddingClient(
                base_url=base_url,
                api_key=str(section.get("api_key") or ""),
                model=model,
                dimensions=int(section.get("dimensions") or 0),
                timeout_seconds=float(section.get("timeout_seconds") or 20),
                batch_size=int(section.get("batch_size") or 32),
            )
            try:
                vectors = await client.embed(["记忆设置连接测试"])
            finally:
                await client.close()
            dim = len(vectors[0]) if vectors and vectors[0] else 0
            result: dict[str, Any] = {
                "ok": True,
                "dim": dim,
                "message": f"连接成功（向量维度 {dim}）",
            }
        else:
            client = RerankClient(
                base_url=base_url,
                api_key=str(section.get("api_key") or ""),
                model=model,
                top_n=int(section.get("top_n") or 10),
                timeout_seconds=float(section.get("timeout_seconds") or 20),
            )
            try:
                results = await client.rerank(
                    "记忆检索连接测试",
                    ["用户喜欢喝咖啡", "用户住在杭州"],
                )
            finally:
                await client.close()
            result = {
                "ok": True,
                "count": len(results),
                "message": f"连接成功（返回 {len(results)} 条重排结果）",
            }
    except MemoryApiError as exc:
        _audit(
            container,
            admin,
            request,
            "memory.settings_tested",
            {"kind": kind, "ok": False},
        )
        raise AppError(
            f"{kind} 连接测试失败：{exc.public_message()}",
            code="upstream_error",
            status=502,
            extra={"ok": False},
        ) from None
    except Exception:  # noqa: BLE001 - never leak transport details/secrets
        _audit(
            container,
            admin,
            request,
            "memory.settings_tested",
            {"kind": kind, "ok": False},
        )
        raise AppError(
            f"{kind} 连接测试失败（连接错误）",
            code="upstream_error",
            status=502,
            extra={"ok": False},
        ) from None

    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    result["model"] = model
    _audit(
        container,
        admin,
        request,
        "memory.settings_tested",
        {"kind": kind, "ok": True},
    )
    return ok(result)


__all__ = ["routes"]
