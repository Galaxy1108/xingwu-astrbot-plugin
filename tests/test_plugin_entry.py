"""Plugin entry smoke: main.py loads inside the AstrBot environment.

These tests run with AstrBot's venv (which is what the plugin really uses).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytest.importorskip("astrbot")


def _load_main(tmp_path: Path):
    from astrbot.core.star.star_tools import StarTools

    StarTools.get_data_dir = classmethod(lambda cls, name=None: tmp_path)
    package_name = "astrbot_plugin_saas"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    module_name = f"{package_name}.main"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _stub_context(registered: list[tuple[str, object]], platforms: list[dict]):
    return SimpleNamespace(
        persona_manager=SimpleNamespace(),
        astrbot_config_mgr=SimpleNamespace(),
        platform_manager=SimpleNamespace(),
        _config={"platform": platforms},
        get_db=lambda: None,
        register_llm_tool=lambda name, args, desc, func: registered.append((name, func)),
    )


async def test_plugin_registers_memory_tools_and_seeds(tmp_path):
    module = _load_main(tmp_path)
    registered: list[tuple[str, object]] = []
    context = _stub_context(registered, [])
    plugin = module.SaaSBotPlugin(
        context,
        config={
            "console_port": 0,
            "console_host": "127.0.0.1",
            "cookie_secure": False,
            "otp_dev_echo": True,
            "dev_mode": True,
            "initial_admin_email": "admin@entry.test",
        },
    )
    try:
        await asyncio.sleep(0.2)  # server task seeds the first admin
        assert plugin.container is not None
        names = {name for name, _ in registered}
        assert {"memory_remember", "memory_recall", "memory_forget"} <= names
        assert plugin.container.auth.get_user_by_email("admin@entry.test") is not None
        # Fail-closed: a UMO without a b_ prefix must never reach memory storage.
        handler = dict(registered)["memory_remember"]
        refused = await handler(
            event=SimpleNamespace(unified_msg_origin="weixin_oc:friend:session"),
            content="x",
        )
        assert '"ok": false' in refused
        # Unknown b_ id is also refused.
        refused_unknown = await handler(
            event=SimpleNamespace(unified_msg_origin="b_unknown:friend:session"),
            content="x",
        )
        assert '"ok": false' in refused_unknown
    finally:
        await plugin.terminate()


async def test_plugin_memory_tool_for_known_bot(tmp_path):
    module = _load_main(tmp_path)
    registered: list[tuple[str, object]] = []
    plugin = module.SaaSBotPlugin(
        _stub_context(registered, []),
        config={
            "console_port": 0,
            "cookie_secure": False,
            "dev_mode": True,
            "initial_admin_email": "admin2@entry.test",
        },
    )
    try:
        await asyncio.sleep(0.2)
        container = plugin.container
        # Replace the framework port with the deterministic fake for this test.
        from saas.fake_astrbot import FakeAstrBot

        fake = FakeAstrBot()
        container.port = fake
        container.bots.port = fake
        container.qr.port = fake
        user = container.auth.create_user("owner@entry.test")
        template = container.templates.list(enabled_only=True)[0]
        bot = await container.bots.create(
            user_id=user["id"],
            name="EntryBot",
            template_id=template["id"],
            platform="weixin_oc",
        )
        handler = dict(registered)["memory_remember"]
        result = await handler(
            event=SimpleNamespace(unified_msg_origin=f"{bot['id']}:friend:session"),
            content="用户喜欢在雨天听爵士乐",
            kind="preference",
        )
        assert '"created": true' in result
        recall = dict(registered)["memory_recall"]
        recalled = await recall(
            event=SimpleNamespace(unified_msg_origin=f"{bot['id']}:friend:session"),
            query="爵士乐",
        )
        assert "爵士乐" in recalled
        forget = dict(registered)["memory_forget"]
        await forget(
            event=SimpleNamespace(unified_msg_origin=f"{bot['id']}:friend:session"),
            memory_id=1,
        )
        assert container.memory_api.list(bot["id"])["total"] == 0
    finally:
        await plugin.terminate()
