"""QR onboarding state machine (FR-B).

- TTL 60s per QR code, at most 3 automatic refreshes, then ``expired``.
- One live session per Bot; sessions idle for 5 minutes are reclaimed.
- Credentials are handed to :class:`BotService` for encryption + platform enable
  only on ``finalize``.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditService
from .bots import BotService
from .clock import Clock, SystemClock
from .config import Settings
from .errors import AppError, Conflict, NotFound
from .ports import AstrBotPort

logger = logging.getLogger(__name__)


def qr_data_url(content: str) -> str:
    """Render QR content to a PNG data URL (used when the provider returns text)."""
    try:
        import qrcode

        image = qrcode.make(content, box_size=6, border=2)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:  # noqa: BLE001
        logger.warning("二维码图片生成失败", exc_info=True)
        return ""


@dataclass
class QrSession:
    id: str
    bot_id: str
    user_id: str
    platform: str
    payload: dict[str, Any]
    content: str
    image: str
    interval: int
    created_at: int
    expires_at: int
    last_poll_at: int
    refresh_count: int = 0
    status: str = "pending"
    credentials: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class QrService:
    def __init__(
        self,
        *,
        port: AstrBotPort,
        bots: BotService,
        settings: Settings,
        audit: AuditService,
        clock: Clock | None = None,
    ) -> None:
        self.port = port
        self.bots = bots
        self.settings = settings
        self.audit = audit
        self.clock = clock or SystemClock()
        self._sessions: dict[str, QrSession] = {}
        self._counter = 0

    def _now(self) -> int:
        return self.clock.now()

    def _new_id(self) -> str:
        self._counter += 1
        return f"j_{int(time.time() * 1000):x}{self._counter:04x}"

    # -- helpers -------------------------------------------------------
    def _session_for(self, bot_id: str) -> QrSession | None:
        session = self._sessions.get(bot_id)
        if session is None:
            return None
        if self._now() - session.last_poll_at > self.settings.qr_idle_timeout_seconds:
            self._sessions.pop(bot_id, None)
            return None
        return session

    def _payload(self, session: QrSession, *, message: str = "") -> dict[str, Any]:
        return {
            "id": session.id,
            "status": session.status,
            "qr_content": session.content,
            "qr_image": session.image,
            "expires_at": session.expires_at,
            "refresh_count": session.refresh_count,
            "interval": session.interval,
            "message": message or session.message,
        }

    async def _new_challenge(self, session: QrSession) -> None:
        challenge = await self.port.request_qr(
            bot_id=session.bot_id, platform=session.platform
        )
        session.payload = dict(challenge.payload or {})
        session.content = challenge.content
        image = challenge.image or ""
        if image and not image.startswith("data:"):
            image = "data:image/png;base64," + image
        session.image = image or qr_data_url(challenge.content)
        session.interval = int(challenge.interval or self.settings.qr_poll_interval)
        session.expires_at = self._now() + self.settings.qr_ttl_seconds
        session.status = "pending"

    # -- public API ----------------------------------------------------
    async def start(
        self, *, user_id: str, bot_id: str, ip: str = ""
    ) -> dict[str, Any]:
        bot = self.bots.get_for_user(user_id, bot_id)
        if bot["status"] in {"creating", "deleting"}:
            raise Conflict("Bot 正在创建/删除中", code="bot_state_invalid")
        existing = self._session_for(bot_id)
        if existing is not None and existing.status != "expired":
            raise Conflict("该 Bot 已有进行中的扫码会话", code="qr_session_exists")
        session = QrSession(
            id=self._new_id(),
            bot_id=bot_id,
            user_id=user_id,
            platform=bot["platform"],
            payload={},
            content="",
            image="",
            interval=self.settings.qr_poll_interval,
            created_at=self._now(),
            expires_at=self._now() + self.settings.qr_ttl_seconds,
            last_poll_at=self._now(),
        )
        await self._new_challenge(session)
        self._sessions[bot_id] = session
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="bot.qr_started",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
            detail={"platform": bot["platform"], "qr_id": session.id},
        )
        return self._payload(session)

    async def poll(self, *, user_id: str, bot_id: str, ip: str = "") -> dict[str, Any]:
        self.bots.get_for_user(user_id, bot_id)
        session = self._session_for(bot_id)
        if session is None:
            raise AppError(
                "扫码会话不存在或已超过 5 分钟未轮询，请重新发起",
                code="qr_expired",
                status=410,
            )
        session.last_poll_at = self._now()
        if session.status == "created":
            return self._payload(session)
        if session.status == "expired":
            return self._payload(session)

        # Local TTL check (a provider may never say "expired" itself).
        expired = self._now() >= session.expires_at
        if not expired:
            try:
                result = await self.port.poll_qr(
                    bot_id=bot_id,
                    platform=session.platform,
                    payload=dict(session.payload),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("轮询二维码失败：%s", exc, exc_info=True)
                result = None
            if result is not None:
                if result.status == "created":
                    session.status = "created"
                    session.credentials = dict(result.credentials or {})
                    session.message = result.message
                    return self._payload(session)
                if result.status == "scanned":
                    session.status = "scanned"
                    session.message = result.message
                    return self._payload(session)
                if result.status in {"expired", "denied"}:
                    expired = True
                    session.message = result.message or "二维码已过期"
                elif result.status == "error":
                    session.message = result.message or "扫码状态异常"
                else:
                    session.status = "pending"
                    return self._payload(session)

        if not expired:
            return self._payload(session)

        # Expiry → automatic refresh, at most ``qr_max_refreshes`` times.
        session.refresh_count += 1
        if session.refresh_count > self.settings.qr_max_refreshes:
            session.status = "expired"
            session.message = "二维码多次过期，请重新发起扫码"
            self.audit.log(
                actor_id=user_id,
                actor_role="user",
                action="bot.qr_expired",
                target_type="bot",
                target_id=bot_id,
                ip=ip,
                detail={"refresh_count": session.refresh_count},
            )
            return self._payload(session)
        try:
            await self._new_challenge(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("自动刷新二维码失败：%s", exc, exc_info=True)
            session.status = "expired"
            session.message = "刷新二维码失败，请重新发起"
            return self._payload(session)
        session.message = "二维码已过期，已自动刷新"
        return self._payload(session)

    async def finalize(
        self, *, user_id: str, bot_id: str, ip: str = ""
    ) -> dict[str, Any]:
        bot = self.bots.get_for_user(user_id, bot_id)
        session = self._session_for(bot_id)
        if session is None or session.status != "created" or not session.credentials:
            raise AppError(
                "尚未完成扫码，不能接入", code="qr_not_ready", status=409
            )
        await self.bots.store_credentials(
            bot_id=bot_id,
            user_id=user_id,
            platform=session.platform,
            credentials=session.credentials,
        )
        await self.port.set_platform_enabled(bot_id, True)
        updated = self.bots.mark_ready(bot_id)
        self._sessions.pop(bot_id, None)
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="bot.qr_finalized",
            target_type="bot",
            target_id=bot_id,
            ip=ip,
            detail={"platform": session.platform},
        )
        return updated

    def cancel(self, bot_id: str) -> None:
        self._sessions.pop(bot_id, None)

    def active_session(self, bot_id: str) -> dict[str, Any] | None:
        session = self._session_for(bot_id)
        if session is None:
            return None
        return self._payload(session)

    def gc(self) -> int:
        """Reclaim sessions idle for too long (called from a periodic task)."""
        now = self._now()
        stale = [
            bot_id
            for bot_id, session in self._sessions.items()
            if now - session.last_poll_at > self.settings.qr_idle_timeout_seconds
        ]
        for bot_id in stale:
            self._sessions.pop(bot_id, None)
        return len(stale)
