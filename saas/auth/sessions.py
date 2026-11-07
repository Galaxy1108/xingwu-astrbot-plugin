"""Server-side sessions with sliding + absolute expiry and CSRF binding."""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..db import Database
from ..security import hmac_hex, random_token, sha256_hex


class SessionService:
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

    def create(
        self, user: dict[str, Any], *, ip: str = "", user_agent: str = ""
    ) -> dict[str, Any]:
        now = self._now()
        role = str(user.get("role") or "user")
        if role == "admin":
            ttl = self.settings.admin_session_hours * 3600
            expires_at = now + ttl
            absolute = expires_at
        else:
            expires_at = now + self.settings.session_sliding_days * 86400
            absolute = now + self.settings.session_absolute_days * 86400
        token = random_token(32)
        csrf_token = random_token(32)
        self.db.execute(
            "INSERT INTO sessions(id, user_id, created_at, expires_at, "
            "absolute_expires_at, last_seen_at, csrf_token_hash, ip, user_agent, revoked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,0)",
            (
                sha256_hex(token),
                user["id"],
                now,
                expires_at,
                absolute,
                now,
                hmac_hex(self._pepper, csrf_token),
                ip,
                user_agent[:512],
            ),
        )
        return {
            "token": token,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
            "absolute_expires_at": absolute,
        }

    def resolve(self, token: str | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if not token:
            return None
        session = self.db.query_one(
            "SELECT * FROM sessions WHERE id = ? AND revoked_at = 0",
            (sha256_hex(token),),
        )
        if session is None:
            return None
        now = self._now()
        if now >= int(session["expires_at"]) or now >= int(session["absolute_expires_at"]):
            return None
        user = self.db.query_one("SELECT * FROM users WHERE id = ?", (session["user_id"],))
        # Banned (status='disabled') users keep a session so they can read the
        # ban notice and appeal; web/app.py gates every other API path.
        if user is None or user["status"] == "deleted":
            return None
        # Sliding expiry for regular users; admin sessions have a fixed 12h TTL.
        if user["role"] != "admin":
            new_expiry = min(
                now + self.settings.session_sliding_days * 86400,
                int(session["absolute_expires_at"]),
            )
            if new_expiry != int(session["expires_at"]):
                self.db.execute(
                    "UPDATE sessions SET expires_at = ? WHERE id = ?",
                    (new_expiry, session["id"]),
                )
        self.db.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, session["id"])
        )
        return user, session

    def validate_csrf(self, session: dict[str, Any], token: str | None) -> bool:
        if not token:
            return False
        expected = str(session.get("csrf_token_hash") or "")
        return bool(expected) and hmac_hex(self._pepper, token) == expected

    def set_csrf(self, session_id: str, csrf_token: str) -> None:
        """Rotate the CSRF token bound to a session (cookie refresh path)."""
        self.db.execute(
            "UPDATE sessions SET csrf_token_hash = ? WHERE id = ?",
            (hmac_hex(self._pepper, csrf_token), session_id),
        )

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        self.db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at = 0",
            (self._now(), sha256_hex(token)),
        )

    def revoke_all_for_user(self, user_id: str) -> int:
        cursor = self.db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = 0",
            (self._now(), user_id),
        )
        return int(cursor.rowcount or 0)

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT id, created_at, expires_at, last_seen_at, ip, user_agent, revoked_at "
            "FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
