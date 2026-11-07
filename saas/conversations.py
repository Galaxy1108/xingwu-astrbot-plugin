"""Conversation encryption + backfill (ENV1 envelope in ``[{"role","content"}]``).

The runtime patch (see ``conversation_patch.py``) keeps new messages encrypted;
this service provides the same conversion for backfill / encryption switch and
the admin content view.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from .clock import Clock, SystemClock
from .crypto import CryptoError, TenantCipher
from .db import Database

logger = logging.getLogger(__name__)

ENVELOPE_PREFIX = "ENC1."
DECRYPT_FAILED_TEXT = "【该条对话无法解密：密钥缺失或数据损坏】"


@dataclass
class ConversationRecord:
    cid: str
    platform_id: str
    user_id: str
    title: str = ""
    content: list[dict[str, Any]] | None = None
    token_usage: int = 0
    created_at: int = 0
    updated_at: int = 0


@dataclass
class FakeConversationBackend:
    """In-memory backend for dev server / tests."""

    records: dict[str, ConversationRecord] = field(default_factory=dict)

    async def list(self, platform_id: str | None = None) -> list[ConversationRecord]:
        items = list(self.records.values())
        if platform_id:
            items = [item for item in items if item.platform_id == platform_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def update_content(self, cid: str, content: list | None) -> None:
        record = self.records.get(cid)
        if record is not None:
            record.content = content

    def add(
        self,
        *,
        platform_id: str,
        user_id: str,
        history: list[dict[str, Any]],
        title: str = "",
        cid: str | None = None,
    ) -> ConversationRecord:
        import uuid

        conversation_id = cid or str(uuid.uuid4())
        record = ConversationRecord(
            cid=conversation_id,
            platform_id=platform_id,
            user_id=user_id,
            title=title,
            content=history,
            created_at=int(__import__("time").time()),
            updated_at=int(__import__("time").time()),
        )
        self.records[conversation_id] = record
        return record


def is_envelope(content: Any) -> bool:
    return (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and isinstance(content[0].get("content"), str)
        and content[0]["content"].startswith(ENVELOPE_PREFIX)
    )


class ConversationService:
    """Encrypt/decrypt conversation content with the per-bot content key."""

    def __init__(
        self,
        backend,
        *,
        db: Database,
        tenants,
        clock: Clock | None = None,
    ) -> None:
        self.backend = backend
        self.db = db
        self.tenants = tenants
        self.clock = clock or SystemClock()

    # -- tenant helpers ------------------------------------------------
    def _bot_owner(self, bot_id: str) -> str | None:
        row = self.db.query_one("SELECT user_id FROM bots WHERE id = ?", (bot_id,))
        return str(row["user_id"]) if row else None

    def _cipher(self, bot_id: str, owner: str) -> TenantCipher:
        return self.tenants.get(owner)

    def should_encrypt(self, bot_id: str) -> bool:
        owner = self._bot_owner(bot_id)
        if owner is None:
            return False
        row = self.db.query_one(
            "SELECT encryption_enabled, encryption_state FROM users WHERE id = ?",
            (owner,),
        )
        if row is None:
            return False
        return bool(row["encryption_enabled"]) and row["encryption_state"] != "plaintext"

    # -- conversion ----------------------------------------------------
    def encrypt_content(
        self, *, bot_id: str, owner: str, cid: str, history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cipher = self._cipher(bot_id, owner)
        token = cipher.encrypt_text(
            json.dumps(history, ensure_ascii=False),
            bot_id=bot_id,
            purpose="content",
            record_id=bot_id,
        )
        return [{"role": "user", "content": token}]

    def decrypt_content(
        self, *, bot_id: str, owner: str, cid: str, content: Any
    ) -> tuple[list[dict[str, Any]] | None, bool]:
        """Return (plaintext, decrypt_error). Never raises to callers."""
        if not is_envelope(content):
            return content if isinstance(content, list) else None, False
        token = content[0]["content"]
        try:
            cipher = self._cipher(bot_id, owner)
            plain = json.loads(
                cipher.decrypt_text(
                    token, bot_id=bot_id, purpose="content", record_id=bot_id
                )
            )
            return plain if isinstance(plain, list) else None, False
        except (CryptoError, ValueError, TypeError):
            logger.error("对话解密失败：bot=%s cid=%s", bot_id, cid, exc_info=True)
            return [{"role": "system", "content": DECRYPT_FAILED_TEXT}], True

    # -- reads ---------------------------------------------------------
    async def list_for_bot(self, bot_id: str, *, decrypt: bool = True) -> list[dict[str, Any]]:
        owner = self._bot_owner(bot_id)
        if owner is None:
            return []
        records = await self.backend.list(bot_id)
        items = []
        for record in records:
            content = record.content
            error = False
            if decrypt:
                content, error = self.decrypt_content(
                    bot_id=bot_id, owner=owner, cid=record.cid, content=content
                )
            items.append(
                {
                    "id": record.cid,
                    "platform_id": record.platform_id,
                    "user_id": record.user_id,
                    "title": record.title,
                    "history": content,
                    "encrypted": is_envelope(record.content),
                    "decrypt_error": error,
                    "token_usage": record.token_usage,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
            )
        return items

    async def add_conversation(
        self,
        *,
        bot_id: str,
        history: list[dict[str, Any]],
        title: str = "",
    ) -> str:
        owner = self._bot_owner(bot_id)
        if owner is None:
            raise ValueError(f"Bot 不存在：{bot_id}")
        record = self.backend.add(platform_id=bot_id, user_id=bot_id, history=history, title=title) if hasattr(self.backend, "add") else None
        if record is None:
            raise ValueError("当前后端不支持新建对话")
        if self.should_encrypt(bot_id):
            await self.backend.update_content(
                record.cid,
                self.encrypt_content(
                    bot_id=bot_id, owner=owner, cid=record.cid, history=history
                ),
            )
        return record.cid

    # -- backfill ------------------------------------------------------
    async def backfill_bot(self, bot_id: str, *, decrypt: bool) -> dict[str, int]:
        owner = self._bot_owner(bot_id)
        if owner is None:
            return {"total": 0, "converted": 0, "failed": 0}
        records = await self.backend.list(bot_id)
        converted = failed = 0
        for record in records:
            try:
                if decrypt:
                    if not is_envelope(record.content):
                        continue
                    plain, error = self.decrypt_content(
                        bot_id=bot_id,
                        owner=owner,
                        cid=record.cid,
                        content=record.content,
                    )
                    if error:
                        failed += 1
                        continue
                    await self.backend.update_content(record.cid, plain)
                else:
                    if is_envelope(record.content):
                        continue
                    plain, _ = self.decrypt_content(
                        bot_id=bot_id,
                        owner=owner,
                        cid=record.cid,
                        content=record.content,
                    )
                    if plain is None:
                        continue
                    await self.backend.update_content(
                        record.cid,
                        self.encrypt_content(
                            bot_id=bot_id, owner=owner, cid=record.cid, history=plain
                        ),
                    )
                converted += 1
            except Exception:  # noqa: BLE001
                failed += 1
                logger.warning("对话回填失败：%s/%s", bot_id, record.cid, exc_info=True)
        return {"total": len(records), "converted": converted, "failed": failed}
