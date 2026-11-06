"""Runtime settings for the SaaS plugin.

Settings are resolved from (in order): explicit overrides, environment
variables (``SAAS_*``), AstrBot plugin config, then defaults.

The plugin must never import AstrBot at module import time so the core can be
unit-tested standalone; ``from_astrbot_config`` accepts a plain mapping.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION = "0.1.0"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw


@dataclass
class Settings:
    """All tunables of the plugin (see docs/ARCHITECTURE.md)."""

    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 6180
    # Cookies
    cookie_secure: bool = True
    cookie_same_site: str = "Lax"
    session_sliding_days: int = 30
    session_absolute_days: int = 90
    admin_session_hours: int = 12
    # Invites / OTP
    invite_ttl_hours: int = 72
    otp_ttl_seconds: int = 600
    otp_resend_seconds: int = 60
    otp_max_attempts: int = 5
    # QR
    qr_ttl_seconds: int = 60
    qr_max_refreshes: int = 3
    qr_idle_timeout_seconds: int = 300
    qr_poll_interval: int = 2
    # Product switches
    allow_public_signup: bool = False
    allow_user_disable_encryption: bool = True
    allow_admin_disable_encryption: bool = False
    # Mail (OTP delivery)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "AstrBot 控制台"
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    # Dev / testing
    dev_mode: bool = False
    otp_dev_echo: bool = False
    admin_email: str = ""
    version: str = VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    # -- derived paths -------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "saas.sqlite3"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"

    @property
    def kek_file(self) -> Path:
        return self.keys_dir / "root_kek.bin"

    @property
    def console_dist(self) -> Path:
        return Path(__file__).resolve().parent.parent / "web" / "dist"

    @property
    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "migrations"

    @property
    def cookie_name(self) -> str:
        # ``__Host-`` requires Secure + Path=/ + no Domain; fall back in dev.
        return "__Host-sid" if self.cookie_secure else "sid"

    @property
    def csrf_cookie_name(self) -> str:
        return "csrf"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.keys_dir, 0o700)
        except OSError:
            pass

    # -- constructors --------------------------------------------------
    @classmethod
    def for_dev(cls, data_dir: str | Path | None = None) -> "Settings":
        base = Path(data_dir or (Path.cwd() / "devdata")).expanduser().resolve()
        return cls(
            data_dir=base,
            host=_env_str("SAAS_HOST", "127.0.0.1"),
            port=_env_int("SAAS_PORT", 6180),
            cookie_secure=False,
            dev_mode=True,
            otp_dev_echo=True,
            admin_email=_env_str("SAAS_ADMIN_EMAIL", "admin@example.com"),
        )

    @classmethod
    def from_env(cls, data_dir: str | Path | None = None) -> "Settings":
        base = Path(
            data_dir
            or os.environ.get("SAAS_DATA_DIR")
            or (Path.cwd() / "data" / "saas")
        ).expanduser().resolve()
        settings = cls(data_dir=base)
        settings.host = _env_str("SAAS_HOST", settings.host)
        settings.port = _env_int("SAAS_PORT", settings.port)
        settings.cookie_secure = _env_bool("SAAS_COOKIE_SECURE", settings.cookie_secure)
        settings.allow_public_signup = _env_bool(
            "SAAS_ALLOW_PUBLIC_SIGNUP", settings.allow_public_signup
        )
        settings.allow_user_disable_encryption = _env_bool(
            "SAAS_ALLOW_USER_DISABLE_ENCRYPTION",
            settings.allow_user_disable_encryption,
        )
        settings.allow_admin_disable_encryption = _env_bool(
            "SAAS_ALLOW_ADMIN_DISABLE_ENCRYPTION",
            settings.allow_admin_disable_encryption,
        )
        settings.otp_dev_echo = _env_bool("SAAS_OTP_DEV_ECHO", settings.otp_dev_echo)
        settings.dev_mode = _env_bool("SAAS_DEV_MODE", settings.dev_mode)
        settings.admin_email = _env_str("SAAS_ADMIN_EMAIL", settings.admin_email)
        settings.smtp_host = _env_str("SAAS_SMTP_HOST", settings.smtp_host)
        settings.smtp_port = _env_int("SAAS_SMTP_PORT", settings.smtp_port)
        settings.smtp_user = _env_str("SAAS_SMTP_USER", settings.smtp_user)
        settings.smtp_password = _env_str("SAAS_SMTP_PASSWORD", settings.smtp_password)
        settings.smtp_from = _env_str("SAAS_SMTP_FROM", settings.smtp_from)
        settings.smtp_from_name = _env_str("SAAS_SMTP_FROM_NAME", settings.smtp_from_name)
        settings.smtp_starttls = _env_bool("SAAS_SMTP_STARTTLS", settings.smtp_starttls)
        settings.smtp_ssl = _env_bool("SAAS_SMTP_SSL", settings.smtp_ssl)
        settings.invite_ttl_hours = _env_int(
            "SAAS_INVITE_TTL_HOURS", settings.invite_ttl_hours
        )
        settings.qr_ttl_seconds = _env_int("SAAS_QR_TTL_SECONDS", settings.qr_ttl_seconds)
        settings.qr_max_refreshes = _env_int(
            "SAAS_QR_MAX_REFRESHES", settings.qr_max_refreshes
        )
        return settings

    @classmethod
    def from_astrbot_config(
        cls, data_dir: str | Path, config: dict[str, Any] | None
    ) -> "Settings":
        """Build settings from AstrBot plugin config (``dict``-like)."""
        settings = cls.from_env(data_dir)
        if not config:
            return settings
        get = getattr(config, "get", None)
        if get is None:
            return settings

        def val(key: str, default: Any) -> Any:
            try:
                value = get(key, default)
            except Exception:
                return default
            return default if value is None else value

        settings.host = str(val("console_host", settings.host))
        try:
            settings.port = int(val("console_port", settings.port))
        except (TypeError, ValueError):
            pass
        settings.cookie_secure = bool(val("cookie_secure", settings.cookie_secure))
        settings.allow_public_signup = bool(
            val("allow_public_signup", settings.allow_public_signup)
        )
        settings.otp_dev_echo = bool(val("otp_dev_echo", settings.otp_dev_echo))
        settings.dev_mode = bool(val("dev_mode", settings.dev_mode))
        settings.admin_email = str(val("initial_admin_email", settings.admin_email))
        settings.qr_ttl_seconds = int(val("qr_ttl_seconds", settings.qr_ttl_seconds))
        settings.qr_max_refreshes = int(
            val("qr_max_refreshes", settings.qr_max_refreshes)
        )
        for attr in (
            "smtp_host",
            "smtp_user",
            "smtp_password",
            "smtp_from",
            "smtp_from_name",
        ):
            raw = val(attr, None)
            if raw is not None:
                setattr(settings, attr, str(raw))
        for attr in ("smtp_port",):
            raw = val(attr, None)
            if raw is not None:
                try:
                    setattr(settings, attr, int(raw))
                except (TypeError, ValueError):
                    pass
        for attr in ("smtp_starttls", "smtp_ssl"):
            raw = val(attr, None)
            if raw is not None:
                setattr(settings, attr, bool(raw))
        # Optional overrides from plugin config (never required).
        for attr in (
            "invite_ttl_hours",
            "otp_ttl_seconds",
            "otp_resend_seconds",
            "otp_max_attempts",
            "session_sliding_days",
            "session_absolute_days",
            "admin_session_hours",
        ):
            raw = val(attr, None)
            if raw is not None:
                try:
                    setattr(settings, attr, int(raw))
                except (TypeError, ValueError):
                    pass
        return settings
