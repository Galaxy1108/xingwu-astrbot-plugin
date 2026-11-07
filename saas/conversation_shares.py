"""Read-only public share links for one conversation.

A share row is keyed by a random URL-safe token and points at
``(user_id, bot_id, conversation_id)``. ``expires_at = 0`` means "never".
Only the owner endpoints create/read/revoke shares; the public endpoint reads a
single conversation through the same tenant decryption path as the owner view.
"""

from __future__ import annotations

import secrets
from typing import Any

from .clock import Clock, SystemClock
from .db import Database

TOKEN_BYTES = 24
MAX_EXPIRES_HOURS = 24 * 365


class ConversationShareService:
    def __init__(self, db: Database, *, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    # -- serialisation -------------------------------------------------
    @staticmethod
    def serialize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "token": row["token"],
            "bot_id": row["bot_id"],
            "conversation_id": row["conversation_id"],
            "created_at": int(row["created_at"]),
            "expires_at": int(row["expires_at"]),
        }

    def expired(self, row: dict[str, Any], *, now: int | None = None) -> bool:
        expires_at = int(row["expires_at"] or 0)
        if expires_at <= 0:
            return False
        return (now if now is not None else self.clock.now()) >= expires_at

    # -- owner ---------------------------------------------------------
    def current(
        self, *, user_id: str, bot_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM conversation_shares WHERE user_id = ? AND bot_id = ? "
            "AND conversation_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id, bot_id, conversation_id),
        )
        if row is None or self.expired(row):
            return None
        return row

    def create(
        self,
        *,
        user_id: str,
        bot_id: str,
        conversation_id: str,
        expires_hours: int | None = None,
    ) -> dict[str, Any]:
        existing = self.current(
            user_id=user_id, bot_id=bot_id, conversation_id=conversation_id
        )
        if existing is not None:
            return existing
        now = self.clock.now()
        expires_at = 0
        if expires_hours:
            hours = max(1, min(MAX_EXPIRES_HOURS, int(expires_hours)))
            expires_at = now + hours * 3600
        token = self._new_token()
        self.db.execute(
            "INSERT INTO conversation_shares(token, user_id, bot_id, conversation_id, "
            "expires_at, created_at) VALUES (?,?,?,?,?,?)",
            (token, user_id, bot_id, conversation_id, expires_at, now),
        )
        row = self.db.query_one(
            "SELECT * FROM conversation_shares WHERE token = ?", (token,)
        )
        return row or {
            "token": token,
            "bot_id": bot_id,
            "conversation_id": conversation_id,
            "expires_at": expires_at,
            "created_at": now,
        }

    def revoke(self, *, user_id: str, bot_id: str, conversation_id: str) -> int:
        cursor = self.db.execute(
            "DELETE FROM conversation_shares WHERE user_id = ? AND bot_id = ? "
            "AND conversation_id = ?",
            (user_id, bot_id, conversation_id),
        )
        return int(cursor.rowcount or 0)

    # -- public --------------------------------------------------------
    def resolve(self, token: str) -> tuple[dict[str, Any] | None, bool]:
        """Return ``(row, expired)``; ``(None, False)`` when unknown/revoked."""
        value = (token or "").strip()
        if not value:
            return None, False
        row = self.db.query_one(
            "SELECT * FROM conversation_shares WHERE token = ?", (value,)
        )
        if row is None:
            return None, False
        return row, self.expired(row)

    def _new_token(self) -> str:
        for _ in range(5):  # collisions are practically impossible, retry anyway
            token = secrets.token_urlsafe(TOKEN_BYTES)
            row = self.db.query_one(
                "SELECT 1 AS hit FROM conversation_shares WHERE token = ?", (token,)
            )
            if row is None:
                return token
        return secrets.token_urlsafe(TOKEN_BYTES * 2)


__all__ = ["ConversationShareService", "MAX_EXPIRES_HOURS"]
