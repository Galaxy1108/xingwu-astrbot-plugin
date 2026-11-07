"""Real AstrBot integration (imports AstrBot lazily).

Everything here mirrors the proven order from ``astrbot_plugin_easy_setup`` but
wrapped in a service-level adapter with explicit rollback support.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from .ports import QrChallenge, QrPollResult

logger = logging.getLogger(__name__)

PLATFORM_TYPES = ("weixin_oc", "qq_official")

DEFAULT_WEIXIN_OC_BASE_URL = "https://ilinkai.weixin.qq.com"


def build_platform_config(platform: str, bot_id: str) -> dict[str, Any]:
    """Disabled-by-default platform config for a new Bot."""
    if platform == "weixin_oc":
        return {
            "id": bot_id,
            "type": "weixin_oc",
            "enable": False,
            "weixin_oc_base_url": DEFAULT_WEIXIN_OC_BASE_URL,
            "weixin_oc_bot_type": "3",
            "weixin_oc_qr_poll_interval": 1,
            "weixin_oc_long_poll_timeout_ms": 35_000,
            "weixin_oc_api_timeout_ms": 120_000,
            "weixin_oc_token": "",
        }
    if platform == "qq_official":
        return {
            "id": bot_id,
            "type": "qq_official",
            "enable": False,
            "appid": "",
            "secret": "",
            "enable_group_c2c": True,
            "enable_guild_direct_message": True,
            "qqofficial_api_timeout_ms": 30_000,
        }
    raise ValueError(f"不支持的平台类型：{platform}")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class AstrBotConversationBackend:
    """Conversation access through AstrBot's SQLModel database."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self.db = context.get_db()

    async def list(self, platform_id: str | None = None):
        from .conversations import ConversationRecord

        convs = await self.db.get_conversations(platform_id=platform_id)
        items = []
        for conv in convs:
            created = getattr(conv, "created_at", 0)
            updated = getattr(conv, "updated_at", 0)
            items.append(
                ConversationRecord(
                    cid=str(conv.conversation_id),
                    platform_id=str(conv.platform_id),
                    user_id=str(conv.user_id),
                    title=str(conv.title or ""),
                    content=conv.content,
                    token_usage=int(getattr(conv, "token_usage", 0) or 0),
                    created_at=int(created.timestamp()) if hasattr(created, "timestamp") else int(created or 0),
                    updated_at=int(updated.timestamp()) if hasattr(updated, "timestamp") else int(updated or 0),
                )
            )
        return items

    async def update_content(self, cid: str, content) -> None:
        await self.db.update_conversation(cid, content=content)


