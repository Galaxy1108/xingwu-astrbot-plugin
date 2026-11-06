"""Bot lifecycle (FR-D): create with full rollback, enable/disable, rename, delete.

Creation order follows the proven ``easy_setup._create_bot_core`` sequence:
persona → config profile → UMO route → memory library → platform (disabled) →
registry. Every step is recorded so a failure can be rolled back completely.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from .audit import AuditService
from .clock import Clock, SystemClock
from .db import Database
from .errors import AppError, Conflict, NotFound, ValidationError
from .memory.storage.sqlcipher import MemoryStorage, MemoryStorageError
from .ports import AstrBotPort
from .templates import TemplateService

logger = logging.getLogger(__name__)

PLATFORM_TYPES = ("weixin_oc", "qq_official")
MAX_NAME_LENGTH = 32


class BotService:
    def __init__(
        self,
        db: Database,
        *,
        port: AstrBotPort,
        templates: TemplateService,
        memory: MemoryStorage,
        tenants,
        settings,
        audit: AuditService,
        clock: Clock | None = None,
    ) -> None:
        self.db = db
        self.port = port
        self.templates = templates
        self.memory = memory
        self.tenants = tenants
        self.settings = settings
        self.audit = audit
        self.clock = clock or SystemClock()

    # -- serialisation -------------------------------------------------
    @staticmethod
    def serialize(row: dict[str, Any]) -> dict[str, Any]:
        snapshot = {}
        try:
            snapshot = json.loads(row.get("snapshot") or "{}")
        except (TypeError, ValueError):
            snapshot = {}
        bound = bool(row.get("bound"))
        return {
            "id": row["id"],
            "name": row["name"],
            "platform": row["platform"],
            "status": row["status"],
            "template_id": row["template_id"],
            "template_name": snapshot.get("template_name", ""),
            "persona_name": row["persona_name"],
            "conf_id": row["conf_id"],
            "memory_db": row["memory_db"],
            "enabled": row["status"] == "ready",
            "bound": bound,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_active_at": row["last_active_at"],
            "qr": None,
        }

    def _fetch(self, bot_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT b.*, EXISTS(SELECT 1 FROM bot_bindings bb WHERE bb.bot_id = b.id) AS bound "
            "FROM bots b WHERE b.id = ?",
            (bot_id,),
        )

    def get(self, bot_id: str) -> dict[str, Any]:
        row = self._fetch(bot_id)
        if row is None or row["status"] == "deleted":
            raise NotFound("Bot 不存在")
        return BotService.serialize(row)

    def get_for_user(self, user_id: str, bot_id: str) -> dict[str, Any]:
        row = self._fetch(bot_id)
        # Cross-tenant access is a 404 (never reveal existence).
        if row is None or row["status"] == "deleted" or row["user_id"] != user_id:
            raise NotFound("Bot 不存在")
        return BotService.serialize(row)

    def _row_for_user(self, user_id: str, bot_id: str) -> dict[str, Any]:
        row = self._fetch(bot_id)
        if row is None or row["status"] == "deleted" or row["user_id"] != user_id:
            raise NotFound("Bot 不存在")
        return row

    # -- queries -------------------------------------------------------
    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT b.*, EXISTS(SELECT 1 FROM bot_bindings bb WHERE bb.bot_id = b.id) AS bound "
            "FROM bots b WHERE b.user_id = ? AND b.status != 'deleted' "
            "ORDER BY b.created_at DESC",
            (user_id,),
        )
        return [BotService.serialize(row) for row in rows]

    def list_all(self, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        total = int(
            self.db.scalar(
                "SELECT COUNT(*) AS c FROM bots WHERE status != 'deleted'", (), 0
            )
        )
        rows = self.db.query(
            "SELECT b.*, u.email AS owner_email, "
            "EXISTS(SELECT 1 FROM bot_bindings bb WHERE bb.bot_id = b.id) AS bound "
            "FROM bots b LEFT JOIN users u ON u.id = b.user_id "
            "WHERE b.status != 'deleted' ORDER BY b.created_at DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        )
        items = []
        for row in rows:
            item = BotService.serialize(row)
            item["owner_email"] = row.get("owner_email", "")
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def count_for_user(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) AS c FROM bots WHERE user_id = ? AND status != 'deleted'",
                (user_id,),
                default=0,
            )
        )

    # -- create --------------------------------------------------------
    async def create(
        self,
        *,
        user_id: str,
        name: str,
        template_id: str,
        platform: str,
        ip: str = "",
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ValidationError("Bot 名称需为 1–32 字符", field="name")
        if platform not in PLATFORM_TYPES:
            raise ValidationError("不支持的平台类型", field="platform")
        if not template_id:
            raise ValidationError("请选择预设模板", field="template_id")
        try:
            template = self.templates.get(template_id)
        except NotFound:
            raise ValidationError("模板不存在", field="template_id") from None
        if not template["enabled"]:
            raise AppError(
                "该模板已下架，不能新建 Bot",
                code="template_disabled",
                status=409,
                field="template_id",
            )
        quota = self._quota_for(user_id)
        if self.count_for_user(user_id) >= quota["max_bots"]:
            raise AppError(
                f"Bot 数量已达配额上限（{quota['max_bots']}）",
                code="quota_exceeded",
                status=409,
            )
        snapshot = self.templates.snapshot(template_id)
        bot_id = f"b_{uuid.uuid4().hex}"
        persona_name = f"saas_{bot_id}"
        conf_name = f"{name}-{bot_id[-6:]}"
        now = self.clock.now()
        # Register early so a crash leaves a recoverable "creating" row.
        self.db.execute(
            "INSERT INTO bots(id, user_id, name, template_id, platform, persona_name, "
            "conf_id, memory_db, status, snapshot, created_at, updated_at) "
            "VALUES (?,?,?,?,?,'','','','creating',?,?,?)",
            (
                bot_id,
                user_id,
                name,
                template_id,
                platform,
                json.dumps(snapshot, ensure_ascii=False),
                now,
                now,
            ),
        )
        created: dict[str, Any] = {
            "persona": False,
            "conf_id": None,
            "route": False,
            "memory": False,
            "platform": False,
        }
        try:
            await self.port.create_persona(
                bot_id=bot_id,
                bot_name=name,
                persona_name=persona_name,
                system_prompt=snapshot.get("persona_prompt", ""),
                begin_dialogs=list(snapshot.get("begin_dialogs") or []),
            )
            created["persona"] = True

            conf_id = await self.port.create_config(
                bot_id=bot_id,
                conf_name=conf_name,
                persona_name=persona_name,
                config_patch=dict(snapshot.get("config_patch") or {}),
            )
            created["conf_id"] = conf_id

            await self.port.bind_route(bot_id=bot_id, conf_id=conf_id)
            created["route"] = True

            key = self.tenants.memory_key(user_id, bot_id)
            memory_path = self.memory.create_library(
                bot_id, key=key, tenant_id=user_id
            )
            created["memory"] = True

            await self.port.create_platform(bot_id=bot_id, platform=platform)
            created["platform"] = True

            self.db.execute(
                "UPDATE bots SET persona_name = ?, conf_id = ?, memory_db = ?, "
                "status = 'pending_qr', updated_at = ? WHERE id = ?",
                (persona_name, conf_id, memory_path, self.clock.now(), bot_id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("创建 Bot %s 失败，开始回滚：%s", bot_id, exc, exc_info=True)
            await self._rollback(bot_id, created)
            self.db.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
            if isinstance(exc, AppError):
                raise
            raise AppError(
                "创建 Bot 失败，已回滚",
                code="internal_error",
                status=500,
            ) from exc
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="bot.created",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
            detail={"name": name, "platform": platform, "template_id": template_id},
        )
        return self.get(bot_id)

    def _quota_for(self, user_id: str) -> dict[str, int]:
        row = self.db.query_one("SELECT * FROM quotas WHERE user_id = ?", (user_id,))
        if row is None:
            return {"max_bots": 3, "monthly_tokens": 1_000_000, "max_memories": 2000}
        return {
            "max_bots": int(row["max_bots"]),
            "monthly_tokens": int(row["monthly_tokens"]),
            "max_memories": int(row["max_memories"]),
        }

    async def _rollback(self, bot_id: str, created: dict[str, Any]) -> None:
        """Best-effort reverse of every side effect; each step is independent."""
        if created.get("platform"):
            await self._safe(self.port.delete_platform, bot_id)
        if created.get("memory"):
            try:
                self.memory.delete_library(bot_id)
            except Exception:  # noqa: BLE001
                logger.warning("回滚记忆库失败：%s", bot_id, exc_info=True)
        if created.get("route"):
            await self._safe(self.port.unbind_route, bot_id)
        if created.get("conf_id"):
            await self._safe(self.port.delete_config, created["conf_id"])
        if created.get("persona"):
            await self._safe(self.port.delete_persona, f"saas_{bot_id}")

    @staticmethod
    async def _safe(func, *args) -> None:
        try:
            await func(*args)
        except Exception:  # noqa: BLE001
            logger.warning("回滚步骤失败：%s%s", func, args, exc_info=True)

    # -- mutations -----------------------------------------------------
    async def rename(
        self,
        *,
        user_id: str,
        bot_id: str,
        name: str,
        ip: str = "",
        actor_id: str | None = None,
        actor_role: str = "user",
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ValidationError("Bot 名称需为 1–32 字符", field="name")
        self._row_for_user(user_id, bot_id)
        self.db.execute(
            "UPDATE bots SET name = ?, updated_at = ? WHERE id = ?",
            (name, self.clock.now(), bot_id),
        )
        self.audit.log(
            actor_id=actor_id or user_id,
            actor_role=actor_role,
            action="bot.renamed",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
            detail={"name": name},
        )
        return self.get(bot_id)

    async def set_enabled(
        self,
        *,
        user_id: str,
        bot_id: str,
        enabled: bool,
        ip: str = "",
        actor_id: str | None = None,
        actor_role: str = "user",
    ) -> dict[str, Any]:
        row = self._row_for_user(user_id, bot_id)
        if row["status"] in {"creating", "deleting"}:
            raise Conflict("Bot 正在创建/删除中，请稍后", code="bot_state_invalid")
        if row["status"] == "pending_qr" and enabled:
            raise Conflict("请先完成扫码接入", code="bot_state_invalid")
        await self.port.set_platform_enabled(bot_id, bool(enabled))
        new_status = "ready" if enabled else "disabled"
        self.db.execute(
            "UPDATE bots SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, self.clock.now(), bot_id),
        )
        self.audit.log(
            actor_id=actor_id or user_id,
            actor_role=actor_role,
            action="bot.enabled" if enabled else "bot.disabled",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
        )
        return self.get(bot_id)

    async def delete(
        self,
        *,
        user_id: str,
        bot_id: str,
        confirm_name: str,
        ip: str = "",
        actor_id: str | None = None,
        actor_role: str = "user",
    ) -> None:
        row = self._row_for_user(user_id, bot_id)
        if (confirm_name or "").strip() != row["name"]:
            raise ValidationError("输入的 Bot 名称不一致", field="confirm_name")
        self.db.execute(
            "UPDATE bots SET status = 'deleting', updated_at = ? WHERE id = ?",
            (self.clock.now(), bot_id),
        )
        # Errors during cleanup must not leave a half-deleted bot registered.
        try:
            await self.port.set_platform_enabled(bot_id, False)
        except Exception:  # noqa: BLE001
            logger.warning("停用平台失败：%s", bot_id, exc_info=True)
        await self._safe(self.port.unbind_route, bot_id)
        if row.get("conf_id"):
            await self._safe(self.port.delete_config, row["conf_id"])
        if row.get("persona_name"):
            await self._safe(self.port.delete_persona, row["persona_name"])
        await self._safe(self.port.delete_platform, bot_id)
        try:
            self.memory.delete_library(bot_id)
        except Exception:  # noqa: BLE001
            logger.warning("删除记忆库失败：%s", bot_id, exc_info=True)
        self.db.execute("DELETE FROM bot_bindings WHERE bot_id = ?", (bot_id,))
        self.db.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        self.audit.log(
            actor_id=actor_id or user_id,
            actor_role=actor_role,
            action="bot.deleted",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
            detail={"name": row["name"]},
        )

    async def disable_all_for_user(self, user_id: str, *, ip: str = "") -> int:
        rows = self.db.query(
            "SELECT id FROM bots WHERE user_id = ? AND status IN ('ready','disabled')",
            (user_id,),
        )
        count = 0
        for row in rows:
            try:
                await self.port.set_platform_enabled(row["id"], False)
            except Exception:  # noqa: BLE001
                logger.warning("禁用用户 Bot 失败：%s", row["id"], exc_info=True)
            self.db.execute(
                "UPDATE bots SET status = 'disabled', updated_at = ? WHERE id = ?",
                (self.clock.now(), row["id"]),
            )
            count += 1
        if count:
            self.audit.log(
                actor_id="system",
                actor_role="system",
                action="bot.disabled_all",
                target_type="user",
                target_id=user_id,
                ip=ip,
                detail={"count": count},
            )
        return count

    # -- credentials ---------------------------------------------------
    async def store_credentials(
        self, *, bot_id: str, user_id: str, platform: str, credentials: dict[str, Any]
    ) -> None:
        cipher = self.tenants.get(user_id)
        encrypted = cipher.encrypt_bytes(
            json.dumps(credentials, ensure_ascii=False).encode("utf-8"),
            bot_id=bot_id,
            purpose="credential",
            record_id=bot_id,
        )
        now = self.clock.now()
        self.db.execute(
            "INSERT INTO bot_bindings(bot_id, platform, credential_cipher, bound_at, last_ok_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(bot_id) DO UPDATE SET platform = excluded.platform, "
            "credential_cipher = excluded.credential_cipher, bound_at = excluded.bound_at, "
            "last_ok_at = excluded.last_ok_at",
            (bot_id, platform, encrypted, now, now),
        )
        await self.port.apply_credentials(
            bot_id=bot_id, platform=platform, credentials=credentials
        )

    def mark_ready(self, bot_id: str) -> dict[str, Any]:
        self.db.execute(
            "UPDATE bots SET status = 'ready', updated_at = ?, last_active_at = ? "
            "WHERE id = ?",
            (self.clock.now(), self.clock.now(), bot_id),
        )
        return self.get(bot_id)

    # -- startup reconciliation ---------------------------------------
    def stale_creating_rows(self, older_than_seconds: int = 600) -> list[dict[str, Any]]:
        cutoff = self.clock.now() - older_than_seconds
        return self.db.query(
            "SELECT * FROM bots WHERE status = 'creating' AND updated_at < ?",
            (cutoff,),
        )
