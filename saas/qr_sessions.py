"""Pre-Bot QR onboarding sessions.

The new console flow never creates a ``bots`` row until the provider confirms
the scan:

1. ``POST /api/qr/sessions`` registers a *temporary* AstrBot platform
   (``temp_platform_id = "qrs_<session id>"``) and requests a QR for it.
2. ``poll`` only synchronises ``pending → scanned → confirmed`` (provider
   "created" is exposed as ``confirmed``) and keeps credentials in memory.
3. ``finalize`` reuses :meth:`BotService.create` to build the real Bot, copies
   the temporary platform config over it, encrypts the credentials and removes
   the temporary platform + session.

The DB row (``qr_sessions``) is the durable ownership/status record; challenge
payloads/credentials stay in memory, so after a process restart an orphaned
session is reported ``expired`` and its temporary platform is cleaned up.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditService
from .bots import MAX_NAME_LENGTH, PLATFORM_TYPES, BotService
from .clock import Clock, SystemClock
from .config import Settings
from .db import Database
from .errors import AppError, Conflict, NotFound, ValidationError
from .ports import AstrBotPort
from .qr import qr_data_url

logger = logging.getLogger(__name__)

SESSION_STATUSES = ("pending", "scanned", "confirmed", "expired", "cancelled")
_TERMINAL = {"expired", "cancelled"}


@dataclass
class _LiveSession:
    payload: dict[str, Any]
    content: str
    image: str
    interval: int
    challenge_expires_at: int
    refresh_count: int = 0
    last_poll_at: int = 0
    credentials: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class QrSessionService:
    """Owns temporary QR platforms and turns a confirmed scan into a Bot."""

    def __init__(
        self,
        db: Database,
        *,
        bots: BotService,
        port: AstrBotPort,
        settings: Settings,
        audit: AuditService,
        clock: Clock | None = None,
    ) -> None:
        self.db = db
        self.bots = bots
        self.port = port
        self.settings = settings
        self.audit = audit
        self.clock = clock or SystemClock()
        self._live: dict[str, _LiveSession] = {}

    # -- helpers -------------------------------------------------------
    def _now(self) -> int:
        return self.clock.now()

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    def _row(self, session_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM qr_sessions WHERE id = ?", (session_id,)
        )

    def _owned_row(self, user_id: str, session_id: str) -> dict[str, Any]:
        row = self._row(session_id)
        if row is None or row["user_id"] != user_id:
            raise NotFound("扫码会话不存在")
        return row

    def _set_status(self, session_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE qr_sessions SET status = ? WHERE id = ?", (status, session_id)
        )

    async def _safe_delete_platform(self, platform_id: str) -> None:
        try:
            await self.port.delete_platform(platform_id)
        except Exception:  # noqa: BLE001
            logger.warning("删除临时扫码平台失败：%s", platform_id, exc_info=True)

    def _challenge_payload(
        self, row: dict[str, Any], live: _LiveSession | None, *, message: str = ""
    ) -> dict[str, Any]:
        qr = {
            "id": row["id"],
            "status": row["status"],
            "qr_content": live.content if live is not None else "",
            "qr_image": live.image if live is not None else "",
            "expires_at": (
                live.challenge_expires_at if live is not None else row["expires_at"]
            ),
            "refresh_count": live.refresh_count if live is not None else 0,
            "interval": live.interval if live is not None else self.settings.qr_poll_interval,
            "message": (message or (live.message if live is not None else "")),
        }
        session = {
            "id": row["id"],
            "status": row["status"],
            "platform": row["platform"],
            "name": row["name"],
            "template_id": row["template_id"],
            "temp_platform_id": row["temp_platform_id"],
            "created_at": int(row["created_at"]),
            "expires_at": int(row["expires_at"]),
            "qr": qr,
        }
        return {"session": session, "qr": qr}

    async def _new_challenge(self, row: dict[str, Any], live: _LiveSession) -> None:
        challenge = await self.port.request_qr(
            bot_id=row["temp_platform_id"], platform=row["platform"]
        )
        live.payload = dict(challenge.payload or {})
        live.content = challenge.content
        image = challenge.image or ""
        if image and not image.startswith("data:"):
            image = "data:image/png;base64," + image
        live.image = image or qr_data_url(challenge.content)
        live.interval = int(challenge.interval or self.settings.qr_poll_interval)
        live.challenge_expires_at = self._now() + self.settings.qr_ttl_seconds

    async def _expire(
        self, row: dict[str, Any], live: _LiveSession | None, message: str
    ) -> dict[str, Any]:
        self._set_status(row["id"], "expired")
        await self._safe_delete_platform(row["temp_platform_id"])
        self._live.pop(row["id"], None)
        row = dict(row)
        row["status"] = "expired"
        return self._challenge_payload(row, live, message=message)

    # -- public API ----------------------------------------------------
    async def create_session(
        self,
        *,
        user_id: str,
        platform: str,
        name: str,
        template_id: str,
        model_profile_id: str = "",
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
            template = self.bots.templates.get(template_id)
        except NotFound:
            raise ValidationError("模板不存在", field="template_id") from None
        if not template["enabled"]:
            raise AppError(
                "该模板已下架，不能新建 Bot",
                code="template_disabled",
                status=409,
                field="template_id",
            )
        quota = self.bots.quota_for(user_id)
        if self.bots.count_for_user(user_id) >= quota["max_bots"]:
            raise AppError(
                f"Bot 数量已达配额上限（{quota['max_bots']}）",
                code="quota_exceeded",
                status=409,
            )
        model_profile_id = str(model_profile_id or "").strip()
        if model_profile_id:
            profile = self.db.query_one(
                "SELECT id FROM model_profiles WHERE id = ? AND enabled = 1",
                (model_profile_id,),
            )
            if profile is None:
                raise ValidationError("模型配置不存在或已停用", field="model_profile_id")

        session_id = self._new_id()
        temp_platform_id = f"qrs_{session_id}"
        now = self._now()
        ttl = max(
            self.settings.qr_ttl_seconds * (self.settings.qr_max_refreshes + 1),
            self.settings.qr_idle_timeout_seconds,
        )
        created = False
        try:
            await self.port.create_platform(
                bot_id=temp_platform_id, platform=platform
            )
            challenge = await self.port.request_qr(
                bot_id=temp_platform_id, platform=platform
            )
            image = challenge.image or ""
            if image and not image.startswith("data:"):
                image = "data:image/png;base64," + image
            live = _LiveSession(
                payload=dict(challenge.payload or {}),
                content=challenge.content,
                image=image or qr_data_url(challenge.content),
                interval=int(challenge.interval or self.settings.qr_poll_interval),
                challenge_expires_at=now + self.settings.qr_ttl_seconds,
                last_poll_at=now,
            )
            self.db.execute(
                "INSERT INTO qr_sessions(id, user_id, platform, name, template_id, "
                "model_profile_id, temp_platform_id, status, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                (
                    session_id,
                    user_id,
                    platform,
                    name,
                    template_id,
                    model_profile_id,
                    temp_platform_id,
                    now,
                    now + ttl,
                ),
            )
            created = True
            self._live[session_id] = live
        except Exception as exc:  # noqa: BLE001
            await self._safe_delete_platform(temp_platform_id)
            if isinstance(exc, AppError):
                raise
            logger.error("发起扫码会话失败", exc_info=True)
            raise AppError(
                "发起扫码失败，请稍后重试", code="qr_failed", status=500
            ) from exc
        if not created:  # pragma: no cover - defensive
            raise AppError("发起扫码失败", code="qr_failed", status=500)

        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="qr_session.created",
            target_type="qr_session",
            target_id=session_id,
            ip=ip,
            detail={"platform": platform, "name": name, "template_id": template_id,
                    "model_profile_id": model_profile_id},
        )
        row = self._row(session_id) or {}
        return self._challenge_payload(row, self._live.get(session_id))

    async def get_session(self, *, user_id: str, session_id: str) -> dict[str, Any]:
        row = self._owned_row(user_id, session_id)
        return self._challenge_payload(row, self._live.get(session_id))

    async def poll(
        self, *, user_id: str, session_id: str, ip: str = ""
    ) -> dict[str, Any]:
        row = self._owned_row(user_id, session_id)
        live = self._live.get(session_id)
        now = self._now()
        if live is None:
            if row["status"] not in _TERMINAL:
                return await self._expire(
                    row, None, "扫码会话已失效，请重新发起"
                )
            return self._challenge_payload(row, None)

        live.last_poll_at = now
        if row["status"] in _TERMINAL:
            return self._challenge_payload(row, live)
        if row["status"] == "confirmed":
            return self._challenge_payload(row, live)
        if now >= int(row["expires_at"]):
            return await self._expire(row, live, "扫码会话已过期，请重新发起")

        # Local QR TTL: refresh a handful of times while still pending.
        if row["status"] == "pending" and now >= live.challenge_expires_at:
            if live.refresh_count >= self.settings.qr_max_refreshes:
                return await self._expire(
                    row, live, "二维码多次过期，请重新发起扫码"
                )
            live.refresh_count += 1
            try:
                await self._new_challenge(row, live)
            except Exception:  # noqa: BLE001
                logger.warning("自动刷新临时扫码二维码失败", exc_info=True)
                return await self._expire(row, live, "刷新二维码失败，请重新发起")
            live.message = "二维码已过期，已自动刷新"
            return self._challenge_payload(row, live)

        try:
            result = await self.port.poll_qr(
                bot_id=row["temp_platform_id"],
                platform=row["platform"],
                payload=dict(live.payload),
            )
        except Exception:  # noqa: BLE001
            logger.warning("轮询临时扫码平台失败", exc_info=True)
            result = None
        if result is not None:
            if result.status == "created":
                self._set_status(session_id, "confirmed")
                row = dict(row)
                row["status"] = "confirmed"
                live.credentials = dict(result.credentials or {})
                live.message = result.message
                return self._challenge_payload(row, live)
            if result.status == "scanned":
                self._set_status(session_id, "scanned")
                row = dict(row)
                row["status"] = "scanned"
                live.message = result.message
                return self._challenge_payload(row, live)
            if result.status in {"expired", "denied"}:
                if result.status == "denied":
                    return await self._expire(row, live, result.message or "用户取消登录")
                if live.refresh_count >= self.settings.qr_max_refreshes:
                    return await self._expire(
                        row, live, result.message or "二维码已过期"
                    )
                live.refresh_count += 1
                try:
                    await self._new_challenge(row, live)
                except Exception:  # noqa: BLE001
                    return await self._expire(row, live, "刷新二维码失败，请重新发起")
                live.message = result.message or "二维码已过期，已自动刷新"
                return self._challenge_payload(row, live)
            if result.status == "error":
                live.message = result.message or "扫码状态异常"
                return self._challenge_payload(row, live)
        return self._challenge_payload(row, live)

    async def finalize(
        self, *, user_id: str, session_id: str, ip: str = ""
    ) -> dict[str, Any]:
        row = self._owned_row(user_id, session_id)
        if row["status"] in _TERMINAL:
            raise AppError(
                "扫码会话已结束，请重新发起", code="qr_expired", status=410
            )
        if row["status"] != "confirmed":
            # The UI polls every 2s; a direct finalize may still catch up once.
            await self.poll(user_id=user_id, session_id=session_id, ip=ip)
            row = self._owned_row(user_id, session_id)
            if row["status"] in _TERMINAL:
                raise AppError(
                    "扫码会话已结束，请重新发起", code="qr_expired", status=410
                )
        live = self._live.get(session_id)
        if (
            row["status"] != "confirmed"
            or live is None
            or not live.credentials
        ):
            raise AppError(
                "尚未完成扫码，不能接入", code="qr_not_ready", status=409
            )

        # 1) Build the real Bot (persona/config/route/memory/platform).
        bot = await self.bots.create(
            user_id=user_id,
            name=row["name"],
            template_id=row["template_id"],
            platform=row["platform"],
            ip=ip,
        )
        bot_id = bot["id"]
        if row.get("model_profile_id"):
            import json as _json

            snapshot = dict(bot.get("snapshot") or {})
            snapshot["model_profile_id"] = row["model_profile_id"]
            self.db.execute(
                "UPDATE bots SET snapshot = ? WHERE id = ?",
                (_json.dumps(snapshot, ensure_ascii=False), bot_id),
            )
        try:
            # 2) Move the provider-specific state from the temporary platform.
            finalize_temp = getattr(self.port, "finalize_temp_platform", None)
            if callable(finalize_temp):
                await finalize_temp(
                    temp_id=row["temp_platform_id"], bot_id=bot_id
                )
            # 3) Encrypt credentials + write them to the real platform.
            await self.bots.store_credentials(
                bot_id=bot_id,
                user_id=user_id,
                platform=row["platform"],
                credentials=live.credentials,
            )
            await self.port.set_platform_enabled(bot_id, True)
            updated = self.bots.mark_ready(bot_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("扫码接入失败，回滚新建 Bot：%s", bot_id, exc_info=True)
            try:
                await self.bots.delete(
                    user_id=user_id,
                    bot_id=bot_id,
                    confirm_name=row["name"],
                    ip=ip,
                    actor_id="system",
                    actor_role="system",
                )
            except Exception:  # noqa: BLE001
                logger.error("扫码接入失败后回滚 Bot 失败：%s", bot_id, exc_info=True)
            if isinstance(exc, AppError):
                raise
            raise AppError(
                "完成扫码接入失败，已回滚", code="qr_finalize_failed", status=500
            ) from exc

        # 4) Clean up the temporary platform + session.
        await self._safe_delete_platform(row["temp_platform_id"])
        self.db.execute("DELETE FROM qr_sessions WHERE id = ?", (session_id,))
        self._live.pop(session_id, None)
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="qr_session.finalized",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
            detail={"session_id": session_id, "platform": row["platform"]},
        )
        return updated

    async def cancel(
        self, *, user_id: str, session_id: str, ip: str = ""
    ) -> None:
        row = self._owned_row(user_id, session_id)
        await self._safe_delete_platform(row["temp_platform_id"])
        self.db.execute("DELETE FROM qr_sessions WHERE id = ?", (session_id,))
        self._live.pop(session_id, None)
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="qr_session.cancelled",
            target_type="qr_session",
            target_id=session_id,
            ip=ip,
            detail={"platform": row["platform"]},
        )

    async def gc(self) -> int:
        """Expire stale sessions and remove their temporary platforms."""
        now = self._now()
        rows = self.db.query(
            "SELECT * FROM qr_sessions WHERE status NOT IN ('expired','cancelled','confirmed') "
            "AND expires_at < ?",
            (now,),
        )
        for row in rows:
            self._set_status(row["id"], "expired")
            self._live.pop(row["id"], None)
            await self._safe_delete_platform(row["temp_platform_id"])
        return len(rows)


__all__ = ["QrSessionService", "SESSION_STATUSES"]
