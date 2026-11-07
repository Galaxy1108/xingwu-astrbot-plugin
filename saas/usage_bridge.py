"""Bridge AstrBot LLM token usage into the SaaS metering ledger.

The bridge is deliberately framework-free: ``main.py`` extracts ``TokenUsage``
from ``LLMResponse`` and calls :meth:`UsageBridge.record` with plain numbers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class UsageBridge:
    def __init__(self, container: Any) -> None:
        self.container = container

    def _bot(self, bot_id: str) -> Any:
        return self.container.db.query_one(
            "SELECT id, user_id, template_id, status, snapshot FROM bots WHERE id = ?",
            (bot_id,),
        )

    def _profile_for(self, bot: Any, model_name: str) -> Any:
        """Resolve the pricing profile: template binding first, then model name."""
        profile_id = ""
        template = self.container.db.query_one(
            "SELECT model_profile_id FROM templates WHERE id = ?",
            (bot["template_id"],),
        )
        if template is not None:
            profile_id = str(template["model_profile_id"] or "")
        if not profile_id:
            try:
                snapshot = json.loads(bot["snapshot"] or "{}")
            except (TypeError, ValueError):
                snapshot = {}
            profile_id = str(snapshot.get("model_profile_id") or "")
        if profile_id:
            row = self.container.db.query_one(
                "SELECT * FROM model_profiles WHERE id = ? AND enabled = 1",
                (profile_id,),
            )
            if row is not None:
                return row
        if model_name:
            return self.container.db.query_one(
                "SELECT * FROM model_profiles WHERE enabled = 1 AND (model = ? OR name = ?) "
                "ORDER BY updated_at DESC LIMIT 1",
                (model_name, model_name),
            )
        return None

    def record(
        self,
        bot_id: str,
        tokens_in: int,
        tokens_out: int,
        *,
        model_name: str = "",
        ref: str = "",
        idem_key: str | None = None,
    ) -> dict[str, Any]:
        bot = self._bot(bot_id)
        if bot is None or bot["status"] == "deleted":
            return {"recorded": False, "reason": "bot_not_found"}
        profile = self._profile_for(bot, model_name)
        if profile is None:
            logger.info(
                "SaaS 用量：Bot %s 使用模型 %s，但未找到匹配的模型定价，跳过计费",
                bot_id,
                model_name or "(unknown)",
            )
            return {"recorded": False, "reason": "no_pricing_profile"}
        try:
            result = self.container.metering.record_usage(
                user_id=bot["user_id"],
                bot_id=bot_id,
                model_id=profile["id"],
                tokens_in=max(0, int(tokens_in or 0)),
                tokens_out=max(0, int(tokens_out or 0)),
                ref=ref,
                idem_key=idem_key,
            )
        except Exception:  # noqa: BLE001
            logger.warning("SaaS 用量记账失败（Bot %s）", bot_id, exc_info=True)
            return {"recorded": False, "reason": "metering_error"}
        return {"recorded": True, **result}
