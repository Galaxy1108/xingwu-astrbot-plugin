"""Multi-tenant routing helpers (fail-closed UMO → bot_id parsing)."""

from __future__ import annotations

BOT_ID_PREFIX = "b_"


def parse_bot_id_from_umo(umo: str | None) -> str | None:
    """Extract ``b_<uuid>`` from the AstrBot UMO ``"{platform_id}:{type}:{session}"``.

    Returns ``None`` when the prefix is missing/unknown, so callers can refuse
    to handle the message instead of falling back to a public tenant.
    """
    if not isinstance(umo, str) or not umo:
        return None
    platform_id = umo.split(":", 1)[0].strip()
    if not platform_id.startswith(BOT_ID_PREFIX):
        return None
    if len(platform_id) <= len(BOT_ID_PREFIX):
        return None
    return platform_id


def route_prefix(bot_id: str) -> str:
    """UMO route pattern registered for a tenant Bot (matches all messages)."""
    return f"{bot_id}::"
