"""Per-bot memory stores: SQLCipher (production) and in-memory (tests)."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable

from .storage.sqlcipher import MemoryStorage, MemoryStorageError
from .storage.repository import SqlCipherRepository

logger = logging.getLogger(__name__)


class SqlCipherMemoryStore:
    """LRU cache of per-bot connections (handoff §4.5.9, max 64 open libraries)."""

    def __init__(
        self,
        storage: MemoryStorage,
        key_provider: Callable[[str], bytes],
        *,
        max_open: int = 64,
    ) -> None:
        self.storage = storage
        self._key_provider = key_provider
        self.max_open = max_open
        self._repos: "OrderedDict[str, SqlCipherRepository]" = OrderedDict()

    def open(self, bot_id: str) -> SqlCipherRepository:
        cached = self._repos.get(bot_id)
        if cached is not None:
            self._repos.move_to_end(bot_id)
            return cached
        key = self._key_provider(bot_id)
        conn = self.storage.open_library(bot_id, key=key)
        repo = SqlCipherRepository(conn)
        self._repos[bot_id] = repo
        self._repos.move_to_end(bot_id)
        while len(self._repos) > self.max_open:
            old_bot, old_repo = self._repos.popitem(last=False)
            try:
                old_repo.conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("关闭记忆库连接失败：%s", old_bot, exc_info=True)
        return repo

    def close(self, bot_id: str) -> None:
        repo = self._repos.pop(bot_id, None)
        if repo is None:
            return
        try:
            repo.conn.close()
        except Exception:  # noqa: BLE001
            logger.warning("关闭记忆库连接失败：%s", bot_id, exc_info=True)

    def close_all(self) -> None:
        for bot_id in list(self._repos):
            self.close(bot_id)

    def exists(self, bot_id: str) -> bool:
        return self.storage.exists(bot_id)


class InMemoryStore:
    """Test double with the same store surface."""

    def __init__(self) -> None:
        from .storage.in_memory import InMemoryRepository

        self.repos: dict[str, InMemoryRepository] = {}

    def open(self, bot_id: str):
        from .storage.in_memory import InMemoryRepository

        repo = self.repos.get(bot_id)
        if repo is None:
            repo = InMemoryRepository()
            self.repos[bot_id] = repo
        return repo

    def close(self, bot_id: str) -> None:
        self.repos.pop(bot_id, None)

    def close_all(self) -> None:
        self.repos.clear()

    def exists(self, bot_id: str) -> bool:
        return bot_id in self.repos


__all__ = ["SqlCipherMemoryStore", "InMemoryStore", "MemoryStorageError"]
