"""Account bans / admin bot disable orchestration (M6).

This module is the single entry point that keeps three things in sync:

* ``users.status`` + ``users.status_reason`` + ``users.status_changed_at``
  (``status='disabled'`` is the ban flag; banned users can still log in to
  read the notice and submit appeals — see ``web/app.py`` ban gate),
* ``users.banned_restore_bots`` — the JSON snapshot of bots that were
  ``status='ready'`` at ban time (so unban never re-enables bots the user had
  already switched off manually),
* ``bots.admin_disabled`` / ``bots.status`` + the AstrBot platform instance via
  ``port.set_platform_enabled``.

All bot-side mechanics live in :class:`saas.bots.BotService` so the same paths
are reusable by admin bot actions and appeal approval.
"""

from __future__ import annotations

import json
from typing import Any

from .audit import AuditService
from .clock import Clock, SystemClock
from .db import Database
from .errors import NotFound


class BanService:
    def __init__(
        self,
        db: Database,
        *,
        auth: Any,
        bots: Any,
        audit: AuditService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.db = db
        self.auth = auth
        self.bots = bots
        self.audit = audit
        self.clock = clock or SystemClock()

    # -- users ---------------------------------------------------------
    async def ban_user(
        self,
        user_id: str,
        reason: str = "",
        *,
        actor_id: str = "",
        actor_role: str = "admin",
        ip: str = "",
    ) -> dict[str, Any]:
        user = self.auth.get_user(user_id)
        if user is None:
            raise NotFound("用户不存在")
        reason = str(reason or "").strip()[:500]
        already_banned = user["status"] == "disabled"
        queued: list[str] = []
        if not already_banned:
            # Snapshot only currently-enabled bots, then stop them.
            queued = await self.bots.admin_disable_user_bots(
                user_id, reason, actor_id=actor_id, ip=ip
            )
            self.db.execute(
                "UPDATE users SET banned_restore_bots = ? WHERE id = ?",
                (json.dumps(queued, ensure_ascii=False), user_id),
            )
        # Sets status/status_reason/status_changed_at, revokes sessions and
        # writes the generic ``user.status_changed`` audit row.
        updated = self.auth.set_user_status(
            user_id,
            "disabled",
            reason=reason,
            actor_id=actor_id,
            actor_role=actor_role,
            ip=ip,
        )
        self._audit(
            actor_id=actor_id,
            actor_role=actor_role,
            action="user.banned",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"reason": reason, "restored_bots": queued},
        )
        return updated

    async def unban_user(
        self,
        user_id: str,
        reason: str = "",
        *,
        actor_id: str = "",
        actor_role: str = "admin",
        ip: str = "",
    ) -> dict[str, Any]:
        user = self.auth.get_user(user_id)
        if user is None:
            raise NotFound("用户不存在")
        reason = str(reason or "").strip()[:500]
        queued = _parse_bot_ids(user.get("banned_restore_bots"))
        restored = await self.bots.restore_banned_bots(
            user_id, queued, actor_id=actor_id, ip=ip
        )
        self.db.execute(
            "UPDATE users SET banned_restore_bots = '[]' WHERE id = ?", (user_id,)
        )
        updated = self.auth.set_user_status(
            user_id,
            "active",
            reason="",
            actor_id=actor_id,
            actor_role=actor_role,
            ip=ip,
        )
        self._audit(
            actor_id=actor_id,
            actor_role=actor_role,
            action="user.unbanned",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"reason": reason, "restored_bots": restored},
        )
        return updated

    def pending_restore_bots(self, user_id: str) -> list[str]:
        user = self.auth.get_user(user_id)
        return _parse_bot_ids(user.get("banned_restore_bots")) if user else []

    # -- bots ----------------------------------------------------------
    async def set_bot_admin_disabled(
        self,
        bot_id: str,
        disabled: bool,
        reason: str = "",
        *,
        actor_id: str = "",
        actor_role: str = "admin",
        ip: str = "",
    ) -> dict[str, Any]:
        return await self.bots.admin_set_disabled(
            bot_id,
            disabled,
            reason,
            actor_id=actor_id,
            actor_role=actor_role,
            ip=ip,
        )

    # -- helpers -------------------------------------------------------
    def _audit(
        self,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str,
        ip: str,
        detail: dict[str, Any],
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            actor_id=actor_id,
            actor_role=actor_role if actor_id else "system",
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            detail=detail,
        )


def _parse_bot_ids(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def bans_of(container: Any) -> BanService:
    """Return the wired ``BanService`` (lazy fallback for older composition roots)."""
    service = getattr(container, "bans", None)
    if service is None:
        service = BanService(
            container.db,
            auth=container.auth,
            bots=container.bots,
            audit=getattr(container, "audit", None),
            clock=getattr(container, "clock", None),
        )
        container.bans = service
    return service
