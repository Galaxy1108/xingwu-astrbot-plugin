"""AstrBot plugin entry: multi-tenant Bot hosting with a built-in console.

The plugin owns its own aiohttp sub-application (JSON API + static Vue console)
and delegates all framework mutations (persona/config/route/platform/QR) to
:class:`saas.astrbot_adapter.AstrBotAdapter`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.star.star_tools import StarTools

from .saas.astrbot_adapter import AstrBotAdapter, AstrBotConversationBackend
from .saas.config import Settings
from .saas.container import Container
from .saas.conversation_patch import ConversationEncryptionPatch
from .saas.conversations_tools import (
    TOOL_DEFINITIONS as CHAT_TOOL_DEFINITIONS,
    dispatch as dispatch_chat_tool,
)
from .saas.memory.models import MemoryDraft
from .saas.memory.auto_extract import extract_memories
from .saas.memory.tools.llm_tools import TOOL_DEFINITIONS, dispatch as dispatch_memory_tool
from .saas.tenancy import parse_bot_id_from_umo
from .saas.web.app import create_app

PLUGIN_NAME = "astrbot_plugin_saas"

logging.getLogger("saas").setLevel(logging.INFO)


class SaaSBotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config: AstrBotConfig = config if config is not None else {}
        self._data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.settings = Settings.from_astrbot_config(self._data_dir, self.config)
        self.container: Container | None = None
        self.conversation_patch: ConversationEncryptionPatch | None = None
        self._runner = None
        self._server_task: asyncio.Task | None = None
        self._gc_task: asyncio.Task | None = None
        try:
            self.container = Container(
                self.settings,
                port=AstrBotAdapter(context),
                conversation_backend=AstrBotConversationBackend(context),
            )
            self.conversation_patch = ConversationEncryptionPatch(self.container)
            self.conversation_patch.install()
        except Exception:
            logger.error("SaaS 核心初始化失败（控制台不会启动）", exc_info=True)
            return
        self._register_memory_tools()
        self._register_chat_tools()
        self._server_task = asyncio.create_task(self._serve())
        self._gc_task = asyncio.create_task(self._gc_loop())
        logger.info(
            "astrbot_plugin_saas: 控制台将在 %s:%s/console/ 提供",
            self.settings.host,
            self.settings.port,
        )

    # -- LLM memory tools (M2) -----------------------------------------
    def _register_memory_tools(self) -> None:
        """Expose memory_remember/recall/forget to the agent (fail-closed by UMO)."""
        self._register_tool_specs(TOOL_DEFINITIONS, self._tool_handler, "记忆")

    def _register_chat_tools(self) -> None:
        """Expose chat_history_search (tenant-scoped by the UMO prefix)."""
        self._register_tool_specs(
            CHAT_TOOL_DEFINITIONS, self._chat_tool_handler, "对话检索"
        )

    def _register_tool_specs(self, definitions, handler_factory, label: str) -> None:
        if self.container is None:
            return
        for spec in definitions:
            properties = (spec.get("parameters") or {}).get("properties") or {}
            func_args = [
                {
                    "type": item.get("type", "string"),
                    "name": name,
                    "description": item.get("description", ""),
                }
                for name, item in properties.items()
                if item.get("type") != "array"
            ]
            try:
                self.context.register_llm_tool(
                    spec["name"],
                    func_args,
                    spec["description"],
                    handler_factory(spec["name"]),
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_saas: 注册 LLM %s工具 %s 失败",
                    label,
                    spec["name"],
                    exc_info=True,
                )

    def _tool_handler(self, name: str):
        async def handler(event=None, context=None, **kwargs):
            return await self._run_memory_tool(name, kwargs, event)

        handler.__name__ = name
        return handler

    def _chat_tool_handler(self, name: str):
        async def handler(event=None, context=None, **kwargs):
            return await self._run_chat_tool(name, kwargs, event)

        handler.__name__ = name
        return handler

    @filter.on_llm_request()
    async def _inject_memories(self, event, request) -> None:
        """Recall relevant + always-inject memories into the system prompt."""
        if self.container is None:
            return
        bot_id = self._bot_id_for_event(event)
        if bot_id is None:
            return
        try:
            behavior = self.container.memory_service._load_retrieval_settings().behavior
            if not behavior.auto_inject:
                return
            query = str(getattr(event, "message_str", "") or "")
            memories = await self.container.memory_service.recall(bot_id, query)
            text = self.container.memory_service.format_for_prompt(memories)
            if not text:
                return
            existing = str(getattr(request, "system_prompt", "") or "")
            if "[记忆]" in existing:
                return
            request.system_prompt = existing + "\n\n" + text
        except Exception:  # noqa: BLE001
            logger.warning("SaaS 记忆注入失败（Bot %s）", bot_id, exc_info=True)

    @filter.on_llm_response()
    async def _record_llm_usage(self, event, response) -> None:
        """Record real token usage reported by the provider (never blocks replies)."""
        if self.container is None:
            return
        bot_id = self._bot_id_for_event(event)
        if bot_id is None:
            return
        # Count incoming/answered messages for the dashboard trend.
        try:
            row = self.container.db.query_one(
                "SELECT user_id, platform FROM bots WHERE id = ?", (bot_id,)
            )
            if row is not None:
                self.container.message_stats.increment(
                    user_id=row["user_id"],
                    bot_id=bot_id,
                    platform=row["platform"] or "",
                )
        except Exception:  # noqa: BLE001
            logger.debug("SaaS 消息统计失败", exc_info=True)
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        model_name = ""
        try:
            provider = await self.context.get_using_provider_async(
                umo=event.unified_msg_origin
            )
            if provider is not None:
                model_name = str(provider.meta().model or "")
        except Exception:  # noqa: BLE001
            logger.debug("SaaS 用量：无法读取当前模型名", exc_info=True)
        response_id = str(getattr(response, "id", "") or "")
        try:
            tokens_in = int(getattr(usage, "input", 0) or 0)
            tokens_out = int(getattr(usage, "output", 0) or 0)
        except (TypeError, ValueError):
            return
        self.container.usage_bridge.record(
            bot_id,
            tokens_in,
            tokens_out,
            model_name=model_name,
            ref=f"llm:{response_id}" if response_id else "",
            idem_key=f"llm:{response_id}" if response_id else None,
        )
        # Automatic memory extraction (rule-based, conservative, best effort).
        try:
            behavior = self.container.memory_service._load_retrieval_settings().behavior
            if not behavior.auto_extract:
                return
            assistant_text = str(getattr(response, "completion_text", "") or "")
            user_text = str(getattr(event, "message_str", "") or "")
            for draft in extract_memories(user_text, assistant_text):
                self.container.memory_service.remember(
                    bot_id,
                    MemoryDraft(
                        content=draft["content"],
                        kind=draft["kind"],
                        memory_type=draft["kind"],
                        importance=draft["importance"],
                        tags=list(draft.get("tags") or []),
                        metadata=dict(draft.get("metadata") or {}),
                    ),
                )
        except Exception:  # noqa: BLE001
            logger.warning("SaaS 自动记忆提取失败（Bot %s）", bot_id, exc_info=True)

    def _bot_id_for_event(self, event) -> str | None:
        if self.container is None:
            return None
        umo = getattr(event, "unified_msg_origin", "") if event is not None else ""
        bot_id = parse_bot_id_from_umo(umo)
        if not bot_id:
            return None
        row = self.container.db.query_one(
            "SELECT status FROM bots WHERE id = ?", (bot_id,)
        )
        if row is None or row["status"] == "deleted":
            return None
        return bot_id

    async def _run_memory_tool(self, name: str, arguments: dict, event) -> str:
        import json

        bot_id = self._bot_id_for_event(event)
        if bot_id is None:
            logger.warning(
                "astrbot_plugin_saas: 拒绝记忆工具调用（无法解析租户 Bot）umo=%s",
                getattr(event, "unified_msg_origin", ""),
            )
            return json.dumps(
                {"ok": False, "error": "无法确定当前 Bot 租户，已拒绝记忆操作"},
                ensure_ascii=False,
            )
        try:
            result = await dispatch_memory_tool(
                self.container.memory_api, bot_id, name, arguments
            )
            return json.dumps({"ok": True, **result}, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001
            logger.warning("astrbot_plugin_saas: 记忆工具执行失败 %s", name, exc_info=True)
            return json.dumps(
                {"ok": False, "error": str(exc)}, ensure_ascii=False
            )

    async def _run_chat_tool(self, name: str, arguments: dict, event) -> str:
        import json

        bot_id = self._bot_id_for_event(event)
        if bot_id is None:
            logger.warning(
                "astrbot_plugin_saas: 拒绝对话检索工具调用（无法解析租户 Bot）umo=%s",
                getattr(event, "unified_msg_origin", ""),
            )
            return json.dumps(
                {"ok": False, "error": "无法确定当前 Bot 租户，已拒绝对话检索"},
                ensure_ascii=False,
            )
        try:
            result = await dispatch_chat_tool(
                self.container.conversations, bot_id, name, arguments
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "astrbot_plugin_saas: 对话检索工具执行失败 %s", name, exc_info=True
            )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _serve(self) -> None:
        from aiohttp import web

        if self.container is None:
            return
        try:
            self._seed_first_run()
            app = create_app(self.container)
            self._runner = web.AppRunner(app, access_log=None)
            await self._runner.setup()
            site = web.TCPSite(
                self._runner, self.settings.host, self.settings.port
            )
            await site.start()
            logger.info(
                "astrbot_plugin_saas: 控制台已启动 http://%s:%s/console/",
                self.settings.host,
                self.settings.port,
            )
        except Exception:
            logger.error("astrbot_plugin_saas: 控制台启动失败", exc_info=True)

    def _seed_first_run(self) -> None:
        """Create the initial admin + demo templates if the DB is empty."""
        if self.container is None or not self.settings.admin_email:
            return
        if self.container.auth.get_user_by_email(self.settings.admin_email):
            return
        result = self.container.seed_defaults()
        invite = self.container.invites.create(
            created_by="system", max_uses=1, note="first-run"
        )
        logger.warning(
            "astrbot_plugin_saas: 已创建初始管理员 %s；一次性邀请码 %s（72h 内有效）",
            self.settings.admin_email,
            invite["code"],
        )
        logger.info("astrbot_plugin_saas: 初始化结果 %s", result)

    async def _gc_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                if self.container is not None:
                    self.container.qr.gc()
                    sessions = getattr(self.container, "qr_sessions", None)
                    if sessions is not None:
                        await sessions.gc()
        except asyncio.CancelledError:
            return

    async def terminate(self) -> None:
        for task in (self._server_task, self._gc_task):
            if task is not None:
                task.cancel()
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                logger.warning("控制台清理失败", exc_info=True)
        if self.conversation_patch is not None:
            try:
                self.conversation_patch.uninstall()
            except Exception:
                logger.warning("对话加密补丁卸载失败", exc_info=True)
        if self.container is not None:
            self.container.close()
