"""User appeals for account bans and admin-disabled bots (M6).

Flow: a banned user (or the owner of an admin-disabled bot) posts an appeal;
admins list all pending appeals and approve/reject them.  Approval goes through
:class:`saas.bans.BanService`, so a user appeal restores exactly the bots that
were enabled at ban time and a bot appeal re-enables that one bot.

Only one ``pending`` appeal per ``(user_id, target_type, target_id)`` is
allowed, enforced both in this service and by a partial unique index in the
migration (concurrent duplicate posts → 409 ``appeal_pending``).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .audit import AuditService
from .bans import BanService, bans_of
from .clock import Clock, SystemClock
from .db import Database
from .errors import AppError, Conflict, NotFound, ValidationError
from .security import random_id

APPEAL_STATUSES = ("pending", "approved", "rejected")
TARGET_TYPES = ("user", "bot")
MAX_REASON = 2000


class AppealService:
    def __init__(
        self,
        db: Database,
        *,
        audit: AuditService | None = None,
        clock: Clock | None = None,
        bans: BanService | None = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock or SystemClock()
        self.bans = bans

    # -- serialisation -------------------------------------------------
    def serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        target_name = row.get("target_bot_name") or ""
        if row["target_type"] == "user":
            target_name = row.get("display_name") or row.get("user_email") or ""
        admin_note = row.get("admin_note") or ""
        resolved_at = int(row.get("resolved_at") or 0)
        admin_id = row.get("admin_id") or ""
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "user_email": row.get("user_email") or "",
            "display_name": row.get("display_name") or "",
            "target_type": row["target_type"],
            "target_id": row.get("target_id") or "",
            "target_name": target_name,
            "reason": row.get("reason") or "",
            "status": row["status"],
            "admin_id": admin_id,
            "admin_note": admin_note,
            "created_at": int(row.get("created_at") or 0),
            "resolved_at": resolved_at,
            # Console aliases (web/src/types.ts Appeal).
            "note": admin_note,
            "handled_by": admin_id,
            "handled_at": resolved_at,
        }

    def _row(self, appeal_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT a.*, u.email AS user_email, u.display_name AS display_name, "
            "(SELECT b.name FROM bots b WHERE b.id = a.target_id) AS target_bot_name "
            "FROM appeals a LEFT JOIN users u ON u.id = a.user_id WHERE a.id = ?",
            (appeal_id,),
        )
        if row is None:
            raise NotFound("申诉不存在")
        return row

    def get(self, appeal_id: str) -> dict[str, Any]:
        return self.serialize(self._row(appeal_id))

    # -- user: create / list -------------------------------------------
    def create(
        self,
        user_id: str,
        target_type: str,
        target_id: str = "",
        reason: str = "",
        *,
        ip: str = "",
    ) -> dict[str, Any]:
        user_id = str(user_id or "").strip()
        user = self.db.query_one(
            "SELECT * FROM users WHERE id = ? AND status != 'deleted'", (user_id,)
        )
        if user is None:
            raise NotFound("用户不存在")
        target_type = str(target_type or "").strip().lower()
        if target_type not in TARGET_TYPES:
            raise ValidationError(
                "target_type 只能是 user 或 bot", field="target_type"
            )
        reason = str(reason or "").strip()
        if not reason or len(reason) > MAX_REASON:
            raise ValidationError(
                f"申诉理由需为 1–{MAX_REASON} 个字符", field="reason"
            )
        if target_type == "user":
            # A ban appeal always targets the logged-in account itself.
            target_id = ""
            if user["status"] != "disabled":
                raise ValidationError(
                    "当前账号未被封禁，无需申诉", field="target_type"
                )
        else:
            target_id = str(target_id or "").strip()
            if not target_id:
                raise ValidationError("Bot 申诉需要 target_id", field="target_id")
            bot = self.db.query_one(
                "SELECT id, admin_disabled FROM bots WHERE id = ? AND user_id = ? "
                "AND status != 'deleted'",
                (target_id, user_id),
            )
            if bot is None:
                raise NotFound("Bot 不存在")
            if not int(bot.get("admin_disabled") or 0):
                raise ValidationError(
                    "该 Bot 未被管理员停用，无需申诉", field="target_id"
                )
        pending = self.db.query_one(
            "SELECT id FROM appeals WHERE user_id = ? AND target_type = ? "
            "AND target_id = ? AND status = 'pending'",
            (user_id, target_type, target_id),
        )
        if pending is not None:
            raise Conflict("已有待处理的申诉，请耐心等待", code="appeal_pending")
        now = self.clock.now()
        appeal_id = random_id("ap", 8)
        try:
            self.db.execute(
                "INSERT INTO appeals(id, user_id, target_type, target_id, reason, "
                "status, admin_id, admin_note, created_at, resolved_at) "
                "VALUES (?,?,?,?,?,'pending','','',?,0)",
                (appeal_id, user_id, target_type, target_id, reason, now),
            )
        except sqlite3.IntegrityError:
            raise Conflict("已有待处理的申诉，请耐心等待", code="appeal_pending") from None
        self._audit(
            actor_id=user_id,
            actor_role=user.get("role") or "user",
            action="appeal.created",
            appeal_id=appeal_id,
            ip=ip,
            detail={
                "target_type": target_type,
                "target_id": target_id,
                "user_id": user_id,
            },
        )
        return self.get(appeal_id)

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT a.*, u.email AS user_email, u.display_name AS display_name, "
            "(SELECT b.name FROM bots b WHERE b.id = a.target_id) AS target_bot_name "
            "FROM appeals a LEFT JOIN users u ON u.id = a.user_id "
            "WHERE a.user_id = ? ORDER BY a.created_at DESC, a.rowid DESC",
            (user_id,),
        )
        return [self.serialize(row) for row in rows]

    def pending_for_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT a.*, u.email AS user_email, u.display_name AS display_name, "
            "(SELECT b.name FROM bots b WHERE b.id = a.target_id) AS target_bot_name "
            "FROM appeals a LEFT JOIN users u ON u.id = a.user_id "
            "WHERE a.user_id = ? AND a.status = 'pending' "
            "ORDER BY a.created_at DESC, a.rowid DESC LIMIT 1",
            (user_id,),
        )
        return self.serialize(row) if row is not None else None

    # -- admin: list / resolve -----------------------------------------
    def list_admin(
        self,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        raw = str(status or "").strip().lower()
        where = ""
        params: list[Any] = []
        if raw and raw != "all":
            if raw not in APPEAL_STATUSES:
                raise ValidationError(f"status 不合法：{raw}", field="status")
            where = "WHERE a.status = ?"
            params.append(raw)
        total = int(
            self.db.scalar(
                f"SELECT COUNT(*) AS c FROM appeals a {where}", params, 0
            )
        )
        rows = self.db.query(
            "SELECT a.*, u.email AS user_email, u.display_name AS display_name, "
            "(SELECT b.name FROM bots b WHERE b.id = a.target_id) AS target_bot_name "
            f"FROM appeals a LEFT JOIN users u ON u.id = a.user_id {where} "
            "ORDER BY a.created_at DESC, a.rowid DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {
            "items": [self.serialize(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def approve(
        self,
        appeal_id: str,
        *,
        admin_id: str,
        note: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        row = self._row(appeal_id)
        if row["status"] != "pending":
            raise Conflict("该申诉已处理", code="appeal_resolved")
        note = str(note or "").strip()[:500]
        if self.bans is None:  # pragma: no cover - composition always injects it
            raise AppError("申诉服务未初始化", code="internal_error", status=500)
        if row["target_type"] == "user":
            await self.bans.unban_user(
                row["user_id"],
                reason=note or "申诉通过",
                actor_id=admin_id,
                ip=ip,
            )
        else:
            await self.bans.set_bot_admin_disabled(
                row["target_id"],
                False,
                reason=note or "申诉通过",
                actor_id=admin_id,
                ip=ip,
            )
        self._resolve(row["id"], "approved", admin_id, note)
        self._audit(
            actor_id=admin_id,
            actor_role="admin",
            action="appeal.approved",
            appeal_id=row["id"],
            ip=ip,
            detail={
                "user_id": row["user_id"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "note": note,
            },
        )
        return self.get(row["id"])

    async def reject(
        self,
        appeal_id: str,
        *,
        admin_id: str,
        note: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        row = self._row(appeal_id)
        if row["status"] != "pending":
            raise Conflict("该申诉已处理", code="appeal_resolved")
        note = str(note or "").strip()[:500]
        self._resolve(row["id"], "rejected", admin_id, note)
        self._audit(
            actor_id=admin_id,
            actor_role="admin",
            action="appeal.rejected",
            appeal_id=row["id"],
            ip=ip,
            detail={
                "user_id": row["user_id"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "note": note,
            },
        )
        return self.get(row["id"])

    # -- helpers -------------------------------------------------------
    def _resolve(
        self, appeal_id: str, status: str, admin_id: str, note: str
    ) -> None:
        self.db.execute(
            "UPDATE appeals SET status = ?, admin_id = ?, admin_note = ?, "
            "resolved_at = ? WHERE id = ?",
            (status, admin_id, note, self.clock.now(), appeal_id),
        )

    def _audit(
        self,
        *,
        actor_id: str,
        actor_role: str,
        action: str,
        appeal_id: str,
        ip: str,
        detail: dict[str, Any],
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            actor_id=actor_id,
            actor_role=actor_role if actor_id else "system",
            action=action,
            target_type="appeal",
            target_id=appeal_id,
            ip=ip,
            detail=detail,
        )


def appeals_of(container: Any) -> AppealService:
    """Return the wired ``AppealService`` (lazy fallback)."""
    service = getattr(container, "appeals", None)
    if service is None:
        service = AppealService(
            container.db,
            audit=getattr(container, "audit", None),
            clock=getattr(container, "clock", None),
            bans=bans_of(container),
        )
        container.appeals = service
    return service
