"""Email one-time passwords: 6 digits, 10 min, single use, 60s resend, 5 tries."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable

from ..config import Settings
from ..db import Database
from ..errors import AppError, RateLimited, ValidationError
from ..security import constant_time_eq, hmac_hex, new_otp, random_id

EMAIL_MAX_LENGTH = 254

# Purpose namespaces keep login / password-reset / e-mail-bind codes isolated:
# requesting a reset code never invalidates (or satisfies) a login code.
OTP_PURPOSES = {"login", "reset", "bind"}


def normalize_purpose(purpose: str | None) -> str:
    value = (purpose or "login").strip().lower()
    if value not in OTP_PURPOSES:
        raise ValidationError("未知的验证码用途", field="purpose")
    return value



def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    if not email or len(email) > EMAIL_MAX_LENGTH or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if any(ch.isspace() for ch in email):
        return False
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return False
    return True


class OtpService:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings,
        pepper: bytes,
        clock=None,
        code_factory: Callable[[], str] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self._pepper = pepper
        self.clock = clock
        self._code_factory = code_factory or new_otp

    def _now(self) -> int:
        return self.clock.now() if self.clock is not None else int(time.time())

    def _hash(self, email: str, code: str, purpose: str) -> str:
        return hmac_hex(self._pepper, f"{purpose}:{email}:{code}")

    def _matches(self, email: str, code: str, purpose: str, stored: str) -> bool:
        if constant_time_eq(self._hash(email, code, purpose), stored):
            return True
        # Backwards compatibility: login codes issued before purpose-aware
        # hashing (007 password-auth deployment) used ``email:code``.
        if purpose == "login":
            return constant_time_eq(hmac_hex(self._pepper, f"{email}:{code}"), stored)
        return False


    def request(
        self, email: str, purpose: str = "login", *, ip: str = ""
    ) -> dict[str, Any]:
        email = normalize_email(email)
        purpose = normalize_purpose(purpose)
        if not is_valid_email(email):
            raise ValidationError("邮箱格式不正确", field="email")
        now = self._now()
        latest = self.db.query_one(
            "SELECT created_at FROM otp_codes WHERE email = ? AND purpose = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (email, purpose),
        )
        if latest is not None:
            elapsed = now - int(latest["created_at"])
            if elapsed < self.settings.otp_resend_seconds:
                raise RateLimited(
                    "请稍后再获取验证码",
                    retry_after=self.settings.otp_resend_seconds - elapsed,
                )
        code = self._code_factory()
        expires_at = now + self.settings.otp_ttl_seconds
        try:
            with self.db.transaction():
                self.db.execute(
                    "UPDATE otp_codes SET consumed_at = ? "
                    "WHERE email = ? AND purpose = ? AND consumed_at = 0",
                    (now, email, purpose),
                )
                self.db.execute(
                    "INSERT INTO otp_codes(id, email, code_hash, purpose, created_at, "
                    "expires_at, attempts, consumed_at, ip) VALUES (?,?,?,?,?,?,0,0,?)",
                    (
                        random_id("otp"),
                        email,
                        self._hash(email, code, purpose),
                        purpose,
                        now,
                        expires_at,
                        ip,
                    ),
                )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise AppError("验证码发送失败，请稍后重试") from exc
        payload: dict[str, Any] = {
            "sent": True,
            "resend_after": self.settings.otp_resend_seconds,
            "expires_at": expires_at,
            "code": code,  # internal: consumed by AuthService (never serialised)
        }
        return payload

    def verify(self, email: str, code: str, purpose: str = "login") -> None:
        email = normalize_email(email)
        purpose = normalize_purpose(purpose)
        code = (code or "").strip()
        if not is_valid_email(email):
            raise ValidationError("邮箱格式不正确", field="email")
        if not code:
            raise ValidationError("请输入验证码", code="otp_invalid", status=401, field="code")
        now = self._now()
        row = self.db.query_one(
            "SELECT * FROM otp_codes WHERE email = ? AND purpose = ? "
            "AND consumed_at = 0 ORDER BY created_at DESC LIMIT 1",
            (email, purpose),
        )
        if row is None:
            raise AppError(
                "验证码无效或已过期", code="otp_invalid", status=401, field="code"
            )
        if int(row["expires_at"]) <= now:
            raise AppError(
                "验证码无效或已过期", code="otp_invalid", status=401, field="code"
            )
        attempts = int(row["attempts"])
        if attempts >= self.settings.otp_max_attempts:
            raise AppError(
                "验证码尝试次数过多，请重新获取",
                code="otp_attempts_exceeded",
                status=429,
                field="code",
            )
        if not self._matches(email, code, purpose, str(row["code_hash"])):
            attempts += 1
            self.db.execute(
                "UPDATE otp_codes SET attempts = ? WHERE id = ?", (attempts, row["id"])
            )
            if attempts >= self.settings.otp_max_attempts:
                raise AppError(
                    "验证码尝试次数过多，请重新获取",
                    code="otp_attempts_exceeded",
                    status=429,
                    field="code",
                )
            raise AppError(
                "验证码无效或已过期", code="otp_invalid", status=401, field="code"
            )
        self.db.execute(
            "UPDATE otp_codes SET consumed_at = ? WHERE id = ?", (now, row["id"])
        )
