"""Runtime patch: transparent conversation encryption inside AstrBot.

Mirrors ``privacy_guard``'s proven approach: patch three ConversationManager
methods (two writes + the single read conversion) instead of every call site.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

FLAG = "_saas_conversation_patch"


def _platform_id(umo: str | None) -> str | None:
    if not isinstance(umo, str) or ":" not in umo:
        return None
    return umo.split(":", 1)[0] or None


class ConversationEncryptionPatch:
    def __init__(self, container) -> None:
        self.container = container
        self.service = container.conversations
        self.db = container.db
        self._manager_cls = None
        self._originals: dict[str, object] = {}

    # -- helpers -------------------------------------------------------
    def _bot_id(self, umo: str | None) -> str | None:
        platform_id = _platform_id(umo)
        if not platform_id or not platform_id.startswith("b_"):
            return None
        row = self.db.query_one("SELECT id FROM bots WHERE id = ?", (platform_id,))
        return str(row["id"]) if row else None

    def _should_encrypt(self, umo: str | None) -> bool:
        bot_id = self._bot_id(umo)
        if bot_id is None:
            return False
        return self.service.should_encrypt(bot_id)

    def _owner(self, bot_id: str) -> str | None:
        return self.service._bot_owner(bot_id)

    def _wrap(self, umo: str, history: list) -> list:
        bot_id = self._bot_id(umo)
        owner = self._owner(bot_id) if bot_id else None
        if bot_id is None or owner is None:
            return history
        return self.service.encrypt_content(
            bot_id=bot_id, owner=owner, cid=umo, history=history
        )

    def _unwrap(self, umo: str, content) -> list | None:
        bot_id = self._bot_id(umo)
        owner = self._owner(bot_id) if bot_id else None
        if bot_id is None or owner is None:
            return None
        plain, _error = self.service.decrypt_content(
            bot_id=bot_id, owner=owner, cid=umo, content=content
        )
        return plain

    # -- install / uninstall ------------------------------------------
    def install(self) -> bool:
        from astrbot.core.conversation_mgr import ConversationManager

        if getattr(ConversationManager, FLAG, False):
            logger.warning("SaaS: 对话加密补丁已存在，跳过重复安装")
            return False
        self._manager_cls = ConversationManager
        self._originals = {
            "update_conversation": ConversationManager.update_conversation,
            "new_conversation": ConversationManager.new_conversation,
            "_convert": ConversationManager._convert_conv_from_v2_to_v1,
        }
        patch = self

        async def update_conversation(
            mgr,
            unified_msg_origin,
            conversation_id=None,
            history=None,
            title=None,
            persona_id=None,
            token_usage=None,
        ):
            if history is not None and patch._should_encrypt(unified_msg_origin):
                history = patch._wrap(unified_msg_origin, history)
            return await patch._originals["update_conversation"](
                mgr,
                unified_msg_origin,
                conversation_id=conversation_id,
                history=history,
                title=title,
                persona_id=persona_id,
                token_usage=token_usage,
            )

        async def new_conversation(
            mgr,
            unified_msg_origin,
            platform_id=None,
            content=None,
            title=None,
            persona_id=None,
        ):
            if content is not None and patch._should_encrypt(unified_msg_origin):
                content = patch._wrap(unified_msg_origin, content)
            return await patch._originals["new_conversation"](
                mgr,
                unified_msg_origin,
                platform_id=platform_id,
                content=content,
                title=title,
                persona_id=persona_id,
            )

        def convert(mgr, conv_v2, include_history=True):
            res = patch._originals["_convert"](mgr, conv_v2, include_history)
            if not include_history or conv_v2 is None:
                return res
            umo = getattr(conv_v2, "user_id", None)
            if not umo:
                return res
            try:
                plain = patch._unwrap(umo, getattr(conv_v2, "content", None))
            except Exception:  # noqa: BLE001
                logger.error("SaaS: 对话解密失败 umo=%s", umo, exc_info=True)
                return res
            if plain is not None:
                res.history = json.dumps(plain, ensure_ascii=False)
            return res

        ConversationManager.update_conversation = update_conversation
        ConversationManager.new_conversation = new_conversation
        ConversationManager._convert_conv_from_v2_to_v1 = convert
        setattr(ConversationManager, FLAG, True)
        logger.info("SaaS: 已接管 ConversationManager 读写边界（对话加密）")
        return True

    def uninstall(self) -> None:
        if self._manager_cls is None or not self._originals:
            return
        self._manager_cls.update_conversation = self._originals["update_conversation"]
        self._manager_cls.new_conversation = self._originals["new_conversation"]
        self._manager_cls._convert_conv_from_v2_to_v1 = self._originals["_convert"]
        setattr(self._manager_cls, FLAG, False)
        self._originals = {}
        logger.info("SaaS: 已还原 ConversationManager")
