"""Model catalog slice (M4): admin-managed model profiles, pricing and keys.

Design rules (handoff §4.9 / §5, docs/API.md §5):

* ``model_profiles`` is the only place a provider credential lives; it is
  sealed with :class:`~saas.crypto.KeyManager` using AAD ``model:{id}:v1`` so a
  ciphertext cannot be replayed under another profile id.
* HTTP serialisation never returns the plaintext key nor the sealed blob.  Admins
  see a mask + ``has_api_key``; regular users see neither key nor ``base_url``.
* Prices are points per 1K tokens and must be finite / non-negative.
"""

from __future__ import annotations

import inspect
import json
import math
import sqlite3
import time
from typing import Any, Awaitable, Callable

from .audit import AuditService
from .clock import Clock, SystemClock
from .crypto import CryptoError, KeyManager
from .db import Database
from .errors import AppError, NotFound, ValidationError
from .security import random_id

MASK = "••••••••"

ADMIN_FIELDS = (
    "id",
    "name",
    "provider",
    "base_url",
    "model",
    "points_per_1k_input",
    "points_per_1k_output",
    "currency",
    "enabled",
    "note",
    "created_by",
    "created_at",
    "updated_at",
)

PUBLIC_FIELDS = (
    "id",
    "name",
    "provider",
    "model",
    "points_per_1k_input",
    "points_per_1k_output",
    "currency",
    "enabled",
    "note",
    "created_at",
    "updated_at",
)

Prober = Callable[[str, str, dict[str, Any]], Awaitable[int] | int]


def aad_for(model_id: str) -> bytes:
    """Additional authenticated data binding a sealed key to one profile id."""
    return f"model:{model_id}:v1".encode()


def _clean_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _price(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{field} 必须是非负数字", field=field)
    try:
        price = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} 必须是非负数字", field=field) from None
    if not math.isfinite(price) or price < 0:
        raise ValidationError(f"{field} 必须是非负数字", field=field)
    return price


def _base_url(value: Any) -> str:
    url = str(value or "").strip()
    if len(url) > 500:
        raise ValidationError("base_url 过长", field="base_url")
    if url and not url.lower().startswith(("http://", "https://")):
        raise ValidationError(
            "base_url 必须以 http:// 或 https:// 开头", field="base_url"
        )
    return url


