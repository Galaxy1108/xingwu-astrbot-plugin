"""Account use-cases: OTP login, invite-gated registration, sessions, roles."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..audit import AuditService
from ..clock import Clock, SystemClock
from ..config import Settings
from ..db import Database
from ..errors import AppError, Forbidden, ValidationError
from ..security import normalize_invite_code, random_id
from .invites import InviteService
from .keys import TenantKeyService
from .otp import OtpService, is_valid_email, normalize_email
from .sessions import SessionService

logger = logging.getLogger(__name__)

DEFAULT_QUOTA = {"max_bots": 3, "monthly_tokens": 1_000_000, "max_memories": 2000}


class AuthService:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings,
        invites: InviteService,
        otp: OtpService,
        sessions: SessionService,
        keys: TenantKeyService,
        audit: AuditService,
        clock: Clock | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.invites = invites
        self.otp = otp
        self.sessions = sessions
        self.keys = keys
        self.audit = audit
        self.clock = clock or SystemClock()

    # -- queries -------------------------------------------------------
    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM users WHERE id = ? AND status != 'deleted'", (user_id,)
        )

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM users WHERE email = ? AND status != 'deleted'",
            (normalize_email(email),),
        )

    def quota_for(self, user_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM quotas WHERE user_id = ?", (user_id,))
        if row is None:
            return dict(DEFAULT_QUOTA)
        return {
            "max_bots": int(row["max_bots"]),
            "monthly_tokens": int(row["monthly_tokens"]),
            "max_memories": int(row["max_memories"]),
            "used_tokens": int(row["used_tokens"]),
            "used_memories": int(row["used_memories"]),
        }

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "status": user["status"],
            "created_at": user["created_at"],
            "encryption": {
                "enabled": bool(user.get("encryption_enabled", 1)),
                "state": user.get("encryption_state", "encrypted"),
            },
        }

    # -- OTP -----------------------------------------------------------
    def request_otp(
        self, email: str, *, invite: str | None = None, ip: str = ""
    ) -> dict[str, Any]:
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValidationError("邮箱格式不正确", field="email")
        user = self.get_user_by_email(email)
        if user is not None and user["status"] == "disabled":
            raise Forbidden("账号已被禁用，请联系管理员")
        if user is None:
            if self.settings.allow_public_signup:
                pass
            elif not (invite or "").strip():
                raise ValidationError(
                    "首次注册需要邀请码", code="invite_invalid", status=410, field="invite"
                )
            else:
                self.invites.verify(invite or "")
        result = self.otp.request(email, ip=ip)
        self.audit.log(
            actor_id=user["id"] if user else "",
            actor_role=user["role"] if user else "",
            action="auth.otp_request",
            target_type="user",
            target_id=user["id"] if user else email,
            ip=ip,
        )
        return result

    def verify_otp(
        self,
        email: str,
        code: str,
        *,
        invite: str | None = None,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, Any]:
        email = normalize_email(email)
        invite_code = normalize_invite_code(invite or "")
        user = self.get_user_by_email(email)
        # Fail fast on a bad invite before consuming the OTP.
        if user is None and not self.settings.allow_public_signup:
            if not invite_code:
                raise ValidationError(
                    "首次注册需要邀请码", code="invite_invalid", status=410, field="invite"
                )
            self.invites.verify(invite_code)
        self.otp.verify(email, code)
        is_new = False
        if user is None:
            user = self._create_user(email, invite_code, ip=ip)
            is_new = True
        if user["status"] != "active":
            raise Forbidden("账号已被禁用，请联系管理员")
        session = self.sessions.create(user, ip=ip, user_agent=user_agent)
        self.audit.log(
            actor_id=user["id"],
            actor_role=user["role"],
            action="auth.register" if is_new else "auth.login",
            target_type="user",
            target_id=user["id"],
            ip=ip,
        )
        return {
            "user": self.public_user(user),
            "is_new": is_new,
            "session": session,
        }

    def logout(self, token: str | None, *, user: dict[str, Any] | None = None) -> None:
        self.sessions.revoke(token)
        if user is not None:
            self.audit.log(
                actor_id=user["id"],
                actor_role=user["role"],
                action="auth.logout",
                target_type="user",
                target_id=user["id"],
            )

    # -- registration --------------------------------------------------
    def _create_user(self, email: str, invite_code: str, *, ip: str = "") -> dict[str, Any]:
        now = self.clock.now()
        user_id = random_id("u", 8)
        invite_hint = invite_code[:8] if invite_code else ""
        with self.db.transaction():
            if invite_code and not self.settings.allow_public_signup:
                self.invites.consume(invite_code)
            self.db.execute(
                "INSERT INTO users(id, email, role, status, created_at, invite_code, "
                "encryption_enabled, encryption_state) VALUES (?,?,?,?,?,?,1,'encrypted')",
                (user_id, email, "user", "active", now, invite_hint),
            )
            self.db.execute(
                "INSERT INTO quotas(user_id, max_bots, monthly_tokens, max_memories, "
                "used_tokens, used_memories, period_start) VALUES (?,?,?,?,0,0,?)",
                (
                    user_id,
                    DEFAULT_QUOTA["max_bots"],
                    DEFAULT_QUOTA["monthly_tokens"],
                    DEFAULT_QUOTA["max_memories"],
                    now,
                ),
            )
            self.db.execute(
                "INSERT INTO wallets(user_id, balance) VALUES (?, 0)", (user_id,)
            )
            self.keys.ensure(user_id)
        user = self.get_user(user_id)
        if user is None:  # pragma: no cover - defensive
            raise AppError("创建账号失败")
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action="auth.register",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"email": email},
        )
        return user

    def create_user(
        self, email: str, *, role: str = "user", invite_code: str = "", ip: str = ""
    ) -> dict[str, Any]:
        """Admin/seed usage: create an account directly (no OTP)."""
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValidationError("邮箱格式不正确", field="email")
        if self.get_user_by_email(email) is not None:
            raise ValidationError("邮箱已注册", field="email")
        user = self._create_user(email, invite_code, ip=ip)
        if role != "user":
            self.db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user["id"]))
            user = self.get_user(user["id"]) or user
        return user

    # -- admin account state -------------------------------------------
    def set_user_status(
        self,
        user_id: str,
        status: str,
        *,
        actor_id: str = "",
        actor_role: str = "admin",
        ip: str = "",
    ) -> dict[str, Any]:
        if status not in {"active", "disabled"}:
            raise ValidationError("status 只能是 active 或 disabled", field="status")
        user = self.get_user(user_id)
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        now = self.clock.now()
        self.db.execute(
            "UPDATE users SET status = ?, disabled_at = ? WHERE id = ?",
            (status, now if status == "disabled" else 0, user_id),
        )
        if status == "disabled":
            self.sessions.revoke_all_for_user(user_id)
        self.audit.log(
            actor_id=actor_id,
            actor_role=actor_role,
            action="user.status_changed",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"status": status},
        )
        return self.get_user(user_id) or user

    def update_quota(
        self,
        user_id: str,
        quota: dict[str, Any],
        *,
        actor_id: str = "",
        ip: str = "",
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        current = self.quota_for(user_id)
        try:
            values = {
                "max_bots": int(quota.get("max_bots", current["max_bots"])),
                "monthly_tokens": int(
                    quota.get("monthly_tokens", current["monthly_tokens"])
                ),
                "max_memories": int(quota.get("max_memories", current["max_memories"])),
            }
        except (TypeError, ValueError):
            raise ValidationError("配额必须是整数", field="quota") from None
        if values["max_bots"] < 0 or values["max_memories"] < 0:
            raise ValidationError("配额不能为负数", field="quota")
        self.db.execute(
            "UPDATE quotas SET max_bots = ?, monthly_tokens = ?, max_memories = ? "
            "WHERE user_id = ?",
            (
                values["max_bots"],
                values["monthly_tokens"],
                values["max_memories"],
                user_id,
            ),
        )
        self.audit.log(
            actor_id=actor_id,
            actor_role="admin",
            action="user.quota_changed",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail=values,
        )
        return self.quota_for(user_id)

    # -- serialisation helpers -----------------------------------------
    def user_with_limits(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            **self.public_user(user),
            "quota": self.quota_for(user["id"]),
        }

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
