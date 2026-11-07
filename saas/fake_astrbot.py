"""In-memory AstrBot fake: deterministic tests + standalone demo server.

It records every side effect so tests can assert that a failed bot creation
rolled back *all* framework mutations (persona/config/route/platform).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any

from .ports import QrChallenge, QrPollResult


class FakeQrError(RuntimeError):
    pass


@dataclass
class FakeState:
    personas: dict[str, dict[str, Any]] = field(default_factory=dict)
    configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    routes: dict[str, str] = field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    conf_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "personas": set(self.personas),
            "configs": set(self.configs),
            "routes": dict(self.routes),
            "platforms": set(self.platforms),
        }


class FakeAstrBot:
    """Test double implementing :class:`saas.ports.AstrBotPort`."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.state = FakeState()
        self.state.conf_profiles = {
            "default": {"id": "default", "name": "默认配置", "is_default": True},
            "conf_companion": {
                "id": "conf_companion",
                "name": "陪伴型配置（示例）",
                "is_default": False,
            },
            "conf_work": {
                "id": "conf_work",
                "name": "工作型配置（示例）",
                "is_default": False,
            },
        }
        self.fail_on = set(fail_on or ())
        # platform -> qr session state
        self._qr: dict[str, dict[str, Any]] = {}
        # keep credentials handed over by "scan" simulation
        self._credentials: dict[str, dict[str, Any]] = {}
        self._scanned: set[str] = set()
        self.credentials: dict[str, dict[str, Any]] = {}

    # -- helpers -------------------------------------------------------
    def _maybe_fail(self, step: str) -> None:
        self.state.calls.append(step)
        if step in self.fail_on:
            raise RuntimeError(f"fake failure at step: {step}")

    def simulate_scan(self, bot_id: str) -> None:
        self._scanned.add(bot_id)

    def simulate_scan_complete(
        self, bot_id: str, credentials: dict[str, Any] | None = None
    ) -> None:
        self._scanned.add(bot_id)
        self._credentials[bot_id] = credentials or {
            "weixin_oc_token": f"tok_{secrets.token_hex(8)}",
            "weixin_oc_account_id": f"acct_{secrets.token_hex(4)}",
        }

    def simulate_denied(self, bot_id: str) -> None:
        self._qr.setdefault(bot_id, {})["denied"] = True

    # -- personas ------------------------------------------------------
    async def create_persona(
        self,
        *,
        bot_id: str,
        bot_name: str,
        persona_name: str,
        system_prompt: str,
        begin_dialogs: list[str],
    ) -> None:
        self._maybe_fail("create_persona")
        if persona_name in self.state.personas:
            raise ValueError(f"Persona with ID {persona_name} already exists.")
        self.state.personas[persona_name] = {
            "bot_id": bot_id,
            "system_prompt": system_prompt,
            "begin_dialogs": list(begin_dialogs),
        }

    async def delete_persona(self, persona_name: str) -> None:
        self._maybe_fail("delete_persona")
        self.state.personas.pop(persona_name, None)

    # -- configs -------------------------------------------------------
    async def list_conf_profiles(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.state.conf_profiles.values()]

    async def create_config(
        self,
        *,
        bot_id: str,
        conf_name: str,
        persona_name: str,
        config_patch: dict[str, Any],
        base_conf_id: str = "default",
    ) -> str:
        self._maybe_fail("create_config")
        if base_conf_id not in self.state.conf_profiles:
            raise ValueError(f"配置文件不存在：{base_conf_id}")
        conf_id = f"conf_{secrets.token_hex(8)}"
        self.state.configs[conf_id] = {
            "bot_id": bot_id,
            "name": conf_name,
            "persona_name": persona_name,
            "base_conf_id": base_conf_id,
            "config_patch": dict(config_patch),
        }
        return conf_id

    async def update_config(self, conf_id: str, patch: dict[str, Any]) -> None:
        self.state.configs.setdefault(conf_id, {}).update(patch or {})

    async def delete_config(self, conf_id: str) -> None:
        self._maybe_fail("delete_config")
        self.state.configs.pop(conf_id, None)

    async def bind_route(self, *, bot_id: str, conf_id: str) -> None:
        self._maybe_fail("bind_route")
        self.state.routes[f"{bot_id}::"] = conf_id

    async def unbind_route(self, bot_id: str) -> None:
        self._maybe_fail("unbind_route")
        self.state.routes.pop(f"{bot_id}::", None)

    # -- platforms -----------------------------------------------------
    async def create_platform(self, *, bot_id: str, platform: str) -> None:
        self._maybe_fail("create_platform")
        self.state.platforms[bot_id] = {
            "id": bot_id,
            "type": platform,
            "enable": False,
        }

    async def delete_platform(self, bot_id: str) -> None:
        self._maybe_fail("delete_platform")
        self.state.platforms.pop(bot_id, None)

    async def finalize_temp_platform(self, *, temp_id: str, bot_id: str) -> None:
        self._maybe_fail("finalize_temp_platform")
        temp = self.state.platforms.get(temp_id)
        target = self.state.platforms.get(bot_id)
        if temp is None or target is None:
            raise ValueError(f"临时或目标平台不存在：{temp_id} -> {bot_id}")
        for key, value in temp.items():
            if key in {"id", "type", "enable"}:
                continue
            target[key] = value

    async def apply_credentials(
        self, *, bot_id: str, platform: str, credentials: dict[str, Any]
    ) -> None:
        self._maybe_fail("apply_credentials")
        self.credentials[bot_id] = dict(credentials)
        platform_config = self.state.platforms.get(bot_id)
        if platform_config is not None:
            platform_config.update(
                {key: value for key, value in credentials.items() if isinstance(key, str)}
            )

    async def set_platform_enabled(self, bot_id: str, enabled: bool) -> None:
        self._maybe_fail("set_platform_enabled")
        platform = self.state.platforms.get(bot_id)
        if platform is None:
            raise ValueError(f"未找到平台实例 {bot_id}")
        platform["enable"] = bool(enabled)

    # -- QR ------------------------------------------------------------
    async def request_qr(self, *, bot_id: str, platform: str) -> QrChallenge:
        self._maybe_fail("request_qr")
        token = secrets.token_urlsafe(12)
        self._qr[bot_id] = {"platform": platform, "token": token, "denied": False}
        return QrChallenge(
            content=f"https://fake-{platform}.example/qr/{bot_id}/{token}",
            payload={"token": token, "platform": platform},
            interval=2,
        )

    async def poll_qr(
        self, *, bot_id: str, platform: str, payload: dict[str, Any]
    ) -> QrPollResult:
        self._maybe_fail("poll_qr")
        session = self._qr.get(bot_id)
        if session is None:
            return QrPollResult(status="expired", message="扫码会话不存在")
        if session.get("denied"):
            return QrPollResult(status="denied", message="用户取消登录")
        credentials = self._credentials.get(bot_id)
        if credentials:
            return QrPollResult(status="created", credentials=dict(credentials))
        if bot_id in self._scanned:
            return QrPollResult(status="scanned")
        return QrPollResult(status="pending")