class ModelCatalogService:
    """CRUD for ``model_profiles`` with sealed API keys."""

    def __init__(
        self,
        db: Database,
        *,
        key_manager: KeyManager,
        audit: AuditService | None = None,
        clock: Clock | None = None,
        prober: Prober | None = None,
    ) -> None:
        self.db = db
        self.key_manager = key_manager
        self.audit = audit
        self.clock = clock or SystemClock()
        self.prober = prober

    # -- serialisation -------------------------------------------------
    @staticmethod
    def serialize(row: dict[str, Any], *, admin: bool = True) -> dict[str, Any]:
        item = {field: row.get(field) for field in (ADMIN_FIELDS if admin else PUBLIC_FIELDS)}
        item["enabled"] = bool(item.get("enabled"))
        if admin:
            has_key = bool(row.get("api_key_cipher"))
            item["has_api_key"] = has_key
            item["api_key"] = MASK if has_key else ""
        else:
            # Defence in depth: users must never see credential/base URL data.
            item.pop("api_key", None)
            item.pop("base_url", None)
        return item

    def _row(self, model_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM model_profiles WHERE id = ?", (model_id,)
        )
        if row is None:
            raise NotFound("模型不存在")
        return row

    # -- validation ----------------------------------------------------
    @staticmethod
    def _validate(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValidationError("请求体必须是 JSON 对象")
        cleaned: dict[str, Any] = {}
        if not partial or "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name or len(name) > 128:
                raise ValidationError("模型名称需为 1–128 字符", field="name")
            cleaned["name"] = name
        if not partial or "model" in payload:
            model = str(payload.get("model") or "").strip()
            if not model or len(model) > 200:
                raise ValidationError("model 不能为空（1–200 字符）", field="model")
            cleaned["model"] = model
        if "provider" in payload or not partial:
            provider = str(payload.get("provider") or "openai").strip() or "openai"
            if len(provider) > 64:
                raise ValidationError("provider 过长", field="provider")
            cleaned["provider"] = provider
        if "base_url" in payload:
            cleaned["base_url"] = _base_url(payload.get("base_url"))
        if "points_per_1k_input" in payload or not partial:
            cleaned["points_per_1k_input"] = _price(
                payload.get("points_per_1k_input", 0), "points_per_1k_input"
            )
        if "points_per_1k_output" in payload or not partial:
            cleaned["points_per_1k_output"] = _price(
                payload.get("points_per_1k_output", 0), "points_per_1k_output"
            )
        if "currency" in payload:
            currency = str(payload.get("currency") or "CNY").strip() or "CNY"
            if len(currency) > 8:
                raise ValidationError("currency 过长", field="currency")
            cleaned["currency"] = currency
        if "note" in payload:
            cleaned["note"] = str(payload.get("note") or "")[:500]
        if "enabled" in payload:
            cleaned["enabled"] = 1 if payload["enabled"] else 0
        return cleaned

    # -- CRUD ----------------------------------------------------------
    def get(self, model_id: str) -> dict[str, Any]:
        return self.serialize(self._row(model_id), admin=True)

    def list(
        self, *, enabled_only: bool = False, page: int = 1, page_size: int = 100
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        where = "WHERE enabled = 1" if enabled_only else ""
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) AS c FROM model_profiles {where}", (), 0
            )
        )
        rows = self.db.query(
            f"SELECT * FROM model_profiles {where} ORDER BY updated_at DESC, rowid DESC "
            "LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        )
        return {
            "items": [self.serialize(row, admin=True) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def public_list(self) -> list[dict[str, Any]]:
        """Enabled profiles only, without credentials or upstream URLs."""
        rows = self.db.query(
            "SELECT * FROM model_profiles WHERE enabled = 1 "
            "ORDER BY updated_at DESC, rowid DESC"
        )
        return [self.serialize(row, admin=False) for row in rows]

    def create(
        self, payload: dict[str, Any], *, actor_id: str = "", ip: str = ""
    ) -> dict[str, Any]:
        cleaned = self._validate(payload)
        model_id = random_id("m", 8)
        api_key = _clean_key(payload.get("api_key"))
        cipher = None
        if api_key:
            cipher = self.key_manager.wrap(
                json.dumps(api_key).encode("utf-8"), aad=aad_for(model_id)
            )
        now = self.clock.now()
        self.db.execute(
            "INSERT INTO model_profiles(id, name, provider, base_url, model, "
            "api_key_cipher, points_per_1k_input, points_per_1k_output, currency, "
            "enabled, note, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                model_id,
                cleaned["name"],
                cleaned.get("provider", "openai"),
                cleaned.get("base_url", ""),
                cleaned["model"],
                None if cipher is None else sqlite3.Binary(cipher),
                cleaned.get("points_per_1k_input", 0.0),
                cleaned.get("points_per_1k_output", 0.0),
                cleaned.get("currency", "CNY"),
                int(cleaned.get("enabled", 1)),
                cleaned.get("note", ""),
                actor_id,
                now,
                now,
            ),
        )
        self._audit(
            actor_id=actor_id,
            ip=ip,
            action="model.created",
            model_id=model_id,
            detail={
                "name": cleaned["name"],
                "model": cleaned["model"],
                "has_api_key": bool(api_key),
            },
        )
        return self.get(model_id)

    def update(
        self,
        model_id: str,
        payload: dict[str, Any],
        *,
        actor_id: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        self._row(model_id)
        cleaned = self._validate(payload, partial=True)
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in cleaned.items():
            assignments.append(f"{key} = ?")
            params.append(value)
        clear_key = bool(payload.get("clear_api_key")) and "api_key" not in payload
        if "api_key" in payload or clear_key:
            api_key = "" if clear_key else _clean_key(payload.get("api_key"))
            cipher = (
                self.key_manager.wrap(
                    json.dumps(api_key).encode("utf-8"), aad=aad_for(model_id)
                )
                if api_key
                else None
            )
            assignments.append("api_key_cipher = ?")
            params.append(None if cipher is None else sqlite3.Binary(cipher))
        if not assignments:
            return self.get(model_id)
        assignments.append("updated_at = ?")
        params.append(self.clock.now())
        params.append(model_id)
        self.db.execute(
            f"UPDATE model_profiles SET {', '.join(assignments)} WHERE id = ?", params
        )
        self._audit(
            actor_id=actor_id,
            ip=ip,
            action="model.updated",
            model_id=model_id,
            detail={
                "fields": sorted(cleaned)
                + (["api_key"] if ("api_key" in payload or clear_key) else [])
            },
        )
        return self.get(model_id)

    def delete(
        self, model_id: str, *, actor_id: str = "", ip: str = ""
    ) -> dict[str, Any]:
        """Soft delete: hide the profile but keep pricing/usage history intact.

        Matches the admin console contract (``web/src/api/admin.ts``): delete ==
        ``enabled=false``.  Re-enable with ``PATCH {"enabled": true}``.
        """
        self._row(model_id)
        self.db.execute(
            "UPDATE model_profiles SET enabled = 0, updated_at = ? WHERE id = ?",
            (self.clock.now(), model_id),
        )
        self._audit(
            actor_id=actor_id,
            ip=ip,
            action="model.deleted",
            model_id=model_id,
            detail={"soft_delete": True},
        )
        return {"deleted": True}

    # -- credentials ---------------------------------------------------
    def secret(self, model_id: str) -> str:
        """Return the decrypted API key. Internal use only — never serialise."""
        row = self._row(model_id)
        cipher = row.get("api_key_cipher")
        if not cipher:
            return ""
        try:
            raw = self.key_manager.unwrap(bytes(cipher), aad=aad_for(model_id))
            value = json.loads(raw.decode("utf-8"))
        except (CryptoError, ValueError, TypeError, UnicodeDecodeError):
            raise AppError("API Key 解密失败", code="internal_error", status=500) from None
        return str(value) if value else ""

    # -- connectivity probe --------------------------------------------
    async def test_connection(self, model_id: str) -> dict[str, Any]:
        """Probe ``base_url``; failures become a sanitised 502 ``upstream_error``."""
        row = self._row(model_id)
        base_url = str(row.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise ValidationError("未配置 base_url，无法探测", field="base_url")
        api_key = self.secret(model_id)
        started = time.monotonic()
        try:
            probe = self.prober or _http_probe
            outcome = probe(base_url, api_key, row)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            status = int(outcome)
        except AppError:
            raise
        except Exception:  # noqa: BLE001 - details may contain the key/URL
            raise AppError(
                "上游模型探测失败（连接错误）", code="upstream_error", status=502
            ) from None
        latency_ms = int((time.monotonic() - started) * 1000)
        if status >= 400:
            raise AppError(
                f"上游模型返回 HTTP {status}", code="upstream_error", status=502
            )
        return {
            "ok": True,
            "status": status,
            "latency_ms": latency_ms,
            "model": row.get("model", ""),
            "base_url": base_url,
        }

    # -- helpers -------------------------------------------------------
    def _audit(
        self,
        *,
        actor_id: str,
        ip: str,
        action: str,
        model_id: str,
        detail: dict[str, Any],
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            actor_id=actor_id,
            actor_role="admin" if actor_id else "system",
            action=action,
            target_type="model",
            target_id=model_id,
            ip=ip,
            detail=detail,
        )


async def _http_probe(base_url: str, api_key: str, row: dict[str, Any]) -> int:
    """Default probe: ``GET {base_url}/models`` with bearer auth."""
    import aiohttp

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{base_url}/models", headers=headers) as response:
            await response.read()
            return response.status
