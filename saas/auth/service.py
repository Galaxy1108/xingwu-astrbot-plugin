"""Account use-cases: OTP login, invite-gated registration, sessions, roles."""

from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
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
from .passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    verify_password,
)
from .sessions import SessionService

logger = logging.getLogger(__name__)

DEFAULT_QUOTA = {"max_bots": 3, "monthly_tokens": 1_000_000, "max_memories": 2000}
PLACEHOLDER_EMAIL_DOMAIN = "no-email.local"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
_USERNAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def is_placeholder_email(email: str | None) -> bool:
    return bool(email) and str(email).lower().endswith("@" + PLACEHOLDER_EMAIL_DOMAIN)


def placeholder_email(user_id: str) -> str:
    return f"{user_id}@{PLACEHOLDER_EMAIL_DOMAIN}"


def validate_username(username: Any) -> str:
    value = str(username or "").strip()
    if not USERNAME_RE.match(value):
        raise ValidationError("用户名需为 3–32 位字母、数字、下划线或连字符", field="username")
    return value


def validate_password_policy(password: Any) -> str:
    value = str(password if password is not None else "")
    if len(value) < MIN_PASSWORD_LENGTH or len(value) > MAX_PASSWORD_LENGTH:
        raise ValidationError(
            f"密码需为 {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} 个字符",
            field="password",
        )
    return value



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
        mailer=None,
        clock: Clock | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.invites = invites
        self.otp = otp
        self.sessions = sessions
        self.keys = keys
        self.audit = audit
        self.mailer = mailer
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

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        value = str(username or "").strip()
        if not value:
            return None
        return self.db.query_one(
            "SELECT * FROM users WHERE username = ? AND status != 'deleted'",
            (value,),
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
        raw_email = str(user.get("email") or "")
        hidden_email = is_placeholder_email(raw_email)
        email = "" if hidden_email else raw_email
        username = str(user.get("username") or "")
        display_name = (
            user.get("display_name")
            or username
            or (email.split("@")[0] if email else "")
        )
        email_verified = bool(int(user.get("email_verified") or 0))
        return {
            "id": user["id"],
            "email": email,
            "username": username,
            "display_name": display_name,
            "role": user["role"],
            "status": user["status"],
            "status_reason": user.get("status_reason") or "",
            "status_changed_at": int(user.get("status_changed_at") or 0),
            "created_at": user["created_at"],
            "email_verified": email_verified,
            "has_password": bool(user.get("password_hash")),
            "recovery_available": bool(email_verified and not hidden_email),
            "encryption": {
                "enabled": bool(user.get("encryption_enabled", 1)),
                "state": user.get("encryption_state", "encrypted"),
            },
        }

    # -- OTP -----------------------------------------------------------
    def _dispatch_otp(
        self, email: str, *, purpose: str = "login", ip: str = ""
    ) -> dict[str, Any]:
        """Create + deliver an OTP; returns the API payload (internal code)."""
        result = self.otp.request(email, ip=ip, purpose=purpose)
        code = str(result.pop("code", "") or "")
        delivered = False
        if code and self.mailer is not None:
            try:
                delivered = bool(
                    self.mailer.send_otp(
                        email,
                        code,
                        expires_minutes=max(1, self.settings.otp_ttl_seconds // 60),
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("发送 OTP 邮件失败：%s", email)
        if self.settings.otp_dev_echo:
            result["dev_code"] = code
        result["delivered"] = delivered
        return result

    def request_otp(
        self,
        email: str,
        *,
        invite: str | None = None,
        ip: str = "",
        purpose: str = "login",
    ) -> dict[str, Any]:
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValidationError("邮箱格式不正确", field="email")
        user = self.get_user_by_email(email)
        # Banned users must still be able to log in: the console shows the ban
        # notice and the appeal form, and every other API is gated by the
        # session middleware (``account_banned``).
        if user is None:
            if self.settings.allow_public_signup:
                pass
            elif not (invite or "").strip():
                raise ValidationError(
                    "首次注册需要邀请码", code="invite_invalid", status=410, field="invite"
                )
            else:
                self.invites.verify(invite or "")
        result = self._dispatch_otp(email, purpose=purpose, ip=ip)
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
        purpose: str = "login",
        password: str | None = None,
        username: str | None = None,
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
        # Validate optional registration fields *before* consuming the OTP so a
        # bad password/username does not force the user to request a new code.
        username_value = ""
        password_hash = ""
        if user is None:
            explicit_username = (username or "").strip()
            if password is not None and str(password) != "":
                password_hash = hash_password(validate_password_policy(password))
            if explicit_username:
                username_value = validate_username(explicit_username)
                if self.get_user_by_username(username_value) is not None:
                    raise AppError(
                        "用户名已被占用", code="username_taken", status=409, field="username"
                    )
            else:
                seed = email.split("@")[0] if "@" in email else email
                username_value = self._unique_username(seed)
        self.otp.verify(email, code, purpose=purpose)
        is_new = False
        if user is None:
            try:
                user = self._insert_account(
                    email=email,
                    username=username_value,
                    display_name=email.split("@")[0][:32],
                    password_hash=password_hash,
                    email_verified=1,
                    invite_code=invite_code,
                    consume_invite=bool(invite_code)
                    and not self.settings.allow_public_signup,
                    ip=ip,
                )
            except sqlite3.IntegrityError:
                raise AppError(
                    "用户名已被占用",
                    code="username_taken",
                    status=409,
                    field="username",
                ) from None
            is_new = True
        if user["status"] == "deleted":
            raise Forbidden("账号已被删除")
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
    @staticmethod
    def _sanitize_username_seed(seed: Any) -> str:
        value = _USERNAME_SAFE_RE.sub("_", str(seed or "").strip()).strip("_-")
        if len(value) < 3:
            value = f"user_{value}" if value else "user"
        return value[:32]

    def _unique_username(self, seed: Any, *, exclude_user_id: str = "") -> str:
        """Generate a free username: sanitized seed, random suffix on conflict."""
        base = self._sanitize_username_seed(seed)
        candidate = base
        for _ in range(8):
            row = self.db.query_one(
                "SELECT id FROM users WHERE username = ?", (candidate,)
            )
            if row is None or str(row["id"]) == str(exclude_user_id):
                return candidate
            suffix = f"_{secrets.token_hex(2)}"
            candidate = f"{base[: 32 - len(suffix)]}{suffix}"
        return f"u_{secrets.token_hex(6)}"

    def _insert_account(
        self,
        *,
        email: str | None,
        username: str,
        display_name: str = "",
        password_hash: str = "",
        email_verified: int = 0,
        invite_code: str = "",
        consume_invite: bool = False,
        ip: str = "",
        placeholder: bool = False,
    ) -> dict[str, Any]:
        now = self.clock.now()
        user_id = random_id("u", 8)
        account_email = placeholder_email(user_id) if placeholder else normalize_email(email or "")
        name = (display_name or username or "用户").strip()[:32]
        invite_hint = invite_code[:8] if invite_code else ""
        with self.db.transaction():
            if consume_invite and invite_code:
                self.invites.consume(invite_code)
            self.db.execute(
                "INSERT INTO users(id, email, display_name, role, status, created_at, "
                "invite_code, encryption_enabled, encryption_state, password_hash, "
                "email_verified, username) VALUES (?,?,?,?,?,?,?,1,'encrypted',?,?,?)",
                (
                    user_id,
                    account_email,
                    name,
                    "user",
                    "active",
                    now,
                    invite_hint,
                    password_hash,
                    1 if email_verified else 0,
                    username,
                ),
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
            detail={"email": account_email, "username": username},
        )
        return user

    def _create_user(self, email: str, invite_code: str, *, ip: str = "") -> dict[str, Any]:
        """OTP registration helper (kept for backwards-compatible call sites)."""
        return self._insert_account(
            email=email,
            username=self._unique_username(email.split("@")[0]),
            display_name=email.split("@")[0][:32],
            email_verified=1,
            invite_code=invite_code,
            consume_invite=bool(invite_code) and not self.settings.allow_public_signup,
            ip=ip,
        )

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: Any = None,
        username: Any = None,
        ip: str = "",
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        changes: dict[str, Any] = {}
        if display_name is not None:
            name = str(display_name or "").strip()
            if not name or len(name) > 32:
                raise ValidationError("用户名需为 1–32 个字符", field="display_name")
            changes["display_name"] = name
        if username is not None:
            value = validate_username(username)
            if value != str(user.get("username") or ""):
                existing = self.get_user_by_username(value)
                if existing is not None and str(existing["id"]) != str(user_id):
                    raise AppError(
                        "用户名已被占用",
                        code="username_taken",
                        status=409,
                        field="username",
                    )
                changes["username"] = value
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            try:
                self.db.execute(
                    f"UPDATE users SET {assignments} WHERE id = ?",
                    [*changes.values(), user_id],
                )
            except sqlite3.IntegrityError:
                raise AppError(
                    "用户名已被占用",
                    code="username_taken",
                    status=409,
                    field="username",
                ) from None
            self.audit.log(
                actor_id=user_id,
                actor_role=user.get("role", "user"),
                action="user.profile_updated",
                target_type="user",
                target_id=user_id,
                ip=ip,
                detail=dict(changes),
            )
        return self.get_user(user_id) or user

    def update_display_name(
        self, user_id: str, display_name: str, *, ip: str = ""
    ) -> dict[str, Any]:
        return self.update_profile(user_id, display_name=display_name, ip=ip)

    def create_user(
        self, email: str, *, role: str = "user", invite_code: str = "", ip: str = ""
    ) -> dict[str, Any]:
        """Admin/seed usage: create an account directly (no OTP)."""
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValidationError("邮箱格式不正确", field="email")
        if self.get_user_by_email(email) is not None:
            raise ValidationError("邮箱已注册", field="email")
        user = self._insert_account(
            email=email,
            username=self._unique_username(email.split("@")[0]),
            display_name=email.split("@")[0][:32],
            email_verified=1,
            invite_code=invite_code,
            consume_invite=bool(invite_code) and not self.settings.allow_public_signup,
            ip=ip,
        )
        if role != "user":
            self.db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user["id"]))
            user = self.get_user(user["id"]) or user
        return user

    # -- password auth --------------------------------------------------
    def register_with_password(
        self,
        *,
        invite: str,
        username: str,
        password: str,
        display_name: str = "",
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, Any]:
        """Invite-gated, e-mail-less registration (placeholder address)."""
        invite_code = normalize_invite_code(invite or "")
        if not invite_code:
            raise ValidationError(
                "首次注册需要邀请码", code="invite_invalid", status=410, field="invite"
            )
        self.invites.verify(invite_code)
        username_value = validate_username(username)
        if self.get_user_by_username(username_value) is not None:
            raise AppError(
                "用户名已被占用", code="username_taken", status=409, field="username"
            )
        password_hash = hash_password(validate_password_policy(password))
        name = str(display_name or "").strip()[:32] or username_value
        try:
            user = self._insert_account(
                email=None,
                placeholder=True,
                username=username_value,
                display_name=name,
                password_hash=password_hash,
                email_verified=0,
                invite_code=invite_code,
                consume_invite=True,
                ip=ip,
            )
        except sqlite3.IntegrityError:
            raise AppError(
                "用户名已被占用", code="username_taken", status=409, field="username"
            ) from None
        session = self.sessions.create(user, ip=ip, user_agent=user_agent)
        return {
            "user": self.public_user(user),
            "session": session,
            "recovery_available": False,
        }

    def password_login(
        self,
        identifier: str,
        password: str,
        *,
        ip: str = "",
        user_agent: str = "",
    ) -> dict[str, Any]:
        value = str(identifier or "").strip()
        if "@" in value:
            user = self.get_user_by_email(value)
        else:
            user = self.get_user_by_username(value)
        if user is None:
            raise AppError(
                "账号或密码错误", code="invalid_credentials", status=401
            )
        stored = str(user.get("password_hash") or "")
        if not stored:
            raise AppError(
                "该账号尚未设置密码", code="password_not_set", status=400, field="password"
            )
        if not verify_password(password, stored):
            raise AppError(
                "账号或密码错误", code="invalid_credentials", status=401
            )
        if needs_rehash(stored):
            self.db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user["id"]),
            )
            user = self.get_user(user["id"]) or user
        session = self.sessions.create(user, ip=ip, user_agent=user_agent)
        self.audit.log(
            actor_id=user["id"],
            actor_role=user["role"],
            action="auth.login",
            target_type="user",
            target_id=user["id"],
            ip=ip,
        )
        return {
            "user": self.public_user(user),
            "session": session,
            "recovery_available": self.public_user(user)["recovery_available"],
        }

    def request_password_reset(self, email: str, *, ip: str = "") -> dict[str, Any]:
        """Send a reset OTP, but never reveal whether the account exists."""
        normalized = normalize_email(email)
        result: dict[str, Any] = {"sent": True}
        user = self.get_user_by_email(normalized) if is_valid_email(normalized) else None
        if user is None:
            return result
        if not int(user.get("email_verified") or 0) or is_placeholder_email(
            user.get("email")
        ):
            return result
        dispatched = self._dispatch_otp(normalized, purpose="reset", ip=ip)
        for key in ("expires_at", "resend_after", "dev_code", "delivered"):
            if key in dispatched:
                result[key] = dispatched[key]
        self.audit.log(
            actor_id=user["id"],
            actor_role=user["role"],
            action="auth.password_reset_requested",
            target_type="user",
            target_id=user["id"],
            ip=ip,
        )
        return result

    def reset_password(
        self, email: str, code: str, password: str, *, ip: str = ""
    ) -> dict[str, Any]:
        normalized = normalize_email(email)
        new_hash = hash_password(validate_password_policy(password))
        self.otp.verify(normalized, code, purpose="reset")
        user = self.get_user_by_email(normalized)
        if user is None or not int(user.get("email_verified") or 0):
            raise AppError(
                "验证码无效或已过期", code="otp_invalid", status=401, field="code"
            )
        self.db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, user["id"]),
        )
        self.sessions.revoke_all_for_user(user["id"])
        self.audit.log(
            actor_id=user["id"],
            actor_role=user["role"],
            action="auth.password_reset",
            target_type="user",
            target_id=user["id"],
            ip=ip,
        )
        return {"reset": True}

    def set_password(
        self,
        user_id: str,
        new_password: str,
        *,
        current_password: str | None = None,
        ip: str = "",
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        stored = str(user.get("password_hash") or "")
        if stored and not verify_password(str(current_password or ""), stored):
            raise AppError(
                "当前密码不正确",
                code="invalid_credentials",
                status=400,
                field="current_password",
            )
        self.db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(validate_password_policy(new_password)), user_id),
        )
        self.audit.log(
            actor_id=user_id,
            actor_role=user["role"],
            action="user.password_changed",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"had_password": bool(stored)},
        )
        return self.get_user(user_id) or user

    # -- e-mail binding -------------------------------------------------
    def request_email_bind(self, user_id: str, email: str, *, ip: str = "") -> dict[str, Any]:
        user = self.get_user(user_id)
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        normalized = normalize_email(email)
        if not is_valid_email(normalized):
            raise ValidationError("邮箱格式不正确", field="email")
        existing = self.get_user_by_email(normalized)
        if existing is not None and str(existing["id"]) != str(user_id):
            raise AppError("该邮箱已被使用", code="email_taken", status=409, field="email")
        result = self._dispatch_otp(normalized, purpose="bind", ip=ip)
        result["sent"] = True
        return result

    def bind_email(self, user_id: str, email: str, code: str, *, ip: str = "") -> dict[str, Any]:
        user = self.get_user(user_id)
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        normalized = normalize_email(email)
        if not is_valid_email(normalized):
            raise ValidationError("邮箱格式不正确", field="email")
        self.otp.verify(normalized, code, purpose="bind")
        existing = self.get_user_by_email(normalized)
        if existing is not None and str(existing["id"]) != str(user_id):
            raise AppError("该邮箱已被使用", code="email_taken", status=409, field="email")
        try:
            self.db.execute(
                "UPDATE users SET email = ?, email_verified = 1 WHERE id = ?",
                (normalized, user_id),
            )
        except sqlite3.IntegrityError:
            raise AppError(
                "该邮箱已被使用", code="email_taken", status=409, field="email"
            ) from None
        self.audit.log(
            actor_id=user_id,
            actor_role=user["role"],
            action="user.email_bound",
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail={"email": normalized},
        )
        return self.get_user(user_id) or user

    # -- OAuth account creation ----------------------------------------
    def create_oauth_user(
        self, *, login: str, invite: str, ip: str = ""
    ) -> dict[str, Any]:
        """Create an e-mail-less account for a third-party identity."""
        invite_code = normalize_invite_code(invite or "")
        if not invite_code:
            raise ValidationError(
                "首次注册需要邀请码", code="invite_invalid", status=410, field="invite"
            )
        username = self._unique_username(login or "github")
        return self._insert_account(
            email=None,
            placeholder=True,
            username=username,
            display_name=username,
            password_hash="",
            email_verified=0,
            invite_code=invite_code,
            consume_invite=True,
            ip=ip,
        )

    # -- admin account state -------------------------------------------
    def set_user_status(
        self,
        user_id: str,
        status: str,
        *,
        reason: str = "",
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
        reason = str(reason or "").strip()[:500]
        self.db.execute(
            "UPDATE users SET status = ?, disabled_at = ?, status_reason = ?, "
            "status_changed_at = ? WHERE id = ?",
            (
                status,
                now if status == "disabled" else 0,
                reason if status == "disabled" else "",
                now,
                user_id,
            ),
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
            detail={"status": status, "reason": reason},
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
        if not isinstance(quota, dict):
            raise ValidationError("quota 必须是对象", field="quota")
        current = self.quota_for(user_id)
        values: dict[str, int] = {}
        for field in ("max_bots", "monthly_tokens", "max_memories"):
            if quota.get(field) is None:
                values[field] = int(current[field])
            else:
                values[field] = self._quota_int(quota[field], field)
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

    @staticmethod
    def _quota_int(value: Any, field: str) -> int:
        """Validate one quota field: integral, non-negative, not a bool."""
        if isinstance(value, bool):
            raise ValidationError(f"{field} 必须是非负整数", field=field)
        if isinstance(value, float):
            if not value.is_integer():
                raise ValidationError(f"{field} 必须是非负整数", field=field)
            number = int(value)
        else:
            try:
                number = int(str(value).strip())
            except (TypeError, ValueError):
                raise ValidationError(f"{field} 必须是非负整数", field=field) from None
        if number < 0:
            raise ValidationError(f"{field} 不能为负数", field=field)
        return number

    # -- serialisation helpers -----------------------------------------
    def user_with_limits(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            **self.public_user(user),
            "quota": self.quota_for(user["id"]),
        }

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
