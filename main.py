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
from astrbot.api.star import Context, Star
from astrbot.core.star.star_tools import StarTools

from .saas.astrbot_adapter import AstrBotAdapter, AstrBotConversationBackend
from .saas.config import Settings
from .saas.container import Container
from .saas.conversation_patch import ConversationEncryptionPatch
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
        if self.container is None:
            return
        for spec in TOOL_DEFINITIONS:
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
                    self._tool_handler(spec["name"]),
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "astrbot_plugin_saas: 注册 LLM 记忆工具 %s 失败", spec["name"], exc_info=True
                )

    def _tool_handler(self, name: str):
        async def handler(event=None, context=None, **kwargs):
            return await self._run_memory_tool(name, kwargs, event)

        handler.__name__ = name
        return handler

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
