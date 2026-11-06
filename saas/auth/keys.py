"""Tenant key lifecycle: envelope-wrapped per-user keys (handoff §6.3)."""

from __future__ import annotations

import logging
import sqlite3

from ..clock import Clock, SystemClock
from ..crypto import CryptoError, KeyManager, TenantCipher
from ..db import Database

logger = logging.getLogger(__name__)


class TenantKeyService:
    def __init__(
        self, db: Database, key_manager: KeyManager, clock: Clock | None = None
    ) -> None:
        self.db = db
        self.key_manager = key_manager
        self.clock = clock or SystemClock()

    def ensure(self, tenant_id: str) -> TenantCipher:
        """Return the tenant cipher, creating a wrapped key on first use."""
        existing = self.db.query_one(
            "SELECT key_version, wrapped_key FROM tenant_keys WHERE tenant_id = ?",
            (tenant_id,),
        )
        if existing is not None:
            raw = self.key_manager.unwrap_tenant_key(
                tenant_id, existing["wrapped_key"], int(existing["key_version"])
            )
            return TenantCipher(raw, tenant_id)
        key = __import__("secrets").token_bytes(32)
        wrapped = self.key_manager.wrap_tenant_key(tenant_id, key, 1)
        now = self.clock.now()
        try:
            self.db.execute(
                "INSERT INTO tenant_keys(tenant_id, key_version, wrapped_key, "
                "created_at, rotated_at) VALUES (?,?,?,?,0)",
                (tenant_id, 1, sqlite3.Binary(wrapped), now),
            )
        except sqlite3.IntegrityError:
            # Concurrent creation: fall back to the stored key.
            return self.get(tenant_id)
        logger.info("已为用户 %s 创建租户密钥", tenant_id)
        return TenantCipher(key, tenant_id)

    def get(self, tenant_id: str) -> TenantCipher:
        row = self.db.query_one(
            "SELECT key_version, wrapped_key FROM tenant_keys WHERE tenant_id = ?",
            (tenant_id,),
        )
        if row is None:
            raise CryptoError(f"租户密钥不存在：{tenant_id}")
        raw = self.key_manager.unwrap_tenant_key(
            tenant_id, row["wrapped_key"], int(row["key_version"])
        )
        return TenantCipher(raw, tenant_id)

    def destroy(self, tenant_id: str) -> None:
        """Crypto-shredding: deleting the wrapped key makes data unrecoverable."""
        self.db.execute("DELETE FROM tenant_keys WHERE tenant_id = ?", (tenant_id,))

    def memory_key(self, tenant_id: str, bot_id: str) -> bytes:
        return self.get(tenant_id).subkey(bot_id, "memory")
