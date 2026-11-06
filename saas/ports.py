"""Ports between SaaS business logic and the AstrBot framework.

Business code (bots / qr / templates) depends only on these protocols, so the
whole backend can run against :class:`saas.fake_astrbot.FakeAstrBot` in tests
and against :class:`saas.astrbot_adapter.AstrBotAdapter` inside AstrBot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class QrChallenge:
    """Provider result for ``request_qr``."""

    content: str
    payload: dict[str, Any] = field(default_factory=dict)
    interval: int = 2
    image: str = ""  # optional data URL / image content from the provider


@dataclass
class QrPollResult:
    """Provider result for ``poll_qr`` (status names normalised by the service)."""

    status: str  # pending | scanned | created | expired | denied | error
    credentials: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class AstrBotPort(Protocol):
    """Side effects that must run inside the AstrBot process."""

    async def create_persona(
        self,
        *,
        bot_id: str,
        bot_name: str,
        persona_name: str,
        system_prompt: str,
        begin_dialogs: list[str],
    ) -> None: ...

    async def delete_persona(self, persona_name: str) -> None: ...

    async def create_config(
        self,
        *,
        bot_id: str,
        conf_name: str,
        persona_name: str,
        config_patch: dict[str, Any],
    ) -> str:
        """Create a config profile and return its ``conf_id``."""
        ...

    async def delete_config(self, conf_id: str) -> None: ...

    async def bind_route(self, *, bot_id: str, conf_id: str) -> None: ...

    async def unbind_route(self, bot_id: str) -> None: ...

    async def create_platform(self, *, bot_id: str, platform: str) -> None:
        """Register a disabled platform instance."""
        ...

    async def delete_platform(self, bot_id: str) -> None: ...

    async def set_platform_enabled(self, bot_id: str, enabled: bool) -> None: ...

    async def apply_credentials(
        self, *, bot_id: str, platform: str, credentials: dict[str, Any]
    ) -> None:
        """Write QR credentials into the platform config (before enabling)."""
        ...

    async def request_qr(self, *, bot_id: str, platform: str) -> QrChallenge: ...

    async def poll_qr(
        self, *, bot_id: str, platform: str, payload: dict[str, Any]
    ) -> QrPollResult: ...


class MemoryBackend(Protocol):
    """Storage side of the per-bot memory library (M0/M2)."""

    def create_library(self, bot_id: str, *, tenant_id: str) -> str: ...

    def delete_library(self, bot_id: str) -> None: ...

    def exists(self, bot_id: str) -> bool: ...
