"""Encrypted platform-level settings (API keys for embedding/rerank/models)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .clock import Clock, SystemClock
from .crypto import CryptoError, KeyManager
from .db import Database


class SettingsStore:
    def __init__(self, db: Database, key_manager: KeyManager, clock: Clock | None = None):
        self.db = db
        self.key_manager = key_manager
        self.clock = clock or SystemClock()

    @staticmethod
    def aad(key: str) -> bytes:
        return f"setting:{key}:v1".encode()

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one(
            "SELECT value_cipher FROM platform_settings WHERE key = ?", (key,)
        )
        if row is None:
            return default
        try:
            raw = self.key_manager.unwrap(bytes(row["value_cipher"]), aad=self.aad(key))
            return json.loads(raw.decode("utf-8"))
        except (CryptoError, ValueError, TypeError):
            return default

    def set(self, key: str, value: Any, *, actor_id: str = "") -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        cipher = self.key_manager.wrap(raw, aad=self.aad(key))
        now = self.clock.now()
        self.db.execute(
            "INSERT INTO platform_settings(key, value_cipher, updated_at, updated_by) "
            "VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET value_cipher = excluded.value_cipher, "
            "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (key, sqlite3.Binary(cipher), now, actor_id),
        )

    def delete(self, key: str) -> None:
        self.db.execute("DELETE FROM platform_settings WHERE key = ?", (key,))

    def masked(self, key: str, default: Any = None) -> Any:
        value = self.get(key, default)
        if not isinstance(value, dict):
            return value
        result = dict(value)
        if result.get("api_key"):
            result["api_key"] = "••••••••"
            result["has_api_key"] = True
        else:
            result["has_api_key"] = False
        return result
