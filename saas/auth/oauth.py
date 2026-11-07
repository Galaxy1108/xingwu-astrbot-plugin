"""GitHub OAuth login / registration / binding.

The network layer is injectable (:class:`OAuthHttpClient` protocol): production
uses ``aiohttp`` directly, tests inject a deterministic fake client and never
touch the public network.

Security model
* ``oauth_states``: 32-byte random state, single use, 10-minute TTL, bound to a
  provider and a mode (login / register / bind).  Bind states also store the
  user id that started the flow and every state may carry an invite + a safe
  post-login redirect (internal path only).
* Identities are unique per ``(provider, subject)``; a GitHub account can only
  be bound to one local user.
* The callback is idempotent for the same user (bind) and for existing
  identities (login).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode

from ..clock import Clock, SystemClock
from ..config import Settings
from ..db import Database
from ..errors import AppError, ValidationError
from ..security import random_id, random_token
from .service import is_placeholder_email

if TYPE_CHECKING:  # pragma: no cover
    from .invites import InviteService
    from .service import AuthService
    from .sessions import SessionService

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

OAUTH_STATE_TTL_SECONDS = 600
OAUTH_MODES = {"login", "register", "bind"}
OAUTH_PROVIDERS: dict[str, str] = {"github": "GitHub"}
OAUTH_SETTINGS_KEY = "oauth.github"
OAUTH_SECRET_MASK = "••••••••"


class OAuthHttpClient(Protocol):
    """Injectable network layer (implemented with aiohttp in production)."""

    async def exchange_code(
        self, provider: str, code: str, settings: Settings, *, redirect_uri: str = ""
    ) -> str: ...

    async def fetch_identity(
        self, provider: str, access_token: str, settings: Settings
    ) -> dict[str, Any]: ...


class HttpOAuthClient:
    """Default aiohttp client for GitHub's OAuth + REST API."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = max(0.1, min(60.0, float(timeout_seconds or 10.0)))

    async def exchange_code(
        self, provider: str, code: str, settings: Settings, *, redirect_uri: str = ""
    ) -> str:
        import aiohttp

        payload = {
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
        }
        redirect = redirect_uri or settings.github_redirect_uri
        if redirect:
            payload["redirect_uri"] = redirect
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    GITHUB_TOKEN_URL,
                    data=payload,
                    headers={"Accept": "application/json"},
                ) as response:
                    data = await response.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("GitHub token exchange failed: %s", type(exc).__name__)
            raise AppError(
                "GitHub 登录失败，请稍后重试", code="oauth_provider_error", status=502
            ) from None
        token = str((data or {}).get("access_token") or "").strip()
        if not token:
            raise AppError(
                "GitHub 授权失败，请重试", code="oauth_provider_error", status=502
            )
        return token

    async def fetch_identity(
        self, provider: str, access_token: str, settings: Settings
    ) -> dict[str, Any]:
        import aiohttp

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "astrbot-saas-plugin",
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(GITHUB_USER_URL, headers=headers) as response:
                    profile = await response.json(content_type=None)
                email = str((profile or {}).get("email") or "").strip()
                if not email:
                    async with session.get(
                        GITHUB_EMAILS_URL, headers=headers
                    ) as response:
                        emails = await response.json(content_type=None)
                    if isinstance(emails, list):
                        chosen = next(
                            (
                                item
                                for item in emails
                                if isinstance(item, dict)
                                and item.get("primary")
                                and item.get("verified")
                            ),
                            None,
                        )
                        if chosen is None:
                            chosen = next(
                                (
                                    item
                                    for item in emails
                                    if isinstance(item, dict) and item.get("verified")
                                ),
                                None,
                            )
                        if chosen is not None:
                            email = str(chosen.get("email") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GitHub profile fetch failed: %s", type(exc).__name__)
            raise AppError(
                "GitHub 登录失败，请稍后重试", code="oauth_provider_error", status=502
            ) from None
        subject = str((profile or {}).get("id") or "").strip()
        login = str((profile or {}).get("login") or "").strip()
        if not subject:
            raise AppError(
                "GitHub 账号信息不完整", code="oauth_provider_error", status=502
            )
        return {"subject": subject, "login": login, "email": email}


def _safe_next_path(value: Any) -> str:
    """Only allow same-site absolute paths (prevents open redirects)."""
    text = str(value or "").strip()
    if not text or len(text) > 500:
        return ""
    if not text.startswith("/") or text.startswith("//"):
        return ""
    return text


class OAuthService:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings,
        auth: "AuthService",
        invites: "InviteService",
        sessions: "SessionService",
        audit: Any = None,
        clock: Clock | None = None,
        client: OAuthHttpClient | None = None,
        settings_store: Any = None,
        state_ttl_seconds: int = OAUTH_STATE_TTL_SECONDS,
    ) -> None:
        self.db = db
        self.settings = settings
        # Optional encrypted platform settings; ``oauth.github`` overrides the
        # env/plugin-config values so an administrator can enable GitHub OAuth
        # from the console without a restart.
        self.settings_store = settings_store
        self.auth = auth
        self.invites = invites
        self.sessions = sessions
        self.audit = audit
        self.clock = clock or SystemClock()
        self.client: Any = client or HttpOAuthClient()
        self.state_ttl_seconds = int(state_ttl_seconds or OAUTH_STATE_TTL_SECONDS)

    # -- helpers -------------------------------------------------------
    def _now(self) -> int:
        return self.clock.now()

    @staticmethod
    def _provider(provider: str) -> str:
        value = str(provider or "").strip().lower()
        if value not in OAUTH_PROVIDERS:
            raise ValidationError("不支持的第三方登录方式", field="provider")
        return value

    def _stored_github(self) -> dict[str, Any]:
        if self.settings_store is None:
            return {}
        value = self.settings_store.get(OAUTH_SETTINGS_KEY)
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _pick(stored: dict[str, Any], key: str, fallback: Any) -> str:
        value = stored.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return str(fallback or "").strip()

    def github_config(self) -> dict[str, str]:
        """Effective GitHub credentials: encrypted store first, Settings second."""
        stored = self._stored_github()
        return {
            "client_id": self._pick(stored, "client_id", self.settings.github_client_id),
            "client_secret": self._pick(
                stored, "client_secret", self.settings.github_client_secret
            ),
            "redirect_uri": self._pick(
                stored, "redirect_uri", self.settings.github_redirect_uri
            ),
        }

    def _client_settings(self) -> Settings:
        """Settings view with the effective GitHub credentials for network calls."""
        config = self.github_config()
        if (
            config["client_id"] == str(self.settings.github_client_id or "").strip()
            and config["client_secret"]
            == str(self.settings.github_client_secret or "").strip()
            and config["redirect_uri"]
            == str(self.settings.github_redirect_uri or "").strip()
        ):
            return self.settings
        return replace(
            self.settings,
            github_client_id=config["client_id"],
            github_client_secret=config["client_secret"],
            github_redirect_uri=config["redirect_uri"],
        )

    def _stored_enabled(self) -> bool:
        """Admin on/off switch (absent = enabled once credentials exist)."""
        return bool(self._stored_github().get("enabled", True))

    def _github_enabled(self) -> bool:
        config = self.github_config()
        return bool(config["client_id"] and config["client_secret"]) and self._stored_enabled()

    def github_enabled(self) -> bool:
        """Public flag used by the admin settings page."""
        return self._github_enabled()

    def _require_enabled(self, provider: str) -> str:
        value = self._provider(provider)
        if not self._github_enabled():
            raise AppError(
                "该第三方登录尚未配置",
                code="oauth_disabled",
                status=400,
                field="provider",
            )
        return value

    def providers(self) -> list[dict[str, Any]]:
        enabled = self._github_enabled()
        return [
            {"id": provider, "name": name, "enabled": enabled}
            for provider, name in OAUTH_PROVIDERS.items()
        ]

    def _authorize_url(
        self, provider: str, state: str, *, callback_url: str = ""
    ) -> str:
        config = self.github_config()
        # Configured redirect URI wins; only fall back to the request origin.
        redirect_uri = config["redirect_uri"] or callback_url
        params = {
            "client_id": config["client_id"],
            "scope": "read:user user:email",
            "state": state,
        }
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    def _consume_state(self, provider: str, state: str) -> dict[str, Any]:
        value = str(state or "").strip()
        if not value:
            raise AppError(
                "登录状态无效或已过期",
                code="oauth_state_invalid",
                status=400,
                field="state",
            )
        row = self.db.query_one(
            "SELECT * FROM oauth_states WHERE state = ?", (value,)
        )
        if row is None:
            raise AppError(
                "登录状态无效或已过期",
                code="oauth_state_invalid",
                status=400,
                field="state",
            )
        self.db.execute("DELETE FROM oauth_states WHERE state = ?", (value,))
        if int(row["expires_at"]) <= self._now():
            raise AppError(
                "登录状态已过期，请重新发起",
                code="oauth_state_expired",
                status=400,
                field="state",
            )
        if row["provider"] != provider:
            raise AppError(
                "登录状态与提供方不匹配",
                code="oauth_state_invalid",
                status=400,
                field="state",
            )
        return row

    def _identity_for(
        self, provider: str, subject: str
    ) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM oauth_identities WHERE provider = ? AND subject = ?",
            (provider, str(subject)),
        )

    def _identities_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM oauth_identities WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        )

    def _insert_identity(
        self,
        user_id: str,
        provider: str,
        subject: str,
        *,
        email: str = "",
        login: str = "",
    ) -> dict[str, Any]:
        try:
            self.db.execute(
                "INSERT INTO oauth_identities(id, user_id, provider, subject, email, "
                "login, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    random_id("oid", 8),
                    user_id,
                    provider,
                    str(subject),
                    str(email or ""),
                    str(login or ""),
                    self._now(),
                ),
            )
        except Exception:  # noqa: BLE001 - UNIQUE(provider, subject)
            existing = self._identity_for(provider, subject)
            if existing is not None:
                if str(existing["user_id"]) != str(user_id):
                    raise AppError(
                        "该第三方账号已绑定其他用户",
                        code="oauth_already_bound",
                        status=409,
                    ) from None
                return existing
            raise
        return self._identity_for(provider, subject) or {}

    @staticmethod
    def _identity_payload(identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": identity["provider"],
            "login": identity["login"],
            "email": identity["email"],
            "created_at": int(identity["created_at"]),
        }

    def _audit(self, action: str, user_id: str, *, ip: str = "", detail=None) -> None:
        if self.audit is None:
            return
        self.audit.log(
            actor_id=user_id,
            actor_role="user",
            action=action,
            target_type="user",
            target_id=user_id,
            ip=ip,
            detail=detail or {},
        )

    # -- public API ----------------------------------------------------
    def start(
        self,
        provider: str,
        mode: str,
        *,
        user_id: str = "",
        invite: str = "",
        redirect: str = "",
        callback_url: str = "",
    ) -> dict[str, Any]:
        provider = self._require_enabled(provider)
        normalized_mode = str(mode or "login").strip().lower()
        if normalized_mode not in OAUTH_MODES:
            raise ValidationError("mode 只能是 login、register 或 bind", field="mode")
        if normalized_mode == "bind":
            if not str(user_id or "").strip():
                raise AppError("绑定第三方账号需要先登录", code="unauthorized", status=401)
            if self.auth.get_user(str(user_id)) is None:
                raise AppError("用户不存在", code="not_found", status=404)
        state = random_token(32)
        now = self._now()
        self.db.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now,))
        self.db.execute(
            "INSERT INTO oauth_states(state, provider, mode, user_id, invite, redirect, "
            "expires_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                state,
                provider,
                normalized_mode,
                str(user_id or ""),
                str(invite or "").strip(),
                _safe_next_path(redirect),
                now + self.state_ttl_seconds,
                now,
            ),
        )
        return {
            "authorize_url": self._authorize_url(
                provider, state, callback_url=callback_url
            ),
            "state": state,
        }

    async def callback(
        self,
        provider: str,
        code: str,
        state: str,
        *,
        current_user_id: str = "",
        ip: str = "",
        user_agent: str = "",
        callback_url: str = "",
    ) -> dict[str, Any]:
        provider = self._require_enabled(provider)
        state_row = self._consume_state(provider, state)
        code = str(code or "").strip()
        if not code:
            raise AppError(
                "缺少授权码，请重新发起登录",
                code="oauth_code_invalid",
                status=400,
                field="code",
            )
        config = self.github_config()
        redirect_uri = config["redirect_uri"] or callback_url
        client_settings = self._client_settings()
        try:
            token = await self.client.exchange_code(
                provider,
                code,
                client_settings,
                redirect_uri=redirect_uri,
            )
        except TypeError:  # injected clients may use the 3-arg signature
            token = await self.client.exchange_code(provider, code, client_settings)
        identity = await self.client.fetch_identity(
            provider, str(token), client_settings
        )
        subject = str((identity or {}).get("subject") or "").strip()
        login = str((identity or {}).get("login") or "").strip()
        email = str((identity or {}).get("email") or "").strip()
        if not subject:
            raise AppError(
                "第三方账号信息不完整", code="oauth_provider_error", status=502
            )

        mode = str(state_row["mode"] or "login")
        next_path = _safe_next_path(state_row["redirect"])

        if mode == "bind":
            return await self._finish_bind(
                provider,
                subject,
                state_row,
                current_user_id=current_user_id,
                email=email,
                login=login,
                ip=ip,
                next_path=next_path,
            )

        existing = self._identity_for(provider, subject)
        is_new = False
        if existing is not None:
            user = self.auth.get_user(str(existing["user_id"]))
            if user is None:
                raise AppError(
                    "该第三方账号绑定的用户不存在",
                    code="oauth_not_bound",
                    status=400,
                )
        else:
            invite = str(state_row["invite"] or "").strip()
            if not invite:
                raise AppError(
                    "该 GitHub 账号尚未绑定本站账号，请使用邀请码注册或先登录后绑定",
                    code="oauth_not_bound",
                    status=400,
                )
            # Fail fast on an invalid invite before creating anything.
            self.invites.verify(invite)
            user = self.auth.create_oauth_user(login=login, invite=invite, ip=ip)
            self._insert_identity(
                user["id"], provider, subject, email=email, login=login
            )
            is_new = True
        session = self.sessions.create(user, ip=ip, user_agent=user_agent)
        if not is_new:
            self._audit(
                "auth.login",
                user["id"],
                ip=ip,
                detail={"provider": provider},
            )
        return {
            "user": self.auth.public_user(user),
            "session": session,
            "is_new": is_new,
            "mode": mode,
            "next": next_path,
            "provider": provider,
        }

    async def _finish_bind(
        self,
        provider: str,
        subject: str,
        state_row: dict[str, Any],
        *,
        current_user_id: str,
        email: str,
        login: str,
        ip: str,
        next_path: str,
    ) -> dict[str, Any]:
        if not current_user_id:
            raise AppError("请先登录后再绑定", code="unauthorized", status=401)
        state_user = str(state_row["user_id"] or "")
        if state_user and state_user != str(current_user_id):
            raise AppError(
                "登录状态已变化，请重新发起绑定",
                code="oauth_state_invalid",
                status=400,
            )
        user = self.auth.get_user(str(current_user_id))
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        existing = self._identity_for(provider, subject)
        if existing is not None:
            if str(existing["user_id"]) != str(current_user_id):
                raise AppError(
                    "该第三方账号已绑定其他用户",
                    code="oauth_already_bound",
                    status=409,
                )
            return {
                "user": self.auth.public_user(user),
                "session": None,
                "is_new": False,
                "mode": "bind",
                "next": next_path,
                "provider": provider,
                "bound": True,
            }
        self._insert_identity(
            user["id"], provider, subject, email=email, login=login
        )
        self._audit(
            "user.oauth_bound",
            user["id"],
            ip=ip,
            detail={"provider": provider},
        )
        return {
            "user": self.auth.public_user(user),
            "session": None,
            "is_new": False,
            "mode": "bind",
            "next": next_path,
            "provider": provider,
            "bound": True,
        }

    def list_identities(self, user_id: str) -> list[dict[str, Any]]:
        return [
            self._identity_payload(row)
            for row in self._identities_for_user(str(user_id))
        ]

    def unbind(self, user_id: str, provider: str, *, ip: str = "") -> dict[str, Any]:
        provider = self._provider(provider)
        user = self.auth.get_user(str(user_id))
        if user is None:
            raise AppError("用户不存在", code="not_found", status=404)
        identity = self.db.query_one(
            "SELECT * FROM oauth_identities WHERE user_id = ? AND provider = ?",
            (str(user_id), provider),
        )
        if identity is None:
            return {"unbound": False, "provider": provider}
        has_email = bool(
            int(user.get("email_verified") or 0)
            and not is_placeholder_email(user.get("email"))
        )
        if not str(user.get("password_hash") or "") and not has_email:
            raise AppError(
                "这是当前账号唯一的登录方式，请先设置密码或绑定邮箱",
                code="last_login_method",
                status=400,
            )
        self.db.execute("DELETE FROM oauth_identities WHERE id = ?", (identity["id"],))
        self._audit(
            "user.oauth_unbound",
            user["id"],
            ip=ip,
            detail={"provider": provider},
        )
        return {"unbound": True, "provider": provider}


__all__ = [
    "GITHUB_AUTHORIZE_URL",
    "OAUTH_SECRET_MASK",
    "OAUTH_SETTINGS_KEY",
    "HttpOAuthClient",
    "OAUTH_STATE_TTL_SECONDS",
    "OAuthHttpClient",
    "OAuthService",
]
