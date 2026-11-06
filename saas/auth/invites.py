"""Invitation codes: one-time, 72h, revocable (FR-A)."""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..db import Database
from ..errors import AppError, ValidationError
from ..security import (
    hmac_hex,
    new_invite_code,
    normalize_invite_code,
    random_id,
)


class InviteService:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings,
        pepper: bytes,
        clock=None,
    ) -> None:
        self.db = db
        self.settings = settings
        self._pepper = pepper
        self.clock = clock

    def _now(self) -> int:
        return self.clock.now() if self.clock is not None else int(time.time())

    def _hash(self, code: str) -> str:
        return hmac_hex(self._pepper, normalize_invite_code(code))

    def create(
        self,
        *,
        created_by: str,
        max_uses: int = 1,
        ttl_hours: int | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        max_uses = int(max_uses or 1)
        if max_uses < 1 or max_uses > 100:
            raise ValidationError("max_uses 必须在 1–100 之间", field="max_uses")
        hours = int(ttl_hours or self.settings.invite_ttl_hours)
        if hours < 1 or hours > 24 * 30:
            raise ValidationError("ttl_hours 必须在 1–720 之间", field="ttl_hours")
        code = new_invite_code()
        now = self._now()
        expires_at = now + hours * 3600
        self.db.execute(
            "INSERT INTO invites(code_hash, code_hint, created_by, max_uses, used_count, "
            "expires_at, revoked_at, created_at, note) VALUES (?,?,?,?,0,?,0,?,?)",
            (
                self._hash(code),
                code[:8],
                created_by,
                max_uses,
                expires_at,
                now,
                note,
            ),
        )
        return {
            "code": code,
            "code_hint": code[:8],
            "max_uses": max_uses,
            "expires_at": expires_at,
            "created_at": now,
        }

    def verify(self, code: str) -> dict[str, Any]:
        """Validate a code without consuming a use (raises 410 errors)."""
        code = (code or "").strip()
        if not code:
            raise ValidationError("请输入邀请码", code="invite_invalid", status=410, field="invite")
        row = self.db.query_one(
            "SELECT * FROM invites WHERE code_hash = ?", (self._hash(code),)
        )
        if row is None or row["revoked_at"]:
            raise AppError(
                "邀请码无效或已作废",
                code="invite_invalid",
                status=410,
                field="invite",
            )
        if int(row["expires_at"]) <= self._now():
            raise AppError(
                "邀请码已过期", code="invite_expired", status=410, field="invite"
            )
        if int(row["used_count"]) >= int(row["max_uses"]):
            raise AppError(
                "邀请码已被使用", code="invite_exhausted", status=410, field="invite"
            )
        return row

    def consume(self, code: str) -> dict[str, Any]:
        """Atomically consume one use; only one concurrent caller can win."""
        row = self.verify(code)
        with self.db.transaction():
            cursor = self.db.execute(
                "UPDATE invites SET used_count = used_count + 1 "
                "WHERE code_hash = ? AND revoked_at = 0 AND expires_at > ? "
                "AND used_count < max_uses",
                (row["code_hash"], self._now()),
            )
            if cursor.rowcount != 1:
                raise AppError(
                    "邀请码已被使用",
                    code="invite_exhausted",
                    status=410,
                    field="invite",
                )
        return self.db.query_one(
            "SELECT * FROM invites WHERE code_hash = ?", (row["code_hash"],)
        )

    def revoke(self, code_or_hint: str, *, actor_id: str = "") -> bool:
        value = (code_or_hint or "").strip()
        if not value:
            raise ValidationError("缺少邀请码", field="code")
        now = self._now()
        cursor = self.db.execute(
            "UPDATE invites SET revoked_at = ? WHERE revoked_at = 0 AND "
            "(code_hash = ? OR substr(code_hint,1,8) = ?)",
            (now, self._hash(value), value[:8]),
        )
        return cursor.rowcount > 0

    def list(self, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        total = int(self.db.scalar("SELECT COUNT(*) AS c FROM invites", (), 0))
        rows = self.db.query(
            "SELECT * FROM invites ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        )
        now = self._now()
        items = []
        for row in rows:
            items.append(
                {
                    "code_hint": row["code_hint"],
                    "max_uses": row["max_uses"],
                    "used_count": row["used_count"],
                    "expires_at": row["expires_at"],
                    "revoked_at": row["revoked_at"],
                    "created_at": row["created_at"],
                    "created_by": row["created_by"],
                    "status": self._status(row, now),
                }
            )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def _status(row: dict[str, Any], now: int) -> str:
        if row["revoked_at"]:
            return "revoked"
        if int(row["expires_at"]) <= now:
            return "expired"
        if int(row["used_count"]) >= int(row["max_uses"]):
            return "used"
        return "active"

    def id_for_hint(self, code_hint: str) -> str:
        row = self.db.query_one(
            "SELECT code_hash FROM invites WHERE substr(code_hint,1,8) = ?",
            (code_hint[:8],),
        )
        if row is None:
            raise AppError("邀请码不存在", code="not_found", status=404)
        return str(row["code_hash"])
