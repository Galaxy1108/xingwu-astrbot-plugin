"""Time source indirection (tests use a frozen clock)."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> int: ...


class SystemClock:
    def now(self) -> int:
        return int(time.time())


class FrozenClock:
    """Deterministic clock for tests; advance with ``tick``/``set``."""

    def __init__(self, start: int = 1_700_000_000) -> None:
        self._now = int(start)

    def now(self) -> int:
        return self._now

    def tick(self, seconds: int) -> int:
        self._now += seconds
        return self._now

    def set(self, value: int) -> None:
        self._now = int(value)
