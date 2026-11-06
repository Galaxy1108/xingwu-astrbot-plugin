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

from .saas.astrbot_adapter import AstrBotAdapter
from .saas.config import Settings
from .saas.container import Container
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
        self._runner = None
        self._server_task: asyncio.Task | None = None
        self._gc_task: asyncio.Task | None = None
        try:
            self.container = Container(
                self.settings, port=AstrBotAdapter(context)
            )
        except Exception:
            logger.error("SaaS 核心初始化失败（控制台不会启动）", exc_info=True)
            return
        self._server_task = asyncio.create_task(self._serve())
        self._gc_task = asyncio.create_task(self._gc_loop())
        logger.info(
            "astrbot_plugin_saas: 控制台将在 %s:%s/console/ 提供",
            self.settings.host,
            self.settings.port,
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
        if self.container is not None:
            self.container.close()
