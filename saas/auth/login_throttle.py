"""Failure counting for password login (brute-force protection).

Counters live in the ``login_attempts`` table. Each key is either
``id:<normalized identifier>`` or ``ip:<client ip>``. A key's window opens at
its first failure and lasts ``login_window_seconds``; once the window has
expired the counter restarts on the next failure. A key is locked while
``failures >= limit`` and the window is still open.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..clock import Clock
from ..config import Settings
from ..db import Database
from ..errors import RateLimited

ERROR_CODE = "too_many_attempts"


@dataclass(frozen=True)
class _Lock:
    key: str
    retry_after: int


def identifier_key(identifier: str) -> str:
    return "id:" + str(identifier or "").strip().lower()


def ip_key(ip: str) -> str:
    return "ip:" + (str(ip or "").strip() or "unknown")


class LoginThrottle:
    def __init__(self, db: Database, *, settings: Settings, clock: Clock) -> None:
        self.db = db
        self.settings = settings
        self.clock = clock

    def _row(self, key: str) -> dict | None:
        return self.db.query_one(
            "SELECT failures, window_start FROM login_attempts WHERE key = ?", (key,)
        )

    def _limit_for(self, key: str) -> int:
        if key.startswith("ip:"):
            return int(self.settings.login_ip_max_failures)
        return int(self.settings.login_max_failures)

    def _open_failures(self, key: str, now: int) -> tuple[int, int]:
        """Return (failures, window_start) of the currently open window."""
        row = self._row(key)
        if row is None:
            return 0, now
        window_start = int(row["window_start"])
        if now - window_start >= int(self.settings.login_window_seconds):
            return 0, now
        return int(row["failures"]), window_start

    def check(self, keys: list[str]) -> None:
        """Raise :class:`RateLimited` (429) if any key is currently locked."""
        now = int(self.clock.now())
        window = int(self.settings.login_window_seconds)
        worst: _Lock | None = None
        for key in keys:
            failures, window_start = self._open_failures(key, now)
            if failures >= self._limit_for(key):
                retry_after = max(1, window_start + window - now)
                if worst is None or retry_after > worst.retry_after:
                    worst = _Lock(key, retry_after)
        if worst is not None:
            raise RateLimited(
                "登录失败次数过多，请稍后再试",
                retry_after=worst.retry_after,
                code=ERROR_CODE,
                status=429,
            )

    def record_failure(self, keys: list[str]) -> None:
        now = int(self.clock.now())
        with self.db.transaction():
            for key in keys:
                failures, window_start = self._open_failures(key, now)
                self.db.execute(
                    "INSERT INTO login_attempts(key, failures, window_start) "
                    "VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                    "failures = excluded.failures, window_start = excluded.window_start",
                    (key, failures + 1, window_start),
                )

    def clear(self, keys: list[str]) -> None:
        for key in keys:
            self.db.execute("DELETE FROM login_attempts WHERE key = ?", (key,))