class AstrBotAdapter:
    """Implements :class:`saas.ports.AstrBotPort` against a live AstrBot context."""

    def __init__(self, context: Any) -> None:
        self.context = context

    # -- helpers -------------------------------------------------------
    @property
    def _config(self) -> Any:
        return self.context._config

    def _platforms(self) -> list[dict[str, Any]]:
        try:
            platforms = self._config.get("platform", [])
        except Exception:  # noqa: BLE001
            platforms = []
        return list(platforms or [])

    def _find_platform(self, bot_id: str) -> dict[str, Any] | None:
        for item in self._platforms():
            if str(item.get("id")) == bot_id:
                return item
        return None

    def _save_config(self) -> None:
        save = getattr(self._config, "save_config", None)
        if callable(save):
            save()

    # -- persona / config ---------------------------------------------
    async def create_persona(
        self,
        *,
        bot_id: str,
        bot_name: str,
        persona_name: str,
        system_prompt: str,
        begin_dialogs: list[str],
    ) -> None:
        await self.context.persona_manager.create_persona(
            persona_name,
            system_prompt or "You are a helpful and friendly assistant.",
            begin_dialogs=list(begin_dialogs or []),
        )

    async def delete_persona(self, persona_name: str) -> None:
        try:
            await self.context.persona_manager.delete_persona(persona_name)
        except ValueError:
            logger.warning("删除人格时未找到：%s", persona_name)

    async def list_conf_profiles(self) -> list[dict[str, Any]]:
        acm = self.context.astrbot_config_mgr
        profiles = []
        for item in acm.get_conf_list():
            profiles.append(
                {
                    "id": getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else ""),
                    "name": getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else ""),
                    "is_default": str(getattr(item, "id", "")) == "default",
                }
            )
        return profiles

    async def create_config(
        self,
        *,
        bot_id: str,
        conf_name: str,
        persona_name: str,
        config_patch: dict[str, Any],
        base_conf_id: str = "default",
    ) -> str:
        acm = self.context.astrbot_config_mgr
        base = acm.confs.get(base_conf_id)
        if base is None and base_conf_id != "default":
            # The profile was deleted after the template was saved.
            raise ValueError(f"配置文件不存在：{base_conf_id}")
        if base is None:
            base = acm.confs.get("default")
        if base is None:
            base = {}
        new_config = _deep_merge(dict(base), config_patch or {})
        provider_settings = new_config.setdefault("provider_settings", {})
        if not isinstance(provider_settings, dict):
            provider_settings = {}
            new_config["provider_settings"] = provider_settings
        provider_settings["default_personality"] = persona_name
        new_config.setdefault("admins_id", [])
        return await acm.create_conf(name=conf_name, config=new_config)

    async def update_config(self, conf_id: str, patch: dict[str, Any]) -> None:
        acm = self.context.astrbot_config_mgr
        conf = acm.confs.get(conf_id)
        if conf is None:
            raise ValueError(f"配置文件不存在：{conf_id}")
        for path, value in (patch or {}).items():
            parts = [part for part in str(path).split(".") if part]
            if not parts:
                continue
            target = conf
            for part in parts[:-1]:
                child = target.get(part)
                if not isinstance(child, dict):
                    child = {}
                    target[part] = child
                target = child
            target[parts[-1]] = value
        conf.save_config()

    async def delete_config(self, conf_id: str) -> None:
        try:
            await self.context.astrbot_config_mgr.delete_conf(conf_id)
        except ValueError:
            logger.warning("删除配置时未找到：%s", conf_id)

    async def bind_route(self, *, bot_id: str, conf_id: str) -> None:
        await self.context.astrbot_config_mgr.ucr.update_route(f"{bot_id}::", conf_id)

    async def unbind_route(self, bot_id: str) -> None:
        await self.context.astrbot_config_mgr.ucr.delete_route(f"{bot_id}::")

    # -- platforms -----------------------------------------------------
    async def create_platform(self, *, bot_id: str, platform: str) -> None:
        config = build_platform_config(platform, bot_id)
        self._config["platform"].append(config)
        self._save_config()
        # Disabled instances are registered but not started; start on enable.

    async def delete_platform(self, bot_id: str) -> None:
        platform = self._find_platform(bot_id)
        if platform is None:
            return
        try:
            await self.context.platform_manager.terminate_platform(bot_id)
        except Exception:  # noqa: BLE001
            logger.warning("终止平台实例失败：%s", bot_id, exc_info=True)
        try:
            self._config["platform"].remove(platform)
        except ValueError:
            pass
        self._save_config()

    async def set_platform_enabled(self, bot_id: str, enabled: bool) -> None:
        platform = self._find_platform(bot_id)
        if platform is None:
            raise ValueError(f"未找到平台实例 {bot_id}")
        platform["enable"] = bool(enabled)
        self._save_config()
        await self.context.platform_manager.reload(platform)

    async def finalize_temp_platform(self, *, temp_id: str, bot_id: str) -> None:
        """Copy provider-specific state from a temporary QR platform.

        The temporary platform was used only to obtain the QR/credentials; the
        real Bot platform was created bare by :meth:`BotService.create`. Copying
        non-structural keys preserves provider fields the login registration
        wrote (tokens/base URLs) before credentials are sealed and applied.
        """
        temp = self._find_platform(temp_id)
        target = self._find_platform(bot_id)
        if temp is None or target is None:
            raise ValueError(f"临时或目标平台不存在：{temp_id} -> {bot_id}")
        for key, value in temp.items():
            if key in {"id", "type", "enable"}:
                continue
            target[key] = value
        self._save_config()

    async def apply_credentials(
        self, *, bot_id: str, platform: str, credentials: dict[str, Any]
    ) -> None:
        platform_config = self._find_platform(bot_id)
        if platform_config is None:
            raise ValueError(f"未找到平台实例 {bot_id}")
        if platform == "weixin_oc":
            token = str(credentials.get("weixin_oc_token") or "").strip()
            if token:
                platform_config["weixin_oc_token"] = token
            for key in (
                "weixin_oc_account_id",
                "weixin_oc_base_url",
                "weixin_oc_user_id",
            ):
                value = str(credentials.get(key) or "").strip()
                if value:
                    platform_config[key] = value
        else:
            appid = str(credentials.get("appid") or "").strip()
            if appid:
                platform_config["appid"] = appid
                platform_config["secret"] = str(credentials.get("secret") or "").strip()
        self._save_config()

    # -- QR ------------------------------------------------------------
    def _login_registration(self, platform: str):
        if platform == "weixin_oc":
            from astrbot.core.platform.sources.weixin_oc.login_registration import (
                poll_weixin_oc_login_once,
                request_weixin_oc_login_qr,
            )

            return request_weixin_oc_login_qr, poll_weixin_oc_login_once
        from astrbot.core.platform.sources.qqofficial.login_registration import (
            poll_qqofficial_login_once,
            request_qqofficial_login_qr,
        )

        return request_qqofficial_login_qr, poll_qqofficial_login_once

    async def request_qr(self, *, bot_id: str, platform: str) -> QrChallenge:
        platform_config = self._find_platform(bot_id)
        if platform_config is None:
            raise ValueError(f"未找到平台实例 {bot_id}")
        request_qr, _ = self._login_registration(platform)
        registration = await request_qr(platform_config)
        if platform == "weixin_oc":
            payload = {
                "qrcode": registration.qrcode,
                "qrcode_img_content": registration.qrcode_img_content,
            }
            image = registration.qrcode_img_content or ""
            content = registration.qrcode
        else:
            payload = {
                "task_id": registration.task_id,
                "bind_key": registration.bind_key,
                "qrcode": registration.qrcode,
            }
            image = ""
            content = registration.qrcode
        return QrChallenge(
            content=content,
            payload=payload,
            interval=int(registration.interval or 2),
            image=image,
        )

    async def poll_qr(
        self, *, bot_id: str, platform: str, payload: dict[str, Any]
    ) -> QrPollResult:
        platform_config = self._find_platform(bot_id)
        if platform_config is None:
            return QrPollResult(status="error", message="平台实例不存在")
        _, poll_once = self._login_registration(platform)
        if platform == "weixin_oc":
            result = await poll_once(
                platform_config=platform_config,
                qrcode=str(payload.get("qrcode") or ""),
            )
        else:
            result = await poll_once(
                platform_config=platform_config,
                task_id=str(payload.get("task_id") or ""),
                bind_key=str(payload.get("bind_key") or ""),
            )
        status = str(result.get("status") or "pending")
        credentials = {
            key: value
            for key, value in result.items()
            if key not in {"status", "qr_status", "message"}
        }
        return QrPollResult(
            status=status,
            credentials=credentials,
            message=str(result.get("message") or ""),
        )
